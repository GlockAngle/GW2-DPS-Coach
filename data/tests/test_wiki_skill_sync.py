from utils.wiki_skill_sync import build_wiki_override


def test_parses_skill_infobox_and_damage_fact():
    skill = {"id": 999, "name": "Test Skill", "slot": "Weapon_2", "weapon_type": "Dagger", "type": "Weapon"}
    page = {
        "revid": 123,
        "fullurl": "https://wiki.guildwars2.com/wiki/Test_Skill",
        "text": """
{{Skill infobox
| profession = thief
| slot = weapon
| mainhand = dagger
| weapon slot = 2
| activation = 0.75
| initiative = 3
| recharge = 0
| id = 999
| facts =
{{skill fact|damage|100|coefficient=1.25|strikes=2}}
{{skill fact|poison|4|stacks=2}}
}}
""",
    }
    result = build_wiki_override(skill, page, "Test Skill")
    assert result["power_coefficient"] == 1.25
    assert result["hits"] == 2
    assert result["cast_time"] == 0.75
    assert result["initiative_cost"] == 3
    assert result["conditions"][0] == {"condition": "Poison", "stacks": 2, "duration": 4.0}
    assert result["data_status"] == "Wiki verified"


def test_flags_same_name_id_mismatch():
    skill = {"id": 999, "name": "Duplicate", "slot": "Weapon_1", "weapon_type": "Dagger", "type": "Weapon"}
    page = {
        "revid": 123,
        "fullurl": "https://wiki.guildwars2.com/wiki/Duplicate",
        "text": "{{Skill infobox|profession=thief|slot=weapon|mainhand=dagger|weapon slot=1|activation=0.5|id=1000|facts={{skill fact|damage|1|coefficient=0.5}}}}",
    }
    result = build_wiki_override(skill, page, "Duplicate")
    assert result["data_status"] == "Partial"
    assert any("does not match" in flag for flag in result["review_flags"])
