# Shared strike multiplier fix

This pass restores the verified per-skill direct-strike coefficients while keeping the later Chak Shield, confusion, condition-total, and encounter-duration fixes.

The previous final baseline divided every direct skill coefficient by the same 1.0926 factor even though the generated build already handled that strike-state stage separately. The result was the uniform ~8.5% deficit visible across Kryptis Turret, Lotus Strike, Death Blossom, Mistburn Mortar, Double Strike, Wild Strike, and other direct attacks.

No total-DPS scaling or runtime calibration is added.
