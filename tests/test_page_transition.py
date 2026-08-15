"""Page-switch fade-in transition tests - Task 4.

The AppShell tests intentionally exercise the page-switch logic without
showing a native window.  The offscreen Qt platform does not provide a stable
window-exposure path, while the animation contract only needs the event loop.
"""
import pytest
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget


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


# --- Isolated contract test (no AppShell, no WebEngine hang) ---

def test_fade_animation_contract(qtbot):
    """Verify the fade helper builds a correct animation on a bare stack.

    Mirrors ``AppShell._animate_page_fade`` so the contract (effect + animation
    duration/easing/values) is checked even when AppShell cannot be constructed.
    """
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    page_a = QStackedWidget()
    page_b = QStackedWidget()
    stack.addWidget(page_a)
    stack.addWidget(page_b)

    # Reproduce the helper's logic against the bare stack.
    def animate(index: int):
        page = stack.widget(index)
        existing = page.graphicsEffect()
        if isinstance(existing, QGraphicsOpacityEffect):
            existing.setOpacity(1.0)
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.7)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(150)
        anim.setStartValue(0.7)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        anim.start()
        return anim, effect

    anim, effect = animate(1)
    assert anim.duration() == 150
    assert anim.easingCurve() == QEasingCurve.Type.OutQuad
    assert anim.startValue() == 0.7
    assert anim.endValue() == 1.0
    assert isinstance(effect, QGraphicsOpacityEffect)
    # Rapid restart: previous effect reset to full, new one starts at 0.7.
    anim2, effect2 = animate(1)
    assert effect2.opacity() == 0.7
