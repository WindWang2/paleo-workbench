"""Advisory xfail registry is empty — the suite is a required gate (#234)."""

from __future__ import annotations

from tests.advisory_xfail import ADVISORY_XFAIL


def test_advisory_xfail_registry_is_empty():
    """The quarantine is lifted: no known failures may hide under xfail.

    The full regression suite is a required merge gate; any test that fails
    must be fixed, not xfailed. An entry here would silently mask a broken
    gate.
    """
    assert ADVISORY_XFAIL == {}


def test_advisory_xfail_does_not_cover_workstation_host_package():
    """Workstation host job must stay a hard gate — never blanket-xfail it."""
    for needle in ADVISORY_XFAIL:
        assert "test_well_log_workstation" not in needle
