# Benchmark skill completion pass

This pass fixes the recurring dagger/utility skills used by the uploaded Condition Antiquary benchmark.

## Resolved

- Double Strike: 2 PvE hits, 0.8 total coefficient.
- Backstab: one defiant-target hit, 3.0 PvE coefficient.
- Wild Strike: one PvE hit, 2 Bleeding for 3 seconds.
- Lotus Strike: one PvE hit, 2 Poison for 5 seconds.
- Death Blossom: three hits; each hit applies 2 Bleeding for 6 seconds.
- Caltrops: ten one-second pulses.
- Spider Venom: six self charges; one 3-second Poison application per successful triggering attack.
- Thousand Needles: separate preparation and activation records; impact plus five pulses.

## Still blocked

The random Antiquary artifact subsystem needs a real state machine. Aggregate log hit rows cannot safely prove child lifetime, follow-up windows, or all condition attribution. Those records remain visibly state-dependent rather than being guessed.
