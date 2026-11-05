#!/usr/bin/env python3
"""Relevé Pinnacle (The Odds API) avec garde-fou de crédits, puis calcul de la valeur FDJ vs référence.

Ne dépense un crédit QUE si un match suivi est dans une fenêtre configurée (config.json > snapshots) :
  - "pre"   : avant les compos officielles (référence pré-match)
  - "close" : juste avant le coup d'envoi (clôture, pour le CLV)
et une seule fois par (compétition, créneau de coup d'envoi, fenêtre) grâce à data/state.json.
S'arrête d'elle-même quand x-requests-remaining passe sous odds_api.min_credits_remaining.
Un run forcé (--force) consomme des crédits mais n'écrit rien dans state.json ; les crédits restants vont dans summary.json.
Une erreur API (401 clé invalide, 429 quota, réseau) est écrite dans state.json (last_error) et summary.json (odds_error) ;
le script termine en code 0 pour ne pas mettre le workflow au rouge.

Sorties :
  data/snapshots/<horodatage>_<pre|close>_<sport_key>.json  réponse brute + cotes FDJ du moment (historique CLV)
  data/value.json      sélections FDJ évaluées (1N2, double chance, +/- 2,5), triées par valeur ; picks = au-dessus du seuil
  data/unmatched.json  matchs FDJ suivis (< 36 h) sans correspondance API -> alias à ajouter dans data/teams.json
  data/summary.json    credits_remaining, picks_count, last_snapshot_at, odds_error

Usage : python3 scripts/odds_ref.py                 (mode normal, clé dans ODDS_API_KEY)
        python3 scripts/odds_ref.py --force pre     (ignore les fenêtres, pour tester ; consomme des crédits)
        python3 scripts/odds_ref.py --mock tests/mock_odds.json --force pre   (sans réseau)
"""
import os, sys, json, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (CONFIG, DATA, SNAP_DIR, now_ts, iso, stamp, load_aliases, match_events, devig, kelly_fraction, ADJ_T,
                    load_json, read_summary, update_summary)

API = CONFIG["odds_api"]
WIN = {k: v for k, v in CONFIG["snapshots"].items() if not k.startswith("_")}
VAL = CONFIG["value"]
STATE = DATA / "state.json"
HORIZON_UNMATCHED_H = CONFIG.get("alias_issue", {}).get("horizon_hours", 36)


class ApiError(Exception):
    pass


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
        raise ApiError("ODDS_API_KEY manquant (secret GitHub ou variable d'environnement)")
    url = f"{API['base_url']}/sports/{sport_key}/odds"
    params = {"apiKey": key, "regions": API["regions"], "markets": API["markets"], "bookmakers": API["bookmakers"], "oddsFormat": "decimal", "dateFormat": "iso"}
    try:
        r = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        raise ApiError(f"réseau : {e}") from e
    if r.status_code in (401, 403):
        raise ApiError(f"HTTP {r.status_code} : clé API refusée (ODDS_API_KEY invalide ?)")
    if r.status_code == 429:
        raise ApiError("HTTP 429 : quota The Odds API épuisé ou trop d'appels")
    if r.status_code >= 400:
        raise ApiError(f"HTTP {r.status_code} : {r.text[:200]}")
    h = r.headers
    usage = {"remaining": int(h.get("x-requests-remaining", -1)), "used": int(h.get("x-requests-used", -1)), "last": int(h.get("x-requests-last", -1))}
    return r.json(), usage


def reference_probs(api_event: dict) -> dict:
    """Probabilités justes par marché à partir du bookmaker de référence (sinon le premier autre bookmaker disponible)."""
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
        rows.append({"event_id": fdj_event["event_id"], "match": fdj_event["match"], "comp": fdj_event["comp"], "start": fdj_event["start"], "fin_ts": fdj_event["fin_ts"],
                     "market": market, "pick": pick, "cote_fdj": cote, "p_juste": round(p, 4), "cote_juste": round(1 / p, 2), "value_pct": round(100 * v, 2),
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


def write_value(all_values: list, all_unmatched: list, now: float) -> int:
    all_values = [r for r in all_values if r["fin_ts"] > now]
    all_values.sort(key=lambda r: -r["value_pct"])
    picks = [r for r in all_values if r["value_pct"] >= VAL["min_value_pct"]]
    (DATA / "value.json").write_text(json.dumps({"updated_at": iso(now), "min_value_pct": VAL["min_value_pct"], "rows": all_values, "picks": picks},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "unmatched.json").write_text(json.dumps({"updated_at": iso(now), "rows": all_unmatched}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"value.json : {len(all_values)} sélections évaluées, {len(picks)} au-dessus de {VAL['min_value_pct']} %")
    return len(picks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", choices=["pre", "close"], help="relever maintenant même hors fenêtre")
    ap.add_argument("--mock", help="fichier JSON {sport_key: [events]} à la place de l'API (tests)")
    a = ap.parse_args()

    offre = load_json(DATA / "offre.json", None)
    if not offre:
        print("data/offre.json absent : lancer fetch_offre.py d'abord")
        return 0
    followed = load_json(DATA / "followed_matches.json", [])
    state = load_json(STATE, {"done": {}, "usage": {}})
    summary = read_summary()
    now = now_ts()
    due = due_snapshots(followed, state, a.force)
    if not due:
        print("aucun relevé dû maintenant (hors fenêtre ou déjà fait) : 0 crédit dépensé")
        # on rafraîchit quand même picks_count (les lignes périmées sortent de value.json à chaque passage)
        existing = load_json(DATA / "value.json", {}).get("rows", [])
        if existing:
            n = write_value(existing, load_json(DATA / "unmatched.json", {}).get("rows", []), now)
            update_summary(picks_count=n)
        return 0

    candidates = [x for x in (state.get("usage", {}).get("remaining"), summary.get("credits_remaining")) if isinstance(x, int) and x >= 0]
    remaining = min(candidates) if candidates else 10**9
    if remaining < API["min_credits_remaining"] and not a.mock:
        msg = f"crédits restants {remaining} < {API['min_credits_remaining']} : relevé sauté"
        print(msg)
        update_summary(odds_error=msg)
        return 0

    aliases = load_aliases()
    mock = load_json(Path(a.mock), {}) if a.mock else None
    fdj_events = [e for e in offre["events"] if e["followed"]]
    all_values, all_unmatched = load_json(DATA / "value.json", {}).get("rows", []), []
    ts = stamp()
    usage = None
    last_kind = None
    for sport_key, kind in due.items():
        if mock is not None:
            api_events, usage = mock.get(sport_key, []), {"remaining": remaining if remaining < 10**9 else -1, "used": 0, "last": 0}
        else:
            try:
                api_events, usage = call_api(sport_key)
            except ApiError as e:
                msg = f"{iso(now)} odds_ref {sport_key} : {e}"
                print(msg)
                state["last_error"] = msg
                state.pop("pending_slots", None)
                if not a.force:
                    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
                update_summary(odds_error=msg)
                return 0
            remaining = usage["remaining"]
        last_kind = kind
        mine = [e for e in fdj_events if e["sport_key"] == sport_key]
        pairs, unmatched = match_events(mine, api_events, aliases)
        if api_events:  # une compétition sans réponse API n'est pas un défaut d'alias
            all_unmatched += [u for u in unmatched if u["start"] <= iso(now + HORIZON_UNMATCHED_H * 3600)]
        snap = {"taken_at": iso(now), "kind": kind, "sport_key": sport_key, "usage": usage, "api_events": api_events,
                "fdj_odds": [{"event_id": e["event_id"], "match": e["match"], "start": e["start"], "markets": {k: e["markets"][k] for k in ("1N2", "DC", "OU25") if k in e["markets"]}} for e in mine],
                "pairs": [{"event_id": e["event_id"], "api_id": apie.get("id"), "score": s} for e, apie, s in pairs]}
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        (SNAP_DIR / f"{ts}_{kind}_{sport_key}.json").write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        matched_ids = {e["event_id"] for e, _, _ in pairs}
        all_values = [r for r in all_values if r.get("event_id") not in matched_ids]
        for e, apie, s in pairs:
            all_values += value_rows(e, reference_probs(apie), kind)
        print(f"{sport_key} [{kind}] : {len(api_events)} événements API, {len(pairs)} appariés, {len(unmatched)} sans correspondance, crédits restants {usage['remaining']}")
        if remaining < API["min_credits_remaining"] and mock is None:
            print("seuil de crédits atteint : arrêt des appels")
            break

    picks = write_value(all_values, all_unmatched, now)
    fields = {"picks_count": picks, "value_rows": len([r for r in all_values if r["fin_ts"] > now]), "last_snapshot_at": iso(now), "last_snapshot_kind": last_kind,
              "unmatched_followed": len(all_unmatched), "odds_error": None}
    if usage and usage.get("remaining", -1) >= 0:
        fields["credits_remaining"] = usage["remaining"]
        fields["credits_used"] = usage.get("used")
    if a.force:
        update_summary(**fields)  # un run forcé n'écrit pas dans state.json
        return 0
    if usage and usage.get("remaining", -1) >= 0:
        state["usage"] = usage
    state["last_error"] = None
    for slot in state.pop("pending_slots", []):
        state.setdefault("done", {})[slot] = iso(now)
    state["done"] = {k: v for k, v in state["done"].items() if (now - int(k.split("|")[1])) < 3 * 86400}  # purge > 3 jours
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    update_summary(**fields)
    return 0


if __name__ == "__main__":
    sys.exit(main())
