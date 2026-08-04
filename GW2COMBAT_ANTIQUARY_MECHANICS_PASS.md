# gw2combat Antiquary mechanics pass

This pass removes the final zero-damage rotation placeholder and improves the generated benchmark package:

- preserves condition pulse intervals instead of collapsing every condition packet at cast completion;
- models charge-based condition packets across successive trigger windows;
- credits Spider Venom applications shared to four nearby allies to the venom owner;
- adds Deadly Ambition poison to Death Blossom;
- reproduces the benchmark condition-duration profile for general conditions, bleeding and poison;
- adds Exposed Weakness, Twin Fangs and Ferocious Strikes to the gw2combat build;
- maps Metal Legion Guitar (Smash) as the current PvE final-smash strike packet.

The result remains an independent gw2combat simulation. It is not force-scaled to 42,040 DPS. Differences that remain after this pass identify mechanics still requiring explicit engine state, particularly Antiquary artifact inventory/child behavior and initiative-driven cast legality.
