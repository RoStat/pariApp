"""dispo.py en mode --mock : appariement FDJ <-> API-Football, absents, compos, compteur de requêtes. Travaille dans un dossier
temporaire (jamais dans data/)."""
import sys, json, shutil, tempfile, unittest, importlib
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestDispo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        offre = json.loads((ROOT / "tests" / "mock_offre.json").read_text(encoding="utf-8"))
        # le mock API-Football est daté : on recale les coups d'envoi de l'offre simulée sur aujourd'hui + 3 h / + 26 h
        import time, datetime as dt
        now = time.time()
        today = dt.datetime.now(dt.timezone.utc).date()
        for e, h in zip(offre["events"], (3, 26, 50)):
            e["start_ts"] = int(now + h * 3600); e["fin_ts"] = e["start_ts"] - 300
            e["start"] = dt.datetime.fromtimestamp(e["start_ts"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.tmp / "offre.json").write_text(json.dumps(offre), encoding="utf-8")
        fx = lambda e, fid, hid, aid, hn, an: {"fixture": {"id": fid, "timestamp": e["start_ts"]}, "teams": {"home": {"id": hid, "name": hn}, "away": {"id": aid, "name": an}}}
        self.mockfile = self.tmp / "mock.json"
        self.mockfile.write_text(json.dumps({
            f"fixtures?from={today}&league=61&season=2026&to={today + dt.timedelta(days=2)}": [fx(offre["events"][0], 9001, 96, 95, "Toulouse", "Strasbourg"), fx(offre["events"][1], 9002, 108, 1063, "Auxerre", "Paris FC")],
            "injuries?fixture=9001": [{"player": {"name": "Casper Tengstedt", "type": "Missing Fixture", "reason": "Knee"}, "team": {"id": 96}}],
            "injuries?fixture=9002": [],
            "fixtures/lineups?fixture=9001": [{"team": {"id": 96}, "formation": "4-3-3", "startXI": [{"player": {"name": "A. Amaaouch"}}], "substitutes": [{"player": {"name": "S. Hidalgo"}}]},
                                               {"team": {"id": 95}, "formation": "3-4-3", "startXI": [{"player": {"name": "J. Panichelli"}}], "substitutes": []}]}))
        import dispo
        self.dispo = importlib.reload(dispo)
        self.dispo.DATA = self.tmp; self.dispo.OUT = self.tmp / "dispo.json"; self.dispo.STATE = self.tmp / "state.json"
        self.dispo.D = {**self.dispo.D, "lineups_before_min": 75}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_dispo(self):
        with mock.patch("dispo.update_summary"), mock.patch.object(sys, "argv", ["dispo.py", "--mock", str(self.mockfile)]):
            self.assertEqual(self.dispo.main(), 0)
        return json.loads((self.tmp / "dispo.json").read_text(encoding="utf-8"))

    def test_appariement_absents_compteur(self):
        d = self.run_dispo()
        self.assertEqual(d["status"], "ok")
        self.assertEqual(set(d["matches"]), {"1", "2"})  # le match à +50 h est hors horizon
        m = d["matches"]["1"]
        self.assertEqual(m["fixture_id"], 9001)
        self.assertEqual(m["home"]["absents"][0]["player"], "Casper Tengstedt")
        self.assertIsNone(m["lineups_at"])  # coup d'envoi dans 3 h : pas encore de compo
        self.assertEqual(d["requests_today"], 3)  # 1 fixtures + 2 injuries (les autres ligues n'ont pas de match dans l'offre simulée)
        d2 = self.run_dispo()
        self.assertEqual(d2["requests_today"], 3)  # second passage : caches fixtures (12 h) et injuries (6 h)

    def test_compos_quand_proche(self):
        self.dispo.D = {**self.dispo.D, "lineups_before_min": 200}
        d = self.run_dispo()
        m = d["matches"]["1"]
        self.assertEqual(m["home"]["xi"], ["A. Amaaouch"]); self.assertEqual(m["home"]["bench"], ["S. Hidalgo"]); self.assertIsNotNone(m["lineups_at"])
        self.assertEqual(d["requests_today"], 4)

    def test_sans_cle(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch("dispo.update_summary"), mock.patch.object(sys, "argv", ["dispo.py"]):
            self.assertEqual(self.dispo.main(), 0)
        self.assertEqual(json.loads((self.tmp / "dispo.json").read_text())["status"], "no_key")


if __name__ == "__main__":
    unittest.main()
