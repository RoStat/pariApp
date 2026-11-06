#!/usr/bin/env python3
"""Disponibilité des joueurs (blessés, suspendus, compos officielles) via API-Football (api-sports.io), plan gratuit 100 req/jour.
Clé : variable APIFOOTBALL_KEY (secret GitHub). Sans clé : data/dispo.json porte status "no_key" et le script sort en code 0.

Par passage, pour les matchs de data/offre.json dont la compétition est dans config.json > dispo.leagues et le coup d'envoi
à moins de horizon_hours :
  1. fixtures de la ligue (1 requête par ligue et par jour) -> appariement FDJ <-> API-Football (noms + heure, common.match_events)
  2. absents par fixture : /injuries?fixture=<id> (1 requête par match, rafraîchie toutes les 6 h)
  3. compos officielles : /fixtures/lineups?fixture=<id> quand le coup d'envoi est à moins de lineups_before_min
     (1 requête par passage et par match tant que la réponse est vide, 4 essais max)
Budget quotidien plafonné (dispo.daily_budget, compteur dans data/state.json > dispo) ; 10 req/min max (pause 6,5 s).

Sortie data/dispo.json :
  {updated_at, status: ok|no_key|error, error, requests_today, budget,
   matches: {event_id: {match, comp, start, fixture_id, home: {team, absents: [{player, type, reason}], xi: [..]|null, bench: [..]|null},
                        away: {...}, injuries_at, lineups_at}},
   unmatched: [{match, start, best_api, score}]}

Usage : python3 scripts/dispo.py                         (clé dans APIFOOTBALL_KEY)
        python3 scripts/dispo.py --mock tests/mock_apifootball.json   (sans réseau ; clés du mock = "chemin?param=val&...")
"""
import os, sys, json, time, argparse, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, now_ts, iso, load_json, load_aliases, match_events, update_summary

D = CONFIG["dispo"]
STATE = DATA / "state.json"
OUT = DATA / "dispo.json"
MIN_GAP_S = 6.5
INJURIES_TTL_S = 6 * 3600
LINEUP_TRIES = 4


class ApiError(Exception):
    pass


class Client:
    def __init__(self, key: str | None, mock: dict | None, state: dict):
        self.key, self.mock, self.state = key, mock, state
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        if state.get("day") != today:
            state.clear(); state.update({"day": today, "requests": 0, "fixtures": {}, "injuries": {}, "lineups": {}})
        self.last_call = 0.0

    def can(self) -> bool:
        return self.state["requests"] < D["daily_budget"]

    def get(self, path: str, **params) -> list:
        if not self.can():
            raise ApiError(f"budget quotidien atteint ({D['daily_budget']} requêtes)")
        q = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        self.state["requests"] += 1
        if self.mock is not None:
            return self.mock.get(f"{path}?{q}", [])
        import requests
        wait = MIN_GAP_S - (time.time() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.time()
        try:
            r = requests.get(f"{D['base_url']}/{path}", params=params, headers={"x-apisports-key": self.key}, timeout=30)
        except requests.RequestException as e:
            raise ApiError(f"réseau : {e}") from e
        if r.status_code in (401, 403):
            raise ApiError(f"HTTP {r.status_code} : clé API-Football refusée")
        if r.status_code == 429:
            raise ApiError("HTTP 429 : quota API-Football dépassé")
        if r.status_code >= 400:
            raise ApiError(f"HTTP {r.status_code} : {r.text[:200]}")
        body = r.json()
        errs = body.get("errors")
        if errs and not isinstance(errs, list):  # {"plan": "..."} / {"token": "..."} / {"requests": "..."}
            raise ApiError("API-Football : " + "; ".join(f"{k}: {v}" for k, v in errs.items()))
        rem = r.headers.get("x-ratelimit-requests-remaining")
        if rem is not None and rem.isdigit():
            self.state["remaining_header"] = int(rem)
        return body.get("response", [])


def fixture_as_event(f: dict) -> dict:
    """Met une fixture API-Football au format attendu par common.match_events (home_team, away_team, commence_time)."""
    return {"id": f["fixture"]["id"], "home_team": f["teams"]["home"]["name"], "away_team": f["teams"]["away"]["name"],
            "commence_time": iso(f["fixture"]["timestamp"]), "home_id": f["teams"]["home"]["id"], "away_id": f["teams"]["away"]["id"]}


def names(block: list) -> list:
    return [x["player"]["name"] for x in block if x.get("player", {}).get("name")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock")
    a = ap.parse_args()
    now = now_ts()
    offre = load_json(DATA / "offre.json", None)
    if not offre:
        print("data/offre.json absent"); return 0
    prev = load_json(OUT, {})
    key = os.environ.get("APIFOOTBALL_KEY")
    mock = load_json(Path(a.mock), {}) if a.mock else None
    if not key and mock is None:
        OUT.write_text(json.dumps({"updated_at": iso(now), "status": "no_key", "error": "APIFOOTBALL_KEY absent : ajouter le secret GitHub (plan gratuit api-football.com)",
                                   "requests_today": 0, "budget": D["daily_budget"], "matches": prev.get("matches", {}), "unmatched": []}, ensure_ascii=False, indent=1), encoding="utf-8")
        update_summary(dispo_status="no_key", dispo_matches=0, dispo_requests_today=0, dispo_error=None)
        print("dispo : pas de clé APIFOOTBALL_KEY, rien relevé"); return 0
    state_all = load_json(STATE, {})
    st = state_all.setdefault("dispo", {})
    cli = Client(key, mock, st)
    if st.get("plan_error"):  # le plan de la clé ne sert pas cette saison : inutile de réessayer avant demain (le compteur se remet à zéro par jour)
        msg = st["plan_error"]
        OUT.write_text(json.dumps({"updated_at": iso(now), "status": "error", "error": msg, "requests_today": st["requests"], "budget": D["daily_budget"],
                                   "matches": {}, "unmatched": []}, ensure_ascii=False, indent=1), encoding="utf-8")
        update_summary(dispo_status="error", dispo_matches=0, dispo_requests_today=st["requests"], dispo_error=msg)
        print(f"dispo : {msg} (pas de nouvel essai aujourd'hui)"); return 0
    aliases = load_aliases()
    horizon = now + D["horizon_hours"] * 3600
    events = [e for e in offre["events"] if str(e["comp_id"]) in D["leagues"] and now < e["start_ts"] <= horizon]
    matches = {k: v for k, v in prev.get("matches", {}).items() if v.get("start_ts", 0) > now - 3 * 3600}
    unmatched, error = [], None
    try:
        by_league = {}
        for e in events:
            by_league.setdefault(D["leagues"][str(e["comp_id"])], []).append(e)
        today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
        for league, evs in by_league.items():
            cache = st["fixtures"].get(str(league))
            if not cache or cache.get("at", 0) < now - 12 * 3600:
                resp = cli.get("fixtures", league=league, season=D["season"], **{"from": str(today), "to": str(today + dt.timedelta(days=2))})
                cache = {"at": now, "rows": [fixture_as_event(f) for f in resp if f.get("fixture", {}).get("timestamp")]}
                st["fixtures"][str(league)] = cache
            pairs, um = match_events(evs, cache["rows"], aliases, min_score=D["min_match_score"])
            if cache["rows"]:
                unmatched += um
            for e, f, score in pairs:
                k = str(e["event_id"])
                m = matches.get(k) or {"match": e["match"], "comp": e["comp"], "start": e["start"], "start_ts": e["start_ts"], "fixture_id": f["id"], "score": score,
                                       "home": {"team": f["home_team"], "absents": [], "xi": None, "bench": None}, "away": {"team": f["away_team"], "absents": [], "xi": None, "bench": None},
                                       "injuries_at": None, "lineups_at": None}
                matches[k] = m
                # 2. absents
                inj_at = st["injuries"].get(str(f["id"]), 0)
                if now - inj_at > INJURIES_TTL_S and cli.can():
                    rows = cli.get("injuries", fixture=f["id"])
                    st["injuries"][str(f["id"])] = now
                    for side in ("home", "away"):
                        m[side]["absents"] = []
                    for r in rows:
                        side = "home" if r.get("team", {}).get("id") == f["home_id"] else "away"
                        p = r.get("player", {})
                        m[side]["absents"].append({"player": p.get("name"), "type": p.get("type"), "reason": p.get("reason")})
                    m["injuries_at"] = iso(now)
                # 3. compos officielles
                mins = (e["start_ts"] - now) / 60
                tries = st["lineups"].get(str(f["id"]), 0)
                if 0 < mins <= D["lineups_before_min"] and m["lineups_at"] is None and tries < LINEUP_TRIES and cli.can():
                    rows = cli.get("fixtures/lineups", fixture=f["id"])
                    st["lineups"][str(f["id"])] = tries + 1
                    if rows:
                        for r in rows:
                            side = "home" if r.get("team", {}).get("id") == f["home_id"] else "away"
                            m[side]["xi"], m[side]["bench"], m[side]["formation"] = names(r.get("startXI", [])), names(r.get("substitutes", [])), r.get("formation")
                        m["lineups_at"] = iso(now)
    except ApiError as e:
        error = str(e)
        if "plan" in error.lower() or "clé" in error:
            st["plan_error"] = error + " — source indisponible : l'agent compositeur se rabat sur l'avis Pronosoft et une recherche web"
        print(f"dispo : {error}")
    status = "error" if error else "ok"
    OUT.write_text(json.dumps({"updated_at": iso(now), "status": status, "error": error, "requests_today": st["requests"], "budget": D["daily_budget"],
                               "matches": matches, "unmatched": unmatched}, ensure_ascii=False, indent=1), encoding="utf-8")
    STATE.write_text(json.dumps(state_all, indent=1), encoding="utf-8")
    update_summary(dispo_status=status, dispo_matches=len(matches), dispo_requests_today=st["requests"], dispo_error=error)
    with_xi = sum(1 for m in matches.values() if m.get("lineups_at"))
    print(f"dispo : {len(matches)} matchs appariés ({with_xi} avec compos), {len(unmatched)} sans correspondance, {st['requests']} requêtes aujourd'hui")
    return 0


if __name__ == "__main__":
    sys.exit(main())
