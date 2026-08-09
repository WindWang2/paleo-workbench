"""Advisory xfail registry — quarantine lifted (#234).

The monorepo regression suite is a required gate (see docs/ci-merge-policy.md);
no known failures are quarantined under xfail anymore. Every entry that used
to live here either passes (entries removed) or was fixed (root causes closed
during the production-readiness quality convergence).

Keep this module so the import path in tests/conftest.py stays stable, but the
registry is intentionally empty: do NOT grow it back without a linked issue —
the goal forbids leaving failures under xfail.
"""

from __future__ import annotations

# nodeid substring → reason (must mention #234 or a dedicated ticket)
ADVISORY_XFAIL: dict[str, str] = {}
