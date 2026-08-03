import json
from pathlib import Path

from utils.benchmark_reference import build_benchmark_reference


def test_dual_benchmark_windows_are_kept_separate():
    report = json.loads(Path('data/benchmark_dagger.json').read_text(encoding='utf-8'))
    result = build_benchmark_reference(report, ingame_displayed_dps=42406)
    assert result['damage'] == 3952297
    assert result['elite_insights']['dps'] == 42040
    assert result['ingame']['dps'] == 42406
    assert 0.80 < result['comparison']['window_difference_s'] < 0.82
    assert result['comparison']['same_damage_basis'] is True
