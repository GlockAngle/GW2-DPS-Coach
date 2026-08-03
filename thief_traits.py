"""Compatibility imports for the unified Thief trait engine.

The application historically had two separate trait modules. Keeping this thin
wrapper ensures the Traits page and Gear/Skill calculators now read and write the
same Streamlit session-state keys and the same effect registry.
"""
from utils.thief_traits import (  # noqa: F401
    THIEF_SPECIALIZATIONS,
    apply_trait_selection,
    calculate_selected_trait_effects,
    current_trait_effect_registry,
    current_trait_selection,
    load_effect_overrides,
    load_presets,
    render_trait_assumptions,
    render_trait_progress_page,
    render_traits_page,
    save_presets,
    selected_trait_ids,
)
