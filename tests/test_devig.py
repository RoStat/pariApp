"""Dévig : les probabilités justes somment à 1 ; 1,80 / 3,60 / 4,80 au prorata -> p_dom = 0,533."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from common import devig, kelly_fraction  # noqa: E402


class TestDevig(unittest.TestCase):
    def test_proportional(self):
        p = devig([1.80, 3.60, 4.80])
        self.assertAlmostEqual(sum(p), 1.0, places=9)
        self.assertAlmostEqual(p[0], 0.533, places=3)
        self.assertAlmostEqual(p[1], 0.267, places=3)
        self.assertAlmostEqual(p[2], 0.200, places=3)

    def test_power(self):
        p = devig([1.80, 3.60, 4.80], "power")
        self.assertAlmostEqual(sum(p), 1.0, places=6)
        self.assertGreater(p[0], 0.533)  # la méthode "power" charge davantage l'outsider

    def test_deux_issues(self):
        p = devig([1.90, 1.90])
        self.assertAlmostEqual(p[0], 0.5)

    def test_kelly(self):
        self.assertAlmostEqual(kelly_fraction(0.5, 2.2), (0.5 * 2.2 - 1) / 1.2)
        self.assertLess(kelly_fraction(0.4, 2.2), 0)


if __name__ == "__main__":
    unittest.main()
