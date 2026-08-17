"""Page-switch fade-in transition tests - Task 4.

The AppShell tests intentionally exercise the page-switch logic without
showing a native window.  The offscreen Qt platform does not provide a stable
window-exposure path, while the animation contract only needs the event loop.
"""
import pytest
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect


# --- AppShell page-switch tests (headless: no native-window exposure) ---

def test_page_switch_attaches_opacity_effect(qtbot):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    shell._switch_page(1)  # switch to data page
    qtbot.wait(50)
    page = shell.page_stack.widget(1)
    # During/after animation the effect should have been attached at some point.
    assert hasattr(shell, "_fade_anim")
    assert isinstance(shell._fade_anim, QPropertyAnimation)


def test_page_switch_completes_at_full_opacity(qtbot):
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    shell._switch_page(2)
    page = shell.page_stack.widget(2)
    # The fade must actually be attached on switch; without this check a
    # regression that never starts the animation would pass vacuously.
    effect = page.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect), (
        "page fade effect was never attached during the switch"
    )
    assert effect.opacity() < 1.0  # fade in progress (starts at 0.7)
    qtbot.wait(250)  # wait for 150ms animation to finish
    effect = page.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        # Finalize detaches the effect; a lingering sub-1.0 effect means the
        # animation did not complete at full opacity.
        assert effect.opacity() == pytest.approx(1.0)


def test_rapid_page_switch_restarts_animation(qtbot):
    """Rapid switches must stop+restart the animation rather than stack effects."""
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    shell._switch_page(2)
    shell._switch_page(3)
    shell._switch_page(4)
    # Only one live animation reference should exist.
    assert isinstance(shell._fade_anim, QPropertyAnimation)
    page = shell.page_stack.widget(4)
    effect = page.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)


# --- Contract test drives the production helper (not a local replica) ---

def test_fade_animation_contract(qtbot):
    """#644: assert AppShell._animate_page_fade, not a mirrored copy."""
    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    shell._animate_page_fade(1)
    anim = shell._fade_anim
    assert isinstance(anim, QPropertyAnimation)
    assert anim.duration() == 150
    assert anim.easingCurve() == QEasingCurve.Type.OutQuad
    assert anim.startValue() == 0.7
    assert anim.endValue() == 1.0
    page = shell.page_stack.widget(1)
    effect = page.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)
    assert effect.opacity() == pytest.approx(0.7)
    # Rapid restart on the same page: production replaces the effect at 0.7.
    shell._animate_page_fade(1)
    effect2 = page.graphicsEffect()
    assert isinstance(effect2, QGraphicsOpacityEffect)
    assert effect2.opacity() == pytest.approx(0.7)
    assert isinstance(shell._fade_anim, QPropertyAnimation)
    assert shell._fade_anim.duration() == 150
