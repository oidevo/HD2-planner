# Planner rules

This directory contains explicit policy, mechanical constraints, and the minimum reviewed capability vocabulary. Planner assessments are not authoritative game facts and must carry provenance/confidence on catalog records. No recommendation, substitution, or ranking engine is implemented. See [planner readiness](../docs/PLANNER_READINESS.md) before beginning Pass 2.

`presentation_order.json` is package-owned presentation metadata, separate from
canonical catalog facts and player profiles. Maintainers should update its
stable-ID arrays only from captured in-game screens or recordings. Record the
capture date, game build when known, and evidence references; then mark only
the supported screen/group as verified. Empty arrays and `unverified` states
are intentional: the application uses a deterministic name/ID fallback and
labels that fallback honestly rather than presenting it as game order.
See [presentation-order evidence and status](../docs/PRESENTATION_ORDER.md) for
the capture and verification process.
