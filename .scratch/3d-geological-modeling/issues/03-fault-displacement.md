# 03 — FaultDisplacement Vector Offset Engine

**What to build:**
Horizon surface vertex displacement across fault planes based on fault throw vectors without mesh self-intersection.

**Blocked by:** 02 — HorizonSculpting RBF Brush Surface Editing Engine

**Status:** ready-for-agent

- [ ] `FaultDisplacement` offsets horizon vertices along fault throw vectors.
- [ ] Preserves non-self-intersection topology invariants near fault zones.
- [ ] Fully verified by unit tests in `tests/test_fault_displacement.py`.
