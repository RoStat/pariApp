#!/usr/bin/env python3
"""Résumé hebdomadaire (D3) : chaque lundi, ajoute en tête de journal/weekly.md la semaine ISO écoulée :
nombre de tickets, mises, P&L réglé, CLV moyen et taille d'échantillon, crédits consommés (compteur The Odds API du mois).
Aucune notification : Jtab ouvre le fichier.

Usage : python3 scripts/weekly.py [--week 2026-W45]
"""
import sys, csv, argparse, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import JOURNAL, read_summary, now_ts, iso


def read_csv(p: Path) -> list:
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def week_of(date_str: str) -> str:
    try:
        d = dt.date.fromisoformat(date_str[:10])
    except ValueError:
        return ""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="semaine ISO (défaut : la semaine écoulée)")
    a = ap.parse_args()
    today = dt.datetime.now(dt.timezone.utc).date()
    if a.week:
        week = a.week
    else:
        y, w, _ = (today - dt.timedelta(days=7)).isocalendar()
        week = f"{y}-W{w:02d}"
    rows = [r for r in read_csv(JOURNAL / "tickets.csv") if week_of(r.get("date", "")) == week]
    clv = {(r.get("date"), r.get("ticket"), r.get("market_id"), r.get("pos")): r for r in read_csv(JOURNAL / "clv.csv")}
    tickets = {(r.get("date"), r.get("ticket")) for r in rows}
    def num(x):
        try:
            return float((x or "0").replace(",", "."))
        except ValueError:
            return 0.0
    mises = {t: 0.0 for t in tickets}
    pnl, regles, gagnes = 0.0, 0, 0
    for r in rows:
        mises[(r.get("date"), r.get("ticket"))] = num(r.get("mise"))
    # P&L au niveau ticket : un combiné est gagné si toutes ses sélections le sont, perdu si une seule l'est
    for t in tickets:
        legs = [r for r in rows if (r.get("date"), r.get("ticket")) == t]
        res = [(r.get("resultat") or "").strip() for r in legs]
        if "P" in res:
            pnl -= mises[t]; regles += 1
        elif res and all(x == "G" for x in res):
            cote = 1.0
            for r in legs:
                cote *= num(r.get("cote_prise")) or 1.0
            pnl += mises[t] * (cote - 1); regles += 1; gagnes += 1
    clvs = []
    for r in rows:
        c = clv.get((r.get("date"), r.get("ticket"), r.get("market_id"), r.get("pos")))
        if c and (c.get("clv_pct") or "").strip():
            clvs.append(num(c["clv_pct"]))
    s = read_summary()
    section = [f"## Semaine {week} (généré le {today.isoformat()})", "",
               f"- Tickets : {len(tickets)} · sélections : {len(rows)} · mises : {sum(mises.values()):.2f} €",
               f"- Réglés : {regles}/{len(tickets)} tickets ({gagnes} gagné(s)) · P&L réglé : {pnl:+.2f} €",
               f"- CLV moyen : {(sum(clvs) / len(clvs)):+.2f} % sur {len(clvs)} sélection(s)" if clvs else "- CLV : aucune sélection avec cote de clôture",
               f"- Crédits The Odds API : {s.get('credits_used', '?')} consommés ce mois, {s.get('credits_remaining', '?')} restants"
               + (" · règlement auto suspendu" if s.get("scores_enabled") is False else ""),
               f"- Dernière offre relayée : {s.get('offer_created_at', '?')} · dernière erreur : {s.get('last_error') or 'aucune'}", ""]
    p = JOURNAL / "weekly.md"
    old = p.read_text(encoding="utf-8") if p.exists() else "# Résumé hebdomadaire PariApp\n\nUne section par semaine ISO, la plus récente en haut. Rien ne se conclut avant 200 sélections.\n\n"
    head, _, rest = old.partition("\n## ")
    rest = ("## " + rest) if rest else ""
    if f"## Semaine {week} " in rest:
        print(f"semaine {week} déjà présente"); return 0
    p.write_text(head.rstrip("\n") + "\n\n" + "\n".join(section) + "\n" + rest, encoding="utf-8")
    print(f"journal/weekly.md : semaine {week}, {len(tickets)} tickets, P&L {pnl:+.2f} €")
    return 0


if __name__ == "__main__":
    sys.exit(main())
