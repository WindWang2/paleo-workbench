from paleo_workbench.ui.deferred_page_bindings import DeferredPageBindings


def test_deferred_page_binding_runs_only_when_flushed():
    bindings = DeferredPageBindings()
    calls: list[str] = []
    bindings.schedule(2, "state", lambda: calls.append("well-log"))

    assert bindings.has_pending(2)
    bindings.flush(3)
    assert calls == []

    bindings.flush(2)
    assert calls == ["well-log"]
    assert not bindings.has_pending(2)


def test_deferred_page_binding_coalesces_to_newest_state():
    bindings = DeferredPageBindings()
    calls: list[str] = []
    bindings.schedule(8, "state", lambda: calls.append("stale"))
    bindings.schedule(8, "state", lambda: calls.append("current"))
    bindings.schedule(8, "project", lambda: calls.append("project"))

    bindings.flush(8)

    assert calls == ["project", "current"]


def test_flush_executes_a_binding_scheduled_during_flush():
    """A project bind may schedule the matching state refresh on first visit."""
    bindings = DeferredPageBindings()
    calls: list[str] = []

    def bind_project() -> None:
        calls.append("project")
        bindings.schedule(8, "state", lambda: calls.append("state"))

    bindings.schedule(8, "project", bind_project)
    bindings.flush(8)

    assert calls == ["project", "state"]
    assert not bindings.has_pending(8)
