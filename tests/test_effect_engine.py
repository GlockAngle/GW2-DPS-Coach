from utils.effect_engine import EffectKind, EffectRegistry


def test_registry_preserves_source_and_totals():
    registry = EffectRegistry()
    registry.register_stat("Dagger Training", "Power", 80, source_id=1245)
    registry.register_stat("Revealed Training", "Power", 80, source_id=1704)
    stats, modifiers = registry.to_legacy()
    assert stats["Power"] == 160
    assert modifiers == {}
    assert [e.source for e in registry.for_target("Power")] == ["Dagger Training", "Revealed Training"]


def test_registry_supports_modifiers_and_conversions():
    registry = EffectRegistry()
    registry.register_modifier("Potent Poison", "poison", 0.33)
    registry.register_conversion("Practiced Tolerance", "precision_to_ferocity", 0.10)
    stats, modifiers = registry.to_legacy()
    assert stats == {}
    assert modifiers["poison"] == 0.33
    assert modifiers["precision_to_ferocity"] == 0.10


def test_registry_round_trip_serialization():
    registry = EffectRegistry()
    registry.register_modifier("Lead Attacks", "global_condition", 0.12, condition="Average configured bonus")
    restored = EffectRegistry.deserialize(registry.serialize())
    effect = restored.effects[0]
    assert effect.kind == EffectKind.MODIFIER_ADD
    assert effect.source == "Lead Attacks"
    assert effect.value == 0.12
    assert effect.condition == "Average configured bonus"
