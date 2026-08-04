from utils.wiki_skill_sync import _candidate_titles, _page_matches_skill


def test_candidate_titles_include_weapon_and_skill_variants():
    skill = {"name": "Backstab", "weapon_type": "Dagger", "slot": "Weapon_1"}
    titles = _candidate_titles(skill)
    assert "Backstab" in titles
    assert "Backstab (skill)" in titles
    assert "Backstab (Dagger)" in titles


def test_page_match_requires_exact_game_id():
    page = {"text": "{{Skill infobox| id = 13005 | slot = weapon | weapon slot = 1}}"}
    assert _page_matches_skill(page, "13005")
    assert not _page_matches_skill(page, "13004")
