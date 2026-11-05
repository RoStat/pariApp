"""Appariement FDJ -> The Odds API : 15 paires connues doivent passer sans alias, plus les alias déclarés dans data/teams.json.
Lancer : python3 -m unittest discover -s tests   (ou pytest tests/)"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import norm, team_match_score, match_events, load_aliases  # noqa: E402

SANS_ALIAS = [  # (libellé FDJ, libellé The Odds API) : score >= 0.82 attendu sans aucune entrée dans teams.json
    ("Celta Vigo", "Celta Vigo"), ("Saint-Gilloise", "Union Saint-Gilloise"), ("Hap.Beer Sheva", "Hapoel Beer Sheva"),
    ("OFI Crète", "OFI Crete"), ("Man. City", "Manchester City"), ("Inter Milan", "Inter Milan"), ("Bodø/Glimt", "Bodo/Glimt"),
    ("NEC Nimègue", "NEC Nijmegen"), ("FC Copenhague", "FC Copenhagen"), ("Leeds Utd", "Leeds United"), ("Juventus Turin", "Juventus"),
    ("Milan AC", "AC Milan"), ("Sparta Prague", "Sparta Praha"), ("Nottingham F.", "Nottingham Forest"), ("Leverkusen", "Bayer Leverkusen"),
    ("Lillestrøm", "Lillestrom"), ("Panathinaïkos", "Panathinaikos"), ("Hoffenheim", "TSG Hoffenheim"), ("Rennes", "Stade Rennais"),
]
AVEC_ALIAS = [("Paris SG", "Paris Saint Germain"), ("Lyon", "Olympique Lyonnais"), ("Etoile Rouge", "Crvena Zvezda"), ("La Gantoise", "KAA Gent"),
              ("Twente", "FC Twente Enschede"), ("Omonia Nicosie", "Omonoia FC"), ("Kairat Almaty", "FC Kairat"), ("Hap.Beer Sheva", "Hapoel Be'er Sheva")]  # cas réels du 05/11/2026
FAUX_AMIS = [("Inter Milan", "AC Milan"), ("Man. City", "Manchester United"), ("Sparta Prague", "Slavia Prague"), ("Celta Vigo", "Vigo FC Porto")]


class TestNorm(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("Man. City"), "manchester city")
        self.assertEqual(norm("FC Copenhague"), "copenhagen")
        self.assertEqual(norm("Bodø/Glimt"), "bodo glimt")
        self.assertEqual(norm("Hap.Beer Sheva"), "hapoel beer sheva")
        self.assertEqual(norm("St Etienne"), "saint etienne")

    def test_paires_sans_alias(self):
        for fdj, api in SANS_ALIAS:
            with self.subTest(fdj=fdj):
                self.assertGreaterEqual(team_match_score(fdj, api, {}), 0.82, f"{fdj} vs {api} : {norm(fdj)!r} / {norm(api)!r}")

    def test_paires_avec_alias(self):
        aliases = load_aliases()
        for fdj, api in AVEC_ALIAS:
            with self.subTest(fdj=fdj):
                self.assertEqual(team_match_score(fdj, api, aliases), 1.0)

    def test_faux_amis(self):
        for fdj, api in FAUX_AMIS:
            with self.subTest(fdj=fdj):
                self.assertLess(team_match_score(fdj, api, {}), 0.82)


class TestMatchEvents(unittest.TestCase):
    def test_match_events(self):
        fdj = [{"match": "Celta Vigo-Saint-Gilloise", "home": "Celta Vigo", "away": "Saint-Gilloise", "start_ts": 1_800_000_000},
               {"match": "Hap.Beer Sheva-OFI Crète", "home": "Hap.Beer Sheva", "away": "OFI Crète", "start_ts": 1_800_000_000},
               {"match": "Paris SG-Inter Milan", "home": "Paris SG", "away": "Inter Milan", "start_ts": 1_800_000_000},
               {"match": "Inconnu FC-Autre", "home": "Inconnu FC", "away": "Autre", "start_ts": 1_800_000_000}]
        import datetime as dt
        t = dt.datetime.fromtimestamp(1_800_000_000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        api = [{"id": "a", "commence_time": t, "home_team": "Celta Vigo", "away_team": "Union Saint-Gilloise"},
               {"id": "b", "commence_time": t, "home_team": "Hapoel Beer Sheva", "away_team": "OFI Crete"},
               {"id": "c", "commence_time": t, "home_team": "Paris Saint Germain", "away_team": "Inter Milan"},
               {"id": "d", "commence_time": "2000-01-01T00:00:00Z", "home_team": "Inconnu FC", "away_team": "Autre"}]  # hors créneau horaire
        pairs, unmatched = match_events(fdj, api, load_aliases())
        self.assertEqual([p[1]["id"] for p in pairs], ["a", "b", "c"])
        self.assertEqual([u["match"] for u in unmatched], ["Inconnu FC-Autre"])


if __name__ == "__main__":
    unittest.main()
