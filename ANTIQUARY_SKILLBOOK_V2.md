# Antiquary Skillbook v2

This branch rebuilds the Dagger/Dagger Condition Antiquary model around an auditable skillbook instead of hard-coded final damage.

## Source order

1. EVTC / Elite Insights: what actually happened — skill IDs, casts, child packets, buff/modifier timelines.
2. GW2 API: canonical skill/trait identity and IDs.
3. GW2 Wiki PvE pages: coefficients, condition packets, durations and mechanic rules that the API does not expose reliably.
4. Snow Crows: the reference build/profile and benchmark target.

Observed benchmark damage is validation data only. It must never be fed back as a hidden damage multiplier.

## Hard rules

- Every combat event is keyed by numeric skill/effect ID.
- Unknown IDs fail closed as UNKNOWN; no name guessing.
- A skill stores only its native packets.
- Traits, sigils, relics, boons and Antiquary states are separate rules.
- Child/proc packets keep their own IDs and attribution.
- Dynamic states (Lead Attacks, Combat High, Exhilarating Ephemera, artifact passives) are evaluated at event time.
- Modifier groups must declare whether they are additive or multiplicative.
- Condition duration and condition damage are calculated separately.
- The engine must be able to explain every predicted packet: base formula -> stats -> active state -> modifiers -> target state -> final value.
- The current benchmark EVTC is the regression test. A model is not "verified" merely because total DPS is close.

## Current target

Snow Crows' Dagger/Dagger Condition Antiquary page was updated 2026-08-08 for the July 2026 balance and currently lists 45,495 max / 45,450 average benchmark DPS. The frozen profile is in:

`data/data/profiles/condition_antiquary_dd_sc_2026-08.json`

## Validation gates

The benchmark importer must produce:

- 0 unknown observed damage-source IDs
- 0 silently guessed skill mappings
- exact observed cast counts for root skills
- explicit child/proc attribution
- exact condition and strike totals from the log as reference data
- exact Lead Attacks / Combat High / Exhilarating Ephemera state timelines where present
- per-source prediction delta
- per-damage-type prediction delta
- total DPS prediction delta

A source is allowed to be "mapped but not simulated". It is not allowed to be silently approximated and called verified.

## Next benchmark pass

Once the current reference .zevtc is present, replace the legacy 42,040-DPS reference with a versioned current reference rather than overwriting it. The importer should preserve both so older regression tests remain reproducible.
