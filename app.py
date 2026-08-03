import base64
import json
from datetime import date, datetime
from pathlib import Path
from utils.skill_library import render_skill_library_page, live_damage_ready_skills, simulate_live_skill
from utils.gw2combat_adapter import engine_status, run_encounter, run_bundled_example, audit_summary, VENDOR_ROOT
from utils.gw2combat_antiquary import build_antiquary_benchmark_package

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

from utils.conditions import (
    CONDITION_NAMES,
    analyse_conditions_from_url,
)
from utils.parser import (
    analyse_basic_report,
    calculate_allies_damage,
)
from utils.gear_simulator import (
    render_gear_simulator_page,
    initialize_persistent_build_state,
    autosave_trait_state,
)
from utils.thief_traits import render_traits_page, render_trait_progress_page

# --------------------------------------------------
# Local benchmark history
# --------------------------------------------------

HISTORY_FILE = Path(__file__).with_name("antiquary_history.json")


def load_benchmark_history():
    """Load locally saved benchmark sessions."""
    if not HISTORY_FILE.exists():
        return []

    try:
        saved_data = json.loads(
            HISTORY_FILE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(saved_data, list):
        return saved_data

    return []


def save_benchmark_history(history):
    """Persist benchmark sessions next to app.py."""
    HISTORY_FILE.write_text(
        json.dumps(history, indent=2),
        encoding="utf-8",
    )


def create_session_record(
    patch_name,
    session_name,
    session_date,
    results,
):
    """Create one history entry from analysed bulk results."""
    return {
        "session_id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "patch": patch_name.strip(),
        "session_name": session_name.strip(),
        "session_date": session_date.isoformat(),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "logs": results,
    }



# --------------------------------------------------
# Bulk damage-profile helpers
# --------------------------------------------------

SPIDER_VENOM_ID = 13037
SPIDER_VENOM_DURATION = 6.0
SPIDER_VENOM_ALLY_DAMAGE_PER_CAST = 0.8 * 72.609 * 1000
DAMAGE_PROFILE_CACHE_VERSION = 2


def _normalise_profile_report_url(report_url):
    """Return a clean normal dps.report permalink."""
    clean_url = str(report_url or "").strip()

    if not clean_url:
        raise ValueError("The dps.report link is empty.")

    clean_url = clean_url.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    if clean_url.endswith(".json"):
        clean_url = clean_url[:-5]

    if not clean_url.startswith(("https://dps.report/", "http://dps.report/")):
        raise ValueError(f"Invalid dps.report link: {report_url}")

    return clean_url


@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_profile_report_json_v2(report_url):
    """
    Download Elite Insights JSON using the real dps.report API.

    Appending '.json' to a normal permalink returns 404. The supported
    endpoint is /getJson with the original permalink as its parameter.
    """
    permalink = _normalise_profile_report_url(report_url)

    response = requests.get(
        "https://dps.report/getJson",
        params={"permalink": permalink},
        timeout=45,
        headers={
            "User-Agent": "Mozilla/5.0 GW2-Antiquary-Benchmark/2.0"
        },
    )
    response.raise_for_status()

    try:
        report = response.json()
    except requests.JSONDecodeError as error:
        raise ValueError(
            "dps.report returned a response that was not valid JSON."
        ) from error

    if not isinstance(report, dict):
        raise ValueError("The downloaded report JSON has an invalid structure.")

    return report


def _player_total_damage(player):
    """Read full-fight damage from common Elite Insights structures."""
    dps_all = player.get("dpsAll", [])

    if not isinstance(dps_all, list) or not dps_all:
        return 0.0

    phase = dps_all[0]

    if isinstance(phase, dict):
        try:
            return float(phase.get("damage", 0.0))
        except (TypeError, ValueError):
            return 0.0

    if isinstance(phase, list) and phase:
        first_entry = phase[0]

        if isinstance(first_entry, dict):
            try:
                return float(first_entry.get("damage", 0.0))
            except (TypeError, ValueError):
                return 0.0

    return 0.0


def _main_player(report):
    """Choose the benchmark player with the highest full-fight damage."""
    all_players = [
        player
        for player in report.get("players", [])
        if isinstance(player, dict)
    ]

    players = [
        player
        for player in all_players
        if not player.get("friendlyNPC", False)
        and not player.get("notInSquad", False)
    ]

    if not players:
        players = all_players

    if not players:
        raise ValueError("The report contains no players.")

    return max(players, key=_player_total_damage)


def _extract_cumulative_damage(player):
    """Return the main cumulative one-second damage series."""
    damage_1s = player.get("damage1S")

    if damage_1s is None:
        damage_1s = player.get("Damage1S")

    if not isinstance(damage_1s, list) or not damage_1s:
        raise ValueError("This log has no damage1S timeline.")

    # EI normally stores one series per phase. Use the full-fight phase.
    first_phase = damage_1s[0]

    if isinstance(first_phase, list):
        return first_phase

    # Defensive fallback for a directly stored timeline.
    if all(isinstance(value, (int, float, type(None))) for value in damage_1s):
        return damage_1s

    raise ValueError("The damage1S timeline has an unsupported structure.")


def _cumulative_to_per_second(cumulative):
    """Convert cumulative damage values to per-second damage."""
    per_second = []
    previous = 0.0

    for value in cumulative:
        try:
            current = float(value or 0.0)
        except (TypeError, ValueError):
            current = previous

        per_second.append(max(0.0, current - previous))
        previous = current

    return per_second


def _rotation_casts(rotation_entry):
    """Return casts regardless of the Elite Insights field name."""
    for key in ("skills", "casts", "rotation"):
        value = rotation_entry.get(key)

        if isinstance(value, list):
            return value

    return []


def _cast_start_seconds(cast):
    """Extract a cast start timestamp and convert milliseconds to seconds."""
    for key in (
        "castTime",
        "time",
        "start",
        "startTime",
        "timestamp",
        "activationTime",
        "t",
    ):
        value = cast.get(key)

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue

        return numeric_value / 1000.0 if numeric_value > 1000 else numeric_value

    return None


def _spider_venom_cast_starts(report):
    """Return all Spider Venom cast starts from the selected player."""
    player = _main_player(report)
    cast_starts = []

    for rotation_entry in player.get("rotation", []):
        if not isinstance(rotation_entry, dict):
            continue

        skill_id = rotation_entry.get(
            "id",
            rotation_entry.get(
                "skillId",
                rotation_entry.get("skillID"),
            ),
        )
        skill_name = str(
            rotation_entry.get(
                "name",
                rotation_entry.get("skillName", ""),
            )
        ).strip().lower()

        is_spider_venom = (
            str(skill_id) == str(SPIDER_VENOM_ID)
            or skill_name == "spider venom"
        )

        if not is_spider_venom:
            continue

        for cast in _rotation_casts(rotation_entry):
            if not isinstance(cast, dict):
                continue

            cast_start = _cast_start_seconds(cast)

            if cast_start is not None:
                cast_starts.append(cast_start)

    return sorted(cast_starts)


def _add_ally_venom(profile, cast_starts, killtime):
    """Add simulated allied Spider Venom damage to each one-second bin."""
    result = [float(value) for value in profile]
    required_length = max(len(result), int(killtime) + 1)

    while len(result) < required_length:
        result.append(0.0)

    damage_rate = (
        SPIDER_VENOM_ALLY_DAMAGE_PER_CAST
        / SPIDER_VENOM_DURATION
    )

    for cast_start in cast_starts:
        active_start = max(0.0, float(cast_start))
        active_end = min(
            float(killtime),
            active_start + SPIDER_VENOM_DURATION,
        )

        if active_end <= active_start:
            continue

        first_bin = int(active_start)
        last_bin = min(
            len(result) - 1,
            int(active_end - 1e-9),
        )

        for second in range(first_bin, last_bin + 1):
            overlap = max(
                0.0,
                min(second + 1.0, active_end)
                - max(float(second), active_start),
            )
            result[second] += damage_rate * overlap

    return result


def _build_log_profile_v2(log_row):
    """Build one corrected allied per-second DPS profile."""
    report = _fetch_profile_report_json_v2(log_row["Report URL"])
    player = _main_player(report)

    cumulative = _extract_cumulative_damage(player)
    raw_profile = _cumulative_to_per_second(cumulative)

    killtime = float(log_row["Killtime"])
    if killtime <= 0:
        raise ValueError("Killtime must be greater than zero.")

    # Include the partial final second rather than discarding it.
    profile_seconds = max(1, int(killtime) + (1 if killtime % 1 else 0))
    raw_profile = raw_profile[:profile_seconds]

    if not raw_profile:
        raise ValueError("The damage1S timeline was empty.")

    # Reconstruct total damage while respecting a partial final second.
    full_seconds = int(killtime)
    final_fraction = killtime - full_seconds
    reconstructed_damage = sum(raw_profile[:full_seconds])

    if final_fraction > 0 and full_seconds < len(raw_profile):
        reconstructed_damage += raw_profile[full_seconds] * final_fraction

    raw_average = reconstructed_damage / killtime
    in_game_dps = float(log_row["In-game Damage"])
    scale = in_game_dps / raw_average if raw_average > 0 else 1.0

    scaled_solo = [value * scale for value in raw_profile]
    ew_correction = float(log_row["EW Correction"])
    corrected_solo = [
        max(0.0, value - ew_correction)
        for value in scaled_solo
    ]

    cast_starts = _spider_venom_cast_starts(report)
    corrected_allied = _add_ally_venom(
        corrected_solo,
        cast_starts,
        killtime,
    )[:profile_seconds]

    return {
        "profile": corrected_allied,
        "cast_starts": cast_starts,
        "killtime": killtime,
    }


@st.cache_data(show_spinner=False, ttl=3600)
def _build_session_profile_v2(serialized_rows, cache_version):
    """Average the valid damage profiles and collect Venom timings."""
    del cache_version  # Used only to force invalidation after parser changes.

    rows = json.loads(serialized_rows)
    profiles = []
    cast_starts_by_log = []
    errors = []

    for row in rows:
        try:
            result = _build_log_profile_v2(row)
            profiles.append(result["profile"])
            cast_starts_by_log.append(result["cast_starts"])
        except Exception as error:
            errors.append(
                f'Log {row.get("Log", "?")}: '
                f'{type(error).__name__}: {error}'
            )

    if not profiles:
        return {
            "times": [],
            "average_profile": [],
            "cast_frequency": [],
            "median_casts": [],
            "included_logs": 0,
            "errors": errors,
        }

    max_seconds = max(len(profile) for profile in profiles)
    times = list(range(max_seconds))
    average_profile = []

    for second in times:
        active_values = [
            profile[second]
            for profile in profiles
            if second < len(profile)
        ]
        average_profile.append(
            sum(active_values) / len(active_values)
            if active_values
            else 0.0
        )

    smoothed_profile = (
        pd.Series(average_profile)
        .rolling(window=3, center=True, min_periods=1)
        .mean()
        .tolist()
    )

    cast_frequency = [0.0 for _ in times]

    for cast_starts in cast_starts_by_log:
        used_seconds = {
            int(cast_start)
            for cast_start in cast_starts
            if 0 <= int(cast_start) < len(cast_frequency)
        }

        for second in used_seconds:
            cast_frequency[second] += 1.0

    log_count = len(profiles)
    cast_frequency = [
        count / log_count * 100.0
        for count in cast_frequency
    ]

    max_cast_count = max(
        (len(casts) for casts in cast_starts_by_log),
        default=0,
    )
    median_casts = []

    for cast_index in range(max_cast_count):
        timings = [
            casts[cast_index]
            for casts in cast_starts_by_log
            if len(casts) > cast_index
        ]

        if timings:
            median_casts.append(
                {
                    "cast": cast_index + 1,
                    "time": float(pd.Series(timings).median()),
                    "logs": len(timings),
                }
            )

    return {
        "times": times,
        "average_profile": smoothed_profile,
        "cast_frequency": cast_frequency,
        "median_casts": median_casts,
        "included_logs": log_count,
        "errors": errors,
    }


# --------------------------------------------------
# Sidebar SVG assets
# --------------------------------------------------

SIDEBAR_ICON_DIR = Path(__file__).with_name("assets") / "sidebar"


def svg_data_uri(filename):
    """Return a local SVG as a self-contained data URI."""
    svg_path = SIDEBAR_ICON_DIR / filename
    encoded = base64.b64encode(svg_path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


SIDEBAR_NAV_ICONS = [
    svg_data_uri("overview.svg"),
    svg_data_uri("benchmark.svg"),
    svg_data_uri("gear.svg"),
    svg_data_uri("traits.svg"),
    svg_data_uri("skills.svg"),
    svg_data_uri("progress.svg"),
]


# --------------------------------------------------
# Page settings
# --------------------------------------------------

st.set_page_config(
    page_title="Thief Lab by Junior",
    page_icon="♦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
    <style>
        .block-container {{
            padding-top: 2.6rem;
            padding-bottom: 3rem;
            max-width: min(1920px, calc(100vw - 245px));
            width: calc(100vw - 275px);
        }}

        [data-testid="stMetric"] {{
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(255, 255, 255, 0.09);
            border-radius: 14px;
            padding: 16px 18px;
        }}

        [data-testid="stMetricLabel"] {{
            font-size: 0.83rem;
            opacity: 0.78;
        }}

        [data-testid="stMetricValue"] {{
            font-size: 1.85rem;
        }}

        .benchmark-hero {{
            padding: 0.85rem 1.1rem;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.10);
            background:
                radial-gradient(circle at top right, rgba(123, 97, 255, 0.20), transparent 34%),
                linear-gradient(135deg, rgba(36, 38, 53, 0.96), rgba(20, 22, 31, 0.96));
            margin-bottom: 0.55rem;
        }}

        .benchmark-kicker {{
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-size: 0.75rem;
            opacity: 0.68;
            margin-bottom: 0.35rem;
        }}

        .benchmark-title {{
            font-size: 1.55rem;
            font-weight: 750;
            line-height: 1.15;
            margin: 0;
        }}

        .benchmark-subtitle {{
            margin-top: 0.3rem;
            font-size: 0.9rem;
            opacity: 0.78;
            max-width: 900px;
        }}

        .scope-note {{
            margin-top: 0.55rem;
            padding: 0.55rem 0.7rem;
            border-radius: 12px;
            background: rgba(123, 97, 255, 0.10);
            border: 1px solid rgba(123, 97, 255, 0.28);
            font-size: 0.92rem;
        }}

        .section-label {{
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.10em;
            opacity: 0.66;
            margin: 0.4rem 0 0.65rem 0;
        }}

        .status-card {{
            padding: 1rem 1.1rem;
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.10);
            margin-bottom: 0.75rem;
        }}

        .status-valid {{
            background: rgba(46, 160, 67, 0.11);
            border-color: rgba(46, 160, 67, 0.34);
        }}

        .status-warning {{
            background: rgba(210, 153, 34, 0.11);
            border-color: rgba(210, 153, 34, 0.34);
        }}

        .status-error {{
            background: rgba(248, 81, 73, 0.11);
            border-color: rgba(248, 81, 73, 0.34);
        }}

        .status-heading {{
            font-size: 1.06rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}

        .status-copy {{
            opacity: 0.82;
            font-size: 0.92rem;
        }}

        .insight-card {{
            padding: 1rem 1.1rem;
            border-radius: 14px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.09);
            margin-bottom: 0.75rem;
        }}

        .insight-number {{
            font-size: 1.6rem;
            font-weight: 750;
            margin-top: 0.2rem;
        }}

        .muted {{
            opacity: 0.70;
        }}

        .metric-card {{
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 14px;
            padding: 16px 18px;
            min-height: 108px;
        }}

        .metric-card-label {{
            font-size: 0.82rem;
            opacity: 0.76;
        }}

        .metric-card-value {{
            font-size: 1.85rem;
            font-weight: 650;
            line-height: 1.2;
            margin-top: 0.28rem;
        }}

        .metric-card-note {{
            font-size: 0.72rem;
            opacity: 0.60;
            margin-top: 0.35rem;
        }}

        .hero-value {{
            font-size: 3.1rem;
            font-weight: 780;
            line-height: 1.08;
            margin-top: 0.2rem;
        }}

        .correction-chip {{
            display: inline-block;
            margin-top: 0.65rem;
            padding: 0.28rem 0.55rem;
            border-radius: 999px;
            background: rgba(248, 81, 73, 0.12);
            border: 1px solid rgba(248, 81, 73, 0.28);
            font-size: 0.74rem;
            opacity: 0.90;
        }}

        .status-badge {{
            display: inline-block;
            margin-top: 0.65rem;
            padding: 0.35rem 0.65rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 650;
        }}

        .badge-valid {{
            background: rgba(46, 160, 67, 0.14);
            border: 1px solid rgba(46, 160, 67, 0.34);
        }}

        .badge-warning {{
            background: rgba(210, 153, 34, 0.14);
            border: 1px solid rgba(210, 153, 34, 0.34);
        }}

        .badge-error {{
            background: rgba(248, 81, 73, 0.14);
            border: 1px solid rgba(248, 81, 73, 0.34);
        }}

        .ew-flow {{
            display: grid;
            grid-template-columns: 1fr auto 1fr auto 1fr;
            align-items: center;
            gap: 0.75rem;
            margin-top: 0.4rem;
            margin-bottom: 0.75rem;
        }}

        .ew-arrow {{
            font-size: 1.35rem;
            opacity: 0.45;
            text-align: center;
        }}

        .section-spacer {{
            height: 0.4rem;
        }}

        div[data-testid="stDataFrame"] {{
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            overflow: hidden;
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.4rem;
        }}

        .stTabs [data-baseweb="tab"] {{
            border-radius: 10px 10px 0 0;
            padding-left: 1rem;
            padding-right: 1rem;
        }}
    

        /* Sidebar brand and navigation */
        section[data-testid="stSidebar"] {{
            width: 282px !important;
            min-width: 282px !important;
            max-width: 282px !important;
            border-right: 1px solid rgba(255,255,255,0.07);
        }}

        section[data-testid="stSidebar"] > div:first-child {{
            width: 282px !important;
            min-width: 282px !important;
            max-width: 282px !important;
            padding-top: 0.9rem;
            box-sizing: border-box;
        }}

        .sidebar-brand {{
            position: relative;
            padding: 0.45rem 0.15rem 1.15rem 0.15rem;
            margin-bottom: 0.75rem;
            border-bottom: 1px solid rgba(190,45,52,0.34);
        }}

        .sidebar-brand-title-row {{
            display: flex;
            align-items: center;
            gap: 0.62rem;
        }}

        .sidebar-brand-accent {{
            width: 4px;
            height: 34px;
            border-radius: 2px;
            background: #c83b42;
            box-shadow: 0 0 10px rgba(200,59,66,0.22);
            flex: 0 0 auto;
        }}

        .sidebar-brand-title {{
            color: #f0ecec;
            font-family: Georgia, "Times New Roman", serif;
            font-size: 1.22rem;
            font-weight: 800;
            line-height: 1;
            letter-spacing: 0.105em;
            text-transform: uppercase;
            white-space: nowrap;
        }}

        .sidebar-brand-rule {{
            width: 82px;
            height: 1px;
            margin: 0.48rem 0 0.42rem 0.66rem;
            background: linear-gradient(90deg, #c83b42 0%, rgba(200,59,66,0.08) 100%);
        }}

        .sidebar-brand-subtitle {{
            color: rgba(232,233,237,0.54);
            font-size: 0.58rem;
            font-weight: 700;
            letter-spacing: 0.24em;
            text-transform: uppercase;
            margin-left: 0.66rem;
        }}

        .sidebar-section-label {{
            color: rgba(230,233,240,0.43);
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            margin: 0.3rem 0 0.5rem 0.15rem;
        }}

        /* Stable button-based sidebar navigation. */
        section[data-testid="stSidebar"] div[class*="st-key-nav_"] {{
            width: 100% !important;
            margin: 0 0 0.34rem 0 !important;
        }}

        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button {{
            position: relative !important;
            display: grid !important;
            grid-template-columns: 18px minmax(0, 1fr) !important;
            column-gap: 0.72rem !important;
            align-items: center !important;
            justify-content: start !important;
            width: 100% !important;
            min-height: 42px !important;
            padding: 0 0.76rem !important;
            margin: 0 !important;
            border-radius: 9px !important;
            box-sizing: border-box !important;
            text-align: left !important;
            font-size: 0.86rem !important;
            font-weight: 560 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            transition: background 130ms ease, border-color 130ms ease, color 130ms ease !important;
        }}

        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button[kind="secondary"] {{
            color: rgba(235,237,242,0.78) !important;
            background: transparent !important;
            border: 1px solid transparent !important;
            box-shadow: none !important;
        }}

        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button[kind="secondary"]:hover {{
            color: #ffffff !important;
            background: rgba(255,255,255,0.045) !important;
            border-color: rgba(255,255,255,0.05) !important;
        }}

        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button[kind="primary"] {{
            color: #ffffff !important;
            background: rgba(200,59,66,0.13) !important;
            border: 1px solid rgba(200,59,66,0.36) !important;
            box-shadow: inset 3px 0 0 #d4484f !important;
        }}

        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button p {{
            grid-column: 2 !important;
            margin: 0 !important;
            padding: 0 !important;
            text-align: left !important;
            line-height: 1.2 !important;
        }}

        section[data-testid="stSidebar"] div[class*="st-key-nav_"] button::before {{
            content: "";
            grid-column: 1;
            grid-row: 1;
            display: block;
            width: 17px;
            height: 17px;
            background-color: currentColor;
            opacity: 0.82;
            -webkit-mask-repeat: no-repeat;
            -webkit-mask-position: center;
            -webkit-mask-size: contain;
            mask-repeat: no-repeat;
            mask-position: center;
            mask-size: contain;
        }}

        section[data-testid="stSidebar"] .st-key-nav_overview button::before {{
            -webkit-mask-image: url("{SIDEBAR_NAV_ICONS[0]}"); mask-image: url("{SIDEBAR_NAV_ICONS[0]}");
        }}
        section[data-testid="stSidebar"] .st-key-nav_antiquary_benchmark button::before {{
            -webkit-mask-image: url("{SIDEBAR_NAV_ICONS[1]}"); mask-image: url("{SIDEBAR_NAV_ICONS[1]}");
        }}
        section[data-testid="stSidebar"] .st-key-nav_gear_simulator button::before {{
            -webkit-mask-image: url("{SIDEBAR_NAV_ICONS[2]}"); mask-image: url("{SIDEBAR_NAV_ICONS[2]}");
        }}
        section[data-testid="stSidebar"] .st-key-nav_traits button::before {{
            -webkit-mask-image: url("{SIDEBAR_NAV_ICONS[3]}"); mask-image: url("{SIDEBAR_NAV_ICONS[3]}");
        }}
        section[data-testid="stSidebar"] .st-key-nav_skill_library button::before {{
            -webkit-mask-image: url("{SIDEBAR_NAV_ICONS[4]}"); mask-image: url("{SIDEBAR_NAV_ICONS[4]}");
        }}
        section[data-testid="stSidebar"] .st-key-nav_trait_progress button::before {{
            -webkit-mask-image: url("{SIDEBAR_NAV_ICONS[5]}"); mask-image: url("{SIDEBAR_NAV_ICONS[5]}");
        }}
</style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# Temporary example overview data
# This will later be replaced with imported logs.
# --------------------------------------------------

logs = pd.DataFrame(
    {
        "Log": [
            "Log 1",
            "Log 2",
            "Log 3",
            "Log 4",
            "Log 5",
            "Log 6",
            "Log 7",
            "Log 8",
        ],
        "DPS": [
            42150,
            43320,
            42890,
            44110,
            43750,
            44620,
            43980,
            44840,
        ],
        "Duration": [
            96.2,
            93.5,
            94.8,
            91.7,
            92.4,
            90.9,
            91.8,
            90.4,
        ],
        "Build": [
            "Condition Thief",
            "Condition Thief",
            "Condition Thief",
            "Condition Thief",
            "Condition Thief",
            "Condition Thief",
            "Condition Thief",
            "Condition Thief",
        ],
    }
)


# --------------------------------------------------
# Session state
# --------------------------------------------------

if "latest_report" not in st.session_state:
    st.session_state["latest_report"] = None

if "latest_report_url" not in st.session_state:
    st.session_state["latest_report_url"] = ""

if "latest_conditions" not in st.session_state:
    st.session_state["latest_conditions"] = None

if "bulk_conditions_results" not in st.session_state:
    st.session_state["bulk_conditions_results"] = []

if "bulk_conditions_errors" not in st.session_state:
    st.session_state["bulk_conditions_errors"] = []

if "benchmark_session_results" not in st.session_state:
    st.session_state["benchmark_session_results"] = []

if "benchmark_session_errors" not in st.session_state:
    st.session_state["benchmark_session_errors"] = []


# --------------------------------------------------
# Sidebar
# --------------------------------------------------

# Restore the durable active build before navigation can trigger a rerun.
initialize_persistent_build_state()

with st.sidebar:
    st.markdown(
        f"""
        <div class="sidebar-brand">
            <div class="sidebar-brand-title-row">
                <span class="sidebar-brand-accent" aria-hidden="true"></span>
                <div class="sidebar-brand-title">Thief Lab</div>
            </div>
            <div class="sidebar-brand-rule"></div>
            <div class="sidebar-brand-subtitle">by Junior</div>
        </div>
        <div class="sidebar-section-label">Workspace</div>
        """,
        unsafe_allow_html=True,
    )

    # Focused workspace: legacy benchmark/debug pages remain in the codebase for
    # reference, but are intentionally hidden from normal navigation while the
    # gw2combat-backed workflow is being completed.
    page_labels = [
        "Overview",
        "Build",
        "Simulation",
        "Skills",
    ]

    legacy_page_map = {
        "Gear Simulator": "Build",
        "Traits": "Build",
        "Skill Library": "Skills",
        "Antiquary Benchmark": "Overview",
        "Implementation Progress": "Overview",
    }
    if "selected_page" not in st.session_state:
        st.session_state["selected_page"] = "Overview"
    elif st.session_state["selected_page"] not in page_labels:
        st.session_state["selected_page"] = legacy_page_map.get(
            st.session_state["selected_page"], "Overview"
        )

    for page_name in page_labels:
        button_key = "nav_" + page_name.lower().replace(" ", "_")
        is_active = st.session_state["selected_page"] == page_name
        if st.button(
            page_name,
            key=button_key,
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state["selected_page"] = page_name
            st.rerun()

    selected_page = st.session_state["selected_page"]

    st.divider()
    st.caption("Local dashboard — your data remains on your PC.")


# --------------------------------------------------
# Overview data
# --------------------------------------------------

filtered_logs = logs.copy()


# --------------------------------------------------
# Overview page
# --------------------------------------------------

if selected_page == "Overview":
    st.title("Performance Overview")
    st.caption(
        "Summary of your selected Guild Wars 2 logs"
    )

    average_dps = filtered_logs["DPS"].mean()
    highest_dps = filtered_logs["DPS"].max()
    median_dps = filtered_logs["DPS"].median()
    total_logs = len(filtered_logs)

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)

    metric_1.metric(
        label="Average DPS",
        value=f"{average_dps:,.0f}",
    )

    metric_2.metric(
        label="Personal Best",
        value=f"{highest_dps:,.0f}",
    )

    metric_3.metric(
        label="Median DPS",
        value=f"{median_dps:,.0f}",
    )

    metric_4.metric(
        label="Logs",
        value=total_logs,
    )

    st.divider()

    left_column, right_column = st.columns([2, 1])

    with left_column:
        st.subheader("DPS Trend")

        trend_chart = px.line(
            filtered_logs,
            x="Log",
            y="DPS",
            markers=True,
            title=None,
        )

        trend_chart.update_layout(
            xaxis_title="",
            yaxis_title="DPS",
            hovermode="x unified",
        )

        st.plotly_chart(
            trend_chart,
            use_container_width=True,
        )

    with right_column:
        st.subheader("Best Performances")

        top_logs = filtered_logs.nlargest(
            5,
            "DPS",
        )[["Log", "DPS", "Duration"]]

        st.dataframe(
            top_logs,
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Recent Logs")

    st.dataframe(
        filtered_logs.sort_index(ascending=False),
        hide_index=True,
        use_container_width=True,
    )


# --------------------------------------------------
# Logs page
# --------------------------------------------------

elif selected_page == "Logs":
    st.title("Import and Analyse Log")

    st.caption(
        "Paste one dps.report link and your in-game End Number."
    )

    report_url = st.text_input(
        "dps.report link",
        value=st.session_state["latest_report_url"],
        placeholder=(
            "https://dps.report/"
            "vqFf-20260716-193555_golem"
        ),
        key="log_report_url",
    )

    end_number_input = st.text_input(
        "In-game End Number",
        placeholder="For example: 40.403",
        help=(
            "Accepted formats: 40403, 40.403 or 40,403."
        ),
    )

    button_column, clear_column = st.columns(
        [1, 1],
        gap="small",
    )

    with button_column:
        analyse_button = st.button(
            "Analyse report",
            type="primary",
            use_container_width=True,
        )

    with clear_column:
        clear_button = st.button(
            "Clear result",
            use_container_width=True,
        )

    if clear_button:
        st.session_state["latest_report"] = None
        st.session_state["latest_conditions"] = None
        st.session_state["latest_report_url"] = ""
        st.rerun()

    if analyse_button:
        if not report_url.strip():
            st.warning("Enter a dps.report link first.")
        else:
            with st.spinner(
                "Downloading and analysing the report..."
            ):
                try:
                    result = analyse_basic_report(
                        report_url
                    )

                    st.session_state["latest_report"] = result
                    st.session_state["latest_report_url"] = (
                        result["report_url"]
                    )

                    # A previous conditions result no longer belongs
                    # to the newly selected log.
                    st.session_state["latest_conditions"] = None

                except Exception as error:
                    st.session_state["latest_report"] = None

                    st.error(
                        f"Analysis failed: {error}"
                    )

    result = st.session_state.get("latest_report")

    if result:
        st.success("Report successfully analysed.")

        allies_result = None

        if end_number_input.strip():
            try:
                allies_result = calculate_allies_damage(
                    end_number=end_number_input,
                    venom_dps_thousands=(
                        result["venom_dps_thousands"]
                    ),
                )
            except ValueError as error:
                st.warning(str(error))

        st.subheader(
            result.get(
                "fight_name",
                "Unknown fight",
            )
        )

        (
            metric_1,
            metric_2,
            metric_3,
            metric_4,
            metric_5,
        ) = st.columns(5)

        metric_1.metric(
            "Killtime",
            f'{result["killtime"]:.3f} s',
        )

        metric_2.metric(
            "Registered Venom Casts",
            result["raw_venom_casts"],
        )

        metric_3.metric(
            "Effective Venom Casts",
            f'{result["effective_venom_casts"]:.3f}',
        )

        metric_4.metric(
            "Venom DPS",
            f'{result["venom_dps"]:,.0f}',
        )

        if allies_result:
            metric_5.metric(
                "Allies Damage",
                allies_result["formatted_allies_damage"],
            )
        else:
            metric_5.metric(
                "Allies Damage",
                "—",
            )

        st.divider()

        detail_1, detail_2 = st.columns(2)

        with detail_1:
            st.subheader("Final Spider Venom")

            last_cast = result["last_venom_cast_start"]
            active_time = result["last_venom_active_time"]

            if last_cast is None:
                st.write(
                    "Final cast timestamp: **not found**"
                )
            else:
                st.write(
                    "Final cast started at "
                    f"**{last_cast:.3f} seconds**."
                )

            if active_time is None:
                st.write(
                    "Active time could not be calculated."
                )
            else:
                st.write(
                    "Final cast was active for "
                    f"**{active_time:.3f} of 6 seconds**."
                )

        with detail_2:
            st.subheader(
                "Spreadsheet-Compatible Result"
            )

            st.write(
                "Venom DPS as stored in your spreadsheet:"
            )

            st.code(
                f'{result["venom_dps_thousands"]:.3f}',
                language=None,
            )

            if allies_result:
                st.subheader("Allies Damage")

                st.write(
                    f'**{allies_result["formatted_end_number"]}** '
                    f'+ **{allies_result["formatted_venom_dps"]}** '
                    f'= **{allies_result["formatted_allies_damage"]}**'
                )

                st.caption(
                    "End Number + simulated allied "
                    "Spider Venom DPS"
                )
            else:
                st.info(
                    "Enter an in-game End Number "
                    "to calculate Allies Damage."
                )

        st.divider()

        status_column, link_column = st.columns(
            [2, 1]
        )

        with status_column:
            success_value = result.get("success")

            if success_value is True:
                st.success(
                    "The encounter was successful."
                )
            elif success_value is False:
                st.warning(
                    "The encounter was not marked "
                    "as successful."
                )
            else:
                st.info(
                    "Success status was unavailable."
                )

        with link_column:
            st.link_button(
                "Open original dps.report",
                result["report_url"],
                use_container_width=True,
            )

    else:
        st.info(
            "No report has been analysed yet."
        )


# --------------------------------------------------
# Antiquary Benchmark workspace
# --------------------------------------------------

elif selected_page == "Antiquary Benchmark":
    st.markdown(
        """
        <div style="margin-bottom: 0.55rem;">
            <div class="benchmark-title">
                Antiquary Benchmark
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    (
        single_log_tab,
        bulk_log_tab,
        patch_overview_tab,
        skill_audit_tab,
        rotation_replay_tab,
    ) = st.tabs(
        [
            "Single Log",
            "Bulk Analysis",
            "Patch Overview",
            "Skill Audit",
            "Rotation Replay",
        ]
    )

    # --------------------------------------------------
    # Single Log
    # --------------------------------------------------

    with single_log_tab:
        st.subheader("Load Single Log")

        input_left, input_middle, input_right = st.columns(
            [5, 2, 1.4],
            vertical_alignment="bottom",
        )

        with input_left:
            single_url = st.text_input(
                "dps.report link",
                value=st.session_state["latest_report_url"],
                placeholder="https://dps.report/example_golem",
                key="single_log_url",
            )

        with input_middle:
            single_end_number = st.text_input(
                "In-game number",
                placeholder="40.403",
                key="single_log_end_number",
            )

        with input_right:
            analyse_single_log = st.button(
                "Analyse",
                type="primary",
                use_container_width=True,
                key="analyse_single_log",
            )

        if analyse_single_log:
            if not single_url.strip():
                st.warning(
                    "Enter a dps.report link first."
                )
            elif not single_end_number.strip():
                st.warning(
                    "Enter the in-game number first."
                )
            else:
                with st.spinner(
                    "Analysing log..."
                ):
                    try:
                        damage_result = analyse_basic_report(
                            single_url
                        )

                        condition_result = (
                            analyse_conditions_from_url(
                                single_url
                            )
                        )

                        allies_result = (
                            calculate_allies_damage(
                                end_number=single_end_number,
                                venom_dps_thousands=(
                                    damage_result[
                                        "venom_dps_thousands"
                                    ]
                                ),
                            )
                        )

                        measured_conditions = (
                            condition_result[
                                "average_unique_conditions"
                            ]
                        )

                        expected_conditions = (
                            condition_result[
                                "intended_conditions"
                            ]
                        )

                        benchmark_error = (
                            measured_conditions
                            - expected_conditions
                        )

                        if benchmark_error > 0.05:
                            benchmark_status = (
                                "Extra conditions detected"
                            )
                        elif benchmark_error < -0.05:
                            benchmark_status = (
                                "Missing condition uptime"
                            )
                        else:
                            benchmark_status = (
                                "Valid Antiquary setup"
                            )

                        st.session_state[
                            "single_benchmark_result"
                        ] = {
                            "damage": damage_result,
                            "conditions": condition_result,
                            "allies": allies_result,
                            "measured_conditions": (
                                measured_conditions
                            ),
                            "expected_conditions": (
                                expected_conditions
                            ),
                            "benchmark_error": (
                                benchmark_error
                            ),
                            "benchmark_status": (
                                benchmark_status
                            ),
                        }

                        st.session_state[
                            "latest_report_url"
                        ] = condition_result[
                            "report_url"
                        ]

                    except Exception as error:
                        st.session_state[
                            "single_benchmark_result"
                        ] = None

                        st.error(
                            f"Analysis failed: {error}"
                        )

        single_result = st.session_state.get(
            "single_benchmark_result"
        )

        if single_result:
            damage_result = single_result["damage"]
            condition_result = single_result[
                "conditions"
            ]
            allies_result = single_result["allies"]

            st.divider()

            header_left, header_right = st.columns(
                [3, 1]
            )

            with header_left:
                st.subheader(
                    condition_result["fight_name"]
                    or "Unknown benchmark"
                )

                st.caption(
                    f'{condition_result["player_name"]} · '
                    f'{condition_result["profession"]} · '
                    f'{condition_result["target_name"]}'
                )

            with header_right:
                st.link_button(
                    "Open dps.report ↗",
                    condition_result["report_url"],
                    use_container_width=True,
                )

            # ------------------------------------------
            # 2.1 Overview
            # ------------------------------------------

            ew_correction_dps = float(
                condition_result["correction_dps"]
            )

            original_solo_damage = float(
                allies_result["end_number"]
            )

            corrected_solo_damage = max(
                0.0,
                original_solo_damage
                - ew_correction_dps,
            )

            benchmark_allied_damage = (
                corrected_solo_damage
                + float(damage_result["venom_dps"])
            )

            st.markdown("### Overview")

            st.markdown(
                f"""
                <div style="
                    background:
                        radial-gradient(circle at top right, rgba(123, 97, 255, 0.28), transparent 34%),
                        linear-gradient(135deg, rgba(36, 38, 53, 0.98), rgba(20, 22, 31, 0.98));
                    border: 1px solid rgba(123, 97, 255, 0.38);
                    border-radius: 18px;
                    padding: 22px 24px;
                    margin-bottom: 1rem;
                ">
                    <div style="
                        font-size: 0.78rem;
                        opacity: 0.72;
                        text-transform: uppercase;
                        letter-spacing: 0.11em;
                    ">
                        Corrected Allied Damage
                    </div>
                    <div class="hero-value">
                        {benchmark_allied_damage:,.0f}
                    </div>
                    <div style="
                        font-size: 0.82rem;
                        opacity: 0.68;
                        margin-top: 0.4rem;
                    ">
                        Corrected Solo Damage ({corrected_solo_damage:,.0f})
                        + Spider Venom ({damage_result["venom_dps"]:,.0f})
                    </div>
                    <div class="correction-chip">
                        EW correction applied to solo damage: -{ew_correction_dps:,.1f} DPS
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            (
                overview_1,
                overview_2,
                overview_3,
                overview_4,
            ) = st.columns(4)

            with overview_1:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Original Solo Damage</div>
                        <div class="metric-card-value">
                            {allies_result["formatted_end_number"]}
                        </div>
                        <div class="metric-card-note">
                            In-game end number before EW correction
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with overview_2:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Spider Venom</div>
                        <div class="metric-card-value">
                            {damage_result["venom_dps"]:,.0f}
                        </div>
                        <div class="metric-card-note">
                            Simulated allied venom contribution
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with overview_3:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Venom Performance</div>
                        <div class="metric-card-value">
                            {damage_result["effective_venom_casts"]:.3f}
                            <span style="opacity: 0.45;">/</span>
                            {damage_result["raw_venom_casts"]}
                        </div>
                        <div class="metric-card-note">
                            Effective Casts / Registered Casts
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with overview_4:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Killtime</div>
                        <div class="metric-card-value">
                            {damage_result["killtime"]:.3f} s
                        </div>
                        <div class="metric-card-note">
                            Total benchmark duration
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # ------------------------------------------
            # 2.2 Conditions
            # ------------------------------------------

            st.markdown("### Conditions Check")

            (
                condition_1,
                condition_2,
                condition_3,
                condition_4,
            ) = st.columns(4)

            with condition_1:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Measured Conditions</div>
                        <div class="metric-card-value">
                            {single_result["measured_conditions"]:.3f}
                        </div>
                        <div class="metric-card-note">
                            Damage-weighted measured value
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with condition_2:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Expected Conditions</div>
                        <div class="metric-card-value">
                            {single_result["expected_conditions"]:.3f}
                        </div>
                        <div class="metric-card-note">
                            10 permanent conditions + Taunt
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with condition_3:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Taunt Uptime</div>
                        <div class="metric-card-value">
                            {condition_result["taunt_uptime_percent"]:.2f}%
                        </div>
                        <div class="metric-card-note">
                            Included in the benchmark expectation
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with condition_4:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Condition Difference</div>
                        <div class="metric-card-value">
                            {single_result["benchmark_error"]:+.3f}
                        </div>
                        <div class="metric-card-note">
                            Measured minus expected
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            benchmark_status = single_result[
                "benchmark_status"
            ]

            if benchmark_status == "Valid Antiquary setup":
                badge_class = "badge-valid"
                badge_text = "● Within benchmark tolerance"
                badge_note = "Condition setup matches the Antiquary benchmark expectation."
            elif benchmark_status == "Extra conditions detected":
                badge_class = "badge-error"
                badge_text = "● Extra conditions detected"
                badge_note = "Exposed Weakness damage is inflated and has been corrected."
            else:
                badge_class = "badge-warning"
                badge_text = "● Missing condition uptime"
                badge_note = "The expected benchmark condition uptime was not maintained."

            st.markdown(
                f"""
                <div class="status-badge {badge_class}">{badge_text}</div>
                <div style="font-size:0.8rem; opacity:0.68; margin-top:0.4rem;">
                    {badge_note}
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ------------------------------------------
            # 2.2.1 EW correction
            # ------------------------------------------

            st.markdown(
                "<div style='height:0.45rem;'></div>",
                unsafe_allow_html=True,
            )

            st.markdown(
                "### EW Correction"
            )

            ew_raw_column, ew_correction_column, ew_corrected_column = (
                st.columns(3, gap="small")
            )

            with ew_raw_column:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Raw EW DPS</div>
                        <div class="metric-card-value">
                            {condition_result["estimated_trait_dps"]:,.1f}
                        </div>
                        <div class="metric-card-note">
                            Estimated trait contribution before correction
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with ew_correction_column:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">EW Correction</div>
                        <div class="metric-card-value">
                            −{condition_result["correction_dps"]:,.1f}
                        </div>
                        <div class="metric-card-note">
                            Damage attributed to excess conditions
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            with ew_corrected_column:
                st.markdown(
                    f"""
                    <div class="metric-card">
                        <div class="metric-card-label">Corrected EW DPS</div>
                        <div class="metric-card-value">
                            {condition_result["corrected_ew_dps"]:,.1f}
                        </div>
                        <div class="metric-card-note">
                            Raw EW DPS minus the correction
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if (
                condition_result["correction_dps"]
                > 0.05
            ):
                st.markdown(
                    """
                    <div style="
                        margin-top: 0.85rem;
                        margin-bottom: 1.1rem;
                        padding: 0.1rem 0.15rem;
                        font-size: 0.82rem;
                        line-height: 1.45;
                        opacity: 0.68;
                    ">
                        <strong style="opacity:0.92;">Correction note:</strong>
                        removes estimated Exposed Weakness damage caused by
                        conditions above the intended 10 + Taunt benchmark setup.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div style="
                        margin-top: 0.85rem;
                        margin-bottom: 1.1rem;
                        padding: 0.1rem 0.15rem;
                        font-size: 0.82rem;
                        line-height: 1.45;
                        opacity: 0.68;
                    ">
                        <strong style="opacity:0.92;">Correction note:</strong>
                        no meaningful Exposed Weakness correction was required.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.markdown(
                "<div style='height:0.25rem;'></div>",
                unsafe_allow_html=True,
            )

            with st.expander(
                "Show condition uptimes"
            ):
                condition_rows = []

                for condition_name in CONDITION_NAMES:
                    condition_rows.append(
                        {
                            "Condition": condition_name,
                            "Uptime (%)": (
                                condition_result[
                                    "condition_uptimes"
                                ].get(
                                    condition_name,
                                    0.0,
                                )
                            ),
                        }
                    )

                condition_dataframe = (
                    pd.DataFrame(condition_rows)
                    .sort_values(
                        "Uptime (%)",
                        ascending=False,
                    )
                )

                st.dataframe(
                    condition_dataframe,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Uptime (%)": (
                            st.column_config.NumberColumn(
                                format="%.2f%%"
                            )
                        )
                    },
                )

        else:
            st.info(
                "Upload one golem log and enter the in-game "
                "number to view the full single-log result."
            )

    # --------------------------------------------------
    # Bulk Analysis
    # --------------------------------------------------

    with bulk_log_tab:
        st.subheader("Bulk Analysis")

        bulk_results = st.session_state.get(
            "benchmark_session_results",
            [],
        )
        bulk_errors = st.session_state.get(
            "benchmark_session_errors",
            [],
        )

        if "bulk_editor_version" not in st.session_state:
            st.session_state["bulk_editor_version"] = 0

        input_expanded = not bool(bulk_results)

        with st.expander(
            "Session Input",
            expanded=input_expanded,
        ):
            meta_left, meta_middle, meta_right = st.columns(
                [1.3, 1.5, 1],
                vertical_alignment="bottom",
            )

            with meta_left:
                bulk_patch_name = st.text_input(
                    "Patch",
                    value=st.session_state.get(
                        "bulk_patch_name_value",
                        "Current Patch",
                    ),
                    key="bulk_patch_name",
                    help=(
                        "All sessions with the same patch name are "
                        "combined in Patch Overview."
                    ),
                )

            with meta_middle:
                bulk_session_name = st.text_input(
                    "Session name",
                    value=st.session_state.get(
                        "bulk_session_name_value",
                        "",
                    ),
                    placeholder="Example: Evening benchmarks",
                    key="bulk_session_name",
                )

            with meta_right:
                bulk_session_date = st.date_input(
                    "Session date",
                    value=date.today(),
                    key="bulk_session_date",
                )

            editor_key = (
                f'bulk_benchmark_editor_'
                f'{st.session_state["bulk_editor_version"]}'
            )

            bulk_input_table = st.data_editor(
                pd.DataFrame(
                    {
                        "dps.report link": ["", "", ""],
                        "In-game number": ["", "", ""],
                    }
                ),
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True,
                key=editor_key,
                column_config={
                    "dps.report link": st.column_config.TextColumn(
                        "dps.report link",
                        width="large",
                        help="Paste the complete dps.report link.",
                    ),
                    "In-game number": st.column_config.TextColumn(
                        "In-game number",
                        width="medium",
                        help=(
                            "Enter the end number shown in game, "
                            "for example 40.403."
                        ),
                    ),
                },
            )

            st.caption(
                "Paste a full column of links and a matching column "
                "of in-game numbers directly from your spreadsheet."
            )

            button_left, button_right = st.columns(
                [1.5, 1],
                vertical_alignment="bottom",
            )

            with button_left:
                analyse_bulk_logs = st.button(
                    "Analyse Session",
                    type="primary",
                    use_container_width=True,
                    key="analyse_bulk_logs",
                )

            with button_right:
                clear_bulk_logs = st.button(
                    "Clear",
                    use_container_width=True,
                    key="clear_bulk_logs",
                )

        if clear_bulk_logs:
            st.session_state["benchmark_session_results"] = []
            st.session_state["benchmark_session_errors"] = []
            st.session_state["bulk_editor_version"] += 1
            st.session_state.pop("last_saved_bulk_session", None)
            st.rerun()

        if analyse_bulk_logs:
            parsed_logs = []
            input_errors = []

            for row_index, row in bulk_input_table.iterrows():
                report_url = str(
                    row.get("dps.report link", "")
                ).strip()
                end_number = str(
                    row.get("In-game number", "")
                ).strip()

                if report_url.lower() == "nan":
                    report_url = ""
                if end_number.lower() == "nan":
                    end_number = ""

                if not report_url and not end_number:
                    continue

                displayed_row = row_index + 1

                if not report_url:
                    input_errors.append(
                        f"Row {displayed_row}: dps.report link is missing."
                    )
                    continue

                if not end_number:
                    input_errors.append(
                        f"Row {displayed_row}: in-game number is missing."
                    )
                    continue

                if "dps.report/" not in report_url:
                    input_errors.append(
                        f"Row {displayed_row}: invalid dps.report link."
                    )
                    continue

                parsed_logs.append(
                    {
                        "line_number": displayed_row,
                        "report_url": report_url,
                        "end_number": end_number,
                    }
                )

            session_results = []
            session_errors = list(input_errors)

            if not parsed_logs:
                st.warning(
                    "Add at least one complete row with a link and "
                    "its matching in-game number."
                )
            else:
                progress_bar = st.progress(0)
                progress_text = st.empty()

                for index, bulk_log in enumerate(
                    parsed_logs,
                    start=1,
                ):
                    progress_text.write(
                        f"Analysing log {index} of "
                        f"{len(parsed_logs)}..."
                    )

                    try:
                        damage_result = analyse_basic_report(
                            bulk_log["report_url"]
                        )
                        condition_result = (
                            analyse_conditions_from_url(
                                bulk_log["report_url"]
                            )
                        )
                        allies_result = calculate_allies_damage(
                            end_number=bulk_log["end_number"],
                            venom_dps_thousands=(
                                damage_result[
                                    "venom_dps_thousands"
                                ]
                            ),
                        )

                        measured_conditions = float(
                            condition_result[
                                "average_unique_conditions"
                            ]
                        )
                        expected_conditions = float(
                            condition_result[
                                "intended_conditions"
                            ]
                        )
                        condition_difference = (
                            measured_conditions
                            - expected_conditions
                        )
                        ew_correction = float(
                            condition_result["correction_dps"]
                        )
                        corrected_solo_damage = max(
                            0.0,
                            float(allies_result["end_number"])
                            - ew_correction,
                        )
                        corrected_allied_damage = (
                            corrected_solo_damage
                            + float(damage_result["venom_dps"])
                        )

                        valid = abs(condition_difference) <= 0.05
                        status = (
                            "Valid"
                            if valid
                            else (
                                "Extra conditions"
                                if condition_difference > 0
                                else "Missing uptime"
                            )
                        )

                        session_results.append(
                            {
                                "Log": index,
                                "Valid": valid,
                                "Status": status,
                                "Corrected Allied DPS": round(
                                    corrected_allied_damage
                                ),
                                "In-game Damage": round(
                                    float(
                                        allies_result["end_number"]
                                    )
                                ),
                                "Spider Venom": round(
                                    float(
                                        damage_result["venom_dps"]
                                    )
                                ),
                                "Killtime": round(
                                    float(
                                        damage_result["killtime"]
                                    ),
                                    3,
                                ),
                                "Condition Difference": round(
                                    condition_difference,
                                    3,
                                ),
                                "EW Correction": round(
                                    ew_correction,
                                    1,
                                ),
                                "Effective Venom Casts": round(
                                    float(
                                        damage_result[
                                            "effective_venom_casts"
                                        ]
                                    ),
                                    3,
                                ),
                                "Venom Casts": int(
                                    damage_result[
                                        "raw_venom_casts"
                                    ]
                                ),
                                "Report URL": (
                                    condition_result["report_url"]
                                ),
                            }
                        )

                    except Exception as error:
                        session_errors.append(
                            f'Row {bulk_log["line_number"]}: '
                            f'{error}'
                        )

                    progress_bar.progress(
                        index / len(parsed_logs)
                    )

                progress_text.empty()
                progress_bar.empty()

                st.session_state[
                    "benchmark_session_results"
                ] = session_results
                st.session_state[
                    "benchmark_session_errors"
                ] = session_errors

                patch_name = (
                    bulk_patch_name.strip()
                    or "Current Patch"
                )
                session_name = (
                    bulk_session_name.strip()
                    or (
                        "Session "
                        f"{bulk_session_date.isoformat()} "
                        f"{datetime.now().strftime('%H:%M')}"
                    )
                )

                record = create_session_record(
                    patch_name=patch_name,
                    session_name=session_name,
                    session_date=bulk_session_date,
                    results=session_results,
                )

                history = load_benchmark_history()
                history.append(record)
                save_benchmark_history(history)

                st.session_state[
                    "last_saved_bulk_session"
                ] = record["session_id"]
                st.session_state[
                    "bulk_patch_name_value"
                ] = patch_name
                st.session_state[
                    "bulk_session_name_value"
                ] = session_name

                st.rerun()

        bulk_results = st.session_state.get(
            "benchmark_session_results",
            [],
        )
        bulk_errors = st.session_state.get(
            "benchmark_session_errors",
            [],
        )

        if bulk_results:
            bulk_dataframe = pd.DataFrame(bulk_results)

            valid_count = int(
                bulk_dataframe["Valid"].astype(bool).sum()
            )
            invalid_count = (
                len(bulk_dataframe) - valid_count
            )
            damage_series = bulk_dataframe[
                "Corrected Allied DPS"
            ].astype(float)
            killtime_series = bulk_dataframe[
                "Killtime"
            ].astype(float)
            condition_series = bulk_dataframe[
                "Condition Difference"
            ].astype(float)
            ew_series = bulk_dataframe[
                "EW Correction"
            ].astype(float)

            st.caption(
                "Session analysed and automatically saved to "
                "**Patch Overview**."
            )

            hero_1, hero_2, hero_3, hero_4 = st.columns(4)
            hero_1.metric("Logs", len(bulk_dataframe))
            hero_2.metric(
                "Average DPS",
                f"{damage_series.mean():,.0f}",
            )
            hero_3.metric(
                "Median DPS",
                f"{damage_series.median():,.0f}",
            )
            hero_4.metric(
                "Best DPS",
                f"{damage_series.max():,.0f}",
            )

            overview_tab, logs_tab = st.tabs(
                ["Overview", "Logs"]
            )

            with overview_tab:
                stat_1, stat_2, stat_3, stat_4 = st.columns(4)
                top_five_average = damage_series.nlargest(
                    min(5, len(damage_series))
                ).mean()
                stat_1.metric(
                    "Top 5 Average",
                    f"{top_five_average:,.0f}",
                )
                stat_2.metric(
                    "DPS Deviation",
                    f"{damage_series.std(ddof=0):,.0f}",
                )
                stat_3.metric(
                    "Average Killtime",
                    f"{killtime_series.mean():.3f} s",
                )
                stat_4.metric(
                    "Condition-clean Logs",
                    f"{valid_count} / {len(bulk_dataframe)}",
                    help=(
                        "Logs with a condition difference between "
                        "-0.05 and +0.05. This is not an overall "
                        "benchmark validity score."
                    ),
                )

                stat_5, stat_6, stat_7, stat_8 = st.columns(4)
                stat_5.metric(
                    "Fastest",
                    f"{killtime_series.min():.3f} s",
                )
                stat_6.metric(
                    "Average Condition Diff.",
                    f"{condition_series.mean():+.3f}",
                )
                stat_7.metric(
                    "Median Condition Diff.",
                    f"{condition_series.median():+.3f}",
                )
                stat_8.metric(
                    "Average EW Correction",
                    f"-{ew_series.mean():.1f} DPS",
                )

                with st.expander(
                    "Show average damage profile",
                    expanded=False,
                ):
                    st.caption(
                        "Damage Profile parser v2 · uses dps.report/getJson"
                    )
                    profile_rows = bulk_dataframe[
                        [
                            "Log",
                            "Report URL",
                            "In-game Damage",
                            "Killtime",
                            "EW Correction",
                        ]
                    ].to_dict("records")

                    with st.spinner(
                        "Building the average damage profile..."
                    ):
                        session_profile = _build_session_profile_v2(
                            json.dumps(profile_rows),
                            DAMAGE_PROFILE_CACHE_VERSION,
                        )

                    profile_times = session_profile["times"]
                    average_profile = session_profile[
                        "average_profile"
                    ]

                    if not profile_times:
                        st.warning(
                            "No per-second damage timelines could "
                            "be read from these logs."
                        )
                    else:
                        chart_left, chart_right = st.columns(2)

                        with chart_left:
                            average_damage_chart = go.Figure()

                            average_damage_chart.add_trace(
                                go.Scatter(
                                    x=profile_times,
                                    y=average_profile,
                                    mode="lines",
                                    name="Average DPS",
                                    fill="tozeroy",
                                    hovertemplate=(
                                        "%{x:.0f}s<br>"
                                        "%{y:,.0f} DPS"
                                        "<extra></extra>"
                                    ),
                                )
                            )

                            average_damage_chart.update_layout(
                                title=(
                                    "Average Corrected Allied "
                                    "Damage Profile"
                                ),
                                margin=dict(
                                    l=10,
                                    r=10,
                                    t=45,
                                    b=10,
                                ),
                                xaxis_title="Time (seconds)",
                                yaxis_title="DPS",
                                showlegend=False,
                            )

                            st.plotly_chart(
                                average_damage_chart,
                                use_container_width=True,
                            )

                        with chart_right:
                            venom_chart = make_subplots(
                                specs=[
                                    [
                                        {
                                            "secondary_y": True
                                        }
                                    ]
                                ]
                            )

                            venom_chart.add_trace(
                                go.Scatter(
                                    x=profile_times,
                                    y=average_profile,
                                    mode="lines",
                                    name="Average DPS",
                                    fill="tozeroy",
                                    hovertemplate=(
                                        "%{x:.0f}s<br>"
                                        "%{y:,.0f} DPS"
                                        "<extra>Average DPS</extra>"
                                    ),
                                ),
                                secondary_y=False,
                            )

                            venom_chart.add_trace(
                                go.Bar(
                                    x=profile_times,
                                    y=session_profile[
                                        "cast_frequency"
                                    ],
                                    name="Venom cast frequency",
                                    opacity=0.35,
                                    hovertemplate=(
                                        "%{x:.0f}s<br>"
                                        "%{y:.0f}% of logs cast "
                                        "Spider Venom"
                                        "<extra></extra>"
                                    ),
                                ),
                                secondary_y=True,
                            )

                            for cast_data in session_profile[
                                "median_casts"
                            ]:
                                venom_chart.add_vline(
                                    x=cast_data["time"],
                                    line_dash="dash",
                                    opacity=0.65,
                                    annotation_text=(
                                        f'V{cast_data["cast"]}'
                                    ),
                                    annotation_position="top",
                                )

                            venom_chart.update_layout(
                                title=(
                                    "Average Profile with "
                                    "Spider Venom Timing"
                                ),
                                margin=dict(
                                    l=10,
                                    r=10,
                                    t=55,
                                    b=75,
                                ),
                                xaxis_title="Time (seconds)",
                                legend=dict(
                                    orientation="h",
                                    yanchor="top",
                                    y=-0.18,
                                    xanchor="center",
                                    x=0.5,
                                    title_text="",
                                    font=dict(size=11),
                                    itemsizing="constant",
                                ),
                            )

                            venom_chart.update_yaxes(
                                title_text="DPS",
                                secondary_y=False,
                            )
                            venom_chart.update_yaxes(
                                title_text="% of logs casting",
                                range=[0, 100],
                                secondary_y=True,
                            )

                            st.plotly_chart(
                                venom_chart,
                                use_container_width=True,
                            )

                        st.caption(
                            "The first chart averages the corrected "
                            "allied per-second damage shape. The "
                            "second overlays Spider Venom usage: "
                            "bars show the percentage of logs casting "
                            "during each second, while V1, V2, etc. "
                            "mark the median timing of each cast."
                        )

                    if session_profile["errors"]:
                        with st.expander(
                            f'{len(session_profile["errors"])} '
                            "profiles could not be included"
                        ):
                            for profile_error in session_profile[
                                "errors"
                            ]:
                                st.write(f"• {profile_error}")

            with logs_tab:
                filter_left, filter_right = st.columns(
                    [1, 1.4],
                    vertical_alignment="bottom",
                )

                with filter_left:
                    valid_only = st.checkbox(
                        "Condition-clean logs only",
                        value=False,
                        key="bulk_valid_only",
                    )

                with filter_right:
                    sort_choice = st.selectbox(
                        "Sort by",
                        options=[
                            "Corrected Allied DPS",
                            "Killtime",
                            "Condition Difference",
                            "EW Correction",
                            "Log",
                        ],
                        key="bulk_sort_choice",
                    )

                display_dataframe = bulk_dataframe.copy()

                if valid_only:
                    display_dataframe = (
                        display_dataframe[
                            display_dataframe["Valid"]
                        ]
                    )

                ascending_sort = sort_choice in {
                    "Killtime",
                    "Condition Difference",
                    "EW Correction",
                    "Log",
                }

                display_dataframe = (
                    display_dataframe.sort_values(
                        sort_choice,
                        ascending=ascending_sort,
                    )
                )

                display_columns = [
                    "Log",
                    "Valid",
                    "Corrected Allied DPS",
                    "Killtime",
                    "Condition Difference",
                    "EW Correction",
                    "Effective Venom Casts",
                    "Report URL",
                ]

                st.dataframe(
                    display_dataframe[display_columns],
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Valid": st.column_config.CheckboxColumn(
                            "Valid",
                            disabled=True,
                        ),
                        "Corrected Allied DPS": (
                            st.column_config.NumberColumn(
                                format="%d",
                            )
                        ),
                        "Killtime": (
                            st.column_config.NumberColumn(
                                format="%.3f s",
                            )
                        ),
                        "Condition Difference": (
                            st.column_config.NumberColumn(
                                format="%+.3f",
                            )
                        ),
                        "EW Correction": (
                            st.column_config.NumberColumn(
                                format="-%.1f",
                            )
                        ),
                        "Report URL": (
                            st.column_config.LinkColumn(
                                "dps.report",
                                display_text="Open ↗",
                            )
                        ),
                    },
                )

                csv_data = display_dataframe.to_csv(
                    index=False
                ).encode("utf-8")

                st.download_button(
                    "Download CSV",
                    data=csv_data,
                    file_name=(
                        "antiquary_benchmark_session.csv"
                    ),
                    mime="text/csv",
                )

            st.caption(
                f"{valid_count} condition-clean · "
                f"{invalid_count} with condition variance"
            )

        if bulk_errors:
            with st.expander(
                f"{len(bulk_errors)} rows could not be analysed"
            ):
                for bulk_error in bulk_errors:
                    st.write(f"• {bulk_error}")

        if not bulk_results and not bulk_errors:
            st.info(
                "Add your logs in Session Input and click "
                "Analyse Session."
            )

    # --------------------------------------------------
    # Patch Overview
    # --------------------------------------------------

    with patch_overview_tab:
        st.subheader("Patch Overview")

        history = load_benchmark_history()

        if not history:
            st.info(
                "No saved sessions yet. Analyse a bulk session first; "
                "it will appear here automatically."
            )
        else:
            available_patches = sorted(
                {
                    str(
                        session.get("patch", "")
                    ).strip()
                    for session in history
                    if str(
                        session.get("patch", "")
                    ).strip()
                },
                reverse=True,
            )

            selected_patch = st.selectbox(
                "Patch",
                options=available_patches,
                key="patch_overview_selection",
            )

            patch_sessions = sorted(
                [
                    session
                    for session in history
                    if session.get("patch") == selected_patch
                ],
                key=lambda item: (
                    item.get("session_date", ""),
                    item.get("saved_at", ""),
                ),
            )

            all_patch_logs = []
            session_summary_rows = []

            for session_number, session in enumerate(
                patch_sessions,
                start=1,
            ):
                session_logs = session.get("logs", [])

                for log in session_logs:
                    combined_log = dict(log)
                    combined_log["Session"] = session.get(
                        "session_name",
                        f"Session {session_number}",
                    )
                    combined_log["Session Date"] = (
                        session.get("session_date", "")
                    )
                    all_patch_logs.append(combined_log)

                if session_logs:
                    frame = pd.DataFrame(session_logs)
                    dps = frame[
                        "Corrected Allied DPS"
                    ].astype(float)

                    session_summary_rows.append(
                        {
                            "Session": session.get(
                                "session_name",
                                f"Session {session_number}",
                            ),
                            "Date": session.get(
                                "session_date",
                                "",
                            ),
                            "Logs": len(frame),
                            "Average DPS": round(dps.mean()),
                            "Median DPS": round(dps.median()),
                            "Best DPS": round(dps.max()),
                            "Deviation": round(
                                dps.std(ddof=0)
                            ),
                        }
                    )

            if not all_patch_logs:
                st.warning(
                    "This patch does not contain any saved logs."
                )
            else:
                patch_dataframe = pd.DataFrame(
                    all_patch_logs
                )
                sessions_dataframe = pd.DataFrame(
                    session_summary_rows
                )
                patch_dps = patch_dataframe[
                    "Corrected Allied DPS"
                ].astype(float)

                st.caption(
                    f"Career statistics for **{selected_patch}**"
                )

                hero_1, hero_2, hero_3, hero_4 = st.columns(4)
                hero_1.metric(
                    "Sessions",
                    len(patch_sessions),
                )
                hero_2.metric(
                    "Logs",
                    len(patch_dataframe),
                )
                hero_3.metric(
                    "Patch Average",
                    f"{patch_dps.mean():,.0f}",
                )
                hero_4.metric(
                    "Personal Best",
                    f"{patch_dps.max():,.0f}",
                )

                average_effective_venom_casts = pd.to_numeric(
                    patch_dataframe["Effective Venom Casts"],
                    errors="coerce",
                ).mean()
                average_venom_dps = pd.to_numeric(
                    patch_dataframe["Spider Venom"],
                    errors="coerce",
                ).mean()

                stat_1, stat_2, stat_3, stat_4 = st.columns(4)
                stat_1.metric(
                    "Median DPS",
                    f"{patch_dps.median():,.0f}",
                )
                stat_2.metric(
                    "DPS Deviation",
                    f"{patch_dps.std(ddof=0):,.0f}",
                    help=(
                        "Standard deviation of Corrected Allied DPS. "
                        "Lower means your benchmark results are more consistent."
                    ),
                )
                stat_3.metric(
                    "Avg Spider Casts",
                    (
                        f"{average_effective_venom_casts:.2f}"
                        if pd.notna(average_effective_venom_casts)
                        else "—"
                    ),
                    help=(
                        "Average effective Spider Venom casts per log. "
                        "A partially completed final cast counts proportionally."
                    ),
                )
                stat_4.metric(
                    "Avg Venom DPS",
                    (
                        f"{average_venom_dps:,.0f}"
                        if pd.notna(average_venom_dps)
                        else "—"
                    ),
                    help=(
                        "Average simulated allied Spider Venom DPS "
                        "across all logs in this patch."
                    ),
                )

                st.markdown("### Progress")

                progress_chart = px.line(
                    sessions_dataframe,
                    x="Date",
                    y=[
                        "Average DPS",
                        "Median DPS",
                        "Best DPS",
                    ],
                    markers=True,
                    hover_name="Session",
                )
                progress_chart.update_layout(
                    margin=dict(
                        l=10,
                        r=10,
                        t=20,
                        b=10,
                    ),
                    xaxis_title="Session date",
                    yaxis_title="Corrected Allied DPS",
                    legend_title_text="",
                )
                st.plotly_chart(
                    progress_chart,
                    use_container_width=True,
                )

                sessions_tab, best_logs_tab = st.tabs(
                    ["Sessions", "Best Logs"]
                )

                with sessions_tab:
                    st.dataframe(
                        sessions_dataframe.sort_values(
                            ["Date", "Session"],
                            ascending=[False, False],
                        ),
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Average DPS": (
                                st.column_config.NumberColumn(
                                    format="%d",
                                )
                            ),
                            "Median DPS": (
                                st.column_config.NumberColumn(
                                    format="%d",
                                )
                            ),
                            "Best DPS": (
                                st.column_config.NumberColumn(
                                    format="%d",
                                )
                            ),
                            "Deviation": (
                                st.column_config.NumberColumn(
                                    format="%d",
                                )
                            ),
                        },
                    )

                with best_logs_tab:
                    best_patch_logs = (
                        patch_dataframe.nlargest(
                            min(
                                10,
                                len(patch_dataframe),
                            ),
                            "Corrected Allied DPS",
                        )[
                            [
                                "Session",
                                "Session Date",
                                "Corrected Allied DPS",
                                "Killtime",
                                "Condition Difference",
                                "Report URL",
                            ]
                        ]
                    )

                    st.dataframe(
                        best_patch_logs,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Corrected Allied DPS": (
                                st.column_config.NumberColumn(
                                    format="%d",
                                )
                            ),
                            "Killtime": (
                                st.column_config.NumberColumn(
                                    format="%.3f s",
                                )
                            ),
                            "Condition Difference": (
                                st.column_config.NumberColumn(
                                    format="%+.3f",
                                )
                            ),
                            "Report URL": (
                                st.column_config.LinkColumn(
                                    "dps.report",
                                    display_text="Open ↗",
                                )
                            ),
                        },
                    )

                with st.expander(
                    "Manage saved sessions",
                    expanded=False,
                ):
                    session_options = {
                        (
                            f'{session.get("session_date", "")} — '
                            + str(
                                session.get(
                                    "session_name",
                                    "Unnamed session",
                                )
                            )
                        ): session.get("session_id")
                        for session in patch_sessions
                    }

                    session_to_delete = st.selectbox(
                        "Session",
                        options=list(
                            session_options.keys()
                        ),
                        key=(
                            "delete_patch_session_selection"
                        ),
                    )

                    confirm_delete = st.checkbox(
                        "Confirm deletion",
                        key=(
                            "confirm_patch_session_delete"
                        ),
                    )

                    if st.button(
                        "Delete Session",
                        disabled=not confirm_delete,
                        key="delete_patch_session",
                    ):
                        delete_id = session_options[
                            session_to_delete
                        ]
                        updated_history = [
                            session
                            for session in history
                            if session.get(
                                "session_id"
                            ) != delete_id
                        ]
                        save_benchmark_history(
                            updated_history
                        )
                        st.success("Session deleted.")
                        st.rerun()


# --------------------------------------------------
# Damage Profile page
# --------------------------------------------------

    # --------------------------------------------------
    # Benchmark skill audit
    # --------------------------------------------------

    with skill_audit_tab:
        st.subheader("Dagger Antiquary skill verification")
        st.caption(
            "Observed log evidence is kept separate from verified game mechanics. "
            "Rotations stay blocked while a used skill has unresolved event or timing data."
        )

        audit_path = Path(__file__).parent / "data" / "benchmark_dagger_skill_audit.json"
        if not audit_path.exists():
            st.error("Benchmark skill-audit data is missing.")
        else:
            audit_data = json.loads(audit_path.read_text(encoding="utf-8"))
            audit_summary = audit_data.get("summary", {})
            audit_skills = audit_data.get("benchmark_skills", [])

            metric_cols = st.columns(4)
            metric_cols[0].metric("Benchmark records", audit_summary.get("benchmark_skill_count", 0))
            metric_cols[1].metric("Need verification", audit_summary.get("needs_verification", 0))
            metric_cols[2].metric("Library blocked", audit_summary.get("whole_library_blocked", 0))
            metric_cols[3].metric("Rotation ready", audit_summary.get("whole_library_rotation_ready", 0))

            st.warning(
                "Strict result: the rotation engine is not enabled yet. "
                "A Wiki-verified label is not enough without explicit events and timing."
            )

            audit_df = pd.DataFrame(audit_skills)
            if not audit_df.empty:
                audit_df["blockers"] = audit_df["missing_or_blockers"].apply(
                    lambda values: " | ".join(values) if isinstance(values, list) else str(values or "")
                )
                display_columns = [
                    "id", "name", "cast_count", "logged_hits", "observed_hits_per_cast",
                    "library_hits", "library_coefficient", "library_cast_time",
                    "has_explicit_condition_events", "status", "blockers",
                ]
                status_filter = st.multiselect(
                    "Show status",
                    sorted(audit_df["status"].dropna().unique().tolist()),
                    default=sorted(audit_df["status"].dropna().unique().tolist()),
                    key="benchmark_skill_audit_status",
                )
                filtered_audit = audit_df[audit_df["status"].isin(status_filter)]
                st.dataframe(
                    filtered_audit[display_columns],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "id": "Skill ID",
                        "name": "Skill / damage source",
                        "cast_count": "Casts",
                        "logged_hits": "Logged hits",
                        "observed_hits_per_cast": "Observed hits/cast",
                        "library_hits": "Stored hits",
                        "library_coefficient": "Stored coefficient",
                        "library_cast_time": "Stored cast time",
                        "has_explicit_condition_events": "Explicit condition events",
                        "status": "Audit status",
                        "blockers": "Missing / blockers",
                    },
                )

                st.markdown("#### Important interpretation")
                st.info(
                    "Condition ticks in Elite Insights are aggregate damage sources. "
                    "They prove the fight produced Bleeding, Poison, Burning, Torment, or Confusion, "
                    "but do not by themselves prove which cast created each stack. "
                    "Those mappings must still be verified per skill."
                )

            readiness_path = Path(__file__).parent / "data" / "benchmark_dagger_readiness.json"
            if readiness_path.exists():
                readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
                readiness_summary = readiness.get("summary", {})
                readiness_records = readiness.get("records", [])

                st.markdown("#### Completion pass")
                ready_cols = st.columns(3)
                ready_cols[0].metric("Core skills ready", readiness_summary.get("ready_skill_records", 0))
                ready_cols[1].metric("Aggregate condition rows", readiness_summary.get("aggregate_condition_rows", 0))
                ready_cols[2].metric("Artifact/state records", readiness_summary.get("state_dependent_or_child_records", 0))

                engine_status = str(readiness_summary.get("rotation_engine_status", "Blocked"))
                st.error(engine_status)
                st.caption(
                    "Resolved skills use explicit PvE event packets and benchmark-observed effective action times. "
                    "Random artifacts remain blocked until their child effects and follow-up windows are modeled as state."
                )

                readiness_df = pd.DataFrame(readiness_records)
                if not readiness_df.empty:
                    st.dataframe(
                        readiness_df[[
                            "id", "name", "casts", "logged_hits", "status",
                            "effective_action_time", "timing_basis", "notes",
                        ]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "id": "Skill ID",
                            "name": "Skill / effect",
                            "casts": "Casts",
                            "logged_hits": "Logged hits",
                            "status": "Readiness",
                            "effective_action_time": "Effective action time",
                            "timing_basis": "Timing basis",
                            "notes": "Critical notes",
                        },
                    )

            artifact_audit_path = Path(__file__).parent / "data" / "benchmark_antiquary_artifacts.json"
            if artifact_audit_path.exists():
                artifact_audit = json.loads(artifact_audit_path.read_text(encoding="utf-8"))
                artifact_summary = artifact_audit.get("summary", {})
                artifact_records = artifact_audit.get("records", [])
                artifact_timeline = artifact_audit.get("timeline", [])

                st.markdown("#### Antiquary artifact engine")
                art_cols = st.columns(4)
                art_cols[0].metric("Root artifact uses", artifact_summary.get("root_artifact_casts", 0))
                art_cols[1].metric("Follow-up uses", artifact_summary.get("follow_up_casts", 0))
                art_cols[2].metric("Families observed", artifact_summary.get("artifact_families_observed", 0))
                art_cols[3].metric("Timeline violations", artifact_summary.get("timeline_violations", 0))

                if int(artifact_summary.get("timeline_violations", 0) or 0) == 0:
                    st.success(str(artifact_summary.get("rotation_engine_status", "Artifact timeline validated")))
                else:
                    st.error(str(artifact_summary.get("rotation_engine_status", "Artifact timeline requires review")))
                st.warning(str(artifact_summary.get("important_limit", "")))

                artifact_df = pd.DataFrame(artifact_records)
                if not artifact_df.empty:
                    artifact_df["child_effects"] = artifact_df["children"].apply(
                        lambda rows: " | ".join(
                            f"{row.get('name')} — {row.get('hits')} hits / {row.get('damage'):,} damage"
                            for row in (rows or [])
                        ) or "—"
                    )
                    st.dataframe(
                        artifact_df[[
                            "id", "name", "family", "role", "casts", "direct_hits",
                            "observed_direct_hits_per_cast", "median_action_ms", "child_effects",
                            "verification", "notes",
                        ]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "id": "Skill ID",
                            "name": "Artifact skill",
                            "family": "Artifact family",
                            "role": "State role",
                            "casts": "Observed uses",
                            "direct_hits": "Direct hits",
                            "observed_direct_hits_per_cast": "Direct hits/use",
                            "median_action_ms": "Median action (ms)",
                            "child_effects": "Separate child effects",
                            "verification": "Evidence",
                            "notes": "State-model notes",
                        },
                    )

                with st.expander("Observed artifact timeline", expanded=False):
                    timeline_df = pd.DataFrame(artifact_timeline)
                    if not timeline_df.empty:
                        timeline_df["time_s"] = timeline_df["time_ms"] / 1000.0
                        st.dataframe(
                            timeline_df[["time_s", "skill_id", "name", "role"]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "time_s": "Time (s)",
                                "skill_id": "Skill ID",
                                "name": "Artifact action",
                                "role": "State role",
                            },
                        )


    # --------------------------------------------------
    # Rotation replay and benchmark comparison
    # --------------------------------------------------

    with rotation_replay_tab:
        st.subheader("Observed rotation replay")
        st.caption(
            "Reconstructs the uploaded 94-second benchmark from Elite Insights casts. "
            "Observed facts, modeled mechanics, and unresolved state inputs stay separate."
        )

        replay_path = Path(__file__).parent / "data" / "benchmark_rotation_replay.json"
        if not replay_path.exists():
            st.error("Rotation replay data is missing.")
        else:
            replay = json.loads(replay_path.read_text(encoding="utf-8"))
            replay_summary = replay.get("summary", {})

            # Full Benchmark Prediction v1 requires the original Elite Insights
            # report, not the derived replay summary. Load the bundled benchmark
            # JSON once for this tab and keep a clear error if it is unavailable.
            benchmark_report_path = Path(__file__).parent / "data" / "benchmark_dagger.json"
            benchmark_report = (
                json.loads(benchmark_report_path.read_text(encoding="utf-8"))
                if benchmark_report_path.exists()
                else None
            )

            reference_path = Path(__file__).parent / "data" / "benchmark_reference.json"
            reference = json.loads(reference_path.read_text(encoding="utf-8")) if reference_path.exists() else {}
            ei_ref = reference.get("elite_insights", {})
            ingame_ref = reference.get("ingame", {})
            ref_compare = reference.get("comparison", {})

            st.markdown("#### Benchmark reference numbers")
            ref_cols = st.columns(5)
            ref_cols[0].metric("In-game golem DPS", f"{int(ingame_ref.get('dps') or 0):,}")
            ref_cols[1].metric("Elite Insights DPS", f"{int(ei_ref.get('dps') or replay_summary.get('observed_dps', 0)):,}")
            ref_cols[2].metric("Player damage", f"{int(reference.get('damage') or replay_summary.get('observed_damage', 0)):,}")
            ref_cols[3].metric("EI window", f"{float(ei_ref.get('duration_s', 0)):.3f}s")
            ref_cols[4].metric("Window difference", f"{float(ref_compare.get('window_difference_s') or 0):.3f}s")
            st.info(
                "**Both DPS values are retained.** The in-game golem displayed **42,406**, while Elite Insights "
                "reports **42,040** over its full 94.013-second fight window. They use the same player damage total; "
                "the in-game value implies a slightly shorter effective timer. EI remains the technical replay reference."
            )

            replay_cols = st.columns(5)
            replay_cols[0].metric("EI observed DPS", f"{int(replay_summary.get('observed_dps', 0)):,}")
            replay_cols[1].metric("Observed damage", f"{int(replay_summary.get('observed_damage', 0)):,}")
            replay_cols[2].metric("Casts replayed", replay_summary.get("observed_casts", 0))
            replay_cols[3].metric("Cast-model coverage", f"{float(replay_summary.get('cast_model_coverage_pct', 0)):.1f}%")
            replay_cols[4].metric("Direct-damage coverage", f"{float(replay_summary.get('direct_damage_model_coverage_pct', 0)):.1f}%")

            st.success(str(replay_summary.get("rotation_engine_status", "Replay created")))
            st.info(
                f"**DPS meaning:** {replay_summary.get('dps_label_status', 'Observed from log')}  \n"
                f"**Profile:** {replay_summary.get('damage_profile', 'Unknown')}"
            )

            compare_cols = st.columns(5)
            compare_cols[0].metric(
                "Rebuilt cast uptime",
                f"{float(replay_summary.get('reconstructed_cast_uptime_pct', 0)):.2f}%",
                delta=f"EI: {float(replay_summary.get('elite_insights_cast_uptime_pct', 0)):.2f}%",
                delta_color="off",
            )
            compare_cols[1].metric("Meaningful idle gaps", replay_summary.get("meaningful_gaps", 0))
            compare_cols[2].metric("Initiative spent", f"{float(replay_summary.get('initiative_spent', 0)):.0f}")
            compare_cols[3].metric(
                "Confirmed artifact initiative",
                f"+{float(replay_summary.get('confirmed_artifact_initiative_gain', 0)):.1f}",
                help="Actual usable initiative gained from wiki-verified Enterprising Aristocrat artifact triggers, capped at maximum initiative.",
            )
            compare_cols[4].metric(
                "Unmodeled initiative income",
                f"{float(replay_summary.get('unmodeled_initiative_income_required', 0)):.1f}",
                help="Any remaining initiative beyond passive regeneration and verified artifact gains. Zero means the observed spend is affordable in aggregate; ordering/state validation is still separate.",
            )

            st.markdown("#### Wiki-verified Antiquary mechanics")
            mechanics_df = pd.DataFrame(replay.get("mechanics", []))
            if not mechanics_df.empty:
                st.dataframe(
                    mechanics_df[["name", "trigger", "effect", "evidence"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "name": "Mechanic",
                        "trigger": "Trigger",
                        "effect": "PvE effect",
                        "evidence": "Evidence",
                    },
                )

            holo_rows = replay.get("holo_utility_consumptions", [])
            if holo_rows:
                with st.expander("Holo-Dancer cooldown consumptions", expanded=False):
                    holo_df = pd.DataFrame(holo_rows)
                    holo_df["time_s"] = holo_df["time_ms"] / 1000.0
                    st.dataframe(
                        holo_df[["time_s", "name", "base_recharge_s", "effective_recharge_s"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "time_s": "Time (s)",
                            "name": "Utility",
                            "base_recharge_s": "Base recharge (s)",
                            "effective_recharge_s": "After 80% reduction (s)",
                        },
                    )

            state_conflicts = replay.get("cooldown_violations", [])
            if state_conflicts:
                st.warning(
                    f"{len(state_conflicts)} cast spacings cannot be explained by plain base recharge alone. "
                    "These are state-model blockers (alacrity, charges, resets, preparations or follow-ups), not automatically player errors."
                )
                conflict_df = pd.DataFrame(state_conflicts)
                conflict_df["time_s"] = conflict_df["time_ms"] / 1000.0
                conflict_df["observed_gap_s"] = conflict_df["elapsed_ms"] / 1000.0
                conflict_df["stored_recharge_s"] = conflict_df["required_ms"] / 1000.0
                st.dataframe(
                    conflict_df[["time_s", "skill_id", "name", "observed_gap_s", "stored_recharge_s"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "time_s": "Cast time (s)",
                        "skill_id": "Skill ID",
                        "name": "Skill",
                        "observed_gap_s": "Observed gap (s)",
                        "stored_recharge_s": "Stored base recharge (s)",
                    },
                )

            st.markdown("#### Simulation readiness gate")
            verification_path = Path(__file__).parent / "data" / "benchmark_verification_report.json"
            if verification_path.exists():
                verification = json.loads(verification_path.read_text(encoding="utf-8"))
                gate = verification.get("summary", {})
                gate_cols = st.columns(5)
                gate_cols[0].metric("Verified categories", f"{gate.get('verified_categories', 0)} / {gate.get('total_categories', 0)}")
                gate_cols[1].metric("Verification progress", f"{float(gate.get('overall_progress_pct', 0)):.1f}%")
                gate_cols[2].metric("Blocking categories", gate.get("blocking_categories", 0))
                gate_cols[3].metric("Observed DPS", f"{int(gate.get('observed_dps', 0)):,}")
                gate_cols[4].metric("Predicted DPS", "NOT AVAILABLE")
                if gate.get("simulation_ready"):
                    st.success(str(gate.get("status", "Ready")))
                else:
                    st.error(str(gate.get("status", "Not ready")))
                st.caption("42,040 is the Elite Insights fight-window value. 42,406 is the player-reported in-game golem value. Neither is an independently predicted DPS result.")

                category_df = pd.DataFrame(verification.get("categories", []))
                if not category_df.empty:
                    st.dataframe(
                        category_df[["category", "status", "progress_pct", "evidence", "blocker"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "category": "Verification area",
                            "status": "Status",
                            "progress_pct": st.column_config.ProgressColumn("Progress", min_value=0, max_value=100, format="%.1f%%"),
                            "evidence": "What is proven",
                            "blocker": "What is still missing",
                        },
                    )

                with st.expander("Required work before Run Simulation can be trusted", expanded=True):
                    for action in verification.get("next_actions", []):
                        st.markdown(f"- {action}")
            else:
                st.warning("Strict benchmark verification report is missing.")

            st.info("Independent prediction has moved to the **Simulation** workspace and now uses gw2combat. Legacy Python formula previews were removed.")

            st.markdown("#### Condition source attribution")
            attribution_path = Path(__file__).parent / "data" / "benchmark_condition_attribution.json"
            if attribution_path.exists():
                attribution = json.loads(attribution_path.read_text(encoding="utf-8"))
                attr_summary = attribution.get("summary", {})
                attr_cols = st.columns(4)
                attr_cols[0].metric("Observed condition damage", f"{int(attr_summary.get('observed_condition_damage', 0)):,}")
                attr_cols[1].metric("Packet-attributed damage", f"{int(attr_summary.get('attributed_condition_damage', 0)):,}")
                attr_cols[2].metric("Attribution coverage", f"{float(attr_summary.get('attribution_coverage_pct', 0)):.1f}%")
                attr_cols[3].metric("Independent prediction", "NOT READY")
                st.warning(str(attr_summary.get("label", "Attribution estimate only")))

                condition_rows = pd.DataFrame(attribution.get("conditions", []))
                if not condition_rows.empty:
                    st.dataframe(
                        condition_rows,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "condition": "Condition",
                            "observed_damage": st.column_config.NumberColumn("Observed damage", format="%d"),
                            "attributed_damage": st.column_config.NumberColumn("Attributed damage", format="%d"),
                            "source_coverage": "Method",
                            "explicit_sources": "Explicit packet sources",
                        },
                    )

                source_rows = pd.DataFrame(attribution.get("sources", []))
                if not source_rows.empty:
                    with st.expander("Estimated condition damage by source", expanded=True):
                        st.caption(
                            "This distributes each observed aggregate condition total using the relative stack-duration weight of explicit skill packets. "
                            "It helps audit source mappings, but it is not an independent DPS prediction."
                        )
                        st.dataframe(
                            source_rows[["skill_id", "name", "phase", "condition", "casts", "base_stack_seconds_per_cast", "attribution_share_pct", "attributed_damage", "attributed_dps"]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "skill_id": "Skill ID",
                                "name": "Source",
                                "phase": "Event phase",
                                "condition": "Condition",
                                "casts": "Casts",
                                "base_stack_seconds_per_cast": st.column_config.NumberColumn("Base stack-seconds / cast", format="%.1f"),
                                "attribution_share_pct": st.column_config.NumberColumn("Condition share", format="%.2f%%"),
                                "attributed_damage": st.column_config.NumberColumn("Attributed damage", format="%d"),
                                "attributed_dps": st.column_config.NumberColumn("Attributed DPS", format="%.1f"),
                            },
                        )

                with st.expander("Why predicted DPS is still blocked", expanded=False):
                    for blocker in attribution.get("prediction_blockers", []):
                        st.markdown(f"- {blocker}")
            else:
                st.info("Condition attribution data has not been generated yet.")

            st.markdown("#### Cast timeline")
            timeline_df = pd.DataFrame(replay.get("timeline", []))
            if not timeline_df.empty:
                timeline_df["time_s"] = timeline_df["time_ms"] / 1000.0
                timeline_df["action_s"] = timeline_df["duration_ms"] / 1000.0
                role_filter = st.multiselect(
                    "Timeline roles",
                    sorted(timeline_df["role"].unique().tolist()),
                    default=sorted(timeline_df["role"].unique().tolist()),
                    key="rotation_replay_roles",
                )
                shown_timeline = timeline_df[timeline_df["role"].isin(role_filter)]
                st.dataframe(
                    shown_timeline[["time_s", "skill_id", "name", "role", "action_s", "initiative_cost", "ready_model"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "time_s": "Time (s)",
                        "skill_id": "Skill ID",
                        "name": "Action",
                        "role": "Model role",
                        "action_s": "Observed action (s)",
                        "initiative_cost": "Initiative",
                        "ready_model": "Mechanic modeled",
                    },
                )

            st.markdown("#### Damage comparison")
            damage_df = pd.DataFrame(replay.get("damage_comparison", []))
            if not damage_df.empty:
                damage_status = st.multiselect(
                    "Damage evidence status",
                    sorted(damage_df["model_status"].unique().tolist()),
                    default=sorted(damage_df["model_status"].unique().tolist()),
                    key="rotation_replay_damage_status",
                )
                damage_df = damage_df[damage_df["model_status"].isin(damage_status)]
                st.dataframe(
                    damage_df[["skill_id", "name", "damage", "hits", "share_pct", "model_status"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "skill_id": "Skill ID",
                        "name": "Damage source",
                        "damage": st.column_config.NumberColumn("Observed damage", format="%d"),
                        "hits": "Logged hits/ticks",
                        "share_pct": st.column_config.NumberColumn("Damage share", format="%.2f%%"),
                        "model_status": "Current evidence",
                    },
                )

            with st.expander("What still blocks free-form rotation prediction", expanded=True):
                for limitation in replay.get("limitations", []):
                    st.markdown(f"- {limitation}")

elif selected_page == "Damage Profile":
    st.title("Damage Profile")

    st.info(
        "This page will later show skill damage, "
        "condition damage and contribution percentages."
    )


# --------------------------------------------------
# Burst Analysis page
# --------------------------------------------------

elif selected_page == "Burst Analysis":
    st.title("Burst Analysis")

    st.info(
        "This page will later use the one-second "
        "damage timelines from your spreadsheet code."
    )


# --------------------------------------------------
# Compare page
# --------------------------------------------------

elif selected_page == "Compare":
    st.title("Compare Logs")

    st.info(
        "This page will later compare two logs "
        "side by side."
    )

# --------------------------------------------------
# Gear Simulator page
# --------------------------------------------------


elif selected_page == "Simulation":
    st.markdown("## Simulation")
    st.caption("gw2combat integration — Step 2: generated Dagger/Dagger Antiquary benchmark package and full log rotation.")
    status = engine_status()

    top1, top2, top3 = st.columns(3)
    top1.metric("Engine", "Ready" if status.available else "Setup required")
    top2.metric("Backend", "gw2combat")
    top3.metric("Integration", "Step 2")

    if status.available:
        st.success(status.message)
    else:
        st.warning(status.message)
        st.code(r".\scripts\build_gw2combat.ps1", language="powershell")
        st.caption("One-time setup: Visual Studio 2022 Build Tools with Desktop development with C++ and CMake tools.")

    overview_tab, run_tab, diagnostics_tab = st.tabs(["Overview", "Run configuration", "Diagnostics"])

    with overview_tab:
        st.markdown("### Generated Antiquary benchmark")
        package = build_antiquary_benchmark_package()
        coverage = package.coverage
        a, b, c, d = st.columns(4)
        a.metric("Rotation casts", f"{coverage['casts']:,}")
        b.metric("Unique skills", coverage['unique_skills'])
        c.metric("Mapped skills", coverage['supported_unique_skills'])
        d.metric("Definition coverage", f"{coverage['support_pct']:.1f}%")
        st.write(
            "The complete cast timeline from your benchmark JSON is now converted into a gw2combat rotation. "
            "Verified Thief skill records generate strike and condition events; unmapped artifact/child skills remain zero-damage placeholders so the engine can expose exactly what is still missing."
        )
        if coverage['placeholder_names']:
            with st.expander(f"Unmapped skill definitions ({coverage['placeholder_unique_skills']})"):
                st.write(coverage['placeholder_names'])

        if st.button("Run Antiquary benchmark simulation", type="primary", disabled=not status.available, use_container_width=True):
            try:
                with st.spinner("Running the generated Dagger/Dagger Antiquary rotation in gw2combat..."):
                    result = run_encounter(package.encounter, package.files)
                st.session_state["gw2combat_antiquary_audit"] = result
                st.success("Antiquary benchmark simulation completed.")
            except Exception as exc:
                st.error(str(exc))

        antiquary_audit = st.session_state.get("gw2combat_antiquary_audit")
        if antiquary_audit is not None:
            summary = audit_summary(antiquary_audit)
            x, y, z = st.columns(3)
            x.metric("Audit objects", f"{summary['events']:,}")
            y.metric("Damage events", f"{summary['damage_events']:,}")
            z.metric("Parsed damage", f"{summary['total_damage']:,.0f}")
            st.caption("This is the first gw2combat subtotal, not yet a final 42k prediction. Placeholder definitions are intentionally visible above.")
            with st.expander("Raw Antiquary audit JSON"):
                st.json(antiquary_audit)

        st.markdown("### Live build sensitivity test")
        st.caption("Select a damage-ready skill, save a baseline, then change gear/traits/sigils/relics and return here. The calculation uses the same shared build state as Skill Inspector.")
        live_skills = live_damage_ready_skills()
        if not st.session_state.get("gear_sim_total_stats"):
            st.warning("Open **Gear Simulator** once first so the active build stats are calculated.")
        elif live_skills:
            test_cols = st.columns([2.2, 1.0, 1.0])
            with test_cols[0]:
                live_skill = st.selectbox("Test skill", live_skills, key="simulation_live_skill")
            with test_cols[1]:
                live_casts = st.number_input("Casts", min_value=1.0, value=10.0, step=1.0, key="simulation_live_casts")
            current = simulate_live_skill(live_skill, live_casts)
            baseline_key = f"{current['skill_id']}:{live_casts:g}"
            with test_cols[2]:
                st.write("")
                st.write("")
                if st.button("Save baseline", use_container_width=True):
                    st.session_state["simulation_live_baseline"] = {"key": baseline_key, "result": current}
            baseline_record = st.session_state.get("simulation_live_baseline", {})
            baseline = baseline_record.get("result") if baseline_record.get("key") == baseline_key else None
            delta = current["expected_total"] - baseline["expected_total"] if baseline else None
            cards = st.columns(4)
            cards[0].metric("Expected / cast", f"{current['expected_per_cast']:,.0f}")
            cards[1].metric("Expected total", f"{current['expected_total']:,.0f}", f"{delta:+,.0f}" if delta is not None else None)
            cards[2].metric("Outgoing multiplier", f"×{current['outgoing_modifier']:.4f}")
            cards[3].metric("Power", f"{current['power']:,.0f}")
            rows = []
            for group, effects in current.get("modifier_effects", {}).items():
                for effect in effects:
                    rows.append({"Source": getattr(effect, "source", "Unknown"), "Group": group, "Amount": f"{float(getattr(effect, 'value', 0.0)):+.2%}"})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            else:
                st.caption("No direct strike modifiers are active for this skill. Proc-only relics appear as separate events and do not alter this per-cast strike value.")

        if st.button("Test gw2combat backend", disabled=not status.available, use_container_width=True):
            try:
                with st.spinner("Running bundled gw2combat example..."):
                    result = run_bundled_example()
                st.session_state["gw2combat_last_audit"] = result
                st.success("Backend test passed. The C++ engine executed and returned an audit file.")
            except Exception as exc:
                st.error(str(exc))

    with run_tab:
        st.markdown("### Run a gw2combat configuration")
        st.caption("Advanced/manual mode for testing encounter, build and rotation definitions.")
        encounter_upload = st.file_uploader("Encounter JSON", type=["json"], key="gw2combat_encounter")
        build_uploads = st.file_uploader(
            "Referenced build, rotation and recipe files",
            accept_multiple_files=True,
            key="gw2combat_files",
        )
        if st.button("Run simulation", type="primary", disabled=not status.available or encounter_upload is None):
            try:
                encounter = json.loads(encounter_upload.getvalue().decode("utf-8"))
                supplied = {upload.name: upload.getvalue() for upload in (build_uploads or [])}
                result = run_encounter(encounter, supplied)
                st.session_state["gw2combat_last_audit"] = result
                st.success("Simulation completed.")
            except Exception as exc:
                st.error(str(exc))

        audit = st.session_state.get("gw2combat_last_audit")
        if audit is not None:
            summary = audit_summary(audit)
            x, y, z = st.columns(3)
            x.metric("Audit objects", f"{summary['events']:,}")
            y.metric("Damage events", f"{summary['damage_events']:,}")
            z.metric("Parsed damage", f"{summary['total_damage']:,.0f}")
            with st.expander("Raw audit JSON"):
                st.json(audit)

    with diagnostics_tab:
        st.markdown("### Engine diagnostics")
        st.json({
            "available": status.available,
            "executable": str(status.executable) if status.executable else None,
            "source_present": status.source_present,
            "example_present": status.example_present,
            "vendor_root": str(VENDOR_ROOT),
        })
        st.markdown("The upstream source and MIT license are included in `vendor/gw2combat`.")

elif selected_page == "Build":
    st.markdown("## Build")
    st.caption("Authoritative build workspace. Gear, equipment and traits here feed both Simulation and Skills.")
    gear_tab, traits_tab = st.tabs(["Gear & equipment", "Traits"])
    with gear_tab:
        render_gear_simulator_page()
    with traits_tab:
        render_traits_page()
        autosave_trait_state()

elif selected_page == "Skills":
    render_skill_library_page()

