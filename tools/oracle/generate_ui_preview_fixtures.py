#!/usr/bin/env python3
"""Oracle fixture generator for the C++ ui_pages_preview cores (UI-07).

Imports the REAL Python implementations — paleo_workbench/ui/pages
{table,text,rich_text,message,json_tree,image,pdf,media,web_document,
seismic_slice,summary_table,geotiff}_preview_widget.py, preview_settings.py,
preview_settings_panel.py, lazy_visualization_tabs.py — and freezes their
observable outputs to JSON so the C++ port in libs/ui_pages_preview can be
verified symbol-for-symbol.

The host environment has no PySide6. A comprehensive Qt stub kit is injected
as ``PySide6.*``: permissive QWidget shells with REAL behavior only where the
exercised semantics need it (signals emit synchronously, tab/stack indexes
track, QStandardItem model is a real tree, QSettings is a dict store,
QPixmap.scaled does real KeepAspectRatio math, qRgba packs for real).

Seam notes (mirroring the ui_shell generator):
- ``paleo_workbench.viz.seismic_3d_api`` (fast_slice_to_indexed8 /
  global_stretch_range) is a numpy-bound native dispatch — stubbed with a
  deterministic sentinel. The slice->Indexed8 kernel itself is
  libs/visualization's contract, already oracle-frozen there.
- ``paleo_workbench.viz.hosts.geoviz_preview_host`` is injected as a stub
  host recording render/clear/release_all — the geoviz host is not in
  UI-07 scope (ledger: geoviz domain).
- ``paleo_workbench.ui.pages.preview_provider`` is stubbed with a plain
  PreviewResult record (UI-03 domain).
- QtPdf/QtMultimedia stubs stand in for the real Qt classes so the same
  code paths Python tests drive through the preview_widgets monkeypatch
  seam are exercised for real here.
- ``numpy`` is a minimal elementwise stub — only the ramp/transpose math
  the widget itself performs is exercised; volume ops are the sentinel.

Regenerate with:

    python3 tools/oracle/generate_ui_preview_fixtures.py
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

FIXTURES_PATH = (
    REPO_ROOT / "libs" / "ui_pages_preview" / "ui_pages_preview_tests"
    / "fixtures" / "ui_pages_preview_oracle.json"
)


# ===========================================================================
# PySide6 stub kit
# ===========================================================================

EMITTED: list[tuple[str, object]] = []


class _BoundSignal:
    def __init__(self, name: str) -> None:
        self._name = name
        self._subs: list = []

    def connect(self, fn) -> None:
        self._subs.append(fn)

    def disconnect(self, fn) -> None:
        if fn in self._subs:
            self._subs.remove(fn)

    def emit(self, *args) -> None:
        EMITTED.append((self._name, args[0] if len(args) == 1 else list(args)))
        for fn in list(self._subs):
            fn(*args)


class _SignalDescriptor:
    def __init__(self, *args, **kwargs) -> None:
        self._name = ""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        bound = obj.__dict__.get(self._name)
        if bound is None:
            bound = _BoundSignal(self._name)
            obj.__dict__[self._name] = bound
        return bound


def _Signal(*args, **kwargs):
    return _SignalDescriptor(*args, **kwargs)


class _QObject:
    def __init__(self, parent=None, *args, **kwargs) -> None:
        self._parent = parent

    def deleteLater(self) -> None:  # noqa: N802
        pass

    def blockSignals(self, block: bool) -> bool:  # noqa: N802
        prev = getattr(self, "_signals_blocked", False)
        self._signals_blocked = block
        return prev

    def installEventFilter(self, obj) -> None:  # noqa: N802
        self._event_filter = obj

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        return False

    def objectName(self) -> str:  # noqa: N802
        return getattr(self, "_object_name", "")

    def setObjectName(self, name) -> None:  # noqa: N802
        self._object_name = name


class _QSettings:
    """Dict-backed QSettings stub honoring org/app identity + groups."""

    _stores: dict = {}

    def __init__(self, org=None, app=None, *args, **kwargs) -> None:
        self._identity = (org, app)
        self._store = self._stores.setdefault(self._identity, {})
        self._group: list[str] = []

    def _key(self, key: str) -> str:
        return "/".join([*self._group, key]) if self._group else key

    def value(self, key, defaultValue=None, type=None):  # noqa: N802
        return self._store.get(self._key(key), defaultValue)

    def setValue(self, key, value) -> None:  # noqa: N802
        if isinstance(value, (list, tuple)):
            value = list(value)
        elif isinstance(value, dict):
            value = dict(value)
        self._store[self._key(key)] = value

    def beginGroup(self, group) -> None:  # noqa: N802
        self._group.append(group)

    def endGroup(self) -> None:  # noqa: N802
        if self._group:
            self._group.pop()

    def allKeys(self):  # noqa: N802
        prefix = "/".join(self._group) + "/" if self._group else ""
        return [k[len(prefix):] for k in self._store if k.startswith(prefix)]

    def remove(self, key) -> None:
        target = self._key(key)
        for k in [k for k in self._store
                  if k == target or k.startswith(target + "/")]:
            del self._store[k]

    def sync(self) -> None:
        pass


class _QTimer(_QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.timeout = _BoundSignal("timeout")
        self._single_shot = False
        self._interval = 0
        self._started = False
        self._start_ms = None

    def setSingleShot(self, v) -> None:  # noqa: N802
        self._single_shot = bool(v)

    def setInterval(self, ms) -> None:  # noqa: N802
        self._interval = ms

    def start(self, ms=None) -> None:
        self._started = True
        self._start_ms = ms

    def stop(self) -> None:
        self._started = False

    @staticmethod
    def singleShot(ms, fn):  # noqa: N802
        fn()


class _QPoint:
    def __init__(self, x=0, y=0) -> None:
        self._x, self._y = int(x), int(y)

    def x(self): return self._x
    def y(self): return self._y

    def __add__(self, o): return _QPoint(self._x + o.x(), self._y + o.y())
    def __sub__(self, o): return _QPoint(self._x - o.x(), self._y - o.y())
    def __eq__(self, o):
        return isinstance(o, _QPoint) and (self._x, self._y) == (o._x, o._y)


class _QPointF:
    def __init__(self, x=0.0, y=0.0) -> None:
        self._x, self._y = float(x), float(y)

    def x(self): return self._x
    def y(self): return self._y


class _QSize:
    def __init__(self, w=0, h=0) -> None:
        self._w, self._h = int(w), int(h)

    def width(self): return self._w
    def height(self): return self._h
    def isValid(self): return self._w >= 0 and self._h >= 0 and (self._w, self._h) != (0, 0) or (self._w > 0 or self._h > 0)

    def scaled(self, w, h, mode=None):
        # KeepAspectRatio math
        sw, sh = self._w, self._h
        if sw <= 0 or sh <= 0 or w <= 0 or h <= 0:
            return _QSize(0, 0)
        rw = w / sw
        rh = h / sh
        r = min(rw, rh)
        return _QSize(max(1, int(sw * r)), max(1, int(sh * r)))


class _QSizeF:
    def __init__(self, w=0.0, h=0.0) -> None:
        self._w, self._h = float(w), float(h)

    def width(self): return self._w
    def height(self): return self._h


class _QRectF:
    def __init__(self, *a) -> None:
        self._a = a


class _QUrl:
    def __init__(self, url="", scheme="", path="") -> None:
        self._url = url
        self._scheme = scheme
        self._path = path
        if url and "://" in url:
            self._scheme = url.split("://", 1)[0]
        elif url and ":" in url and not scheme:
            self._scheme = url.split(":", 1)[0]

    def scheme(self): return self._scheme

    @staticmethod
    def fromLocalFile(path):  # noqa: N802
        return _QUrl(url="file://" + str(path), scheme="file", path=str(path))


class _QByteArray:
    def __init__(self, data=b"") -> None:
        self._data = bytes(data)


class _QBuffer(_QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data = b""
        self._open = False

    def setData(self, data) -> None:
        self._data = bytes(data)

    def open(self, mode) -> bool:
        self._open = True
        return True

    def close(self) -> None:
        self._open = False


class _QIODevice:
    class OpenModeFlag:
        ReadOnly = 0x1


class _QEvent:
    class Type:
        Wheel = 31


class _QModelIndex:
    def __init__(self, item=None, row=-1, column=0, parent=None, model=None):
        self._item = item
        self._row = row
        self._col = column
        self._parent = parent
        self._model = model

    def isValid(self): return self._item is not None
    def row(self): return self._row
    def column(self): return self._col
    def parent(self): return self._parent if self._parent is not None else _QModelIndex()
    def data(self, role=0):
        if self._item is None:
            return None
        return self._item.display(role, self._row, self._col)


class _QItemSelection:
    def __init__(self, tl=None, br=None) -> None:
        self._tl, self._br = tl, br


class _QItemSelectionModel:
    class SelectionFlag:
        Select = 0x1
        Current = 0x2

    def __init__(self) -> None:
        self.selected = []

    def select(self, sel, flags) -> None:
        self.selected.append((sel, flags))


class _QAbstractTableModel(_QObject):
    def beginResetModel(self): pass  # noqa: N802
    def endResetModel(self): pass  # noqa: N802

    def index(self, row, column, parent=None):
        return _QModelIndex(item=self, row=row, column=column,
                            parent=parent or _QModelIndex(), model=self)

    # uniform data() probe used by _QModelIndex.data
    def display(self, role, row, col):
        return None


class _QColor:
    def __init__(self, spec="") -> None:
        self._spec = spec

    def name(self): return self._spec


class _QBrush:
    def __init__(self, color=None) -> None:
        self._color = color

    def color(self): return self._color


class _QFont:
    def __init__(self, family="", size=0) -> None:
        self._family = family
        self._size = size
        self._bold = False

    def setBold(self, b): self._bold = bool(b)
    def setPointSize(self, s): self._size = s
    def pointSize(self): return self._size


class _QFontMetrics:
    def __init__(self, font=None) -> None:
        pass

    def horizontalAdvance(self, text): return len(str(text)) * 7


class _QKeySequence:
    class StandardKey:
        Copy = 1


class _QPainter:
    def __init__(self, *a) -> None: pass
    def setRenderHint(self, *a): pass
    def drawPixmap(self, *a): pass


class _QPixmap:
    def __init__(self, w=0, h=0, valid=None) -> None:
        self._w, self._h = int(w), int(h)
        self._null = (valid is False) or (valid is None and w == 0 and h == 0)

    def isNull(self): return self._null
    def width(self): return self._w
    def height(self): return self._h

    def scaled(self, w, h=None, aspect=None, mode=None):
        # Overloads: scaled(QSize, aspect, mode) or scaled(w, h, aspect, mode).
        if hasattr(w, "width") and h is not None and not isinstance(h, int):
            aspect = h
            h = None
        if hasattr(w, "width"):
            tw, th = w.width(), w.height()
        else:
            tw, th = w, (h if h is not None else w)
        # Real KeepAspectRatio math so the frozen dims are the real output.
        if self._w <= 0 or self._h <= 0 or tw <= 0 or th <= 0:
            return _QPixmap(0, 0, valid=False)
        r = min(tw / self._w, th / self._h)
        return _QPixmap(max(1, int(self._w * r)), max(1, int(self._h * r)),
                        valid=True)

    def loadFromData(self, data) -> bool:
        ok = bool(data)
        self._null = not ok
        if ok:
            self._w, self._h = 640, 480
        return ok

    @staticmethod
    def fromImage(image):  # noqa: N802
        if image is None or image.isNull():
            return _QPixmap(0, 0, valid=False)
        return _QPixmap(image.width(), image.height(), valid=True)


class _QImage:
    class Format:
        Format_Indexed8 = 3

    def __init__(self, *a, valid=None, w=0, h=0) -> None:
        self._args = a
        self._w, self._h = int(w), int(h)
        self._null = (valid is False) if valid is not None else (w == 0 and h == 0 and not a)
        self._color_table = None

    def isNull(self): return self._null
    def width(self): return self._w or (self._args[1] if len(self._args) > 1 else 0)
    def height(self): return self._h or (self._args[2] if len(self._args) > 2 else 0)
    def setColorTable(self, t): self._color_table = list(t)


class _QImageReader:
    """Deterministic fake: 'FAKEIMG:WxH' sources decode; others fail."""

    def __init__(self, source=None) -> None:
        self._source = source
        self._scaled = None

    def setAutoTransform(self, v): pass  # noqa: N802

    def _src_size(self):
        data = None
        if isinstance(self._source, str) and self._source.startswith("FAKEIMG:"):
            data = self._source
        elif isinstance(self._source, _QBuffer):
            try:
                data = self._source._data.decode()
            except Exception:
                data = None
        if data and data.startswith("FAKEIMG:"):
            w, h = data.split(":", 1)[1].split("x")
            return _QSize(int(w), int(h))
        return _QSize(0, 0)

    def size(self):
        return self._src_size()

    def setScaledSize(self, s):  # noqa: N802
        self._scaled = s

    def read(self):
        s = self._scaled or self._src_size()
        if not s or (s.width() <= 0 and s.height() <= 0):
            return _QImage(valid=False)
        return _QImage(w=s.width(), h=s.height(), valid=True)


class _QStandardItem:
    def __init__(self, text="") -> None:
        self._text = str(text)
        self._editable = True
        self._data: dict = {}
        self._rows: list[list] = []
        self._parent = None

    def text(self): return self._text
    def setEditable(self, v): self._editable = bool(v)  # noqa: N802
    def setData(self, value, role): self._data[role] = value  # noqa: N802
    def data(self, role): return self._data.get(role)

    def appendRow(self, row) -> None:  # noqa: N802
        items = row if isinstance(row, (list, tuple)) else [row]
        for it in items:
            it._parent = self
        self._rows.append(list(items))

    def removeRow(self, r) -> None:  # noqa: N802
        if 0 <= r < len(self._rows):
            del self._rows[r]

    def rowCount(self): return len(self._rows)  # noqa: N802
    def child(self, r, c=0):
        if 0 <= r < len(self._rows) and c < len(self._rows[r]):
            return self._rows[r][c]
        return None
    def parent(self): return self._parent
    def row(self):
        if self._parent is None:
            return 0
        for i, r in enumerate(self._parent._rows):
            if r and r[0] is self:
                return i
        return 0

    # model-side probes used by _QStandardItemModel.index().data()
    def display(self, role, row, col):
        return None


class _QStandardItemModel(_QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root = _QStandardItem("")
        self._headers = []

    def invisibleRootItem(self): return self._root  # noqa: N802
    def clear(self):
        self._root = _QStandardItem("")
        self._headers = []
    def setHorizontalHeaderLabels(self, labels): self._headers = list(labels)  # noqa: N802

    def rowCount(self, parent=None):  # noqa: N802
        if parent is None or not isinstance(parent, _QModelIndex) or not parent.isValid():
            return self._root.rowCount()
        return parent._item.rowCount()

    def index(self, row, column=0, parent=None):  # noqa: N802
        container = self._root
        if isinstance(parent, _QModelIndex) and parent.isValid():
            container = parent._item
        item = container.child(row, column)
        return _QModelIndex(item=item, row=row, column=column, parent=parent)

    def hasChildren(self, index):  # noqa: N802
        return index.isValid() and index._item.rowCount() > 0

    def itemFromIndex(self, index):  # noqa: N802
        return index._item if index.isValid() else None


def _qRgba(r, g, b, a):  # noqa: N802
    return ((int(a) & 0xFF) << 24) | ((int(r) & 0xFF) << 16) | \
        ((int(g) & 0xFF) << 8) | (int(b) & 0xFF)


class _QClipboard:
    def __init__(self) -> None:
        self._text = ""

    def setText(self, t): self._text = t
    def text(self): return self._text


_CLIPBOARD = _QClipboard()


class _Qt:
    class AlignmentFlag:
        AlignCenter = 0x84
        AlignRight = 0x2
        AlignVCenter = 0x80
        AlignHCenter = 0x4

    class Orientation:
        Horizontal = 1
        Vertical = 2

    class ItemDataRole:
        DisplayRole = 0
        FontRole = 6
        ForegroundRole = 9
        BackgroundRole = 10
        TextAlignmentRole = 7
        UserRole = 0x100

    class KeyboardModifier:
        NoModifier = 0
        ControlModifier = 0x4000000

    class MouseButton:
        LeftButton = 0x1

    class CursorShape:
        OpenHandCursor = 17
        ClosedHandCursor = 18

    class TransformationMode:
        FastTransformation = 0
        SmoothTransformation = 1

    class AspectRatioMode:
        IgnoreAspectRatio = 0
        KeepAspectRatio = 1
        KeepAspectRatioByExpanding = 2

    class TextInteractionFlag:
        NoTextInteraction = 0
        TextSelectableByMouse = 1

    class Key:
        Key_C = 0x43


class _Widget(_QObject):
    def __init__(self, parent=None, *a, **kw) -> None:
        super().__init__(parent)
        self._children: list = []
        self._layout = None
        self._text = ""
        self._visible = True
        self._enabled = True
        self._stylesheet = ""
        self._w, self._h = 640, 480
        self._font = _QFont()
        self._tooltip = ""
        self._statustip = ""
        self._min_h = 0
        self._min_w = 0
        self._word_wrap = False
        self._interaction_flags = 0
        self._cursor = None
        self._accessible_name = ""
        if isinstance(parent, _Widget):
            parent._children.append(self)

    def __getattr__(self, name):
        # Permissive fallback for unmodeled QWidget API (setEditTriggers,
        # setAlternatingRowColors, ...). Private/dunder names still raise so
        # `getattr(self, "_x", None)` probes behave like real attributes.
        if name.startswith("_"):
            raise AttributeError(name)

        def _noop(*a, **kw):
            return None
        return _noop

    # -- hierarchy / find --
    def findChild(self, cls, name=None):  # noqa: N802
        for c in self._children:
            if isinstance(c, cls) and (name is None or c.objectName() == name):
                return c
            found = c.findChild(cls, name) if isinstance(c, _Widget) else None
            if found is not None:
                return found
        return None

    def findChildren(self, cls, name=None):  # noqa: N802
        out = []
        for c in self._children:
            if isinstance(c, cls) and (name is None or c.objectName() == name):
                out.append(c)
            if isinstance(c, _Widget):
                out.extend(c.findChildren(cls, name))
        return out

    # -- geometry --
    def width(self): return self._w
    def height(self): return self._h
    def x(self): return self._x if hasattr(self, "_x") else 0
    def y(self): return self._y if hasattr(self, "_y") else 0
    def pos(self): return _QPoint(self.x(), self.y())
    def move(self, x, y): self._x, self._y = int(x), int(y)
    def resize(self, w, h): self._w, self._h = int(w), int(h)
    def sizeHint(self): return _QSize(self._w, self._h)  # noqa: N802
    def minimumSizeHint(self): return _QSize(40, 20)  # noqa: N802
    def setMinimumHeight(self, h): self._min_h = h  # noqa: N802
    def setMinimumWidth(self, w): self._min_w = w  # noqa: N802
    def minimumHeight(self): return self._min_h  # noqa: N802

    # -- text / style --
    def setStyleSheet(self, s): self._stylesheet = s  # noqa: N802
    def styleSheet(self): return self._stylesheet  # noqa: N802
    def setToolTip(self, t): self._tooltip = t  # noqa: N802
    def setStatusTip(self, t): self._statustip = t  # noqa: N802
    def toolTip(self): return self._tooltip  # noqa: N802
    def setFont(self, f): self._font = f  # noqa: N802
    def font(self): return self._font
    def fontMetrics(self): return _QFontMetrics(self._font)  # noqa: N802
    def setCursor(self, c): self._cursor = c  # noqa: N802
    def unsetCursor(self): self._cursor = None  # noqa: N802
    def setAccessibleName(self, n): self._accessible_name = n  # noqa: N802

    # -- state --
    def setVisible(self, v): self._visible = bool(v)  # noqa: N802
    def hide(self): self._visible = False
    def show(self): self._visible = True
    def isVisible(self): return self._visible  # noqa: N802
    def setEnabled(self, v): self._enabled = bool(v)  # noqa: N802
    def isEnabled(self): return self._enabled  # noqa: N802
    def update(self): pass
    def clear(self): self._text = ""

    # -- layout --
    def setLayout(self, l): self._layout = l
    def layout(self): return self._layout


class _Layout:
    def __init__(self, owner=None, *a, **kw) -> None:
        self._owner = owner
        self._items: list = []
        if isinstance(owner, _Widget):
            owner.setLayout(self)

    def _attach(self, w):
        if isinstance(w, _Widget):
            w._parent = self._owner
            if self._owner is not None and w not in self._owner._children:
                self._owner._children.append(w)
        self._items.append(w)

    def addWidget(self, w, *a): self._attach(w)
    def insertWidget(self, i, w, *a): self._attach(w)
    def addLayout(self, l, *a): self._items.append(l)
    def addRow(self, *a): self._items.append(a)
    def addStretch(self, *a): pass
    def removeWidget(self, w):
        if w in self._items:
            self._items.remove(w)
        if isinstance(w, _Widget) and self._owner is not None and w in self._owner._children:
            self._owner._children.remove(w)
    def setContentsMargins(self, *a): pass
    def setSpacing(self, *a): pass
    def setHorizontalSpacing(self, *a): pass
    def setVerticalSpacing(self, *a): pass
    def count(self): return len(self._items)


class _QVBoxLayout(_Layout):
    pass


class _QHBoxLayout(_Layout):
    pass


class _QFormLayout(_Layout):
    pass


class _QLabel(_Widget):
    def __init__(self, text="", parent=None, *a, **kw) -> None:
        if isinstance(text, _Widget) and parent is None:
            parent, text = text, ""
        super().__init__(parent)
        self._text = str(text)
        self._pixmap = None
        self._alignment = 0

    def setText(self, t): self._text = str(t)
    def text(self): return self._text
    def setAlignment(self, a): self._alignment = a  # noqa: N802
    def setPixmap(self, p): self._pixmap = p  # noqa: N802
    def pixmap(self): return self._pixmap
    def setWordWrap(self, v): self._word_wrap = bool(v)  # noqa: N802
    def setTextInteractionFlags(self, f): self._interaction_flags = f  # noqa: N802
    def clear(self):
        self._text = ""
        self._pixmap = None


class _QPushButton(_Widget):
    def __init__(self, text="", parent=None, *a, **kw) -> None:
        if isinstance(text, _Widget) and parent is None:
            parent, text = text, ""
        super().__init__(parent)
        self._text = str(text)
        self.clicked = _BoundSignal("clicked")
        self._checkable = False
        self._checked = False

    def setText(self, t): self._text = str(t)
    def text(self): return self._text
    def setCheckable(self, v): self._checkable = bool(v)  # noqa: N802
    def setChecked(self, v): self._checked = bool(v)  # noqa: N802
    def isChecked(self): return self._checked  # noqa: N802
    def click(self):
        if not getattr(self, "_signals_blocked", False):
            self.clicked.emit()


class _QSlider(_Widget):
    def __init__(self, orientation=None, parent=None, *a, **kw) -> None:
        if isinstance(orientation, _Widget) and parent is None:
            parent, orientation = orientation, None
        super().__init__(parent)
        self._min, self._max, self._val = 0, 99, 0
        self.valueChanged = _BoundSignal("valueChanged")
        self.sliderMoved = _BoundSignal("sliderMoved")
        self._down = False

    def setRange(self, a, b): self._min, self._max = a, b  # noqa: N802
    def setMinimum(self, v): self._min = v  # noqa: N802
    def setMaximum(self, v): self._max = v  # noqa: N802
    def maximum(self): return self._max
    def value(self): return self._val
    def setValue(self, v):
        self._val = v
        if not getattr(self, "_signals_blocked", False):
            self.valueChanged.emit(v)
    def isSliderDown(self): return self._down  # noqa: N802


class _QComboBox(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list = []
        self._current = -1
        self.currentIndexChanged = _BoundSignal("currentIndexChanged")

    def addItem(self, label, data=None):
        self._items.append((label, data))
        if self._current < 0:
            self._current = 0

    def addItems(self, labels):
        for l in labels:
            self.addItem(l)

    def currentIndex(self): return self._current  # noqa: N802
    def setCurrentIndex(self, i):
        if i != self._current:
            self._current = i
            if not getattr(self, "_signals_blocked", False):
                self.currentIndexChanged.emit(i)
    def currentData(self):  # noqa: N802
        return self._items[self._current][1] if 0 <= self._current < len(self._items) else None
    def findData(self, data):  # noqa: N802
        for i, (_l, d) in enumerate(self._items):
            if d == data:
                return i
        return -1
    def count(self): return len(self._items)
    def itemText(self, i): return self._items[i][0]  # noqa: N802


class _QCheckBox(_Widget):
    def __init__(self, text="", parent=None) -> None:
        if isinstance(text, _Widget) and parent is None:
            parent, text = text, ""
        super().__init__(parent)
        self._text = str(text)
        self._checked = False

    def isChecked(self): return self._checked  # noqa: N802
    def setChecked(self, v): self._checked = bool(v)  # noqa: N802


class _QSpinBox(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._min, self._max, self._val = 0, 99, 0
        self._suffix = ""

    def setRange(self, a, b): self._min, self._max = a, b  # noqa: N802
    def setSuffix(self, s): self._suffix = s  # noqa: N802
    def value(self): return self._val
    def setValue(self, v):
        self._val = max(self._min, min(self._max, int(v)))


class _QHeaderView(_Widget):
    class ResizeMode:
        Interactive = 0
        ResizeToContents = 2

    def __init__(self) -> None:
        super().__init__()
        self._stretch = False
        self._mode = None
        self._sizes: dict = {}
        self._default = 0

    def setStretchLastSection(self, v): self._stretch = bool(v)  # noqa: N802
    def setSectionResizeMode(self, m): self._mode = m  # noqa: N802
    def resizeSection(self, i, s): self._sizes[i] = s  # noqa: N802
    def sectionSize(self, i): return self._sizes.get(i, 28)  # noqa: N802
    def setDefaultSectionSize(self, s): self._default = s  # noqa: N802
    def height(self): return 0


class _QTableView(_Widget):
    class EditTrigger:
        NoEditTriggers = 0

    class SelectionBehavior:
        SelectItems = 0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = None
        self._hheader = _QHeaderView()
        self._vheader = _QHeaderView()
        self._selection_model = _QItemSelectionModel()

    def setModel(self, m): self._model = m
    def model(self): return self._model
    def horizontalHeader(self): return self._hheader  # noqa: N802
    def verticalHeader(self): return self._vheader  # noqa: N802
    def selectionModel(self): return self._selection_model  # noqa: N802
    def selectedIndexes(self): return []  # noqa: N802


class _QTreeView(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = None
        self.expanded = _BoundSignal("expanded")
        self._expanded_indexes: list = []

    def setModel(self, m): self._model = m
    def setHeaderHidden(self, v): pass  # noqa: N802
    def expand(self, index): self._expanded_indexes.append(index)
    def rootIndex(self): return _QModelIndex()  # noqa: N802


class _QTextEdit(_Widget):
    class LineWrapMode:
        NoWrap = 0
        WidgetWidth = 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._readonly = False
        self._wrap = self.LineWrapMode.WidgetWidth
        self._plain = ""

    def setReadOnly(self, v): self._readonly = bool(v)  # noqa: N802
    def setLineWrapMode(self, m): self._wrap = m  # noqa: N802
    def lineWrapMode(self): return self._wrap  # noqa: N802
    def setPlainText(self, t): self._plain = str(t)  # noqa: N802
    def toPlainText(self): return self._plain  # noqa: N802


class _QTextBrowser(_QTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._open_external = True
        self._html = ""

    def setOpenExternalLinks(self, v): self._open_external = bool(v)  # noqa: N802
    def setHtml(self, h): self._html = str(h)  # noqa: N802
    def loadResource(self, t, url):  # noqa: N802
        return "BASE_RESOURCE"


class _QScrollBar(_QObject):
    def __init__(self) -> None:
        super().__init__()
        self.valueChanged = _BoundSignal("valueChanged")
        self._value = 0

    def setValue(self, v):
        self._value = v
        self.valueChanged.emit(v)
    def value(self): return self._value


class _QScrollArea(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._widget = None
        self._vbar = _QScrollBar()
        self._resizable = False

    def setWidgetResizable(self, v): self._resizable = bool(v)  # noqa: N802
    def setWidget(self, w): self._widget = w
    def verticalScrollBar(self): return self._vbar  # noqa: N802
    def viewport(self): return self  # noqa: N802


class _QStackedWidget(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._widgets: list = []
        self._current = None

    def addWidget(self, w):
        self._widgets.append(w)
        self._attach_child(w)
        if self._current is None:
            self._current = w
        return len(self._widgets) - 1

    def _attach_child(self, w):
        if isinstance(w, _Widget):
            w._parent = self
            if w not in self._children:
                self._children.append(w)

    def setCurrentWidget(self, w):  # noqa: N802
        if w is not None:
            self._current = w

    def currentWidget(self): return self._current  # noqa: N802
    def setCurrentIndex(self, i):
        if 0 <= i < len(self._widgets):
            self._current = self._widgets[i]


class _QTabWidget(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tabs: list = []
        self._current = -1
        self._tab_enabled: list = []
        self.currentChanged = _BoundSignal("currentChanged")

    def addTab(self, w, title):
        self._tabs.append((w, title))
        self._tab_enabled.append(True)
        self._attach_child(w)
        if self._current < 0:
            self._current = 0
        return len(self._tabs) - 1

    def _attach_child(self, w):
        if isinstance(w, _Widget):
            w._parent = self
            if w not in self._children:
                self._children.append(w)

    def setCurrentIndex(self, i):
        if i != self._current:
            self._current = i
            if not getattr(self, "_signals_blocked", False):
                self.currentChanged.emit(i)

    def currentIndex(self): return self._current  # noqa: N802
    def setTabEnabled(self, i, v): self._tab_enabled[i] = bool(v)  # noqa: N802
    def isTabEnabled(self, i): return self._tab_enabled[i]  # noqa: N802
    def widget(self, i): return self._tabs[i][0]
    def tabText(self, i): return self._tabs[i][1]  # noqa: N802


class _QSplitter(_Widget):
    def __init__(self, orientation=None, parent=None) -> None:
        if isinstance(orientation, _Widget) and parent is None:
            parent, orientation = orientation, None
        super().__init__(parent)
        self._widgets: list = []
        self._sizes = None
        self._collapsible = True
        self._stretch: dict = {}

    def setChildrenCollapsible(self, v): self._collapsible = bool(v)  # noqa: N802
    def addWidget(self, w):
        self._widgets.append(w)
        w._parent = self
        if w not in self._children:
            self._children.append(w)
    def setStretchFactor(self, i, f): self._stretch[i] = f  # noqa: N802
    def setSizes(self, s): self._sizes = list(s)  # noqa: N802


class _QFrame(_Widget):
    pass


class _QSizePolicy:
    class Policy:
        Expanding = 7


class _QApplication:
    @staticmethod
    def clipboard():
        return _CLIPBOARD


# ---------------------------------------------------------------------------
# QtPdf stubs (driven via the same preview_widgets monkeypatch seam the Python
# tests use — here the stub classes simply ARE what the seam resolves).
# ---------------------------------------------------------------------------


class _FakeQPdfDocument(_QObject):
    """Controllable fake: load() succeeds synchronously by default."""

    class Status:
        Null = "Null"
        Loading = "Loading"
        Ready = "Ready"
        Unloading = "Unloading"
        Error = "Error"

    class Error:
        None_ = "None"
        FileNotFound = "FileNotFound"
        InvalidFileFormat = "InvalidFileFormat"

    # class knobs the generator tunes per scenario
    next_page_count = 3
    next_error = Error.None_
    next_status = Status.Ready
    page_text_prefix = "PAGE"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.statusChanged = _BoundSignal("statusChanged")
        self._status = _FakeQPdfDocument.Status.Null
        self._error = _FakeQPdfDocument.Error.None_
        self._page_count = 0
        self._loaded_from = None

    def load(self, source):
        self._loaded_from = source
        self._page_count = _FakeQPdfDocument.next_page_count
        self._error = _FakeQPdfDocument.next_error
        self._status = _FakeQPdfDocument.next_status
        if self._status in (self.Status.Ready, self.Status.Error):
            self.statusChanged.emit(self._status)
        return self._error

    def status(self): return self._status
    def error(self): return self._error
    def pageCount(self): return self._page_count  # noqa: N802
    def pagePointSize(self, i): return _QSizeF(595.0, 842.0)  # noqa: N802
    def render(self, i, size):
        if self._page_count <= 0:
            return _QImage(valid=False)
        return _QImage(w=size.width(), h=size.height(), valid=True)

    def getAllText(self, i):  # noqa: N802
        doc = self

        class _Sel:
            def text(self):
                return f"{doc.page_text_prefix}{i + 1} TEXT"

        return _Sel()


class _FakeQPdfNavigator(_QObject):
    def __init__(self) -> None:
        super().__init__()
        self.currentZoomChanged = _BoundSignal("currentZoomChanged")
        self.currentPageChanged = _BoundSignal("currentPageChanged")
        self._zoom = 1.0
        self._page = 0
        self.jumps: list = []

    def currentZoom(self): return self._zoom  # noqa: N802
    def jump(self, page, location, zoom=None):
        self._page = page
        self.jumps.append((page, zoom))


class _FakeQPdfView(_Widget):
    class ZoomMode:
        Custom = "Custom"
        FitToWidth = "FitToWidth"
        FitInView = "FitInView"

    class PageMode:
        SinglePage = "SinglePage"
        MultiPage = "MultiPage"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc = None
        self._navigator = _FakeQPdfNavigator()
        self._zoom_mode = None
        self._zoom_factor = None
        self._page_mode = None

    def setDocument(self, d): self._doc = d  # noqa: N802
    def pageNavigator(self): return self._navigator  # noqa: N802
    def setZoomMode(self, m): self._zoom_mode = m  # noqa: N802
    def setZoomFactor(self, f): self._zoom_factor = f  # noqa: N802
    def setPageMode(self, m): self._page_mode = m  # noqa: N802


# ---------------------------------------------------------------------------
# QtMultimedia stubs
# ---------------------------------------------------------------------------


class _FakeQMediaPlayer(_QObject):
    class PlaybackState:
        StoppedState = 0
        PlayingState = 1
        PausedState = 2

    class MediaStatus:
        NoMedia = 0
        LoadingMedia = 1
        LoadedMedia = 2
        InvalidMedia = 7

    class Error:
        NoError = 0
        ResourceError = 1
        FormatError = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.positionChanged = _BoundSignal("positionChanged")
        self.durationChanged = _BoundSignal("durationChanged")
        self.errorOccurred = _BoundSignal("errorOccurred")
        self.mediaStatusChanged = _BoundSignal("mediaStatusChanged")
        self._state = self.PlaybackState.StoppedState
        self._pos = 0
        self._dur = 0
        self._source = None
        self._audio = None
        self._video = None
        self.calls: list = []

    def setAudioOutput(self, a): self._audio = a  # noqa: N802
    def setVideoOutput(self, v): self._video = v  # noqa: N802
    def setSource(self, u): self._source = u  # noqa: N802
    def source(self): return self._source
    def play(self):
        self._state = self.PlaybackState.PlayingState
        self.calls.append("play")
    def pause(self):
        self._state = self.PlaybackState.PausedState
        self.calls.append("pause")
    def stop(self):
        self._state = self.PlaybackState.StoppedState
        self.calls.append("stop")
    def playbackState(self): return self._state  # noqa: N802
    def position(self): return self._pos
    def duration(self): return self._dur
    def setPosition(self, ms): self._pos = ms  # noqa: N802


class _FakeQAudioOutput(_QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._volume = None

    def setVolume(self, v): self._volume = v  # noqa: N802
    def volume(self): return self._volume


class _FakeQVideoWidget(_Widget):
    pass


# ---------------------------------------------------------------------------
# QtWebEngine stubs
# ---------------------------------------------------------------------------


class _QWebEngineUrlRequestInfo:
    def __init__(self, url) -> None:
        self._url = url
        self._blocked = False

    def requestUrl(self): return self._url  # noqa: N802
    def block(self, v): self._blocked = bool(v)


class _QWebEngineUrlRequestInterceptor(_QObject):
    # No interceptRequest() — PySide virtual dispatch must reach the
    # _LocalOnlyRequestInterceptor mixin further down the MRO.
    pass


class _QWebEngineSettings:
    class WebAttribute:
        LocalContentCanAccessRemoteUrls = 19

    def __init__(self) -> None:
        self._attrs: dict = {}

    def setAttribute(self, a, v): self._attrs[a] = v  # noqa: N802


class _QWebEngineProfile(_QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._interceptor = None

    def setUrlRequestInterceptor(self, i): self._interceptor = i  # noqa: N802


class _QWebEnginePage(_QObject):
    # No acceptNavigationRequest() — virtual dispatch must reach the
    # _LocalOnlyPage mixin further down the MRO.
    def __init__(self, profile=None, parent=None) -> None:
        super().__init__(parent)
        self._profile = profile


class _QWebEngineView(_Widget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page = None
        self._settings = _QWebEngineSettings()
        self._loaded = None
        self._html = None
        self._zoom = 1.0

    def setPage(self, p): self._page = p  # noqa: N802
    def settings(self): return self._settings
    def load(self, url): self._loaded = url
    def setHtml(self, h, base=None): self._html = (h, base)  # noqa: N802
    def setZoomFactor(self, z): self._zoom = z  # noqa: N802


# ---------------------------------------------------------------------------
# numpy stub — elementwise 1-D/2-D ops the exercised code paths need
# ---------------------------------------------------------------------------


class _NDArray:
    def __init__(self, data) -> None:
        self._data = data  # list or list-of-lists

    @property
    def shape(self):
        if self._data and isinstance(self._data[0], list):
            return (len(self._data), len(self._data[0]))
        return (len(self._data),)

    @property
    def T(self):
        rows, cols = self.shape
        return _NDArray([[self._data[r][c] for r in range(rows)]
                         for c in range(cols)])

    @property
    def data(self):
        # flat bytes-ish handle (only used as QImage data arg)
        return self

    def reshape(self, n):
        flat = []

        def rec(x):
            if isinstance(x, list):
                for y in x:
                    rec(y)
            else:
                flat.append(x)
        rec(self._data)
        return _NDArray(flat)

    def _bin(self, other, fn):
        if isinstance(other, _NDArray):
            return _NDArray([fn(a, b) for a, b in zip(self._data, other._data)])
        return _NDArray([fn(a, other) for a in self._data])

    def __mul__(self, o): return self._bin(o, lambda a, b: a * b)
    def __rmul__(self, o): return self._bin(o, lambda a, b: a * b)
    def __sub__(self, o): return self._bin(o, lambda a, b: a - b)
    def __rsub__(self, o): return _NDArray([o - a for a in self._data])
    def __iter__(self): return iter(self._data)
    def __len__(self): return len(self._data)


def _np_linspace(a, b, n):
    if n <= 1:
        return _NDArray([float(a)])
    step = (b - a) / (n - 1)
    return _NDArray([a + i * step for i in range(n)])


def _np_clip(arr, lo, hi):
    return _NDArray([max(lo, min(hi, x)) for x in arr])


def _np_minimum(a, b):
    return _NDArray([min(x, y) for x, y in zip(a, b)])


def _np_asarray(v, dtype=None):
    if isinstance(v, _NDArray):
        return v
    return _NDArray(v)


def _np_ascontiguousarray(v):
    return v


class _np_errstate:
    def __init__(self, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _np_isfinite(v):
    import math
    return math.isfinite(v)


def _np_nanmin(arr):
    import math
    return min(x for x in arr if math.isfinite(x))


def _np_nanmax(arr):
    import math
    return max(x for x in arr if math.isfinite(x))


def _install_pyside_stub() -> None:
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtpdf = types.ModuleType("PySide6.QtPdf")
    qtpdfw = types.ModuleType("PySide6.QtPdfWidgets")
    qtmm = types.ModuleType("PySide6.QtMultimedia")
    qtmmw = types.ModuleType("PySide6.QtMultimediaWidgets")
    qtwe_core = types.ModuleType("PySide6.QtWebEngineCore")
    qtwe_w = types.ModuleType("PySide6.QtWebEngineWidgets")

    for name, val in {
        "QObject": _QObject, "Signal": _Signal, "QSettings": _QSettings,
        "QTimer": _QTimer, "Qt": _Qt, "QPoint": _QPoint, "QPointF": _QPointF,
        "QSize": _QSize, "QSizeF": _QSizeF, "QRectF": _QRectF,
        "QUrl": _QUrl, "QBuffer": _QBuffer, "QByteArray": _QByteArray,
        "QIODevice": _QIODevice, "QEvent": _QEvent,
        "QModelIndex": _QModelIndex, "QItemSelection": _QItemSelection,
        "QItemSelectionModel": _QItemSelectionModel,
        "QAbstractTableModel": _QAbstractTableModel,
    }.items():
        setattr(qtcore, name, val)

    for name, val in {
        "QBrush": _QBrush, "QColor": _QColor, "QFont": _QFont,
        "QFontMetrics": _QFontMetrics, "QKeySequence": _QKeySequence,
        "QPainter": _QPainter, "QPixmap": _QPixmap, "QImage": _QImage,
        "QImageReader": _QImageReader, "QStandardItem": _QStandardItem,
        "QStandardItemModel": _QStandardItemModel, "qRgba": _qRgba,
        "QClipboard": _QClipboard,
    }.items():
        setattr(qtgui, name, val)

    for name, val in {
        "QApplication": _QApplication, "QWidget": _Widget, "QLabel": _QLabel,
        "QPushButton": _QPushButton, "QSlider": _QSlider,
        "QComboBox": _QComboBox, "QCheckBox": _QCheckBox,
        "QSpinBox": _QSpinBox, "QTableView": _QTableView,
        "QTreeView": _QTreeView, "QTextEdit": _QTextEdit,
        "QTextBrowser": _QTextBrowser, "QScrollArea": _QScrollArea,
        "QScrollBar": _QScrollBar, "QStackedWidget": _QStackedWidget,
        "QTabWidget": _QTabWidget, "QSplitter": _QSplitter,
        "QFrame": _QFrame, "QVBoxLayout": _QVBoxLayout,
        "QHBoxLayout": _QHBoxLayout, "QFormLayout": _QFormLayout,
        "QHeaderView": _QHeaderView, "QSizePolicy": _QSizePolicy,
    }.items():
        setattr(qtwidgets, name, val)

    qtpdf.QPdfDocument = _FakeQPdfDocument
    qtpdfw.QPdfView = _FakeQPdfView
    qtmm.QMediaPlayer = _FakeQMediaPlayer
    qtmm.QAudioOutput = _FakeQAudioOutput
    qtmmw.QVideoWidget = _FakeQVideoWidget
    qtwe_core.QWebEnginePage = _QWebEnginePage
    qtwe_core.QWebEngineProfile = _QWebEngineProfile
    qtwe_core.QWebEngineSettings = _QWebEngineSettings
    qtwe_core.QWebEngineUrlRequestInterceptor = _QWebEngineUrlRequestInterceptor
    qtwe_core.QWebEngineUrlRequestInfo = _QWebEngineUrlRequestInfo
    qtwe_w.QWebEngineView = _QWebEngineView

    pyside.QtCore = qtcore
    pyside.QtGui = qtgui
    pyside.QtWidgets = qtwidgets
    for mod_name, mod in {
        "PySide6": pyside, "PySide6.QtCore": qtcore, "PySide6.QtGui": qtgui,
        "PySide6.QtWidgets": qtwidgets, "PySide6.QtPdf": qtpdf,
        "PySide6.QtPdfWidgets": qtpdfw,
        "PySide6.QtMultimedia": qtmm,
        "PySide6.QtMultimediaWidgets": qtmmw,
        "PySide6.QtWebEngineCore": qtwe_core,
        "PySide6.QtWebEngineWidgets": qtwe_w,
    }.items():
        sys.modules[mod_name] = mod


def _install_numpy_stub() -> None:
    np = types.ModuleType("numpy")
    np.ndarray = _NDArray
    np.float32 = float
    np.linspace = _np_linspace
    np.clip = _np_clip
    np.minimum = _np_minimum
    np.asarray = _np_asarray
    np.ascontiguousarray = _np_ascontiguousarray
    np.errstate = _np_errstate
    np.isfinite = _np_isfinite
    np.nanmin = _np_nanmin
    np.nanmax = _np_nanmax
    sys.modules["numpy"] = np


def _install_pwb_stubs() -> None:
    """Stub the out-of-scope paleo_workbench seams (viz/preview_provider)."""
    # paleo_workbench.ui.style — palette() backed by the REAL tokens, bind()
    # applies the render once (same observable effect as the real registry).
    import _legacy_reference
    _legacy_reference.ensure_legacy_reference()  # archived-reference shim
    import paleo_workbench.tokens as real_tokens

    style = types.ModuleType("paleo_workbench.ui.style")
    style.palette = lambda: real_tokens.palette_for("light")

    def _bind(widget, render):
        try:
            widget.setStyleSheet(render())
        except Exception:
            pass

    style.bind = _bind
    sys.modules["paleo_workbench.ui.style"] = style

    theme = types.ModuleType("paleo_workbench.ui.theme")
    theme.theme_manager = types.SimpleNamespace(
        current_theme=types.SimpleNamespace(value="light"))
    sys.modules["paleo_workbench.ui.theme"] = theme

    # preview_provider stub — PreviewResult record (UI-03 domain).
    pp = types.ModuleType("paleo_workbench.ui.pages.preview_provider")

    class PreviewResult:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    pp.PreviewResult = PreviewResult
    sys.modules["paleo_workbench.ui.pages.preview_provider"] = pp

    # viz package + seismic_3d_api sentinel + geoviz host stub.
    viz = types.ModuleType("paleo_workbench.viz")
    viz.__path__ = [str(REPO_ROOT / "paleo_workbench" / "viz")]
    sys.modules["paleo_workbench.viz"] = viz

    s3d = types.ModuleType("paleo_workbench.viz.seismic_3d_api")

    def fast_slice_to_indexed8(volume, axis, index, value_range=None):
        # Sentinel: deterministic 4x3 norm plane (not the real kernel —
        # that lives in libs/visualization's own oracle).
        norm = _NDArray([[float((i + index) % 256) for i in range(3)]
                         for _ in range(4)])
        return norm, 0.0, 1.0

    def global_stretch_range(volume):
        return (0.0, 1.0)

    s3d.fast_slice_to_indexed8 = fast_slice_to_indexed8
    s3d.global_stretch_range = global_stretch_range
    s3d.HAS_CPP_SEISMIC = False
    sys.modules["paleo_workbench.viz.seismic_3d_api"] = s3d
    viz.seismic_3d_api = s3d

    hosts = types.ModuleType("paleo_workbench.viz.hosts")
    hosts.__path__ = [str(REPO_ROOT / "paleo_workbench" / "viz" / "hosts")]
    sys.modules["paleo_workbench.viz.hosts"] = hosts

    gph = types.ModuleType("paleo_workbench.viz.hosts.geoviz_preview_host")

    class GeoVizPreviewHost(_Widget):
        def __init__(self, engine=None, well_state_store=None, parent=None):
            super().__init__(parent)
            self._engine = engine
            self.rendered: list = []
            self.cleared = 0
            self.released = 0

        def render(self, prepared):
            self.rendered.append(prepared)

        def clear(self):
            self.cleared += 1

        def release_all(self):
            self.released += 1

    gph.GeoVizPreviewHost = GeoVizPreviewHost
    sys.modules["paleo_workbench.viz.hosts.geoviz_preview_host"] = gph
    hosts.geoviz_preview_host = gph


_install_pyside_stub()
_install_numpy_stub()
_install_pwb_stubs()

# ---------------------------------------------------------------------------
# Real module imports (PySide6 now stubbed)
# ---------------------------------------------------------------------------

import paleo_workbench.ui.pages.table_preview_widget as table_mod  # noqa: E402
import paleo_workbench.ui.pages.text_preview_widget as text_mod  # noqa: E402
import paleo_workbench.ui.pages.rich_text_preview_widget as rich_mod  # noqa: E402
import paleo_workbench.ui.pages.message_preview_widget as message_mod  # noqa: E402
import paleo_workbench.ui.pages.json_tree_preview_widget as json_mod  # noqa: E402
import paleo_workbench.ui.pages.image_preview_widget as image_mod  # noqa: E402
import paleo_workbench.ui.pages.pdf_preview_widget as pdf_mod  # noqa: E402
import paleo_workbench.ui.pages.media_preview_widget as media_mod  # noqa: E402
import paleo_workbench.ui.pages.web_document_preview_widget as web_mod  # noqa: E402
import paleo_workbench.ui.pages.seismic_slice_preview_widget as seis_mod  # noqa: E402
import paleo_workbench.ui.pages.summary_table_preview_widget as summary_mod  # noqa: E402
import paleo_workbench.ui.pages.geotiff_preview_widget as geotiff_mod  # noqa: E402
import paleo_workbench.ui.pages.preview_settings as ps_mod  # noqa: E402
import paleo_workbench.ui.pages.preview_settings_panel as panel_mod  # noqa: E402
import paleo_workbench.ui.pages.lazy_visualization_tabs as lazy_mod  # noqa: E402
import paleo_workbench.ui.pages.preview_widgets as pw_facade  # noqa: E402

from paleo_workbench.resources.preview_settings import PreviewSettings  # noqa: E402


# ===========================================================================
# Section builders
# ===========================================================================


def build_settings() -> dict:
    defaults = PreviewSettings.defaults()
    mapping = defaults.to_mapping()

    # from_mapping cases: (label, input, expect | error-kind)
    cases = []

    def fm(label, values):
        try:
            s = PreviewSettings.from_mapping(values)
            cases.append({"label": label, "ok": True,
                          "settings": s.to_mapping()})
        except TypeError as e:
            cases.append({"label": label, "ok": False, "kind": "TypeError",
                          "error": str(e)})
        except ValueError as e:
            cases.append({"label": label, "ok": False, "kind": "ValueError",
                          "error": str(e)})

    fm("empty", {})
    fm("subset_valid", {"font_size": 20, "wrap_text": True,
                        "pdf_fit_mode": "page"})
    fm("unknown_ignored", {"no_such_key": 1, "font_size": 10})
    fm("bool_not_bool", {"wrap_text": 1})
    fm("int_not_int", {"font_size": "12"})
    fm("int_bool", {"font_size": True})
    fm("below_min", {"font_size": 4})
    fm("above_max", {"table_max_rows": 5000})
    fm("bad_fit_mode", {"pdf_fit_mode": "stretch"})
    fm("bad_density", {"density": "spacious"})
    fm("bad_theme", {"theme_mode": "dark"})

    modes = ["text", "rich_text", "web_document", "table", "well_log",
             "seismic", "image", "geotiff", "pdf", "json_tree", "media",
             "geoviz", "unknown_mode", ""]

    # store roundtrip via the REAL PreviewSettingsStore + stub QSettings
    store = ps_mod.PreviewSettingsStore(
        _QSettings("TEST_ORG", "TEST_APP"))
    loaded_default = store.load().to_mapping()
    custom = PreviewSettings.from_mapping({
        "font_size": 14, "media_volume": 55, "pdf_fit_mode": "page",
        "wrap_text": True})
    store.save(custom)
    loaded_custom = store.load().to_mapping()
    # tamper one value with a wrong type then reload → defaults
    raw = _QSettings("TEST_ORG", "TEST_APP")
    raw.beginGroup(ps_mod.PreviewSettingsStore.GROUP)
    raw.setValue("font_size", "not-an-int")
    raw.endGroup()
    loaded_bad = store.load().to_mapping()
    reset_result = store.reset().to_mapping()

    return {
        "defaults": mapping,
        "fingerprint": defaults.fingerprint(),
        "from_mapping_cases": cases,
        "mode_category": {m: panel_mod._MODE_CATEGORY.get(m, "general")
                          for m in modes},
        "store": {
            "loaded_default": loaded_default,
            "loaded_custom": loaded_custom,
            "loaded_bad": loaded_bad,
            "reset_result": reset_result,
            "group": ps_mod.PreviewSettingsStore.GROUP,
        },
    }


def _model_probe(model, row, col):
    """Freeze the data() role answers of a cell as role->string map."""
    idx = model.index(row, col)
    out = {"display": model.data(idx, _Qt.ItemDataRole.DisplayRole)}
    f = model.data(idx, _Qt.ItemDataRole.FontRole)
    out["font"] = None
    if f is not None:
        out["font"] = "mono_bold" if getattr(f, "_bold", False) else "mono"
    fg = model.data(idx, _Qt.ItemDataRole.ForegroundRole)
    out["fg"] = None
    if fg is not None and getattr(fg, "_color", None) is not None:
        out["fg"] = fg._color.name()
    bg = model.data(idx, _Qt.ItemDataRole.BackgroundRole)
    out["bg"] = None
    if bg is not None and getattr(bg, "_color", None) is not None:
        out["bg"] = bg._color.name()
    al = model.data(idx, _Qt.ItemDataRole.TextAlignmentRole)
    out["align"] = al
    return out


def build_table() -> dict:
    is_number_cases = [
        "NaN", "0", "-1", "3.14", "+2.5", ".5", "5.", "1e3", "1E-3", "1_000",
        "inf", "-inf", "infinity", "nan", "NAN", "0x10", "0b11", "1__0",
        "_10", "10_", "", "abc", " 12", "12 ", "1.2.3", "--5", "深度",
    ]
    is_number_out = {v: table_mod._is_number(v) for v in is_number_cases}

    depth_cases = [
        ["DEPT", "GR", "CALI"], ["depth", "x"], ["Depth", "y"],
        ["深度", "z"], ["dept_extra", "w"], ["A", "B"], [],
    ]
    depth_out = []
    for headers in depth_cases:
        m = table_mod.TablePreviewModel()
        m.set_table(tuple(headers), ())
        depth_out.append({"headers": headers, "depth_col": m._depth_column,
                          "curve_def": m._is_curve_def})

    curve_cases = [
        ["曲线", "单位", "值"], ["Mnemonic", "Unit", "Val"],
        ["曲线", "b"], ["曲线A", "b", "c"], ["a", "b", "c"], [],
    ]
    curve_out = []
    for headers in curve_cases:
        m = table_mod.TablePreviewModel()
        m.set_table(tuple(headers), ())
        curve_out.append({"headers": headers, "curve_def": m._is_curve_def,
                          "depth_col": m._depth_column})

    # truncation: (rows, cols) → (keep, truncated, message)
    trunc_cases = [(10, 5), (0, 0), (300000, 5), (5001, 200), (250001, 4)]
    trunc_out = []
    for n_rows, n_cols in trunc_cases:
        w = table_mod.TablePreviewWidget()
        w.auto_fit_columns = False
        headers = tuple(f"c{i}" for i in range(n_cols))
        rows = tuple(tuple(f"v{r}_{c}" for c in range(n_cols))
                     for r in range(n_rows))
        w.load_table(headers, rows)
        trunc_out.append({
            "rows": n_rows, "cols": n_cols,
            "kept": w._model.rowCount(),
            "truncated": w.truncated,
            "message": w.truncation_message,
            "tooltip": w._tooltip,
        })

    # copy_all TSV + row_text padding
    w = table_mod.TablePreviewWidget()
    w.auto_fit_columns = False
    w.load_table(("a", "b", "c"), (("1", "2", "3"), ("x",), ()))
    copy_all = w.copy_all()
    row_texts = [w._model.row_text(r) for r in range(3)]
    w2 = table_mod.TablePreviewWidget()
    w2.auto_fit_columns = False
    w2.load_table((), ())
    copy_all_empty = w2.copy_all()

    # cell role probes over a mixed table (depth col + curve-def + NaN)
    m = table_mod.TablePreviewModel()
    m.set_table(("DEPTH", "GR", "CALI"),
                (("100.5", " 80 ", "NaN"), ("x", "-1", "abc")))
    depth_table_cells = [_model_probe(m, r, c) for r in range(2)
                         for c in range(3)]
    m2 = table_mod.TablePreviewModel()
    m2.set_table(("曲线", "单位", "描述", "备注"),
                 (("GR", "gAPI", "gamma", "7"),))
    curve_table_cells = [_model_probe(m2, 0, c) for c in range(4)]
    m3 = table_mod.TablePreviewModel()
    m3.set_table(("A", "B"), (("  padded  ", "NaN"), ("3.5", "plain")))
    plain_table_cells = [_model_probe(m3, r, c) for r in range(2)
                         for c in range(2)]

    return {
        "is_number": is_number_out,
        "depth_cases": depth_out,
        "curve_cases": curve_out,
        "truncation_cases": trunc_out,
        "copy_all": copy_all,
        "row_texts": row_texts,
        "copy_all_empty": copy_all_empty,
        "depth_table_cells": depth_table_cells,
        "curve_table_cells": curve_table_cells,
        "plain_table_cells": plain_table_cells,
    }


def _dump_item(item):
    """Freeze a QStandardItem row pair as a nested dict."""
    key = item.text() if item is not None else ""
    children = []
    for r in range(item.rowCount()):
        children.append(_dump_item(item.child(r, 0)))
    return {"key": key, "children": children}


def _dump_row(items):
    key_item = items[0]
    val_item = items[1] if len(items) > 1 else None
    return {
        "key": key_item.text(),
        "label": val_item.text() if val_item is not None else "",
        "has_container": key_item.data(json_mod._ROLE_CONTAINER) is not None,
        "has_more": key_item.data(json_mod._ROLE_MORE) is not None,
        # child rows are [k, v] pairs under the key item — same shape as
        # _dump_row_like produces for the model root.
        "children": _dump_row_like(key_item),
    }


def _dump_row_like(item):
    """Children under a key item are stored as row pairs on the item."""
    # children appended via appendRow([k, v]) → item._rows entries
    rows = []
    for r in range(item.rowCount()):
        pair = item._rows[r]
        k = pair[0]
        v = pair[1] if len(pair) > 1 else None
        rows.append({
            "key": k.text(),
            "label": v.text() if v is not None else "",
            "has_container": k.data(json_mod._ROLE_CONTAINER) is not None,
            "has_more": k.data(json_mod._ROLE_MORE) is not None,
            "children": _dump_row_like(k),
        })
    return rows


def build_json_tree() -> dict:
    # _build_row outcomes for representative values
    w = json_mod.JsonTreePreviewWidget()
    w.array_collapse_threshold = 3

    def spec(key, value, depth=0):
        items = w._build_row(key, value, depth=depth)
        return _dump_row(items)

    row_cases = [
        ("scalar_str", "k", "hello"),
        ("scalar_int", "k", 42),
        ("scalar_float", "k", 3.5),
        ("scalar_true", "k", True),
        ("scalar_false", "k", False),
        ("scalar_none", "k", None),
        ("small_dict", "k", {"a": 1, "b": "x"}),
        ("small_list", "k", [1, "a", None]),
        ("lazy_dict", "k", {f"k{i}": i for i in range(5)}),
        ("lazy_list", "k", [0, 1, 2, 3, 4]),
        ("nested", "k", {"inner": [1, {"deep": True}]}),
    ]
    rows = [{"case": c, "spec": spec(k, v)} for c, k, v in row_cases]

    # depth cap
    deep = spec("k", {"a": 1}, depth=64)

    # load_payload trees
    def tree(payload, threshold=3):
        w2 = json_mod.JsonTreePreviewWidget()
        w2.array_collapse_threshold = threshold
        w2.expand_depth = 0  # skip expand walk (stub expand records only)
        w2.load_payload(payload)
        root = w2._model.invisibleRootItem()
        return _dump_row_like(root)

    trees = [
        {"case": "dict_small",
         "tree": tree({"a": 1, "b": [1, 2]}, threshold=3)},
        {"case": "dict_lazy_root",
         "tree": tree({f"k{i}": i for i in range(5)}, threshold=3)},
        {"case": "list_root", "tree": tree([1, 2], threshold=3)},
        {"case": "scalar_root", "tree": tree("just-a-string", threshold=3)},
    ]

    # _container_items + _append_batch + sentinel
    container = [f"item{i}" for i in range(7)]
    items_list = [[k, str(v)] for k, v in w._container_items(container)]
    container_d = {"a": 1, "b": 2}
    items_dict = [[k, str(v)] for k, v in w._container_items(container_d)]

    big = list(range(4500))  # > _EXPAND_BATCH=2000 → two batches + sentinel
    parent = _QStandardItem("parent")
    off1 = w._append_batch(parent, big, 0, 0)
    sent1 = []
    if off1 < len(big):
        w._append_sentinel(parent, big, off1)
        sent1 = [parent._rows[-1][0].text()]
    off2 = w._append_batch(parent, big, off1, 0)
    sent2 = []
    if off2 < len(big):
        w._append_sentinel(parent, big, off2)
        sent2 = [parent._rows[-1][0].text()]
    off3 = w._append_batch(parent, big, off2, 0)
    batch_trace = {"off1": off1, "off2": off2, "off3": off3,
                   "sentinel1": sent1, "sentinel2": sent2,
                   "total_rows_after": parent.rowCount()}

    return {
        "expand_batch": json_mod._EXPAND_BATCH,
        "max_build_depth": json_mod.JsonTreePreviewWidget._MAX_BUILD_DEPTH,
        "row_cases": rows,
        "depth_cap": deep,
        "trees": trees,
        "container_items_list": items_list,
        "container_items_dict": items_dict,
        "batch_trace": batch_trace,
    }


def build_pdf() -> dict:
    # Pure zoom math via the widget with a fake doc+view (view present)
    out = {"zoom_sequences": [], "fallback": {}, "view_path": {}}

    def widget(view=True, pages=3):
        _FakeQPdfDocument.next_page_count = pages
        _FakeQPdfDocument.next_error = _FakeQPdfDocument.Error.None_
        _FakeQPdfDocument.next_status = _FakeQPdfDocument.Status.Ready
        if view:
            pw_facade.QPdfView = _FakeQPdfView
        else:
            pw_facade.QPdfView = None
        w = pdf_mod.PdfPreviewWidget()
        return w

    # zoom sequence on the QPdfView path
    w = widget(view=True)
    seq = []
    for op in ["in", "in", "out", "out", "out", "in"]:
        getattr(w, "_zoom_in" if op == "in" else "_zoom_out")()
        seq.append({"op": op, "percent": w.zoom_percent,
                    "fit_mode": w.fit_mode,
                    "zoom_label": w.zoom_label.text(),
                    "view_zoom_mode": w.pdf_view._zoom_mode,
                    "view_zoom_factor": w.pdf_view._zoom_factor})
    # clamp boundaries
    w.zoom_percent = 790
    w._zoom_in()
    seq.append({"op": "in@790", "percent": w.zoom_percent,
                "fit_mode": w.fit_mode, "zoom_label": w.zoom_label.text()})
    w.zoom_percent = 11
    w._zoom_out()
    seq.append({"op": "out@11", "percent": w.zoom_percent,
                "fit_mode": w.fit_mode, "zoom_label": w.zoom_label.text()})
    # fit buttons
    w._on_fit_page_clicked()
    seq.append({"op": "fit_page", "percent": w.zoom_percent,
                "fit_mode": w.fit_mode,
                "view_zoom_mode": w.pdf_view._zoom_mode,
                "page_checked": w.fit_page_btn._checked,
                "width_checked": w.fit_width_btn._checked})
    w._on_fit_width_clicked()
    seq.append({"op": "fit_width", "percent": w.zoom_percent,
                "fit_mode": w.fit_mode,
                "view_zoom_mode": w.pdf_view._zoom_mode,
                "page_checked": w.fit_page_btn._checked,
                "width_checked": w.fit_width_btn._checked})
    out["zoom_sequences"] = seq

    # load + page status + nav on the view path
    w = widget(view=True)
    w.load("/tmp/doc.pdf")
    view_path = {
        "page_label_after_load": w.page_label.text(),
        "prev_enabled": w.prev_btn.isEnabled(),
        "next_enabled": w.next_btn.isEnabled(),
        "page_mode": w.pdf_view._page_mode,
        "navigator_jumps": [list(j) for j in w.pdf_view._navigator.jumps],
    }
    w.next_page()
    view_path["after_next"] = {"page": w._page,
                               "page_label": w.page_label.text(),
                               "prev_enabled": w.prev_btn.isEnabled(),
                               "next_enabled": w.next_btn.isEnabled()}
    w.next_page()
    w.next_page()  # past last — no-op
    view_path["after_next3"] = {"page": w._page,
                                "page_label": w.page_label.text(),
                                "prev_enabled": w.prev_btn.isEnabled(),
                                "next_enabled": w.next_btn.isEnabled()}
    w.previous_page()
    view_path["after_prev"] = {"page": w._page,
                               "page_label": w.page_label.text()}
    # navigator-driven zoom/page sync
    w.pdf_view._navigator.currentZoomChanged.emit(2.345)
    view_path["zoom_sync"] = {"percent": w.zoom_percent,
                              "label": w.zoom_label.text(),
                              "fit_mode": w.fit_mode}
    w.pdf_view._navigator.currentPageChanged.emit(0)
    view_path["page_sync"] = {"page": w._page,
                              "label": w.page_label.text()}
    # copy all text
    w.copy_all_btn.click()
    view_path["copy_all"] = {"clipboard": _CLIPBOARD.text(),
                             "btn_text": w.copy_all_btn.text()}
    out["view_path"] = view_path

    # fallback path (no QPdfView): renders every page into the scroll area
    w = widget(view=False, pages=4)
    w.load("/tmp/doc2.pdf")
    fb = {
        "current_is_scroll": w._content_stack.currentWidget()
            is w._fallback_scroll,
        "labels": len(w._fallback_page_labels),
        "page_label": w.page_label.text(),
        "prev_enabled": w.prev_btn.isEnabled(),
        "next_enabled": w.next_btn.isEnabled(),
        "label0_h": w._fallback_page_labels[0].pixmap().height()
            if w._fallback_page_labels[0].pixmap() else None,
        "label0_w": w._fallback_page_labels[0].pixmap().width()
            if w._fallback_page_labels[0].pixmap() else None,
    }
    w.next_page()
    fb["after_next"] = {"page": w._page, "page_label": w.page_label.text(),
                        "scroll_value": w._fallback_scroll._vbar._value}
    # scroll tracking: move the bar past label y positions
    for i, lbl in enumerate(w._fallback_page_labels):
        lbl._y = i * 100  # fake geometry
    w._fallback_scroll.viewport()._h = 100
    w._on_fallback_scroll(150)
    fb["scroll_mid"] = {"page": w._page, "page_label": w.page_label.text()}
    # error path
    _FakeQPdfDocument.next_page_count = 0
    _FakeQPdfDocument.next_error = _FakeQPdfDocument.Error.InvalidFileFormat
    _FakeQPdfDocument.next_status = _FakeQPdfDocument.Status.Error
    w2 = widget(view=False)
    w2.load("/tmp/bad.pdf")
    fb["error"] = {"text": w2.fallback_image.text(),
                   "page_label": w2.page_label.text(),
                   "load_failed": w2._load_failed}
    out["fallback"] = fb

    # unavailable path (no QPdfDocument at all)
    pw_facade.QPdfDocument = None
    w3 = pdf_mod.PdfPreviewWidget()
    out["unavailable"] = {"text": w3.fallback_image.text(),
                          "page_label": w3.page_label.text(),
                          "copy_visible": w3.copy_all_btn.isVisible(),
                          "prev_enabled": w3.prev_btn.isEnabled()}
    pw_facade.QPdfDocument = _FakeQPdfDocument
    pw_facade.QPdfView = _FakeQPdfView
    return out


def build_image() -> dict:
    out = {}

    # failure path (undecodable source)
    w = image_mod.ImagePreviewWidget()
    w.load("/nonexistent.png")
    out["load_failure"] = {"text": w.text(), "pixmap_null":
                           w._pixmap is None or w._pixmap.isNull()}

    # success path: FAKEIMG sentinel decodes to 4000x3000 (bounded to 2048)
    w = image_mod.ImagePreviewWidget()
    w.resize(800, 600)
    w.load("FAKEIMG:4000x3000")
    fit_pm = w._pixmap
    out["load_ok"] = {
        "decoded_w": fit_pm.width(), "decoded_h": fit_pm.height(),
        "shown_w": w.pixmap().width() if w.pixmap() else None,
        "shown_h": w.pixmap().height() if w.pixmap() else None,
        "fit_mode": w._fit_mode, "zoom": w._zoom_factor,
    }

    # zoom sequence with emissions
    EMITTED.clear()
    w._zoom_factor = 1.0
    w._fit_mode = True
    seq = []
    for op in ["in", "in", "in", "out", "reset"]:
        if op == "in":
            w.zoom_in()
        elif op == "out":
            w.zoom_out()
        else:
            w.reset_zoom()
        seq.append({"op": op, "zoom": w._zoom_factor,
                    "fit_mode": w._fit_mode,
                    "pixmap_null": w.pixmap() is None or w.pixmap().isNull()})
    out["zoom_seq"] = seq
    out["zoom_emitted"] = [v for n, v in EMITTED if n == "zoom_changed"]

    # zoom clamps at bounds
    w.set_zoom_factor(100.0)
    hi = {"zoom": w._zoom_factor, "fit": w._fit_mode}
    w.set_zoom_factor(0.0001)
    lo = {"zoom": w._zoom_factor, "fit": w._fit_mode}
    out["clamps"] = {"high": hi, "low": lo}

    # virtual size + pan clamp cases (zoom mode)
    w._pixmap = _QPixmap(2000, 1000, valid=True)
    w._zoom_factor = 2.0
    w.resize(800, 600)
    pan_cases = [(0, 0), (2000, 2000), (-2000, -2000), (700, 500), (-700, -500)]
    pans = []
    for x, y in pan_cases:
        p = w._clamp_pan(_QPoint(x, y))
        pans.append({"in": [x, y], "out": [p.x(), p.y()]})
    out["pan_cases"] = pans
    vs = w._virtual_size()
    out["virtual_size"] = list(vs)

    # fit mode size hints
    w._fit_mode = False
    out["size_hints_zoom"] = {"w": w.sizeHint().width(),
                              "h": w.sizeHint().height()}
    w._fit_mode = True
    return out


def build_media() -> dict:
    out = {}

    ms_cases = [0, 999, 1000, 61000, 60000, 3599999, 3600000, 7265000, -500]
    out["ms"] = {str(v): media_mod.MediaPreviewWidget._ms(v)
                 for v in ms_cases}

    # unavailable path: QtMultimedia classes forced off via the facade seam
    pw_facade.QMediaPlayer = None
    pw_facade.QAudioOutput = None
    pw_facade.QVideoWidget = None
    media_mod._media_classes = (None, None, None)
    w = media_mod.MediaPreviewWidget()
    ok = w.ensure_player()
    out["unavailable"] = {
        "ensure": ok, "status": w.status_label.text(),
        "play_enabled": w.play_btn.isEnabled(),
        "attempted": w._player_init_attempted,
        "available": w._player_available,
    }
    w.set_media_path("/tmp/a.mp3")
    out["unavailable_set_path"] = {"status": w.status_label.text(),
                                   "play_enabled": w.play_btn.isEnabled()}

    # available path with the fake player
    pw_facade.QMediaPlayer = _FakeQMediaPlayer
    pw_facade.QAudioOutput = _FakeQAudioOutput
    pw_facade.QVideoWidget = _FakeQVideoWidget
    media_mod._media_classes = (_FakeQMediaPlayer, _FakeQAudioOutput,
                                _FakeQVideoWidget)
    w = media_mod.MediaPreviewWidget()
    ok = w.ensure_player()
    avail = {"ensure": ok, "status": w.status_label.text(),
             "has_video": w._video_widget is not None,
             "volume": w._audio_out._volume}
    w.set_media_path("/tmp/clip.mp3")
    avail["after_path"] = {"status": w.status_label.text(),
                           "play_enabled": w.play_btn.isEnabled(),
                           "play_text": w.play_btn.text(),
                           "source_scheme": w._player.source().scheme()}
    # toggle play/pause labels
    w._toggle_play()
    avail["toggle1"] = {"text": w.play_btn.text(),
                        "state": w._player.playbackState()}
    w._toggle_play()
    avail["toggle2"] = {"text": w.play_btn.text(),
                        "state": w._player.playbackState()}
    # position/duration → time label
    w._player._dur = 125000
    w._player.durationChanged.emit(125000)
    w._player._pos = 61000
    w._player.positionChanged.emit(61000)
    avail["time"] = {"label": w.time_label.text(),
                     "slider_value": w.position_slider.value(),
                     "slider_max": w.position_slider._max}
    # error → decoder fallback
    w._player.errorOccurred.emit("err", "boom")
    avail["after_error"] = {"status": w.status_label.text(),
                            "play_enabled": w.play_btn.isEnabled(),
                            "path_label": w._path_label.text(),
                            "path_visible": w._path_label.isVisible(),
                            "controls_hidden": all(
                                not c.isVisible()
                                for c in w._control_widgets)}
    out["available"] = avail

    # autoplay path
    w = media_mod.MediaPreviewWidget()
    w.autoplay = True
    w.set_media_path("/tmp/auto.mp3")
    out["autoplay"] = {"play_text": w.play_btn.text(),
                       "status": w.status_label.text(),
                       "calls": list(w._player.calls)}
    return out


def build_web() -> dict:
    w = web_mod.WebDocumentPreviewWidget()
    schemes = ["file", "data", "about", "blob", "http", "https", "ftp",
               "javascript", "", "FILE"]
    intercept = {}
    for s in schemes:
        info = _QWebEngineUrlRequestInfo(_QUrl(url=f"{s}://x", scheme=s))
        w._interceptor.interceptRequest(info)
        intercept[s] = not info._blocked  # True = allowed through
    nav = {}
    for s in schemes:
        nav[s] = w._page.acceptNavigationRequest(
            _QUrl(url=f"{s}://x", scheme=s), None, True)
    w.load_document("/tmp/doc.html", "<b>hi</b>")
    html_call = {"html": w._engine_view._html[0],
                     "base_scheme": w._engine_view._html[1].scheme()}
    w.load_document("/tmp/doc.html")
    load_call = {"scheme": w._engine_view._loaded.scheme()}
    s = PreviewSettings.defaults()
    w.apply_settings(s)
    return {"intercept_allowed": intercept, "nav_allowed": nav,
            "html_call": html_call, "load_call": load_call,
            "zoom_factor": w._engine_view._zoom,
            "remote_attr": w._engine_view._settings._attrs.get(
                _QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls)}


def _fake_volume(shape):
    return _NDArray.__new__(_NDArray) if False else types.SimpleNamespace(
        shape=tuple(shape))


def build_seismic() -> dict:
    w = seis_mod.SeismicSlicePreviewWidget()
    combo_items = [w.type_combo.itemText(i) for i in range(w.type_combo.count())]

    # null-volume fallback path
    w.load_seismic("/tmp/x.segy", None, volume=None, message="")
    null_path = {"text": w.image_label.text(),
                 "slider_enabled": w.slider.isEnabled(),
                 "combo_enabled": w.type_combo.isEnabled(),
                 "index_label": w.index_label.text(),
                 "slider_max": w.slider.maximum()}

    ranges = []
    for shape in [(5, 7, 9), (1, 1, 1), (10, 3, 2)]:
        w2 = seis_mod.SeismicSlicePreviewWidget()
        w2.load_seismic("/tmp/x.segy", None,
                        volume=_fake_volume(shape), message="")
        for combo_idx in range(3):
            w2.type_combo.setCurrentIndex(combo_idx)
            ranges.append({
                "shape": list(shape), "axis": combo_idx,
                "slider_max": w2.slider.maximum(),
                "slider_value": w2.slider.value(),
                "index_label": w2.index_label.text(),
            })

    # render path: fake volume + sentinel slice fn; freeze color table +
    # scaled pixmap dims (slider up → SmoothTransformation)
    w3 = seis_mod.SeismicSlicePreviewWidget()
    w3.image_label.resize(404, 304)
    w3.load_seismic("/tmp/x.segy", None,
                    volume=_fake_volume((5, 7, 9)), message="")
    ct = getattr(w3, "_color_table", None) or []
    render = {
        "color_table_len": len(ct),
        "color_table_samples": [hex(ct[i]) for i in (0, 1, 64, 128, 192, 255)
                                ] if ct else [],
        "pixmap_w": w3.image_label.pixmap().width()
            if w3.image_label.pixmap() else None,
        "pixmap_h": w3.image_label.pixmap().height()
            if w3.image_label.pixmap() else None,
        "stretch_range": list(w3._stretch_range)
            if w3._stretch_range else None,
    }
    return {"combo_items": combo_items, "null_path": null_path,
            "slider_ranges": ranges, "render": render}


def build_summary() -> dict:
    w = summary_mod.SummaryTablePreviewWidget()

    def chip_val(chip):
        lbl = chip.findChild(_QLabel, "chip_val")
        return lbl.text() if lbl else None

    cases = []
    for rows in [
        (("井名", "W-1"), ("曲线数", "12"), ("采样点", "1500")),
        (("井名", " W-2 "), ("曲线数", "3"), ("采样点", "1,000")),
        (("井名", "W-3"), ("采样点", "abc"), ("曲线数", "7")),
        (("其他", "x"),),
    ]:
        w.load_summary(rows, ("h1",), (("r1",),), "msg")
        cases.append({
            "rows": [list(r) for r in rows],
            "well": chip_val(w.chip_well),
            "curves": chip_val(w.chip_curves),
            "samples": chip_val(w.chip_samples),
            "message": w.message_label.text(),
            "summary_min_h": w.summary_table.minimumHeight(),
        })

    # data tab enable/disable
    w.load_summary((("井名", "W"),), ("h",), (("r",),), "",
                   data_headers=("d1",), data_rows=(("v",),))
    data_on = w.tabs.isTabEnabled(1)
    w.load_summary((("井名", "W"),), ("h",), (("r",),), "")
    data_off = w.tabs.isTabEnabled(1)

    return {"chip_cases": cases, "data_tab_on": data_on,
            "data_tab_off": data_off,
            "tab_titles": [w.tabs.tabText(i) for i in range(2)]}


def build_lazy_tabs() -> dict:
    out = {"scenarios": []}

    def snap(w):
        cur_visual = w.visual_stack.currentWidget()
        vname = ("prompt" if cur_visual is w.prompt_label else
                 "loading" if cur_visual is w.loading_label else
                 "message" if cur_visual is w.message_panel else
                 "host" if cur_visual is w._host else "?")
        cur_summary = w.summary_stack.currentWidget()
        sname = ("table" if cur_summary is w.summary else
                 "text" if cur_summary is w.text else
                 "well_log" if cur_summary is w.well_log_summary else "?")
        return {"tab": w.currentIndex(), "visual": vname,
                "summary": sname, "requested": w._requested,
                "host_created": w._host is not None}

    import paleo_workbench.ui.pages.preview_provider as pp

    # scenario 1: load table summary → click visual tab → loading → preview
    EMITTED.clear()
    w = lazy_mod.LazyVisualizationTabs()
    steps = []
    w.load_summary(pp.PreviewResult(
        mode="table", table_headers=("a",), table_rows=(("1",),),
        message="m"))
    steps.append({"op": "load_table", **snap(w)})
    w.setCurrentIndex(1)
    steps.append({"op": "click_tab1", **snap(w)})
    w.show_loading()
    steps.append({"op": "loading", **snap(w)})
    w.show_preview({"prepared": 1})
    steps.append({"op": "preview", **snap(w)})
    emits1 = [n for n, _v in EMITTED]

    # scenario 2: text + well_log modes, error flows, reset
    EMITTED.clear()
    w = lazy_mod.LazyVisualizationTabs()
    steps2 = []
    w.load_summary(pp.PreviewResult(mode="text", text="hello"))
    steps2.append({"op": "load_text", **snap(w)})
    w.load_summary(pp.PreviewResult(
        mode="well_log", summary_rows=(("井名", "W"),),
        table_headers=("h",), table_rows=(("r",),), message="m2"))
    steps2.append({"op": "load_well_log", **snap(w)})
    w.show_error("bad thing", retryable=True, activate=True)
    steps2.append({"op": "error_retry", **snap(w)})
    w._request_retry()
    steps2.append({"op": "retry", **snap(w)})
    w.show_error("fatal", retryable=False, activate=False)
    steps2.append({"op": "error_fatal", **snap(w)})
    w.reset()
    steps2.append({"op": "reset", **snap(w)})
    emits2 = [n for n, _v in EMITTED]

    # scenario 3: no-steal — loading/preview while on tab 0
    EMITTED.clear()
    w = lazy_mod.LazyVisualizationTabs()
    steps3 = []
    w.load_summary(pp.PreviewResult(mode="table", table_headers=("a",),
                                    table_rows=(("1",),)))
    w.show_loading()
    steps3.append({"op": "loading_bg", **snap(w)})
    w.show_preview({"p": 1}, activate=False)
    steps3.append({"op": "preview_noactivate", **snap(w)})
    emits3 = [n for n, _v in EMITTED]

    # scenario 4: was_visual latch — preview while already on tab 1 stays
    EMITTED.clear()
    w = lazy_mod.LazyVisualizationTabs()
    steps4 = []
    w.load_summary(pp.PreviewResult(mode="table", table_headers=("a",),
                                    table_rows=(("1",),)))
    w.setCurrentIndex(1)
    steps4.append({"op": "click_tab1", **snap(w)})
    w.show_preview({"p": 1}, activate=False)
    steps4.append({"op": "preview_was_visual", **snap(w)})
    emits4 = [n for n, _v in EMITTED]

    # scenario 5: engine swap guard
    w = lazy_mod.LazyVisualizationTabs()
    _ = w.host
    guard = None
    try:
        w.set_engine(object())
    except RuntimeError as e:
        guard = str(e)

    return {"scenarios": [
        {"name": "click_flow", "steps": steps, "emitted": emits1},
        {"name": "modes_errors", "steps": steps2, "emitted": emits2},
        {"name": "no_steal", "steps": steps3, "emitted": emits3},
        {"name": "was_visual", "steps": steps4, "emitted": emits4},
    ], "engine_guard": guard}


def build_settings_panel() -> dict:
    store = ps_mod.PreviewSettingsStore(_QSettings("P_ORG", "P_APP"))
    panel = panel_mod.PreviewSettingsPanel(store=store)

    mode_cases = ["text", "rich_text", "web_document", "table", "well_log",
                  "seismic", "image", "geotiff", "pdf", "json_tree", "media",
                  "geoviz", "nonsense"]
    mode_map = {}
    for m in mode_cases:
        panel.set_preview_mode(m)
        mode_map[m] = {"combo_index": panel.category_combo.currentIndex(),
                       "page_index": panel.pages._widgets.index(
                           panel.pages.currentWidget())
                       if panel.pages.currentWidget() in panel.pages._widgets
                       else -1}

    # settings() round trip
    s = panel.settings()
    s_map = s.to_mapping()

    # apply → store.save + emitted payload
    EMITTED.clear()
    panel.font_size_spin.setValue(20)
    panel.media_volume_spin.setValue(33)
    panel.apply_btn.click()
    applied = [v for n, v in EMITTED if n == "settings_applied"]
    after_apply = store.load().to_mapping()

    # reset → defaults + emitted
    EMITTED.clear()
    panel.reset_btn.click()
    reset_emitted = [v for n, v in EMITTED if n == "settings_applied"]
    after_reset = store.load().to_mapping()
    controls_after_reset = panel.settings().to_mapping()

    return {
        "mode_map": mode_map,
        "settings_defaults": s_map,
        "applied": applied[-1].to_mapping() if applied else None,
        "after_apply": after_apply,
        "reset_emitted": reset_emitted[-1].to_mapping()
            if reset_emitted else None,
        "after_reset": after_reset,
        "controls_after_reset": controls_after_reset,
    }


def build_misc_widgets() -> dict:
    out = {}

    # text widget
    t = text_mod.TextPreviewWidget()
    s = PreviewSettings.from_mapping({"font_size": 18, "wrap_text": True})
    t.apply_settings(s)
    out["text"] = {"wrap": t._wrap, "font_size": t.font().pointSize()}
    t.load_text("abc")

    # rich text: wrap + resource filter verdicts
    r = rich_mod.RichTextPreviewWidget()
    r.apply_settings(PreviewSettings.from_mapping({"wrap_text": False}))
    verdicts = {}
    for scheme in ("file", "http", "https", "", "data"):
        res = r.loadResource(1, _QUrl(url=f"{scheme}://x", scheme=scheme))
        verdicts[scheme] = res is not None
    out["rich_text"] = {"wrap": r._wrap, "readonly": r._readonly,
                        "resource_allowed": verdicts}

    # message
    m = message_mod.MessagePreviewWidget()
    m.set_message("hello 世界")
    out["message"] = {"text": m.text()}

    # geotiff
    g = geotiff_mod.GeoTiffPreviewWidget()
    g.resize(400, 300)
    g.load("/tmp/x.tif", None, b"", (("CRS", "EPSG:4326"), ("范围", "1,2,3,4")))
    out["geotiff_noimg"] = {
        "label": g._image_label.text(),
        "summary_rows": g.summary_table._model.rowCount(),
        "summary_hdr": list(g.summary_table._model.headers),
    }
    g2 = geotiff_mod.GeoTiffPreviewWidget()
    g2.resize(400, 300)
    g2.load("/tmp/x.tif", None, b"PNGDATA", (("a", "b"),))
    out["geotiff_img"] = {
        "pixmap_null": g2.pixmap() is None or g2.pixmap().isNull(),
        "label_w": g2._image_label.pixmap().width()
            if g2._image_label.pixmap() else None,
        "label_h": g2._image_label.pixmap().height()
            if g2._image_label.pixmap() else None,
        "table_visible": g2.summary_table.isVisible(),
    }
    g2.apply_settings(PreviewSettings.from_mapping(
        {"show_geo_metadata": False, "smooth_images": False}))
    out["geotiff_settings"] = {
        "table_visible": g2.summary_table.isVisible(),
        "transform": g2._transformation_mode,
    }
    return out


def _capture(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — freeze the error text
        return str(exc)
    return None


def main() -> None:
    fixtures = {
        "meta": {
            "generator": "tools/oracle/generate_ui_preview_fixtures.py",
            "python": sys.version.split()[0],
            "note": ("PySide6 stubbed comprehensively; seismic_3d_api and "
                     "geoviz host are sentinels/stubs — their kernels live "
                     "in other slices. Widget-observable sections are "
                     "replayed by ui_pages_preview.qt_widgets_smoke; the "
                     "Qt-free cores by ui_pages_preview.oracle_replay."),
        },
        "settings": build_settings(),
        "table": build_table(),
        "json_tree": build_json_tree(),
        "pdf": build_pdf(),
        "image": build_image(),
        "media": build_media(),
        "web": build_web(),
        "seismic": build_seismic(),
        "summary": build_summary(),
        "lazy_tabs": build_lazy_tabs(),
        "settings_panel": build_settings_panel(),
        "misc_widgets": build_misc_widgets(),
    }
    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(
        json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {FIXTURES_PATH}")


if __name__ == "__main__":
    main()
