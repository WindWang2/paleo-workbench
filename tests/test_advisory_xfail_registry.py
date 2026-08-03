"""Sanity checks for the advisory xfail registry (#234)."""

from __future__ import annotations

from tests.advisory_xfail import ADVISORY_XFAIL


def test_advisory_xfail_registry_is_documented():
    assert ADVISORY_XFAIL, "registry must list known monorepo failures"
    for needle, reason in ADVISORY_XFAIL.items():
        assert needle.startswith("tests/"), needle
        assert "#234" in reason or "http" in reason, reason


def test_advisory_xfail_does_not_cover_workstation_host_package():
    """Workstation host job must stay a hard gate — never blanket-xfail it."""
    for needle in ADVISORY_XFAIL:
        assert "test_well_log_workstation" not in needle
