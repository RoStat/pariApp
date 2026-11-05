#!/usr/bin/env python3
"""Règlement automatique des résultats (D2) : renseigne la colonne `resultat` (G/P) de journal/tickets.csv pour les marchés
1/N/2, Double chance et Plus/Moins 2,5, à partir de The Odds API /scores?daysFrom=N (2 crédits par compétition, doc API).

Économie de crédits : n'appelle que les compétitions qui ont des sélections en attente jouées dans les days_from derniers jours ;
un jour sans ticket en attente coûte 0 crédit. Coupe-circuit (config.json > scores) : si les crédits restants passent sous
disable_below_credits avant le jour mid_month_day (ou sous odds_api.min_credits_remaining après), le règlement est désactivé
et summary.json le dit (scores_enabled=false, scores_disabled_reason). Les scores reçus sont mémorisés dans data/results.json.

Usage : python3 scripts/scores.py                       (clé dans ODDS_API_KEY)
        python3 scripts/scores.py --mock tests/mock_scores.json   (sans réseau)
"""
import os, sys, csv, json, argparse, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, JOURNAL, now_ts, iso, load_aliases, match_events, load_json, read_summary, update_summary

API = CONFIG["odds_api"]
SC = CONFIG["scores"]
SETTLEABLE = {"1/N/2", "Double chance", "Plus/Moins 2,5"}
RESULTS = DATA / "results.json"
FIELDS = ["date", "ticket", "event_id", "match", "market", "pick", "market_id", "pos", "cote_prise", "mise", "resultat"]


def read_journal() -> list:
    p = JOURNAL / "tickets.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def write_journal(rows: list) -> None:
    p = JOURNAL / "tickets.csv"
    fields = list(rows[0].keys()) if rows else FIELDS
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader(); w.writerows(rows)


def settle(market: str, pick: str, hg: int, ag: int) -> str | None:
    """G/P pour un pick donné et un score final (temps réglementaire). None si le marché/pick est inconnu."""
    res = "1" if hg > ag else ("2" if ag > hg else "N")
    if market == "1/N/2":
        return "G" if pick == res else "P" if pick in ("1", "N", "2") else None
    if market == "Double chance":
        return "G" if res in pick.split("/") else "P" if pick in ("1/N", "N/2", "1/2") else None
    if market == "Plus/Moins 2,5":
        p = pick.replace(",", ".").lower()
        if p.startswith("plus"):
            return "G" if hg + ag > 2.5 else "P"
        if p.startswith("moins"):
            return "G" if hg + ag < 2.5 else "P"
    return None


def call_scores(sport_key: str) -> tuple:
    import requests
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY manquant")
    r = requests.get(f"{API['base_url']}/sports/{sport_key}/scores", params={"apiKey": key, "daysFrom": SC["days_from"], "dateFormat": "iso"}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} : {r.text[:200]}")
    h = r.headers
    return r.json(), {"remaining": int(h.get("x-requests-remaining", -1)), "used": int(h.get("x-requests-used", -1))}


def circuit_breaker(remaining) -> str | None:
    """Raison de désactivation, ou None si le budget permet un passage."""
    if not isinstance(remaining, int) or remaining < 0:
        return None  # inconnu : on laisse passer, l'appel renseignera
    day = dt.datetime.now(dt.timezone.utc).day
    if day <= SC["mid_month_day"] and remaining < SC["disable_below_credits"]:
        return f"crédits restants {remaining} < {SC['disable_below_credits']} le {day} du mois : règlement automatique suspendu jusqu'au renouvellement du quota"
    if remaining < API["min_credits_remaining"] + SC["cost_per_call"]:
        return f"crédits restants {remaining} : réserve minimale atteinte, règlement automatique suspendu"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", help="fichier JSON {sport_key: [events scores]} (tests)")
    a = ap.parse_args()
    now = float(os.environ.get("SCORES_NOW") or now_ts())  # SCORES_NOW : horloge figée pour les tests
    rows = read_journal()
    hist = load_json(DATA / "followed_history.json", {})
    results = load_json(RESULTS, {})
    pending = [r for r in rows if r.get("market") in SETTLEABLE and not (r.get("resultat") or "").strip()]
    if not pending:
        print("aucune sélection en attente : 0 crédit")
        update_summary(scores_last_run=iso(now), scores_pending=0)
        return 0
    # 1) régler ce qu'on sait déjà (results.json), 2) ne demander à l'API que les compétitions restantes
    def apply_known() -> int:
        n = 0
        for r in pending:
            if (r.get("resultat") or "").strip():
                continue
            res = results.get(str(r.get("event_id")))
            if res and res.get("completed"):
                v = settle(r["market"], r["pick"], res["home_score"], res["away_score"])
                if v:
                    r["resultat"] = v; n += 1
        return n
    settled = apply_known()
    todo = {}
    for r in pending:
        if (r.get("resultat") or "").strip():
            continue
        h = hist.get(str(r.get("event_id")))
        if not h or h["start_ts"] > now or h["start_ts"] < now - SC["days_from"] * 86400:
            continue  # pas encore joué, ou trop vieux pour daysFrom : reste manuel
        todo.setdefault(h["sport_key"], []).append(h)
    summary = read_summary()
    usage = None
    if todo:
        reason = circuit_breaker(summary.get("credits_remaining")) if not a.mock else None
        if reason:
            print(reason)
            update_summary(scores_enabled=False, scores_disabled_reason=reason, scores_last_run=iso(now), scores_pending=len(todo))
            if settled:
                write_journal(rows)
            return 0
        mock = load_json(Path(a.mock), {}) if a.mock else None
        aliases = load_aliases()
        for sport_key, events in todo.items():
            try:
                api_events, usage = (mock.get(sport_key, []), None) if mock is not None else call_scores(sport_key)
            except Exception as e:  # noqa: BLE001
                msg = f"{iso(now)} scores {sport_key} : {e}"
                print(msg)
                update_summary(scores_error=msg, scores_last_run=iso(now))
                break
            completed = [x for x in api_events if x.get("completed") and x.get("scores")]
            fdj = [{"match": h["match"], "home": h["home"], "away": h["away"], "start_ts": h["start_ts"], "event_id": None} for h in events]
            for f, h in zip(fdj, events):
                f["event_id"] = next(k for k, v in hist.items() if v is h)
            pairs, _ = match_events(fdj, completed, aliases, max_minutes_gap=30)
            for f, apie, s in pairs:
                sc = {x["name"]: int(x["score"]) for x in apie["scores"] if x.get("score") is not None}
                if apie["home_team"] in sc and apie["away_team"] in sc:
                    results[f["event_id"]] = {"match": f["match"], "home_score": sc[apie["home_team"]], "away_score": sc[apie["away_team"]],
                                              "completed": True, "api_id": apie.get("id"), "settled_at": iso(now)}
            print(f"{sport_key} : {len(completed)} matchs terminés, {len(pairs)} appariés" + (f", crédits restants {usage['remaining']}" if usage else ""))
        settled += apply_known()
        limit = now - 15 * 86400
        results = {k: v for k, v in results.items() if v.get("settled_at", iso(now)) >= iso(limit)}
        RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if settled:
        write_journal(rows)
    still = len([r for r in pending if not (r.get("resultat") or "").strip()])
    fields = {"scores_last_run": iso(now), "scores_settled": settled, "scores_pending": still, "scores_enabled": True, "scores_disabled_reason": None, "scores_error": None}
    if usage and usage.get("remaining", -1) >= 0:
        fields["credits_remaining"] = usage["remaining"]
        fields["credits_used"] = usage.get("used")
    update_summary(**fields)
    print(f"{settled} sélection(s) réglée(s), {still} en attente")
    return 0


if __name__ == "__main__":
    sys.exit(main())
