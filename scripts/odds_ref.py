#!/usr/bin/env python3
"""Relevé Pinnacle (The Odds API) avec garde-fou de crédits, puis calcul de la valeur FDJ vs référence.

Ne dépense un crédit QUE si un match suivi est dans une fenêtre configurée :
  - "pre"   : 60 à 80 min avant le coup d'envoi (référence avant les compos officielles)
  - "close" : 1 à 12 min avant (clôture, pour le CLV)
et une seule fois par (compétition, créneau de coup d'envoi, fenêtre) grâce à data/state.json.
S'arrête d'elle-même quand x-requests-remaining passe sous odds_api.min_credits_remaining.

Sorties :
  data/snapshots/<horodatage>_<pre|close>_<sport_key>.json  réponse brute + cotes FDJ du moment (historique CLV)
  data/value.json      sélections FDJ dont la cote dépasse la probabilité juste (1N2, double chance, +/- 2,5)
  data/unmatched.json  matchs FDJ sans correspondance API -> ajouter un alias dans data/teams.json

Usage : python3 scripts/odds_ref.py                 (mode normal, clé dans ODDS_API_KEY)
        python3 scripts/odds_ref.py --force pre     (ignore les fenêtres, pour tester ; consomme des crédits)
        python3 scripts/odds_ref.py --mock tests/mock_odds.json --force pre   (sans réseau)
"""
import os, sys, json, argparse
from pathlib import Path
import sys as _sys; from pathlib import Path as _P; _sys.path.insert(0, str(_P(__file__).resolve().parent))
from common import CONFIG, DATA, SNAP_DIR, now_ts, iso, stamp, load_aliases, match_events, devig, kelly_fraction, ADJ_T

API = CONFIG["odds_api"]
WIN = CONFIG["snapshots"]
VAL = CONFIG["value"]
STATE = DATA / "state.json"


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def due_snapshots(followed: list, state: dict, force: str | None) -> dict:
    """{sport_key: kind} des relevés à faire maintenant."""
    now = now_ts()
    due = {}
    for m in followed:
        mins = (m["start_ts"] - now) / 60
        for kind, w in WIN.items():
            if force and force != kind:
                continue
            if force or (w["minutes_before_kickoff_min"] <= mins <= w["minutes_before_kickoff_max"]):
                slot = f"{m['sport_key']}|{int(m['start_ts'] // 900) * 900}|{kind}"  # créneau de 15 min
                if slot in state.get("done", {}) and not force:
                    continue
                due[m["sport_key"]] = kind
                if not force:  # un relevé forcé ne doit pas bloquer les vraies fenêtres à venir
                    state.setdefault("pending_slots", []).append(slot)
    return due


def call_api(sport_key: str) -> tuple:
    import requests
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY manquant (secret GitHub ou variable d'environnement)")
    url = f"{API['base_url']}/sports/{sport_key}/odds"
    params = {"apiKey": key, "regions": API["regions"], "markets": API["markets"], "bookmakers": API["bookmakers"], "oddsFormat": "decimal", "dateFormat": "iso"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    h = r.headers
    usage = {"remaining": int(h.get("x-requests-remaining", -1)), "used": int(h.get("x-requests-used", -1)), "last": int(h.get("x-requests-last", -1))}
    return r.json(), usage


def reference_probs(api_event: dict) -> dict:
    """Probabilités justes par marché à partir du bookmaker de référence (sinon moyenne des autres)."""
    ref = API["reference_bookmaker"]
    books = {b["key"]: b for b in api_event.get("bookmakers", [])}
    order = [ref] + [k for k in books if k != ref]
    out = {"source": None, "h2h": None, "totals_2.5": None, "raw": {}}
    for k in order:
        b = books.get(k)
        if not b:
            continue
        for mk in b.get("markets", []):
            if mk["key"] == "h2h" and out["h2h"] is None and len(mk["outcomes"]) == 3:
                names = {o["name"]: o["price"] for o in mk["outcomes"]}
                home, away = api_event["home_team"], api_event["away_team"]
                if home in names and away in names and "Draw" in names:
                    probs = devig([names[home], names["Draw"], names[away]], VAL["devig"])
                    out["h2h"] = {"1": probs[0], "N": probs[1], "2": probs[2]}
                    out["raw"]["h2h"] = {"book": k, "1": names[home], "N": names["Draw"], "2": names[away]}
                    out["source"] = out["source"] or k
            if mk["key"] == "totals" and out["totals_2.5"] is None:
                line = {(o["name"], o.get("point")): o["price"] for o in mk["outcomes"]}
                if ("Over", 2.5) in line and ("Under", 2.5) in line:
                    probs = devig([line[("Over", 2.5)], line[("Under", 2.5)]], VAL["devig"])
                    out["totals_2.5"] = {"Plus": probs[0], "Moins": probs[1]}
                    out["raw"]["totals_2.5"] = {"book": k, "Plus": line[("Over", 2.5)], "Moins": line[("Under", 2.5)]}
                    out["source"] = out["source"] or k
        if out["h2h"] and out["totals_2.5"]:
            break
    return out


def value_rows(fdj_event: dict, ref: dict, kind: str) -> list:
    rows = []
    mk = fdj_event["markets"]
    def add(market, pick, cote, p, market_id, pos):
        v = p * cote - 1
        k = kelly_fraction(p, cote)
        rows.append({"match": fdj_event["match"], "comp": fdj_event["comp"], "start": fdj_event["start"], "fin_ts": fdj_event["fin_ts"], "market": market, "pick": pick,
                     "cote_fdj": cote, "p_juste": round(p, 4), "cote_juste": round(1 / p, 2), "value_pct": round(100 * v, 2),
                     "mise_pct_bankroll": round(100 * min(max(k, 0) * VAL["kelly_fraction"], VAL["max_stake_pct_bankroll"] / 100), 2),
                     "market_id": market_id, "pos": pos, "lien": f"https://33xb.adj.st/betslip?bet_type=1&market_id={market_id},{pos}&adj_t={ADJ_T}&pr=0",
                     "reference": ref["source"], "snapshot": kind})
    if ref.get("h2h") and "1N2" in mk:
        for o in mk["1N2"]["outcomes"]:
            if o["lib"] in ref["h2h"]:
                add("1/N/2", o["lib"], o["cote"], ref["h2h"][o["lib"]], mk["1N2"]["market_id"], o["pos"])
        if "DC" in mk:
            p = ref["h2h"]
            dc = {"1/N": p["1"] + p["N"], "N/2": p["N"] + p["2"], "1/2": p["1"] + p["2"]}
            for o in mk["DC"]["outcomes"]:
                if o["lib"] in dc:
                    add("Double chance", o["lib"], o["cote"], dc[o["lib"]], mk["DC"]["market_id"], o["pos"])
    if ref.get("totals_2.5") and "OU25" in mk:
        for o in mk["OU25"]["outcomes"]:
            side = "Plus" if o["lib"].startswith("Plus") else "Moins"
            add("Plus/Moins 2,5", o["lib"], o["cote"], ref["totals_2.5"][side], mk["OU25"]["market_id"], o["pos"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", choices=["pre", "close"], help="relever maintenant même hors fenêtre")
    ap.add_argument("--mock", help="fichier JSON {sport_key: [events]} à la place de l'API (tests)")
    a = ap.parse_args()

    offre = load_json(DATA / "offre.json", None)
    if not offre:
        sys.exit("data/offre.json absent : lancer fetch_offre.py d'abord")
    followed = load_json(DATA / "followed_matches.json", [])
    state = load_json(STATE, {"done": {}, "usage": {}})
    due = due_snapshots(followed, state, a.force)
    if not due:
        print("aucun relevé dû maintenant (hors fenêtre ou déjà fait) : 0 crédit dépensé")
        return

    remaining = state.get("usage", {}).get("remaining", 10**9)
    if remaining < API["min_credits_remaining"] and not a.mock:
        print(f"crédits restants {remaining} < {API['min_credits_remaining']} : relevé sauté")
        return

    aliases = load_aliases()
    mock = load_json(Path(a.mock), {}) if a.mock else None
    fdj_events = [e for e in offre["events"] if e["followed"]]
    all_values, all_unmatched = load_json(DATA / "value.json", {}).get("rows", []), []
    ts = stamp()
    for sport_key, kind in due.items():
        if mock is not None:
            api_events, usage = mock.get(sport_key, []), {"remaining": remaining, "used": 0, "last": 0}
        else:
            api_events, usage = call_api(sport_key)
            state["usage"] = usage
            remaining = usage["remaining"]
        mine = [e for e in fdj_events if e["sport_key"] == sport_key]
        pairs, unmatched = match_events(mine, api_events, aliases)
        if api_events:  # une compétition sans réponse API n'est pas un défaut d'alias
            all_unmatched += [u for u in unmatched if u["start"] <= iso(now_ts() + 36 * 3600)]
        snap = {"taken_at": iso(now_ts()), "kind": kind, "sport_key": sport_key, "usage": usage, "api_events": api_events,
                "fdj_odds": [{"event_id": e["event_id"], "match": e["match"], "start": e["start"], "markets": {k: e["markets"][k] for k in ("1N2", "DC", "OU25") if k in e["markets"]}} for e in mine],
                "pairs": [{"event_id": e["event_id"], "api_id": apie.get("id"), "score": s} for e, apie, s in pairs]}
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        (SNAP_DIR / f"{ts}_{kind}_{sport_key}.json").write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        # valeur : on remplace les lignes précédentes de ces matchs par le relevé le plus récent
        matched_ids = {e["event_id"] for e, _, _ in pairs}
        all_values = [r for r in all_values if r.get("event_id") not in matched_ids]
        for e, apie, s in pairs:
            ref = reference_probs(apie)
            for r in value_rows(e, ref, kind):
                r["event_id"] = e["event_id"]
                all_values.append(r)
        print(f"{sport_key} [{kind}] : {len(api_events)} événements API, {len(pairs)} appariés, {len(unmatched)} sans correspondance, crédits restants {usage['remaining']}")
        if remaining < API["min_credits_remaining"] and mock is None:
            print("seuil de crédits atteint : arrêt des appels")
            break

    now = now_ts()
    all_values = [r for r in all_values if r["fin_ts"] > now]
    all_values.sort(key=lambda r: -r["value_pct"])
    (DATA / "value.json").write_text(json.dumps({"updated_at": iso(now), "min_value_pct": VAL["min_value_pct"], "rows": all_values,
                                                 "picks": [r for r in all_values if r["value_pct"] >= VAL["min_value_pct"]]}, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "unmatched.json").write_text(json.dumps({"updated_at": iso(now), "rows": all_unmatched}, ensure_ascii=False, indent=1), encoding="utf-8")
    for slot in state.pop("pending_slots", []):
        state.setdefault("done", {})[slot] = iso(now)
    # purge des créneaux de plus de 3 jours
    state["done"] = {k: v for k, v in state["done"].items() if (now - int(k.split("|")[1])) < 3 * 86400}
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    picks = [r for r in all_values if r["value_pct"] >= VAL["min_value_pct"]]
    print(f"value.json : {len(all_values)} sélections évaluées, {len(picks)} au-dessus de {VAL['min_value_pct']} %")


if __name__ == "__main__":
    main()
