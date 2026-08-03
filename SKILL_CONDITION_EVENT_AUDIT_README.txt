SKILL CONDITION EVENT AUDIT V2

Critical correction
- Venomous Volley (71852) is one skill and now stores only its own cast: 3 thrown axes, each applying 1 Poison for 2 seconds.
- Recall Axes (71895) is a separate skill. It recalls up to five existing axes and resolves effects from each axe's source. A recalled Venomous Volley axe applies 1 Poison for 2 seconds.
- Recall payloads are state-dependent and are not added to Venomous Volley's cast totals.

Strict audit policy
- Repeated condition rows without explicit event mapping are marked for review.
- Multi-hit condition skills without a per-hit/per-cast map are marked for review.
- Condition skills without a verified application count are marked for review.
- Such records are downgraded from Wiki verified to Partial — condition events unverified.
- Rotation work must not consume REVIEW records as exact data.

See SKILL_CONDITION_EVENT_AUDIT_V2.csv for every stored record and its current audit state.
