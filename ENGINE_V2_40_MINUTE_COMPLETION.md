# Benchmark Engine v2 completion pass

Implemented against the uploaded Condition Dagger/Dagger Antiquary benchmark.

## Added
- Deadly Ambition +180 condition damage.
- Deadly Ambition poison packet on every Death Blossom use; Potent Poison adds the additional stack.
- Timeline-driven Lead Attacks stacks.
- Timeline-driven Combat High stacks.
- Exposed Weakness, Twin Fangs, Ferocious Strikes and Executioner strike modifiers.
- Kryptis Turret strike modifier while its benchmark buff is active.
- Superior Sigil of Earth bleeding packet with a 2-second ICD reconstruction.
- Relic of the Fractal PvE burning/torment packet with a 20-second ICD reconstruction.
- Fixed test discovery from a clean checkout.
- Fixed cast-coverage calculation so synthetic proc rows do not inflate coverage.

## Honest remaining limitation
Elite Insights does not expose exact per-hit timestamps in this JSON export. Sigil of Earth uses the earliest reconstructed attacking cast after each ICD. Several artifact child strike coefficients are still not independently sourced and remain listed as unsupported rather than reverse-engineered from observed damage.
