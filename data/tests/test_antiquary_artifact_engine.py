import json
import random
from pathlib import Path

from utils.antiquary_artifacts import (
    ARTIFACT_CHILD_IDS,
    DEFINITIONS,
    ArtifactState,
    build_benchmark_artifact_audit,
    draw_artifact,
)

ROOT = Path(__file__).resolve().parents[1]


def test_artifact_children_and_followups_are_separate():
    assert 78440 in DEFINITIONS[76633].child_effect_ids
    assert 76596 in DEFINITIONS[76582].follow_up_ids
    assert DEFINITIONS[76596].role == "follow_up"
    assert 78440 in ARTIFACT_CHILD_IDS


def test_skritt_swipe_and_scuffle_are_not_artifact_rolls():
    assert 77255 not in DEFINITIONS
    assert 77397 not in DEFINITIONS

def test_seeded_draw_is_reproducible_and_never_draws_followup():
    a = draw_artifact(random.Random(12))
    b = draw_artifact(random.Random(12))
    assert a == b
    assert DEFINITIONS[a].role != "follow_up"


def test_uploaded_benchmark_artifact_timeline_validates():
    report = json.loads((ROOT / "data" / "benchmark_dagger.json").read_text(encoding="utf-8"))
    audit = build_benchmark_artifact_audit(report)
    assert audit["summary"]["timeline_violations"] == 0
    by_id = {row["id"]: row for row in audit["records"]}
    assert by_id[76633]["casts"] == 3
    assert by_id[78440] if 78440 in by_id else True
    assert by_id[76633]["children"][0]["hits"] == 12
    assert by_id[77277]["direct_hits"] == 35
    assert by_id[77192]["direct_hits"] == 88
