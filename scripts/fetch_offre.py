#!/usr/bin/env python3
"""Télécharge le zip de l'offre Parions Sport point de vente, l'extrait et produit :
  - offre/spdv_mobile_offre.sqlite.zip + offre/fetched_at.txt (le relais brut, lu par PariApp et le skill)
  - data/offre.json : matchs des compétitions suivies (+ autres compétitions configurées) avec les marchés utiles,
    market_id et pos prêts pour les liens adj.st
  - data/followed_matches.json : coups d'envoi à venir des compétitions suivies (sert de garde-fou à odds_ref.py)

Usage : python3 scripts/fetch_offre.py            (télécharge)
        python3 scripts/fetch_offre.py --zip chemin/vers/un.zip   (sans réseau, pour tester)
"""
import sys, json, zipfile, sqlite3, io, argparse
from pathlib import Path
import sys as _sys; from pathlib import Path as _P; _sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import CONFIG, DATA, OFFRE_DIR, now_ts, iso

MARKETS = CONFIG["offre_json"]["markets"]
LINES = CONFIG["offre_json"]["team_total_lines"]
TOP_N = CONFIG["offre_json"]["player_top_n"]
COMPS = {**CONFIG["followed_comps"], **CONFIG["other_comps_in_offre"]}


def download(url: str) -> bytes:
    import requests  # pip install requests
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    return r.content


def extract_sqlite(zip_bytes: bytes) -> Path:
    OFFRE_DIR.mkdir(exist_ok=True)
    (OFFRE_DIR / "spdv_mobile_offre.sqlite.zip").write_bytes(zip_bytes)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.endswith((".sqlite", ".db")))
        out = OFFRE_DIR / "spdv_mobile_offre.sqlite"
        out.write_bytes(z.read(name))
    (OFFRE_DIR / "fetched_at.txt").write_text(iso(now_ts()) + "\n")
    return out


def split_teams(match: str, team_libs: set) -> tuple:
    home = next((t for t in team_libs if match.startswith(t + "-")), None)
    away = next((t for t in team_libs if match.endswith("-" + t)), None)
    if home and away:
        return home, away
    i = match.find("-")
    return match[:i], match[i + 1:]


def build_offre_json(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    created = (con.execute("SELECT created_ts FROM info").fetchone() or {"created_ts": None})["created_ts"]
    now = now_ts()
    horizon = now + 7 * 86400
    comp_ids = ",".join(COMPS.keys())
    events = []
    for e in con.execute(f"""SELECT o.event_id, o.match, o.start_ts, o.fin_ts, o.comp_ref, c.comp FROM offer_1n2 o JOIN comp c ON c.comp_id=o.comp_ref
                             WHERE o.comp_ref IN ({comp_ids}) AND o.fin_ts > ? AND o.start_ts < ? ORDER BY o.start_ts, o.match""", (now, horizon)):
        mk = con.execute("SELECT market_id, lib, handicap FROM market WHERE event_id=?", (e["event_id"],)).fetchall()
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
        events.append({"event_id": e["event_id"], "match": e["match"], "home": home, "away": away, "comp_id": e["comp_ref"], "comp": e["comp"],
                       "sport_key": COMPS[str(e["comp_ref"])]["sport_key"], "followed": str(e["comp_ref"]) in CONFIG["followed_comps"],
                       "start": iso(e["start_ts"]), "start_ts": e["start_ts"], "fin_ts": e["fin_ts"], "markets": markets})
    return {"fetched_at": iso(now), "offer_created_at": iso(created) if created else None, "link_template": "https://33xb.adj.st/betslip?bet_type=1&market_id=<market_id>,<pos>&adj_t=1toqzbnl&pr=0",
            "comps": {k: v["name"] for k, v in COMPS.items()}, "events": events}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="zip local (sans téléchargement)")
    a = ap.parse_args()
    zip_bytes = Path(a.zip).read_bytes() if a.zip else download(CONFIG["zip_url"])
    db = extract_sqlite(zip_bytes)
    offre = build_offre_json(db)
    DATA.mkdir(exist_ok=True)
    (DATA / "offre.json").write_text(json.dumps(offre, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    followed = [{"event_id": e["event_id"], "match": e["match"], "sport_key": e["sport_key"], "start_ts": e["start_ts"], "fin_ts": e["fin_ts"]} for e in offre["events"] if e["followed"]]
    (DATA / "followed_matches.json").write_text(json.dumps(followed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"offre {offre['offer_created_at']} : {len(offre['events'])} matchs ({len(followed)} suivis) -> data/offre.json")


if __name__ == "__main__":
    main()
