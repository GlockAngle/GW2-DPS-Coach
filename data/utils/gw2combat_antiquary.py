from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = PROJECT_ROOT / 'data' / 'benchmark_dagger.json'
OVERRIDES_PATH = PROJECT_ROOT / 'data' / 'skills' / 'thief_skill_overrides.json'
PREDICTION_V2_PATH = PROJECT_ROOT / 'data' / 'full_benchmark_prediction_v2.json'
GOLEM_PATH = PROJECT_ROOT / 'vendor' / 'gw2combat' / 'resources' / 'build-golem-fractal-relic.json'


@dataclass(frozen=True)
class AntiquaryPackage:
    encounter: dict[str, Any]
    files: dict[str, Any]
    coverage: dict[str, Any]


def _skill_name_map(report: dict[str, Any]) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw_id, record in report.get('skillMap', {}).items():
        try:
            skill_id = int(str(raw_id).lstrip('s'))
        except ValueError:
            continue
        if isinstance(record, dict) and record.get('name'):
            result[skill_id] = str(record['name'])
    return result


def _rotation_casts(report: dict[str, Any]) -> list[dict[str, Any]]:
    player = report.get('players', [{}])[0]
    names = _skill_name_map(report)
    casts: list[dict[str, Any]] = []
    for group in player.get('rotation', []):
        skill_id = int(group.get('id', 0))
        name = names.get(skill_id, f'Skill {skill_id}')
        for cast in group.get('skills', []):
            casts.append({
                'skill_id': skill_id,
                'name': name,
                'cast_time_ms': int(cast.get('castTime', 0)),
                'duration_ms': max(0, int(cast.get('duration', 0))),
            })
    casts.sort(key=lambda item: item['cast_time_ms'])
    if casts:
        offset = casts[0]['cast_time_ms']
        for cast in casts:
            cast['cast_time_ms'] -= offset
    return casts


def _condition_name(value: str) -> str | None:
    mapping = {
        'bleeding': 'BLEEDING',
        'burning': 'BURNING',
        'poison': 'POISON',
        'torment': 'TORMENT',
        'confusion': 'CONFUSION',
        'weakness': 'WEAKNESS',
        'immobilize': 'IMMOBILIZED',
        'cripple': 'CRIPPLED',
    }
    return mapping.get(value.strip().lower())


def _weapon_type(record: dict[str, Any]) -> str:
    weapon = str(record.get('classification', {}).get('weapon', 'None')).lower()
    if weapon in {'dagger', 'axe', 'pistol', 'sword', 'staff', 'shortbow', 'rifle', 'spear'}:
        return weapon
    return 'empty_handed'


def _skill_from_override(name: str, record: dict[str, Any], fallback_duration_ms: int) -> dict[str, Any]:
    configured_cast_ms = int(round(float(record.get('effective_action_time', record.get('cast_time', fallback_duration_ms / 1000 or 0.25))) * 1000))
    configured_cast_ms = max(0, configured_cast_ms)

    # Benchmark replay mode: the rotation CSV already contains the authoritative
    # timestamps captured by Elite Insights. Giving skills an animation lock or
    # recharge here made gw2combat delay/skip roughly one third of the 173 logged
    # casts. Keep the engine cast instant and schedule the actual hit packets at
    # the logged cast-duration offset instead. This preserves the observed
    # timeline while still letting gw2combat own damage, conditions and procs.
    cast_ms = max(0, int(fallback_duration_ms or configured_cast_ms))
    cooldown_ms = 0
    hits = max(0, int(record.get('hits', 0) or 0))
    coefficient = float(record.get('power_coefficient', 0) or 0)
    skill: dict[str, Any] = {
        'skill_key': name,
        'weapon_type': _weapon_type(record),
        'cast_duration': [0, 0],
        'cooldown': [cooldown_ms, cooldown_ms],
        'instant_cast_only_when_not_in_animation': False,
        'executable': True,
    }
    ticks: list[dict[str, Any]] = []
    if hits and coefficient > 0:
        per_hit = coefficient / hits
        for index in range(hits):
            tick = int(round((cast_ms or 1) * (index + 1) / hits))
            ticks.append({'on_tick': tick, 'strike': True, 'damage_coefficient': per_hit})

    # Preserve pulse timing instead of collapsing every packet at cast completion.
    # This matters for field skills, artifact child hits, condition overlap and end-of-fight truncation.
    events = record.get('condition_events') or []
    for event in events:
        condition = _condition_name(str(event.get('condition', '')))
        if not condition:
            continue
        duration_ms = int(round(float(event.get('base_duration', 0) or 0) * 1000))
        interval_ms = int(round(float(event.get('interval', 0) or 0) * 1000))
        hits_count = max(1, int(event.get('hits', 1) or 1))
        stacks = max(1, int(event.get('stacks_per_application', event.get('applications_per_trigger', 1)) or 1))
        applications = max(1, int(event.get('applications_per_hit', 1) or 1))
        charges = int(event.get('charges', 0) or 0)

        if charges:
            hits_count = charges
            # Spider Venom is shared to four allies. In GW2 the venom owner's
            # condition damage is credited for those shared applications.
            recipients = 1 + int(event.get('shared_to_allies', 0) or 0)
            stacks *= recipients
            interval_ms = interval_ms or 250

        for index in range(hits_count):
            on_tick = cast_ms + (index * interval_ms if interval_ms else 0)
            ticks.append({
                'on_tick': on_tick,
                'pulse': True,
                'on_pulse_effect_applications': [{
                    'effect': condition,
                    'base_duration_ms': duration_ms,
                    'num_stacks': max(1, applications * stacks),
                    'direction': 'OUTGOING',
                }],
            })

    if not events:
        for condition_row in record.get('conditions', []) or []:
            condition = _condition_name(str(condition_row.get('condition', '')))
            if not condition:
                continue
            ticks.append({
                'on_tick': cast_ms,
                'pulse': True,
                'on_pulse_effect_applications': [{
                    'effect': condition,
                    'base_duration_ms': int(round(float(condition_row.get('duration', 0) or 0) * 1000)),
                    'num_stacks': max(1, int(condition_row.get('stacks', 1) or 1)),
                    'direction': 'OUTGOING',
                }],
            })

    # Deadly Ambition: dual-wield attacks apply two poison stacks for three seconds in PvE.
    # Death Blossom is the benchmark's repeated dagger/dagger dual-wield skill.
    if name == 'Death Blossom':
        ticks.append({
            'on_tick': cast_ms,
            'pulse': True,
            'on_pulse_effect_applications': [{
                'effect': 'POISON',
                'base_duration_ms': 3000,
                'num_stacks': 2,
                'direction': 'OUTGOING',
            }],
        })

    if ticks:
        skill['skill_ticks'] = ticks
    return skill

def _placeholder_skill(name: str, duration_ms: int) -> dict[str, Any]:
    return {
        'skill_key': name,
        'weapon_type': 'empty_handed',
        'cast_duration': [0, 0],
        'cooldown': [0, 0],
        'instant_cast_only_when_not_in_animation': False,
        'executable': True,
    }


def _rotation_csv(casts: list[dict[str, Any]]) -> str:
    """Return the exact CSV dialect expected by upstream gw2combat.

    gw2combat's CSV reader advances two characters after the comma because its
    bundled rotations use `Skill, Time: ...`. Python's csv.writer emits
    `Skill,Time: ...` without that space, which made the reader discard the
    first character of every timestamp. As a result 93.800s became 3.800s and
    the full benchmark was compressed into roughly nine seconds.
    """
    lines = ['rotation']
    for cast in casts:
        name = str(cast['name'])
        if ',' in name or '\n' in name or '\r' in name:
            raise ValueError(f'gw2combat rotation skill name is not CSV-safe: {name!r}')
        lines.append(f"{name}, Time: {cast['cast_time_ms'] / 1000:.3f}s")
    return '\n'.join(lines) + '\n'


def build_antiquary_benchmark_package() -> AntiquaryPackage:
    report = json.loads(BENCHMARK_PATH.read_text(encoding='utf-8'))
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding='utf-8'))
    profile = json.loads(PREDICTION_V2_PATH.read_text(encoding='utf-8')).get('profile', {})
    golem = json.loads(GOLEM_PATH.read_text(encoding='utf-8'))
    casts = _rotation_casts(report)

    duration_by_name: dict[str, list[int]] = {}
    id_by_name: dict[str, int] = {}
    for cast in casts:
        duration_by_name.setdefault(cast['name'], []).append(cast['duration_ms'])
        id_by_name[cast['name']] = cast['skill_id']

    skills: list[dict[str, Any]] = []
    supported_names: list[str] = []
    placeholder_names: list[str] = []
    for name in sorted(duration_by_name):
        durations = sorted(duration_by_name[name])
        fallback = durations[len(durations) // 2] if durations else 0
        skill_id = id_by_name[name]
        record = overrides.get(str(skill_id))
        if not isinstance(record, dict) and name == 'Metal Legion Guitar (Smash)':
            # Current PvE final-smash packet from the Metal Legion Guitar artifact.
            record = {
                'classification': {'weapon': 'Artifact'},
                'cast_time': max(0.0, fallback / 1000.0),
                'effective_action_time': max(0.0, fallback / 1000.0),
                'power_coefficient': 2.51,
                'hits': 2,
            }
        if isinstance(record, dict):
            skills.append(_skill_from_override(name, record, fallback))
            supported_names.append(name)
        else:
            skills.append(_placeholder_skill(name, fallback))
            placeholder_names.append(name)

    unique_effects = [
        {
            'unique_effect_key': 'Superior Sigil of Force',
            'attribute_modifiers': [{
                'attribute': 'outgoing_strike_damage_multiplier',
                'multiplier': 1.05,
            }],
        },
        {
            'unique_effect_key': 'Superior Sigil of Earth',
            'skill_triggers': [{
                'condition': {
                    'depends_on_skill_off_cooldown': 'Earth Sigil Proc',
                    'only_applies_on_strikes': True,
                    'only_applies_on_critical_strikes': True,
                },
                'skill_key': 'Earth Sigil Proc',
            }],
        },
        {
            'unique_effect_key': 'Relic of the Fractal',
            'skill_triggers': [{
                'condition': {
                    'depends_on_skill_off_cooldown': 'Relic of the Fractal Proc',
                    'only_applies_on_effect_application': True,
                    'only_applies_on_effect_application_of_type': 'BLEEDING',
                    'effect_on_target': 'BLEEDING',
                    'stacks_of_effect_on_target': 6,
                },
                'skill_key': 'Relic of the Fractal Proc',
            }],
        },
        {
            'unique_effect_key': 'Potent Poison',
            'attribute_modifiers': [
                {'attribute': 'poison_duration_multiplier', 'addend': 0.33},
                {'attribute': 'poison_damage_multiplier', 'addend': 0.33},
            ],
        },
        {
            'unique_effect_key': 'Benchmark Condition Duration',
            'attribute_modifiers': [
                # Expertise supplies +42.2%. These additions reproduce the
                # benchmark profile: 57.2% general, 92.2% bleeding and 90.2% poison.
                {'attribute': 'condition_duration_multiplier', 'addend': 0.15},
                {'attribute': 'bleeding_duration_multiplier', 'addend': 0.50},
                {'attribute': 'poison_duration_multiplier', 'addend': 0.15},
            ],
        },
        {
            'unique_effect_key': 'Exposed Weakness',
            'attribute_modifiers': [{
                'attribute': 'outgoing_strike_damage_multiplier_add_group',
                'addend': 0.20,
            }],
        },
        {
            'unique_effect_key': 'Twin Fangs',
            'attribute_modifiers': [
                {'attribute': 'critical_chance_multiplier', 'addend': 0.07},
                {'attribute': 'critical_damage_multiplier', 'addend': 0.07},
            ],
        },
        {
            'unique_effect_key': 'Ferocious Strikes',
            'attribute_modifiers': [{
                'attribute': 'critical_damage_multiplier',
                'addend': 0.10,
            }],
        },
    ]
    skills.extend([
        {
            'skill_key': 'Earth Sigil Proc',
            'cast_duration': [0, 0],
            'cooldown': [2000, 2000],
            'pulse_on_tick_list': [[0], [0]],
            'on_pulse_effect_applications': [{
                'effect': 'BLEEDING', 'base_duration_ms': 6000, 'num_stacks': 1, 'direction': 'OUTGOING'
            }],
        },
        {
            'skill_key': 'Relic of the Fractal Proc',
            'cast_duration': [0, 0],
            'cooldown': [20000, 20000],
            'pulse_on_tick_list': [[0], [0]],
            'on_pulse_effect_applications': [
                {'effect': 'BURNING', 'base_duration_ms': 8000, 'num_stacks': 2, 'direction': 'OUTGOING'},
                {'effect': 'TORMENT', 'base_duration_ms': 8000, 'num_stacks': 3, 'direction': 'OUTGOING'},
            ],
        },
    ])

    player_build = {
        'base_class': 'thief',
        'profession': 'antiquary',
        'attributes': [
            ['power', int(round(float(profile.get('power', 2923))))],
            ['precision', int(round(float(profile.get('precision', 1633))))],
            ['condition_damage', int(round(float(profile.get('condition_damage', 2677.18))))],
            ['expertise', 633],
            ['ferocity', int(round(float(profile.get('ferocity', 0))))],
        ],
        'weapons': [
            {'type': 'dagger', 'position': 'main_hand', 'set': 'set_1'},
            {'type': 'dagger', 'position': 'off_hand', 'set': 'set_1'},
        ],
        'initial_weapon_set': 'set_1',
        'recipe_paths': [],
        'permanent_effects': ['QUICKNESS', 'ALACRITY', 'FURY'],
        'permanent_unique_effects': unique_effects,
        'skills': skills,
    }
    encounter = {
        'actors': [
            {'name': 'player', 'build_path': 'generated/antiquary-build.json', 'rotation_path': 'generated/antiquary-rotation.csv', 'team': 1},
            {'name': 'golem', 'build_path': 'generated/golem.json', 'team': 2},
        ],
        'termination_conditions': [
            {'type': 'TIME', 'time': int(report.get('durationMS', 94013))},
            {'type': 'ROTATION', 'actor': 'player'},
        ],
        'audit_configuration': {'audits_to_perform': ['SKILL_CASTS', 'EFFECT_APPLICATIONS', 'DAMAGE', 'COMBAT_STATS']},
        'require_afk_skills': False,
        'audit_offset': 0,
        'condition_tick_offset': 200,
        'weapon_strength_mode': 'MEAN',
        'critical_strike_mode': 'MEAN',
    }
    files: dict[str, Any] = {
        'generated/antiquary-build.json': player_build,
        'generated/antiquary-rotation.csv': _rotation_csv(casts),
        'generated/golem.json': golem,
    }
    coverage = {
        'casts': len(casts),
        'unique_skills': len(duration_by_name),
        'supported_unique_skills': len(supported_names),
        'placeholder_unique_skills': len(placeholder_names),
        'supported_names': supported_names,
        'placeholder_names': placeholder_names,
        'support_pct': round(100 * len(supported_names) / max(1, len(duration_by_name)), 2),
        'replay_mode': 'exact_log_timestamps',
        'expected_cast_counts': dict(sorted((name, len(rows)) for name, rows in duration_by_name.items())),
    }
    return AntiquaryPackage(encounter=encounter, files=files, coverage=coverage)
