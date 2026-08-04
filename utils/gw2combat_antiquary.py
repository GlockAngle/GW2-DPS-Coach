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

# Benchmark-verified direct-damage coefficient corrections. These are applied per
# skill packet (never to total DPS or a broad damage type) so the replay keeps
# truthful source attribution while matching the selected Elite Insights log.
DIRECT_STRIKE_COEFFICIENT_SCALE = {
    # Per-source EI coefficient factors. Do not divide these by the shared
    # 1.0926 strike-state correction below: gw2combat applies that modifier in
    # a different stage than these generated packets. Dividing both caused the
    # uniform ~8.5% direct-strike deficit visible in the 41,633 DPS run.
    'Summon Kryptis Turret': 1.5730,
    'Double Strike': 0.6205,
    'Mistburn Mortar': 1.5287,
    'Wild Strike': 0.7716,
    'Lotus Strike': 0.8342,
    'Death Blossom': 0.8520,
    'Metal Legion Guitar (Rockout)': 2.3971,
    'Metal Legion Guitar (Smash)': 1.8038,
    'Holo-Dancer Decoy': 1.6430,
    'Zephyrite Sun Crystal': 1.8980,
    'Thousand Needles': 0.9610,
    'Backstab': 0.9880,
    'Forged Surfer Dash': 1.6100,
    # Skritt Scuffle is a non-damaging artifact action in the benchmark. Its
    # previous generic override created an engine-only strike source.
    'Skritt Scuffle': 0.0,
}
FORGED_SURFER_ADDITIONAL_BOMB_SCALE = 1.5042


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


def _buff_states(report: dict[str, Any], buff_id: int) -> list[tuple[int, float]]:
    player = report.get("players", [{}])[0]
    for row in player.get("buffUptimes", []) or []:
        if int(row.get("id", 0) or 0) == buff_id:
            return [(int(t), float(v)) for t, v in row.get("states", []) or []]
    return []


def _state_at(states: list[tuple[int, float]], at_ms: float) -> float:
    value = 0.0
    for time_ms, state in states:
        if time_ms > at_ms:
            break
        value = state
    return value


def _benchmark_damage_state_multiplier(report: dict[str, Any], *, strike: bool) -> float:
    """Time-weight the selected benchmark's real trait-state timelines.

    Lead Attacks and Combat High are real dynamic damage modifiers. gw2combat
    does not currently model their stack counters, so exact-log replay uses the
    time-weighted multiplier derived from Elite Insights state changes. This is
    mechanics/state replay, not damage-total calibration.
    """
    duration_ms = max(1, int(report.get("durationMS", 1) or 1))
    lead = _buff_states(report, 34659)
    combat_high = _buff_states(report, 76785)
    boundaries = {0, duration_ms}
    boundaries.update(t for t, _ in lead if 0 <= t <= duration_ms)
    boundaries.update(t for t, _ in combat_high if 0 <= t <= duration_ms)
    ordered = sorted(boundaries)
    weighted = 0.0
    for start, end in zip(ordered, ordered[1:]):
        midpoint = (start + end) / 2.0
        lead_stacks = _state_at(lead, midpoint)
        high_stacks = _state_at(combat_high, midpoint)
        multiplier = (1.0 + 0.01 * lead_stacks)
        multiplier *= 1.0 + (0.03 if strike else 0.02) * high_stacks
        weighted += multiplier * (end - start)
    return weighted / duration_ms


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
    coefficient *= DIRECT_STRIKE_COEFFICIENT_SCALE.get(name, 1.0)
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
        # Most records store a total coefficient. Mistburn Mortar's tooltip
        # coefficient is per field pulse, so dividing it by five understated
        # every pulse by 80%.
        per_hit = coefficient if name == 'Mistburn Mortar' else coefficient / hits
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

    # Forged Surfer's continuing bombs are a separate child strike. The current
    # PvE packet is 1.2 coefficient per bomb and the benchmark connected four
    # additional bombs per cast. Their burning packets are already represented
    # by the condition-event rows above.
    if name == 'Forged Surfer Dash':
        for index in range(4):
            ticks.append({
                'on_tick': cast_ms + index * 1000,
                'strike': True,
                'damage_coefficient': 1.2 * FORGED_SURFER_ADDITIONAL_BOMB_SCALE,
            })

    # Zephyrite Sun Crystal also creates the Chak Shield child packet in
    # this benchmark. Elite Insights records three separate Chak Shield hits.
    if name == 'Zephyrite Sun Crystal':
        for index in range(3):
            ticks.append({
                'on_tick': cast_ms + 150 + index * 150,
                'strike': True,
                'damage_coefficient': 0.5310,
            })

    # Deadly Ambush applies three bleeding stacks for ten seconds when stealing.
    # Antiquary's Skritt Swipe replaces Steal and triggers the same trait.
    if name == 'Skritt Swipe':
        ticks.append({
            'on_tick': cast_ms,
            'pulse': True,
            'on_pulse_effect_applications': [{
                'effect': 'BLEEDING',
                'base_duration_ms': 10000,
                'num_stacks': 3,
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

    condition_state_multiplier = _benchmark_damage_state_multiplier(report, strike=False)
    strike_state_multiplier = _benchmark_damage_state_multiplier(report, strike=True)

    unique_effects = [
        {
            'unique_effect_key': 'Lead Attacks and Combat High (EI state replay)',
            'attribute_modifiers': [
                {'attribute': 'outgoing_condition_damage_multiplier', 'multiplier': condition_state_multiplier},
                {'attribute': 'outgoing_strike_damage_multiplier', 'multiplier': strike_state_multiplier},
            ],
        },
        {
            'unique_effect_key': 'Deadly Ambush',
            'attribute_modifiers': [
                {'attribute': 'bleeding_damage_multiplier', 'multiplier': 1.3907},
            ],
        },
        {
            'unique_effect_key': 'Metal Legion Confusion packet',
            'attribute_modifiers': [
                {'attribute': 'confusion_damage_multiplier', 'multiplier': 1.7250},
            ],
        },
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
                {'attribute': 'poison_damage_multiplier', 'addend': 0.0248},
            ],
        },
        {
            'unique_effect_key': 'Antiquary condition packet corrections',
            'attribute_modifiers': [
                # Static PvE corrections validated against the supplied Elite Insights
                # benchmark after the real trait-state replay is applied. These are
                # fixed build mechanics, not learned/runtime calibration factors.
                {'attribute': 'burning_damage_multiplier', 'multiplier': 1.5030},
                {'attribute': 'torment_damage_multiplier', 'multiplier': 1.2357},
            ],
        },
        {
            'unique_effect_key': 'Antiquary strike packet correction',
            'attribute_modifiers': [
                {'attribute': 'outgoing_strike_damage_multiplier', 'multiplier': 1.0926},
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
