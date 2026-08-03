import json
import unittest
from pathlib import Path

from utils.rune_engine import calculate_rune_bonus

CORE_STATS = (
    "Power", "Toughness", "Vitality", "Precision", "Ferocity",
    "Condition Damage", "Expertise", "Concentration", "Defense", "Healing Power",
)

DATA = json.loads((Path(__file__).parents[1] / "data" / "gear_data.json").read_text(encoding="utf-8"))


class RuneEngineTests(unittest.TestCase):
    def rune(self, name):
        return calculate_rune_bonus(DATA["runes"][name], CORE_STATS, 6)

    def test_scholar_adds_ferocity(self):
        stats, _ = self.rune("Scholar")
        self.assertEqual(stats["Ferocity"], 225.0)

    def test_deadeye_adds_ferocity(self):
        stats, _ = self.rune("Deadeye")
        self.assertEqual(stats["Ferocity"], 100.0)

    def test_golemancer_adds_ferocity(self):
        stats, _ = self.rune("Golemancer")
        self.assertEqual(stats["Ferocity"], 300.0)

    def test_trapper_has_no_ferocity(self):
        stats, _ = self.rune("Trapper")
        self.assertEqual(stats["Ferocity"], 0.0)

    def test_rune_change_changes_result(self):
        scholar, _ = self.rune("Scholar")
        trapper, _ = self.rune("Trapper")
        self.assertEqual(scholar["Ferocity"] - trapper["Ferocity"], 225.0)


if __name__ == "__main__":
    unittest.main()
