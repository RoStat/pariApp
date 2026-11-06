"""check_tickets.py : résolution des jambes contre l'offre, règles dures (une sélection par match, couvertures, absents, deadline)
et calculs (cote, bonus, lien). Offre et disponibilité simulées (tests/mock_offre.json), horloge figée au 06/11/2026 10:00 UTC."""
import sys, json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_tickets as ct

OFFRE = json.loads((ROOT / "tests" / "mock_offre.json").read_text(encoding="utf-8"))
NOW = 1793959200.0  # 2026-11-06T10:00:00Z
DISPO = {"matches": {"1": {"match": "Toulouse-Strasbourg", "home": {"team": "Toulouse", "absents": [{"player": "Casper Tengstedt", "type": "Missing Fixture", "reason": "Knee Injury"}], "xi": None, "bench": None},
                           "away": {"team": "Strasbourg", "absents": [{"player": "Emanuel Emegha", "type": "Questionable", "reason": "Thigh"}], "xi": None, "bench": None}}}}
VALUE = {"rows": [{"market_id": 101, "pos": 3, "value_pct": 4.2}]}


def run(tickets, dispo=DISPO, now=NOW):
    c = ct.Checker(now, offre=OFFRE, value=VALUE, dispo=dispo)
    return c, c.run({"params": {"nb": 2, "mise": 3, "gmin": 30, "gmax": 2000}, "tickets": tickets})


class TestResolution(unittest.TestCase):
    def test_jambes_resolues_et_calculs(self):
        c, out = run([{"name": "A", "legs": [{"event_id": 1, "mk": "1N2", "pick": "2"}, {"match": "Auxerre", "mk": "OU25", "pick": "Moins"},
                                             {"match": "Lens-Marseille", "mk": "double_match", "pick": "Oui"}]}])
        self.assertEqual(c.errors, [])
        t = out["tickets"][0]
        self.assertEqual([l["market_id"] for l in t["legs"]], [101, 203, 302])
        self.assertEqual([l["pos"] for l in t["legs"]], [3, 2, 1])
        self.assertEqual(t["legs"][0]["type"], "outsider"); self.assertEqual(t["legs"][0]["value_pct"], 4.2)
        self.assertEqual(t["legs"][0]["label"], "Strasbourg gagne"); self.assertEqual(t["legs"][1]["market"], "Plus/Moins 2,5")
        self.assertAlmostEqual(t["cote"], round(3.6 * 1.72 * 1.7, 2))
        self.assertEqual(t["boost"], 0)  # 3 sélections : pas de Combi Boosté
        self.assertIn("market_id=101,3&market_id=203,2&market_id=302,1", t["link"])
        self.assertEqual(t["deadline_ts"], 1793994000); self.assertTrue(out["check"]["ok"])

    def test_joueur_par_sous_chaine_et_bonus(self):
        c, out = run([{"name": "B", "legs": [{"event_id": 1, "mk": "buteur", "pick": "Amaaouch"}, {"event_id": 2, "mk": "1N2", "pick": "1"},
                                             {"event_id": 3, "mk": "1N2", "pick": "N"}, {"match": "Toulouse", "mk": "team_total", "team": "Toulouse", "line": "1,5", "pick": "Plus"}]}])
        self.assertIn("deux sélections sur un même match", " ".join(c.errors))
        c, out = run([{"name": "B", "legs": [{"event_id": 1, "mk": "buteur", "pick": "Amaaouch"}, {"event_id": 2, "mk": "1N2", "pick": "1"},
                                             {"event_id": 3, "mk": "1N2", "pick": "N"}, {"event_id": 2, "mk": "OU25", "pick": "Plus"}]}])
        self.assertIn("deux sélections", " ".join(c.errors))

    def test_bonus_combi(self):
        legs = [{"event_id": 1, "mk": "buteur", "pick": "Amaaouch"}, {"event_id": 2, "mk": "1N2", "pick": "1"}, {"event_id": 3, "mk": "1N2", "pick": "N"}]
        c, out = run([{"name": "C", "legs": legs + [{"event_id": 1, "mk": "DC", "pick": "1/N"}]}])  # même match -> erreur
        self.assertTrue(c.errors)

    def test_bouton_introuvable(self):
        c, _ = run([{"name": "D", "legs": [{"event_id": 1, "mk": "buteur", "pick": "Mbappé"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]}])
        self.assertTrue(any("introuvable" in e for e in c.errors))
        c, _ = run([{"name": "D", "legs": [{"event_id": 2, "mk": "buteur", "pick": "X"}, {"event_id": 1, "mk": "1N2", "pick": "1"}]}])
        self.assertTrue(any("marché « buteur » absent" in e for e in c.errors))


class TestRegles(unittest.TestCase):
    def test_absent_bloque_incertain_avertit(self):
        c, _ = run([{"name": "E", "legs": [{"event_id": 1, "mk": "double", "pick": "Tengstedt"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]}])
        self.assertTrue(any("absent" in e for e in c.errors))
        dispo = {"matches": {"1": {"match": "x", "home": {"team": "Toulouse", "absents": [], "xi": ["G. Restes", "A. Amaaouch"], "bench": ["C. Tengstedt"]}, "away": {"team": "Strasbourg", "absents": [], "xi": ["J. Panichelli"], "bench": []}}}}
        c, out = run([{"name": "E", "legs": [{"event_id": 1, "mk": "buteur", "pick": "Tengstedt"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]}], dispo=dispo)
        self.assertTrue(any("remplaçant" in e for e in c.errors))
        c, out = run([{"name": "E", "legs": [{"event_id": 1, "mk": "buteur", "pick": "Amaaouch"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]}], dispo=dispo)
        self.assertEqual(c.errors, []); self.assertEqual(out["tickets"][0]["checks"]["dispo"], "ok")
        c, out = run([{"name": "E", "legs": [{"event_id": 1, "mk": "buteur", "pick": "Amaaouch"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]}], dispo={"matches": {}})
        self.assertEqual(out["tickets"][0]["checks"]["dispo"], "unknown")

    def test_couverture_entre_tickets(self):
        c, out = run([{"name": "F", "legs": [{"event_id": 1, "mk": "1N2", "pick": "1"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]},
                      {"name": "G", "legs": [{"event_id": 1, "mk": "1N2", "pick": "N"}, {"event_id": 3, "mk": "1N2", "pick": "1"}]}])
        self.assertTrue(any("couvre" in e for e in c.errors))
        c, out = run([{"name": "F", "legs": [{"event_id": 1, "mk": "1N2", "pick": "1"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]},
                      {"name": "G", "legs": [{"event_id": 1, "mk": "DC", "pick": "1/N"}, {"event_id": 3, "mk": "1N2", "pick": "1"}]}])  # compatible
        self.assertEqual(c.errors, [])
        c, out = run([{"name": "F", "legs": [{"event_id": 1, "mk": "OU25", "pick": "Plus"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]},
                      {"name": "G", "legs": [{"event_id": 1, "mk": "OU25", "pick": "Moins"}, {"event_id": 3, "mk": "1N2", "pick": "1"}]}])
        self.assertTrue(any("couvre" in e for e in c.errors))

    def test_deadline(self):
        c, _ = run([{"name": "H", "legs": [{"event_id": 1, "mk": "1N2", "pick": "1"}, {"event_id": 2, "mk": "1N2", "pick": "1"}]}], now=1793994000 - 20 * 60)
        self.assertTrue(any("marge" in e for e in c.errors))

    def test_noms_joueurs(self):
        self.assertTrue(ct.same_player("Amaaouch, Aymen", "A. Amaaouch"))
        self.assertTrue(ct.same_player("Casper Tengstedt", "C. Tengstedt"))
        self.assertFalse(ct.same_player("Casper Tengstedt", "J. Tengstedt"))
        self.assertTrue(ct.same_player("Ortega, Jacobo", "Jacobo Ortega"))
        self.assertFalse(ct.same_player("Emanuel Emegha", "Casper Tengstedt"))


if __name__ == "__main__":
    unittest.main()
