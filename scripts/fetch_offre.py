#!/usr/bin/env python3
"""Télécharge le zip de l'offre Parions Sport point de vente, l'extrait et produit :
  - offre/spdv_mobile_offre.sqlite(.zip) + offre/fetched_at.txt (jamais versionnés : dossier offre/ dans .gitignore)
  - data/offre.json : matchs des compétitions suivies (+ autres compétitions configurées) avec les marchés utiles,
    market_id et pos prêts pour les liens adj.st, grille Combi Boosté et limites de l'offre
  - data/followed_matches.json : coups d'envoi à venir des compétitions suivies (garde-fou de odds_ref.py)
  - data/followed_history.json : mémoire 10 jours des matchs suivis (sert au règlement des résultats, scores.py)
  - data/summary.json : champs offer_created_at, fetched_at, next_followed_kickoffs, fetch_error

Si FDJ ne répond pas (3 essais), le script écrit fetch_error dans summary.json et sort en code 0 : le workflow ne doit pas
passer au rouge pour une indisponibilité FDJ ; l'offre.json précédente reste en place.

Usage : python3 scripts/fetch_offre.py            (télécharge)
        python3 scripts/fetch_offre.py --zip chemin/vers/un.zip   (sans réseau, pour tester)
"""
import sys, json, zipfile, sqlite3, io, argparse, time, re, html
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, OFFRE_DIR, now_ts, iso, load_json, update_summary

MARKETS = CONFIG["offre_json"]["markets"]
LINES = CONFIG["offre_json"]["team_total_lines"]
TOP_N = CONFIG["offre_json"]["player_top_n"]
HORIZON_DAYS = CONFIG["offre_json"].get("horizon_days", 7)
AVIS_HOURS = CONFIG["offre_json"].get("avis_hours", 48)
COMPS = {**CONFIG["followed_comps"], **CONFIG["other_comps_in_offre"]}
RETRY_WAITS = (5, 15, 30)


def download(url: str) -> bytes:
    import requests  # pip install requests
    last = None
    for i, wait in enumerate((0,) + RETRY_WAITS):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            r.raise_for_status()
            if len(r.content) < 100_000:
                raise ValueError(f"réponse trop courte ({len(r.content)} octets)")
            return r.content
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"téléchargement FDJ : essai {i + 1} échoué ({e})")
    raise RuntimeError(f"FDJ indisponible après {1 + len(RETRY_WAITS)} essais : {last}")


def extract_sqlite(zip_bytes: bytes) -> Path:
    OFFRE_DIR.mkdir(exist_ok=True)
    (OFFRE_DIR / "spdv_mobile_offre.sqlite.zip").write_bytes(zip_bytes)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.endswith((".sqlite", ".db")))
        out = OFFRE_DIR / "spdv_mobile_offre.sqlite"
        out.write_bytes(z.read(name))
    (OFFRE_DIR / "fetched_at.txt").write_text(iso(now_ts()) + "\n")
    return out


def strip_html(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def split_teams(match: str, team_libs: set) -> tuple:
    home = next((t for t in team_libs if match.startswith(t + "-")), None)
    away = next((t for t in team_libs if match.endswith("-" + t)), None)
    if home and away:
        return home, away
    i = match.find("-")
    return match[:i], match[i + 1:]


def read_boost(con) -> dict:
    """Grille Combi Boosté : {nb_selections: pourcentage} + cote minimale par sélection + plafonds de l'offre (table info)."""
    info = con.execute("SELECT * FROM info").fetchone()
    grid = {}
    try:
        for r in con.execute("SELECT level, percentage_cents FROM boost_grid ORDER BY level"):
            grid[str(r["level"])] = r["percentage_cents"] / 100.0
    except sqlite3.Error:
        pass
    return {"enabled": (info["boost_enabled"] == "1") if info else False, "min_cote": (info["boost_minimum_price_cents"] / 100.0) if info else 1.2,
            "grid_pct": grid, "additional_winning_limit": (info["boost_additional_winning_limit_cents"] / 100.0) if info else None,
            "min_stake": (info["betcomponent_min_global_price_cents"] / 100.0) if info else 1.1,
            "max_win": (info["betcomponent_max_potential_win_cents"] / 100.0) if info else 250000.0}


def build_offre_json(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    created = (con.execute("SELECT created_ts FROM info").fetchone() or {"created_ts": None})["created_ts"]
    now = now_ts()
    horizon = now + HORIZON_DAYS * 86400
    comp_ids = ",".join(COMPS.keys())
    events = []
    avis_horizon = now + AVIS_HOURS * 3600
    for e in con.execute(f"""SELECT o.event_id, o.match, o.start_ts, o.fin_ts, o.comp_ref, c.comp, o.edito FROM offer_1n2 o JOIN comp c ON c.comp_id=o.comp_ref
                             WHERE o.comp_ref IN ({comp_ids}) AND o.fin_ts > ? AND o.start_ts < ? ORDER BY o.start_ts, o.match""", (now, horizon)):
        mk = con.execute("SELECT market_id, lib, handicap FROM market WHERE event_id=?", (e["event_id"],)).fetchall()
        if e["match"].startswith("Multiplex") or not any(m["lib"] == "1/N/2" for m in mk):
            continue  # Multiplex / paris spéciaux : pas un match, pas de 1N2 -> inutile pour les tickets et l'appariement
        team_libs = {m["lib"][11:] for m in mk if m["lib"].startswith("Plus/Moins ") and m["lib"] not in ("Plus/Moins MT", "Plus/Moins 2ème MT")}
        home, away = split_teams(e["match"], team_libs)
        def btns(mid, top=None):
            rows = con.execute("SELECT pos, lib, cote FROM buttons WHERE market_id=? AND cote>1 ORDER BY cote", (mid,)).fetchall()
            rows = rows[:top] if top else sorted(rows, key=lambda r: r["pos"])
            return [{"pos": r["pos"], "lib": r["lib"], "cote": r["cote"]} for r in rows]
        markets = {"team_totals": []}
        for m in mk:
            lib, hcp = m["lib"], m["handicap"] or ""
            tr = "Temps R" in hcp or "Tps R" in hcp
            if lib == "1/N/2":
                markets["1N2"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"])}
            elif lib == "Double chance":
                markets["DC"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"])}
            elif lib == "Plus/Moins" and tr and hcp.startswith("2,5"):
                markets["OU25"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"])}
            elif lib == "Les 2 équipes marquent":
                markets["BTTS"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"])}
            elif lib.startswith("Plus/Moins ") and tr and lib not in ("Plus/Moins MT", "Plus/Moins 2ème MT") and hcp[:3] in LINES:
                markets["team_totals"].append({"team": lib[11:], "line": hcp[:3], "market_id": m["market_id"], "outcomes": btns(m["market_id"])})
            elif lib == "Buteur":
                markets["buteur"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"], TOP_N)}
            elif lib == "Buteur 2 fois ou plus":
                markets["double"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"], TOP_N)}
            elif lib == "Joueur décisif":
                markets["decisif"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"], TOP_N)}
            elif lib == "Un doublé sera-t-il marqué ?":
                markets["double_match"] = {"market_id": m["market_id"], "outcomes": btns(m["market_id"])}
        ev = {"event_id": e["event_id"], "match": e["match"], "home": home, "away": away, "comp_id": e["comp_ref"], "comp": e["comp"],
              "sport_key": COMPS[str(e["comp_ref"])]["sport_key"], "followed": str(e["comp_ref"]) in CONFIG["followed_comps"],
              "start": iso(e["start_ts"]), "start_ts": e["start_ts"], "fin_ts": e["fin_ts"], "markets": markets}
        if e["edito"] and e["start_ts"] <= avis_horizon:
            ev["avis"] = strip_html(e["edito"])  # avis Pronosoft (texte) : seule source d'absents dans le zip, lu par l'agent compositeur
        events.append(ev)
    return {"fetched_at": iso(now), "offer_created_at": iso(created) if created else None, "offer_created_ts": created,
            "link_template": "https://33xb.adj.st/betslip?bet_type=1&market_id=<market_id>,<pos>&adj_t=1toqzbnl&pr=0",
            "boost": read_boost(con), "comps": {k: v["name"] for k, v in COMPS.items()}, "events": events}


def update_history(followed: list) -> None:
    """Mémoire 10 jours des matchs suivis (event_id -> équipes, coup d'envoi) pour régler les résultats après coup."""
    p = DATA / "followed_history.json"
    hist = load_json(p, {})
    for f in followed:
        hist[str(f["event_id"])] = {k: f[k] for k in ("match", "home", "away", "sport_key", "comp", "start_ts", "fin_ts")}
    limit = now_ts() - 10 * 86400
    hist = {k: v for k, v in hist.items() if v["start_ts"] > limit}
    p.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="zip local (sans téléchargement)")
    a = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    try:
        zip_bytes = Path(a.zip).read_bytes() if a.zip else download(CONFIG["zip_url"])
        db = extract_sqlite(zip_bytes)
        offre = build_offre_json(db)
    except Exception as e:  # noqa: BLE001 — indisponibilité FDJ : on garde l'offre précédente, sortie propre
        msg = f"{iso(now_ts())} fetch_offre : {e}"
        update_summary(fetch_error=msg)
        print(msg)
        return 0
    (DATA / "offre.json").write_text(json.dumps(offre, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    followed = [{k: e[k] for k in ("event_id", "match", "home", "away", "sport_key", "comp", "start_ts", "fin_ts")} for e in offre["events"] if e["followed"]]
    (DATA / "followed_matches.json").write_text(json.dumps(followed, ensure_ascii=False, indent=1), encoding="utf-8")
    update_history(followed)
    now = now_ts()
    nxt = [{"match": f["match"], "comp": f["comp"], "start": iso(f["start_ts"]), "fin": iso(f["fin_ts"])} for f in followed if f["fin_ts"] > now][:12]
    update_summary(offer_created_at=offre["offer_created_at"], fetched_at=offre["fetched_at"], events_count=len(offre["events"]),
                   followed_count=len(followed), next_followed_kickoffs=nxt, fetch_error=None)
    print(f"offre {offre['offer_created_at']} : {len(offre['events'])} matchs ({len(followed)} suivis) -> data/offre.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
