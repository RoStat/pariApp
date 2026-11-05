"""Fenêtres de relevé vs cron GitHub (UTC). Pour des coups d'envoi à 18h45 et 21h00 heure de Paris, été comme hiver,
les crons de .github/workflows/pariapp.yml doivent produire au moins un passage dans chaque fenêtre pre et close de config.json,
en tolérant un retard de démarrage de 5 minutes (GitHub ne garantit pas l'heure exacte des crons)."""
import sys, re, json, unittest, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
WORKFLOW = (ROOT / ".github" / "workflows" / "pariapp.yml").read_text(encoding="utf-8")
PARIS = ZoneInfo("Europe/Paris")
RETARD_MAX_MIN = 5


def cron_field(spec: str, lo: int, hi: int) -> set:
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step = part.split("/"); step = int(step)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return out


def crons() -> list:
    return re.findall(r'cron:\s*"([^"]+)"', WORKFLOW)


def passes(day: dt.date) -> list:
    """Instants UTC de tous les passages planifiés un jour donné (crons de la journée entière, tous confondus)."""
    out = set()
    for c in crons():
        m, h, dom, mon, dow = c.split()
        if dow != "*" and str(day.isoweekday() % 7) != dow and str(day.isoweekday()) != dow:
            continue
        for hh in cron_field(h, 0, 23):
            for mm in cron_field(m, 0, 59):
                out.add(dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=dt.timezone.utc))
    return sorted(out)


def hits(kickoff: dt.datetime, lo: int, hi: int, retard: int = 0) -> list:
    """Minutes avant le coup d'envoi des passages qui tombent dans [lo, hi] même démarrés avec `retard` minutes de retard."""
    res = []
    for t in passes(kickoff.astimezone(dt.timezone.utc).date()):
        mins = (kickoff - (t + dt.timedelta(minutes=retard))).total_seconds() / 60
        if lo <= mins <= hi:
            res.append(round(mins))
    return res


class TestWindows(unittest.TestCase):
    def test_couverture(self):
        pre, close = CONFIG["snapshots"]["pre"], CONFIG["snapshots"]["close"]
        for label, day in (("hiver", dt.date(2026, 1, 21)), ("été", dt.date(2026, 9, 16))):
            for hh, mm in ((18, 45), (21, 0), (20, 0), (19, 0)):
                ko = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=PARIS)
                for retard in (0, RETARD_MAX_MIN):
                    with self.subTest(saison=label, ko=f"{hh:02d}:{mm:02d}", retard=retard):
                        self.assertTrue(hits(ko, pre["minutes_before_kickoff_min"], pre["minutes_before_kickoff_max"], retard), "aucun passage pre")
                        self.assertTrue(hits(ko, close["minutes_before_kickoff_min"], close["minutes_before_kickoff_max"], retard), "aucun passage close")

    def test_cron_soir_present(self):
        self.assertIn("*/10 16-21 * * *", crons())


if __name__ == "__main__":
    # affichage du calcul explicite (repris en commentaire dans config.json)
    pre, close = CONFIG["snapshots"]["pre"], CONFIG["snapshots"]["close"]
    for label, day in (("hiver", dt.date(2026, 1, 21)), ("été", dt.date(2026, 9, 16))):
        for hh, mm in ((18, 45), (21, 0)):
            ko = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=PARIS)
            print(f"{label} {hh:02d}:{mm:02d} Paris = {ko.astimezone(dt.timezone.utc):%H:%M} UTC  pre {hits(ko, pre['minutes_before_kickoff_min'], pre['minutes_before_kickoff_max'])}  close {hits(ko, close['minutes_before_kickoff_min'], close['minutes_before_kickoff_max'])}  (retard 5 min : pre {hits(ko, pre['minutes_before_kickoff_min'], pre['minutes_before_kickoff_max'], 5)} close {hits(ko, close['minutes_before_kickoff_min'], close['minutes_before_kickoff_max'], 5)})")
    unittest.main()
