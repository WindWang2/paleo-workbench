"""Composition component contract: factory, undoable edit session, bindings.

One contract for every cartographic component — creatable, deletable,
movable, scalable, configurable, serializable, copyable, z-orderable, and
undoable. All document mutations go through :class:`CompositionEditSession`
commands (add/remove/move/scale/configure/reorder/duplicate), so any host
(UI or headless) gets identical undo/redo semantics and a monotonic
revision counter for cache invalidation.

Data/style bindings are declarative: an element property may carry
``data_binding = {"key": "factor.colorbar"}`` which
:func:`bind_template` resolves against a host-supplied binding context
(e.g. a FactorGridResult's colormap). Templates never embed bitmaps.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from paleo_workbench.mapping.composer.models import (
    PAPER_SIZES_MM,
    ComposerElement,
    ElementType,
    MapCompositionDocument,
    _new_element_id,
)

# Default geometry per component (mm) — sensible authoring sizes on A4.
DEFAULT_GEOMETRY_MM: dict[ElementType, tuple[float, float, float, float]] = {
    ElementType.MAIN_MAP: (15.0, 30.0, 180.0, 140.0),
    ElementType.LEGEND: (205.0, 30.0, 80.0, 60.0),
    ElementType.NORTH_ARROW: (250.0, 15.0, 14.0, 18.0),
    ElementType.SCALE_BAR: (20.0, 180.0, 50.0, 8.0),
    ElementType.GRID: (15.0, 30.0, 180.0, 140.0),
    ElementType.TITLE: (15.0, 8.0, 180.0, 14.0),
    ElementType.ANNOTATION: (60.0, 90.0, 45.0, 8.0),
    ElementType.TIMESCALE: (15.0, 175.0, 180.0, 12.0),
    ElementType.TEXT: (30.0, 160.0, 80.0, 8.0),
    ElementType.IMAGE: (200.0, 110.0, 70.0, 50.0),
    ElementType.INSET_MAP: (210.0, 140.0, 60.0, 50.0),
    ElementType.STAT_CHART: (210.0, 30.0, 75.0, 55.0),
    ElementType.METADATA: (15.0, 188.0, 150.0, 16.0),
    ElementType.COLORBAR: (200.0, 90.0, 12.0, 80.0),
}

DEFAULT_PROPERTIES: dict[ElementType, dict[str, Any]] = {
    ElementType.MAIN_MAP: {"title": "主图"},
    ElementType.TITLE: {"text": "图件标题", "font_size": 8, "align": "center"},
    ElementType.TEXT: {"text": "文本", "font_size": 4, "align": "left", "color": "#000000"},
    ElementType.ANNOTATION: {"text": "注释", "leader": True, "font_size": 3.5},
    ElementType.NORTH_ARROW: {"label": "N"},
    ElementType.SCALE_BAR: {"length_km": 10, "units": "km"},
    ElementType.GRID: {"spacing_mm": 20.0, "color": "#9aa4b2", "line_width_mm": 0.2},
    ElementType.LEGEND: {},
    ElementType.COLORBAR: {
        "title": "数值",
        "min": 0.0,
        "max": 1.0,
        "stops": ((0.0, "#053061"), (0.5, "#f7f7f7"), (1.0, "#67001f")),
        "discrete": False,
        "data_binding": {"key": "factor.colorbar"},
    },
    ElementType.STAT_CHART: {"chart_type": "bar", "title": "统计", "series": ()},
    ElementType.METADATA: {
        "fields": (("编制", ""), ("日期", ""), ("比例尺", "")),
        "font_size": 3.0,
    },
    ElementType.IMAGE: {"image_path": None, "image_data_png_b64": None, "fit": "contain"},
    ElementType.INSET_MAP: {"locator_scale": 4.0},
    ElementType.TIMESCALE: {"stages": ()},
}


class CompositionFactory:
    """Creates components and empty documents with authoring defaults."""

    def __init__(self, id_prefix: str = "el") -> None:
        self._id_prefix = id_prefix

    def create(
        self,
        element_type: ElementType,
        *,
        x_mm: float | None = None,
        y_mm: float | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> ComposerElement:
        dx, dy, dw, dh = DEFAULT_GEOMETRY_MM[element_type]
        merged: dict[str, Any] = {
            **copy.deepcopy(DEFAULT_PROPERTIES.get(element_type, {})),
            **dict(properties or {}),
        }
        return ComposerElement(
            id=f"{self._id_prefix}_{uuid.uuid4().hex[:10]}",
            element_type=element_type,
            x_mm=float(dx if x_mm is None else x_mm),
            y_mm=float(dy if y_mm is None else y_mm),
            width_mm=float(dw if width_mm is None else width_mm),
            height_mm=float(dh if height_mm is None else height_mm),
            properties=merged,
        )

    def create_document(
        self,
        *,
        title: str = "",
        paper_size: str = "A4",
        orientation: str = "landscape",
        dpi: float = 300.0,
    ) -> MapCompositionDocument:
        doc = MapCompositionDocument(
            id=f"comp_{uuid.uuid4().hex[:10]}",
            title=title,
            dpi=dpi,
        )
        doc.set_paper(paper_size, orientation)
        return doc


# ---------------------------------------------------------------------------
# Undoable edit session
# ---------------------------------------------------------------------------


@dataclass
class _CompositionCommand:
    """A single reversible document mutation."""

    label: str
    apply: Callable[[], None]
    revert: Callable[[], None]


class CompositionEditSession:
    """Command-pattern edit history over one :class:`MapCompositionDocument`.

    Pure Python (no Qt): UI hosts drive it, headless callers (tests, batch
    product assembly) get the same semantics. The ``revision`` counter
    increases on every applied command and every undo/redo, giving consumers
    a cheap staleness key.
    """

    def __init__(self, document: MapCompositionDocument, factory: CompositionFactory | None = None):
        self.document = document
        self.factory = factory or CompositionFactory()
        self.revision: int = 0
        self._undo_stack: list[_CompositionCommand] = []
        self._redo_stack: list[_CompositionCommand] = []

    # -- queries ----------------------------------------------------------

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    # -- commands ----------------------------------------------------------

    def add_element(
        self,
        element_type: ElementType,
        *,
        x_mm: float | None = None,
        y_mm: float | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> ComposerElement:
        element = self.factory.create(
            element_type,
            x_mm=x_mm,
            y_mm=y_mm,
            width_mm=width_mm,
            height_mm=height_mm,
            properties=properties,
        )
        self._execute(
            f"add {element_type.value}",
            apply_fn=lambda: self.document.add_element(element),
            revert_fn=lambda: self._discard(element.id),
        )
        return element

    def insert_element(self, element: ComposerElement) -> None:
        self._execute(
            f"insert {element.element_type.value}",
            apply_fn=lambda: self.document.add_element(element),
            revert_fn=lambda: self._discard(element.id),
        )

    def remove_element(self, element_id: str) -> ComposerElement | None:
        element = self.document.get_element(element_id)
        if element is None:
            return None
        index = self.document.elements.index(element)
        self._execute(
            f"remove {element.element_type.value}",
            apply_fn=lambda: self._discard(element_id),
            revert_fn=lambda: self.document.elements.insert(index, element),
        )
        return element

    def move_element(self, element_id: str, x_mm: float, y_mm: float) -> None:
        element = self._require(element_id)
        old = (element.x_mm, element.y_mm)

        def apply_move() -> None:
            element.x_mm, element.y_mm = float(x_mm), float(y_mm)

        def revert_move() -> None:
            element.x_mm, element.y_mm = old

        self._execute("move", apply_fn=apply_move, revert_fn=revert_move)

    def scale_element(self, element_id: str, width_mm: float, height_mm: float) -> None:
        element = self._require(element_id)
        if width_mm <= 0.0 or height_mm <= 0.0:
            raise ValueError("component size must be positive")
        old = (element.width_mm, element.height_mm)

        def apply_scale() -> None:
            element.width_mm, element.height_mm = float(width_mm), float(height_mm)

        def revert_scale() -> None:
            element.width_mm, element.height_mm = old

        self._execute("scale", apply_fn=apply_scale, revert_fn=revert_scale)

    def configure_element(self, element_id: str, properties: Mapping[str, Any]) -> None:
        element = self._require(element_id)
        old = dict(element.properties)

        def apply_config() -> None:
            element.properties.update(copy.deepcopy(dict(properties)))

        def revert_config() -> None:
            element.properties = dict(old)

        self._execute("configure", apply_fn=apply_config, revert_fn=revert_config)

    def duplicate_element(self, element_id: str) -> ComposerElement | None:
        element = self.document.get_element(element_id)
        if element is None:
            return None
        clone = ComposerElement(
            id=_new_element_id(),
            element_type=element.element_type,
            x_mm=element.x_mm + 5.0,
            y_mm=element.y_mm + 5.0,
            width_mm=element.width_mm,
            height_mm=element.height_mm,
            z_index=element.z_index + 1,
            visible=element.visible,
            properties=copy.deepcopy(element.properties),
        )
        self._execute(
            "duplicate",
            apply_fn=lambda: self.document.add_element(clone),
            revert_fn=lambda: self._discard(clone.id),
        )
        return clone

    # -- z-order -------------------------------------------------------------

    def bring_to_front(self, element_id: str) -> None:
        element = self._require(element_id)
        top = max((e.z_index for e in self.document.elements), default=0)

        def apply_front() -> None:
            element.z_index = top + 1
            self.document.elements.sort(key=lambda e: e.z_index)

        def revert_front() -> None:
            element.z_index = top
            self.document.elements.sort(key=lambda e: e.z_index)

        self._execute("bring_to_front", apply_fn=apply_front, revert_fn=revert_front)

    def send_to_back(self, element_id: str) -> None:
        element = self._require(element_id)
        bottom = min((e.z_index for e in self.document.elements), default=0)

        def apply_back() -> None:
            element.z_index = bottom - 1
            self.document.elements.sort(key=lambda e: e.z_index)

        def revert_back() -> None:
            element.z_index = bottom
            self.document.elements.sort(key=lambda e: e.z_index)

        self._execute("send_to_back", apply_fn=apply_back, revert_fn=revert_back)

    def raise_element(self, element_id: str) -> None:
        element = self._require(element_id)
        old = element.z_index

        def apply_raise() -> None:
            element.z_index = old + 1
            self.document.elements.sort(key=lambda e: e.z_index)

        def revert_raise() -> None:
            element.z_index = old
            self.document.elements.sort(key=lambda e: e.z_index)

        self._execute("raise", apply_fn=apply_raise, revert_fn=revert_raise)

    # -- history ---------------------------------------------------------------

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        command = self._undo_stack.pop()
        command.revert()
        self._redo_stack.append(command)
        self.revision += 1
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        command = self._redo_stack.pop()
        command.apply()
        self._undo_stack.append(command)
        self.revision += 1
        return True

    def clear_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    # -- internals ---------------------------------------------------------------

    def _execute(self, label: str, *, apply_fn: Callable[[], None], revert_fn: Callable[[], None]) -> None:
        command = _CompositionCommand(label=label, apply=apply_fn, revert=revert_fn)
        command.apply()
        self._undo_stack.append(command)
        self._redo_stack.clear()
        self.revision += 1

    def _require(self, element_id: str) -> ComposerElement:
        element = self.document.get_element(element_id)
        if element is None:
            raise KeyError(f"no composition element {element_id!r}")
        return element

    def _discard(self, element_id: str) -> None:
        element = self.document.get_element(element_id)
        if element is not None:
            self.document.elements.remove(element)


# ---------------------------------------------------------------------------
# Declarative bindings
# ---------------------------------------------------------------------------


def bind_template(
    document: MapCompositionDocument,
    *,
    binding_context: Mapping[str, Mapping[str, Any]],
) -> int:
    """Resolve every element's ``data_binding`` against *binding_context*.

    A binding is ``{"key": "factor.colorbar", "fields": [...opt]}`` on an
    element property; the context maps keys to property updates. Returns the
    number of resolved bindings. Unresolved keys are left untouched (the
    component keeps its defaults) — never invented values.
    """
    resolved = 0
    for element in document.elements:
        binding = element.properties.get("data_binding")
        if not isinstance(binding, Mapping):
            continue
        key = str(binding.get("key") or "")
        if not key or key not in binding_context:
            continue
        updates = dict(binding_context[key])
        fields = binding.get("fields")
        if fields:
            updates = {k: v for k, v in updates.items() if k in set(fields)}
        element.properties.update(copy.deepcopy(updates))
        resolved += 1
    return resolved
