# Antiquary timestamp CSV fix

The exact-replay build generated rotation rows as `Skill,Time: 93.800s`, while the bundled gw2combat CSV parser expects `Skill, Time: 93.800s` and blindly skips two characters after the comma.

This discarded the first digit of every timestamp: for example, `93.800s` was parsed as `3.800s`. The complete 94-second benchmark was therefore compressed into roughly nine seconds, producing the misleading 47,922 DPS result.

The generator now emits the exact upstream dialect with a comma followed by a space. A regression test verifies that the 93.800-second final cast is preserved.
