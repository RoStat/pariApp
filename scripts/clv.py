#!/usr/bin/env python3
"""CLV (closing line value) des tickets journalisés, calculé avec les relevés "close" de data/snapshots.

journal/tickets.csv (une ligne par sélection) :
  date;ticket;event_id;match;market;pick;market_id;pos;cote_prise;mise;resultat
  resultat : G (gagné), P (perdu), vide si en attente. market : 1/N/2 | Double chance | Plus/Moins 2,5 (les autres sont ignorés pour le CLV).

Sortie : journal/clv.csv = la même ligne + cote_cloture_juste + clv_pct, et un résumé en console.
Règle de lecture : CLV moyen > 0 sur 200 sélections = tu bats le marché ; < 0 = tu paies la marge, point.
"""
import csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import JOURNAL, SNAP_DIR, CONFIG
from odds_ref import reference_probs

VAL = CONFIG["value"]


def closing_probs_by_event() -> dict:
    """{event_id: {"1N2": {"1":p,...}, "OU25": {"Plus":p,"Moins":p}, "DC": {...}}} depuis le dernier relevé close de chaque match."""
    out = {}
    for f in sorted(SNAP_DIR.glob("*_close_*.json")):
        snap = json.loads(f.read_text(encoding="utf-8"))
        api_by_id = {a.get("id"): a for a in snap["api_events"]}
        for p in snap["pairs"]:
            a = api_by_id.get(p["api_id"])
            if not a:
                continue
            ref = reference_probs(a)
            d = {}
            if ref.get("h2h"):
                d["1/N/2"] = ref["h2h"]
                h = ref["h2h"]
                d["Double chance"] = {"1/N": h["1"] + h["N"], "N/2": h["N"] + h["2"], "1/2": h["1"] + h["2"]}
            if ref.get("totals_2.5"):
                d["Plus/Moins 2,5"] = {"Plus 2.5": ref["totals_2.5"]["Plus"], "Moins 2.5": ref["totals_2.5"]["Moins"], "Plus 2,5": ref["totals_2.5"]["Plus"], "Moins 2,5": ref["totals_2.5"]["Moins"]}
            out[p["event_id"]] = d  # le dernier relevé écrase les précédents
    return out


def main():
    src = JOURNAL / "tickets.csv"
    if not src.exists():
        print("journal/tickets.csv absent"); return
    closing = closing_probs_by_event()
    rows = list(csv.DictReader(src.open(encoding="utf-8"), delimiter=";"))
    out, clvs, pnl = [], [], 0.0
    for r in rows:
        p = None
        try:
            ev = int(r.get("event_id") or 0)
        except ValueError:
            ev = 0
        probs = closing.get(ev, {}).get(r["market"], {})
        p = probs.get(r["pick"])
        cote = float(r["cote_prise"].replace(",", "."))
        r["cote_cloture_juste"] = round(1 / p, 2) if p else ""
        r["clv_pct"] = round(100 * (cote * p - 1), 2) if p else ""
        if p:
            clvs.append(cote * p - 1)
        mise = float(r.get("mise", "0").replace(",", ".") or 0)
        if r.get("resultat") == "G":
            pnl += mise * (cote - 1)
        elif r.get("resultat") == "P":
            pnl -= mise
        out.append(r)
    dst = JOURNAL / "clv.csv"
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else [], delimiter=";")
        w.writeheader(); w.writerows(out)
    n = len(clvs)
    print(f"{len(rows)} sélections, {n} avec cote de clôture ; CLV moyen {100 * sum(clvs) / n:.2f} % " if n else "aucune cote de clôture trouvée ; ", end="")
    print(f"; P&L réglé {pnl:+.2f} €")
    if n < 200:
        print(f"échantillon {n}/200 : pas de conclusion possible")


if __name__ == "__main__":
    main()
