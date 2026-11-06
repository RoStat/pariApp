#!/usr/bin/env python3
"""Vérifie et complète data/tickets.json (tickets composés par l'agent Claude, docs/COMPOSER.md) contre l'offre réelle.

Entrée minimale par jambe : {"event_id": 1318918, "mk": "1N2", "pick": "2"}   (mk = clé du marché dans offre.json :
1N2 | DC | OU25 | BTTS | team_total (+ "team", "line") | buteur | double | decisif | double_match ; pick = libellé du bouton,
pour les joueurs une sous-chaîne suffit si elle est unique). Tout le reste (market_id, pos, cote, libellés, type, lien,
cote totale, gain, bonus Combi Boosté, TRJ, deadline) est recalculé ici : Claude n'a pas à recopier des identifiants.

Erreurs (code 1, le fichier n'est pas réécrit sauf --write-anyway) :
  - match / marché / bouton introuvable ou ambigu ; validation fermée dans moins de marge_scan_min
  - deux sélections sur un même match dans un ticket ; plus de max_legs ; moins de 2 sélections
  - couverture entre tickets (sélections incompatibles sur un même match : 1 contre N, Plus contre Moins, Oui contre Non…)
  - joueur absent (blessé / suspendu) ou hors compo officielle d'après data/dispo.json
Avertissements (écrits dans le fichier) : cote totale hors fourchette, jambe > cote_max_jambe, matchs communs > max_matchs_communs,
joueur dans > max_tickets_par_joueur tickets, joueur « incertain » (Questionable), match sans donnée de disponibilité.

Usage : python3 scripts/check_tickets.py data/tickets.json [--now <ts>] [--write-anyway]
"""
import sys, json, argparse, re, unicodedata
from math import prod
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, now_ts, iso, load_json, ADJ_T

T = CONFIG["tickets"]
MARKET_LIB = {"1N2": "1/N/2", "DC": "Double chance", "OU25": "Plus/Moins 2,5", "BTTS": "Les 2 équipes marquent", "team_total": "Plus/Moins équipe",
              "buteur": "Buteur", "double": "Buteur 2 fois ou plus", "decisif": "Joueur décisif", "double_match": "Un doublé sera-t-il marqué ?"}
PLAYER_MK = {"buteur", "double", "decisif"}
TRJ_KEY = {"1N2": "1N2", "DC": "DC", "OU25": "OU25", "BTTS": "BTTS", "team_total": "team_total", "buteur": "buteur", "double": "double", "decisif": "decisif", "double_match": "double_match"}


def pname(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).strip()


def player_tokens(name: str) -> tuple:
    """'Amaaouch, Aymen' -> ('amaaouch', 'a') ; 'A. Amaaouch' -> ('amaaouch', 'a') ; 'Casper Tengstedt' -> ('tengstedt', 'c').
    Nom de famille = le dernier mot (ou le premier si la forme est 'Nom, Prénom'), initiale du prénom si connue."""
    raw = name or ""
    if "," in raw:
        last, first = [pname(x) for x in raw.split(",", 1)]
        return (last.split()[-1] if last else "", first[:1])
    toks = pname(raw).replace(".", " ").split()
    if not toks:
        return ("", "")
    if len(toks) == 1:
        return (toks[0], "")
    return (toks[-1], toks[0][:1])


def same_player(a: str, b: str) -> bool:
    la, ia = player_tokens(a); lb, ib = player_tokens(b)
    return bool(la) and la == lb and (not ia or not ib or ia == ib)


def win_set(mk: str, pick: str):
    if mk == "1N2":
        return {pick}
    if mk == "DC":
        return set(pick.split("/"))
    return None


def opposed(a: dict, b: dict) -> bool:
    if a["event_id"] != b["event_id"]:
        return False
    if a["market_id"] == b["market_id"]:
        return a["pos"] != b["pos"]
    wa, wb = win_set(a["mk"], a["pick"]), win_set(b["mk"], b["pick"])
    return bool(wa and wb and not (wa & wb))


def leg_type(mk: str, pick: str, cote: float, outcomes: list) -> str:
    if mk == "1N2":
        if pick == "N":
            return "nul"
        best = min(o["cote"] for o in outcomes if o["lib"] in ("1", "2"))
        return "fav" if cote == best else "outsider"
    return {"DC": "dc", "OU25": "total", "BTTS": "btts", "team_total": "buts_eq", "buteur": "buteur", "double": "double", "decisif": "decisif", "double_match": "double_match"}[mk]


def label_for(e: dict, mk: str, pick: str, team: str | None, line: str | None) -> str:
    home, away = e["home"], e["away"]
    if mk == "1N2":
        return {"1": home + " gagne", "N": "Match nul", "2": away + " gagne"}.get(pick, pick)
    if mk == "DC":
        return {"1/N": home + " ou nul", "N/2": away + " ou nul", "1/2": "Pas de nul"}.get(pick, pick)
    if mk == "OU25":
        return ("+" if pick.lower().startswith("plus") else "−") + "2,5 buts dans le match"
    if mk == "BTTS":
        return "Les 2 équipes marquent" if pick == "Oui" else "Une équipe ne marque pas"
    if mk == "team_total":
        return f"{team} {'+' if pick.lower().startswith('plus') else '−'}{line} buts"
    if mk == "double_match":
        return "Un doublé dans le match" if pick == "Oui" else "Pas de doublé dans le match"
    return f"{pick} " + {"buteur": "buteur", "double": "doublé", "decisif": "décisif (but ou passe)"}[mk]


class Checker:
    def __init__(self, now: float, offre: dict | None = None, value: dict | None = None, dispo: dict | None = None):
        self.now = now
        self.offre = offre or load_json(DATA / "offre.json", None) or sys.exit("data/offre.json absent")
        self.by_id = {e["event_id"]: e for e in self.offre["events"]}
        self.value = {f"{r['market_id']}:{r['pos']}": r for r in (value if value is not None else load_json(DATA / "value.json", {})).get("rows", [])}
        self.dispo = (dispo if dispo is not None else load_json(DATA / "dispo.json", {})).get("matches", {})
        self.errors, self.warnings = [], []

    def find_event(self, spec: dict, where: str) -> dict | None:
        if spec.get("event_id") is not None:
            e = self.by_id.get(int(spec["event_id"]))
            if not e:
                self.errors.append(f"{where} : event_id {spec['event_id']} absent de l'offre"); return None
            return e
        key = (spec.get("match") or "").lower()
        cands = [e for e in self.offre["events"] if key and key in e["match"].lower()]
        if len(cands) != 1:
            self.errors.append(f"{where} : match « {spec.get('match')} » introuvable ou ambigu ({len(cands)} candidats)"); return None
        return cands[0]

    def resolve(self, spec: dict, where: str) -> dict | None:
        e = self.find_event(spec, where)
        if not e:
            return None
        mk = spec.get("mk") or ""
        mks = e["markets"]
        if mk == "team_total":
            tt = [t for t in mks.get("team_totals", []) if str(t["line"]) == str(spec.get("line", "")).replace(".", ",") and (spec.get("team") or "").lower() in t["team"].lower()]
            if len(tt) != 1:
                self.errors.append(f"{where} : Plus/Moins équipe « {spec.get('team')} {spec.get('line')} » introuvable ou ambigu dans {e['match']}"); return None
            market, team, line = {"market_id": tt[0]["market_id"], "outcomes": tt[0]["outcomes"]}, tt[0]["team"], tt[0]["line"]
        elif mk in MARKET_LIB and mk in mks:
            market, team, line = mks[mk], None, None
        else:
            self.errors.append(f"{where} : marché « {mk} » absent pour {e['match']} (disponibles : {', '.join(k for k in mks if k != 'team_totals')})"); return None
        pick = str(spec.get("pick", ""))
        outs = market["outcomes"]
        exact = [o for o in outs if o["lib"] == pick]
        if mk in PLAYER_MK and not exact:
            exact = [o for o in outs if same_player(o["lib"], pick) or pname(pick) in pname(o["lib"])]
        if mk in ("OU25", "team_total") and not exact:
            exact = [o for o in outs if o["lib"].lower().startswith(pick.lower()[:4])]
        if len(exact) != 1:
            self.errors.append(f"{where} : bouton « {pick} » introuvable ou ambigu dans {e['match']} / {MARKET_LIB[mk]} ({', '.join(o['lib'] for o in outs[:6])})"); return None
        o = exact[0]
        v = self.value.get(f"{market['market_id']}:{o['pos']}")
        return {"event_id": e["event_id"], "match": e["match"], "comp": e["comp"], "start": e["start"], "start_ts": e["start_ts"], "fin_ts": e["fin_ts"],
                "mk": mk, "market": MARKET_LIB[mk] if mk != "team_total" else f"Plus/Moins {team}", "pick": o["lib"], "type": leg_type(mk, o["lib"], o["cote"], outs),
                "label": label_for(e, mk, o["lib"], team, line), "market_id": market["market_id"], "pos": o["pos"], "cote": o["cote"],
                "player": o["lib"] if mk in PLAYER_MK else None, "team": team, "line": line, "value_pct": v["value_pct"] if v else None, "why": spec.get("why")}

    def check_dispo(self, leg: dict, where: str) -> str:
        d = self.dispo.get(str(leg["event_id"]))
        if not d:
            return "unknown"
        status = "ok"
        if leg["player"]:
            for side in ("home", "away"):
                for ab in d[side].get("absents", []):
                    if same_player(ab.get("player", ""), leg["player"]):
                        if (ab.get("type") or "").lower().startswith("quest"):
                            self.warnings.append(f"{where} : {leg['player']} incertain ({ab.get('reason')})"); status = "warn"
                        else:
                            self.errors.append(f"{where} : {leg['player']} absent ({ab.get('type')}, {ab.get('reason')}) d'après dispo.json")
                xi = d[side].get("xi")
                if xi and d[side].get("team"):
                    in_xi = any(same_player(x, leg["player"]) for x in xi)
                    in_bench = any(same_player(x, leg["player"]) for x in d[side].get("bench") or [])
                    if not in_xi and in_bench:
                        self.errors.append(f"{where} : {leg['player']} remplaçant d'après la compo officielle")
            if d["home"].get("xi") and d["away"].get("xi"):
                allp = (d["home"]["xi"] or []) + (d["away"]["xi"] or []) + (d["home"].get("bench") or []) + (d["away"].get("bench") or [])
                if not any(same_player(x, leg["player"]) for x in allp):
                    self.errors.append(f"{where} : {leg['player']} hors feuille de match (compos officielles)")
        return status

    def run(self, doc: dict) -> dict:
        params = {**{"nb": T["nb"], "mise": T["mise"], "gmin": T["gain_min"], "gmax": T["gain_max"]}, **(doc.get("params") or {})}
        mise = float(params["mise"])
        boost = self.offre.get("boost") or {}
        out_tickets, all_legs, players, ev_count = [], [], {}, {}
        for i, t in enumerate(doc.get("tickets", []), 1):
            name = t.get("name") or f"Ticket {i}"
            legs = [l for l in (self.resolve(s, f"[{name}] jambe {j}") for j, s in enumerate(t.get("legs", []), 1)) if l]
            if len(legs) != len(t.get("legs", [])):
                continue
            if len(legs) < 2:
                self.errors.append(f"[{name}] : moins de 2 sélections"); continue
            if len(legs) > T["max_legs"]:
                self.errors.append(f"[{name}] : {len(legs)} sélections > {T['max_legs']}")
            evs = [l["event_id"] for l in legs]
            if len(set(evs)) != len(evs):
                self.errors.append(f"[{name}] : deux sélections sur un même match")
            for l in legs:
                if l["fin_ts"] < self.now + T["marge_scan_min"] * 60:
                    self.errors.append(f"[{name}] : {l['match']} ferme à {iso(l['fin_ts'])}, moins de {T['marge_scan_min']} min de marge")
                if l["cote"] > T["cote_max_jambe"]:
                    self.warnings.append(f"[{name}] : {l['label']} à {l['cote']} > {T['cote_max_jambe']}")
                for u in all_legs:
                    if opposed(u["leg"], l):
                        self.errors.append(f"[{name}] : « {l['label']} » couvre « {u['leg']['label']} » du ticket {u['ticket']} ({l['match']})")
            dispo_status = "ok"
            for l in legs:
                s = self.check_dispo(l, f"[{name}]")
                dispo_status = "warn" if s == "warn" or dispo_status == "warn" else ("unknown" if s == "unknown" and l["player"] else dispo_status)
            legs.sort(key=lambda l: l["start_ts"])
            cote = prod(l["cote"] for l in legs)
            style = t.get("style") or "melange"
            lo, hi = ((3, 8) if style == "discipline" else (params["gmin"] / mise, params["gmax"] / mise))
            if not (lo * 0.9 <= cote <= hi * 1.1):
                self.warnings.append(f"[{name}] : cote {cote:.1f} hors fourchette {lo:.0f}–{hi:.0f}")
            b = 0.0
            if boost.get("enabled") and len(legs) >= 4 and all(l["cote"] >= boost.get("min_cote", 1.2) for l in legs):
                b = (boost.get("grid_pct", {}).get(str(len(legs)), 0) or 0) / 100
            bonus = min(mise * (cote - 1) * b, boost.get("additional_winning_limit") or float("inf"))
            gain = min(mise * cote + bonus, boost.get("max_win") or float("inf"))
            trj = prod(T["trj"].get(TRJ_KEY[l["mk"]], 0.8) for l in legs) * (1 + b * (1 - 1 / cote))
            link = "https://33xb.adj.st/betslip?bet_type=1&" + "&".join(f"market_id={l['market_id']},{l['pos']}" for l in legs) + f"&adj_t={ADJ_T}&pr=0"
            deadline = min(l["fin_ts"] for l in legs)
            for l in legs:
                all_legs.append({"leg": l, "ticket": name}); ev_count[l["event_id"]] = ev_count.get(l["event_id"], 0) + 1
                if l["player"]:
                    players.setdefault(l["player"], set()).add(name)
            out_tickets.append({"id": t.get("id") or f"{iso(self.now)[:10]}-{i}", "name": name, "style": style, "story": t.get("story", ""), "legs": legs,
                                "cote": round(cote, 2), "mise": mise, "gain": round(gain, 2), "boost": b, "trj": round(trj, 3), "deadline": iso(deadline), "deadline_ts": deadline,
                                "link": link, "key": "|".join(sorted(f"{l['market_id']}:{l['pos']}" for l in legs)),
                                "checks": {"one_per_match": len(set(evs)) == len(evs), "no_hedge": True, "dispo": dispo_status}})
        for p, names in players.items():
            if len(names) > T["max_tickets_par_joueur"]:
                self.warnings.append(f"{p} dans {len(names)} tickets ({', '.join(sorted(names))})")
        for a_i in range(len(out_tickets)):
            for b_i in range(a_i + 1, len(out_tickets)):
                common = {l["event_id"] for l in out_tickets[a_i]["legs"]} & {l["event_id"] for l in out_tickets[b_i]["legs"]}
                if len(common) > T["max_matchs_communs"]:
                    self.warnings.append(f"{out_tickets[a_i]['name']} et {out_tickets[b_i]['name']} partagent {len(common)} matchs")
        for t in out_tickets:
            t["checks"]["no_hedge"] = not any(f"[{t['name']}]" in e and "couvre" in e for e in self.errors)
        return {"generated_at": doc.get("generated_at") or iso(self.now), "offer_created_at": self.offre.get("offer_created_at"), "author": doc.get("author", "claude"),
                "params": params, "notes": doc.get("notes", []), "exclusions": doc.get("exclusions", []), "tickets": out_tickets,
                "check": {"ok": not self.errors, "errors": self.errors, "warnings": self.warnings, "checked_at": iso(self.now)}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--now", type=float)
    ap.add_argument("--write-anyway", action="store_true")
    a = ap.parse_args()
    p = Path(a.path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    c = Checker(a.now or now_ts())
    out = c.run(doc)
    for t in out["tickets"]:
        print(f"\n== {t['name']} — {len(t['legs'])} sél. — cote {t['cote']} — gain {t['gain']} € pour {t['mise']:.0f} € — TRJ {t['trj']:.0%} — avant {t['deadline']} — dispo {t['checks']['dispo']}")
        for l in t["legs"]:
            print(f"   {l['start'][5:16].replace('T', ' ')}  {l['match']:<28} {l['label']:<44} {l['cote']}{'  value %+.1f' % l['value_pct'] if l['value_pct'] is not None else ''}")
        print("   " + t["link"])
    for w in c.warnings:
        print("AVERTISSEMENT :", w)
    for e in c.errors:
        print("ERREUR :", e)
    if c.errors and not a.write_anyway:
        print(f"\n{len(c.errors)} erreur(s) : fichier non réécrit")
        return 1
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{p} : {len(out['tickets'])} ticket(s), {len(c.warnings)} avertissement(s), {len(c.errors)} erreur(s)")
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())
