#!/usr/bin/env python3
"""Boucle « journée » du relais : un job GitHub Actions par tranche horaire (config.json > boucle.tranches_utc), qui enchaîne
fetch_offre → odds_ref → dispo → clv → alias_issue → commit/push, puis dort jusqu'au prochain passage, jusqu'à la fin de la
tranche (ou job_max_min, limite GitHub de 6 h par job). Remplace des dizaines de crons que GitHub exécute de façon aléatoire :
il suffit qu'UN cron de secours parte dans la journée pour que la couverture soit assurée jusqu'au soir.

Cadence : cadence_min (30) ; cadence_near_min (10) dès qu'un match suivi est à moins de near_kickoff_min (100) du coup d'envoi,
ce qui garantit au moins un passage dans chaque fenêtre pre [55,85] et close [1,15] de odds_ref.py (vérifié par tests/test_windows.py).

Usage : python3 scripts/boucle.py --tranche 0|1|2      (dans le workflow)
        python3 scripts/boucle.py --once                (un seul passage, pour tester ; DRY_RUN=1 pour ne pas pousser)
        python3 scripts/boucle.py --until 21:30         (boucle jusqu'à une heure UTC donnée)
"""
import os, sys, time, argparse, subprocess, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, ROOT, DATA, JOURNAL, now_ts, iso, load_json

B = CONFIG["boucle"]
STEPS = [("offre", ["scripts/fetch_offre.py"]), ("pinnacle", ["scripts/odds_ref.py"]), ("dispo", ["scripts/dispo.py"]),
         ("clv", ["scripts/clv.py"]), ("alias", ["scripts/alias_issue.py"])]


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def run_step(name: str, cmd: list) -> None:
    if name == "clv" and not (JOURNAL / "tickets.csv").exists():
        return
    try:
        r = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True, timeout=600)
        out = (r.stdout + r.stderr).strip()
        log(f"{name} (code {r.returncode}) : {out[-800:] if out else 'silencieux'}")
    except subprocess.TimeoutExpired:
        log(f"{name} : délai dépassé (10 min), passage suivant")
    except Exception as e:  # noqa: BLE001 — une étape ne doit jamais tuer la boucle
        log(f"{name} : erreur {e}")


def commit_push() -> None:
    r = subprocess.run(["bash", "scripts/commit_push.sh", "relais"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    log(f"commit : {(r.stdout + r.stderr).strip()[-300:]}")


def next_delay(now: float, kickoffs: list, cfg: dict = B) -> float:
    """Secondes à attendre avant le prochain passage. Fonction pure (testée) : cadence courte si un match suivi est à moins de
    near_kickoff_min du coup d'envoi, sinon cadence longue mais sans dépasser l'instant où un match entrera dans cette zone."""
    near, cad, cad_near = cfg["near_kickoff_min"] * 60, cfg["cadence_min"] * 60, cfg["cadence_near_min"] * 60
    ahead = [k - now for k in kickoffs if k > now]
    if any(d <= near for d in ahead):
        return cad_near
    delay = cad
    for d in ahead:
        delay = min(delay, max(60.0, d - near))
    return delay


def plan_passes(start: float, end: float, kickoffs: list, cfg: dict = B) -> list:
    """Instants des passages qu'effectuerait la boucle entre start et end (simulation, pour les tests)."""
    out, t = [], start
    while t < end:
        out.append(t)
        t += next_delay(t, kickoffs, cfg)
    return out


def tranche_end(i: int, now: float) -> float:
    hh, mm = map(int, B["tranches_utc"][i][1].split(":"))
    d = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    return d.replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tranche", type=int)
    ap.add_argument("--until", help="heure UTC HH:MM")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    start = now_ts()
    if a.once:
        end = start
    elif a.until:
        hh, mm = map(int, a.until.split(":"))
        end = dt.datetime.fromtimestamp(start, dt.timezone.utc).replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()
    elif a.tranche is not None:
        end = tranche_end(a.tranche, start)
    else:
        ap.error("--tranche, --until ou --once")
    end = min(end, start + B["job_max_min"] * 60)
    if not a.once and start >= end:
        log(f"tranche déjà terminée ({iso(end)}) : rien à faire")
        return 0
    log(f"boucle de {iso(start)} à {iso(end)}")
    n = 0
    while True:
        n += 1
        t0 = now_ts()
        log(f"— passage {n} —")
        for name, cmd in STEPS:
            run_step(name, cmd)
        commit_push()
        now = now_ts()
        kick = [m["start_ts"] for m in load_json(DATA / "followed_matches.json", [])]
        delay = max(30.0, next_delay(t0, kick) - (now - t0))  # grille fixe depuis le début du passage : pas de dérive
        if a.once or t0 + next_delay(t0, kick) >= end:
            log(f"fin de boucle après {n} passage(s), {(now - start) / 60:.0f} min")
            return 0
        log(f"passage en {now - t0:.0f} s ; prochain dans {delay / 60:.1f} min")
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())
