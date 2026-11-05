"""Règlement des résultats : fonction settle() et passage complet en mode mock sur un journal temporaire."""
import sys, os, csv, json, shutil, subprocess, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from scores import settle  # noqa: E402


class TestSettle(unittest.TestCase):
    def test_1n2(self):
        self.assertEqual(settle("1/N/2", "1", 2, 1), "G")
        self.assertEqual(settle("1/N/2", "N", 2, 2), "G")
        self.assertEqual(settle("1/N/2", "2", 2, 1), "P")

    def test_double_chance(self):
        self.assertEqual(settle("Double chance", "1/N", 1, 1), "G")
        self.assertEqual(settle("Double chance", "N/2", 3, 0), "P")
        self.assertEqual(settle("Double chance", "1/2", 0, 1), "G")

    def test_ou25(self):
        self.assertEqual(settle("Plus/Moins 2,5", "Plus 2.5", 2, 1), "G")
        self.assertEqual(settle("Plus/Moins 2,5", "Moins 2.5", 2, 1), "P")
        self.assertEqual(settle("Plus/Moins 2,5", "Moins 2,5", 1, 0), "G")

    def test_inconnu(self):
        self.assertIsNone(settle("Buteur", "Mbappé", 1, 0))


class TestScoresMock(unittest.TestCase):
    """Copie le dépôt dans un dossier temporaire, écrit un journal avec 3 sélections et règle avec tests/mock_scores.json."""
    def test_passage_mock(self):
        tmp = Path(tempfile.mkdtemp())
        for d in ("scripts", "tests"):
            shutil.copytree(ROOT / d, tmp / d)
        shutil.copy(ROOT / "config.json", tmp / "config.json")
        (tmp / "data").mkdir(); (tmp / "journal").mkdir()
        shutil.copy(ROOT / "data" / "teams.json", tmp / "data" / "teams.json")
        import datetime as dt
        start = int(dt.datetime(2026, 11, 5, 20, 0, tzinfo=dt.timezone.utc).timestamp())
        hist = {"1302264": {"match": "Leverkusen-Marseille", "home": "Leverkusen", "away": "Marseille", "sport_key": "soccer_uefa_europa_league", "comp": "Europa League", "start_ts": start, "fin_ts": start - 300},
                "1302265": {"match": "Celtic-Besiktas", "home": "Celtic", "away": "Besiktas", "sport_key": "soccer_uefa_europa_league", "comp": "Europa League", "start_ts": start, "fin_ts": start - 300}}
        (tmp / "data" / "followed_history.json").write_text(json.dumps(hist))
        rows = [["2026-11-05", "T1", "1302264", "Leverkusen-Marseille", "1/N/2", "N", "34625255", "2", "6.5", "3", ""],
                ["2026-11-05", "T1", "1302265", "Celtic-Besiktas", "Plus/Moins 2,5", "Moins 2.5", "1", "2", "1.7", "3", ""],
                ["2026-11-05", "T2", "1302265", "Celtic-Besiktas", "Buteur", "Maeda", "2", "3", "2.1", "3", ""]]
        with (tmp / "journal" / "tickets.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";"); w.writerow(["date", "ticket", "event_id", "match", "market", "pick", "market_id", "pos", "cote_prise", "mise", "resultat"]); w.writerows(rows)
        env = {**os.environ, "SCORES_NOW": str(start + 12 * 3600)}
        r = subprocess.run([sys.executable, str(tmp / "scripts" / "scores.py"), "--mock", str(tmp / "tests" / "mock_scores.json")], capture_output=True, text=True, env=env, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = list(csv.DictReader((tmp / "journal" / "tickets.csv").open(encoding="utf-8"), delimiter=";"))
        self.assertEqual([x["resultat"] for x in out], ["G", "G", ""], r.stdout + r.stderr)
        shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
