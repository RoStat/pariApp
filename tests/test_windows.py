"""Couverture des fenêtres de relevé par la boucle « journée » (scripts/boucle.py). Pour des coups d'envoi à 15h00, 17h00, 18h45,
20h45 et 21h00 heure de Paris, été comme hiver, la boucle démarrée à n'importe quelle minute de la journée (un seul cron de secours
suffit) doit passer au moins une fois dans chaque fenêtre pre et close de config.json, en tolérant 60 s de durée par passage."""
import sys, json, unittest, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import boucle

CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
PARIS = ZoneInfo("Europe/Paris")
PRE, CLOSE = CONFIG["snapshots"]["pre"], CONFIG["snapshots"]["close"]


def tranches(day: dt.date) -> list:
    out = []
    for a, b in CONFIG["boucle"]["tranches_utc"]:
        ha, ma = map(int, a.split(":")); hb, mb = map(int, b.split(":"))
        out.append((dt.datetime(day.year, day.month, day.day, ha, ma, tzinfo=dt.timezone.utc).timestamp(), dt.datetime(day.year, day.month, day.day, hb, mb, tzinfo=dt.timezone.utc).timestamp()))
    return out


def passes_from(start: float, day: dt.date, kickoffs: list, pass_duration: float = 60.0) -> list:
    """Passages d'un run démarré à `start` : chaque tranche encore ouverte boucle jusqu'à sa fin ; un passage dure pass_duration."""
    out = []
    for a, b in tranches(day):
        t = max(a, start)
        while t < b:
            out.append(t)
            t += max(30.0, boucle.next_delay(t, kickoffs)) + 0  # grille fixe : la durée du passage ne décale pas le suivant
    return out


class TestBoucle(unittest.TestCase):
    def test_couverture_toute_la_journee(self):
        for label, day in (("hiver", dt.date(2026, 1, 25)), ("été", dt.date(2026, 9, 13))):
            kos = [dt.datetime(day.year, day.month, day.day, h, m, tzinfo=PARIS).timestamp() for h, m in ((15, 0), (17, 0), (18, 45), (20, 45), (21, 0))]
            first_tranche = tranches(day)[0][0]
            for start_min in range(0, 6 * 60 + 1, 7):  # démarrage entre 07:00 et 13:00 UTC, toutes les 7 min (cron perdu, secours en retard…)
                start = first_tranche + start_min * 60
                ps = passes_from(start, day, kos)
                for ko in kos:
                    if ko - start < PRE["minutes_before_kickoff_max"] * 60:
                        continue  # un run démarré après la fenêtre pre ne peut pas la rattraper (cas 15h00 Paris avec départ tardif)
                    with self.subTest(saison=label, ko=dt.datetime.fromtimestamp(ko, PARIS).strftime("%H:%M"), start=dt.datetime.fromtimestamp(start, dt.timezone.utc).strftime("%H:%M")):
                        pre = [p for p in ps if PRE["minutes_before_kickoff_min"] * 60 <= ko - p <= PRE["minutes_before_kickoff_max"] * 60]
                        close = [p for p in ps if CLOSE["minutes_before_kickoff_min"] * 60 <= ko - p - 60 <= CLOSE["minutes_before_kickoff_max"] * 60]
                        self.assertTrue(pre, "aucun passage pre"); self.assertTrue(close, "aucun passage close (même avec 60 s de durée)")

    def test_cadence(self):
        now = 1_800_000_000.0
        self.assertEqual(boucle.next_delay(now, [now + 90 * 60]), CONFIG["boucle"]["cadence_near_min"] * 60)
        self.assertEqual(boucle.next_delay(now, [now + 5 * 3600]), CONFIG["boucle"]["cadence_min"] * 60)
        self.assertEqual(boucle.next_delay(now, [now + 110 * 60]), 10 * 60)  # entre dans la zone « proche » dans 10 min
        self.assertEqual(boucle.next_delay(now, []), CONFIG["boucle"]["cadence_min"] * 60)

    def test_tranches_tiennent_dans_6h(self):
        for (a, b) in tranches(dt.date(2026, 1, 25)):
            self.assertLessEqual((b - a) / 60, CONFIG["boucle"]["job_max_min"])
        self.assertLess(CONFIG["boucle"]["job_max_min"], 360)


if __name__ == "__main__":
    unittest.main()
