import gc
import unittest
import weakref

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from shiboken6 import Shiboken

from welllog import (
    WellLogThreadError,
    WellLogValidationError,
    WellLogView,
)


class WellLogViewEmbeddingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_generated_view_follows_qwidget_parent_lifetime(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        view = WellLogView()
        destroyed_count = 0

        def record_destruction() -> None:
            nonlocal destroyed_count
            destroyed_count += 1

        view.destroyed.connect(record_destruction)
        layout.addWidget(view)

        self.assertIsInstance(view, QOpenGLWidget)
        self.assertIs(view.parentWidget(), host)
        self.assertTrue(Shiboken.isValid(view))

        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        gc.collect()

        self.assertEqual(destroyed_count, 1)
        self.assertFalse(Shiboken.isValid(view))

    def test_numpy_curve_is_zero_copy_and_owned_by_the_document(self) -> None:
        view = WellLogView()
        depth = np.arange(1000.0, 1006.0, dtype=np.float64)
        values_source = np.arange(12.0, dtype=np.float32)
        values = values_source[::2]
        depth_ref = weakref.ref(depth)
        values_ref = weakref.ref(values)
        expected_depth_address = depth.ctypes.data
        expected_value_address = values.ctypes.data

        report = view.submit_curve(
            depth,
            values,
            "10000000-0000-4000-8000-000000000001",
            "10000000-0000-4000-8000-000000000002",
            "10000000-0000-4000-8000-000000000003",
            "GR",
            "m",
            "API",
        )

        self.assertEqual(report["depth"]["access_mode"], "zero_copy")
        self.assertEqual(report["curve"]["access_mode"], "zero_copy")
        self.assertEqual(report["depth"]["address"], expected_depth_address)
        self.assertEqual(report["curve"]["address"], expected_value_address)
        self.assertEqual(report["curve"]["stride_bytes"], 8)

        del depth
        del values
        del values_source
        gc.collect()

        self.assertIsNotNone(depth_ref())
        self.assertIsNotNone(values_ref())
        self.assertEqual(
            view.sample_value("10000000-0000-4000-8000-000000000003", 3),
            6.0,
        )

        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        gc.collect()

        self.assertIsNone(depth_ref())
        self.assertIsNone(values_ref())

    def test_synchronous_failures_use_stable_typed_exceptions(self) -> None:
        view = WellLogView()
        arguments = (
            "20000000-0000-4000-8000-000000000001",
            "20000000-0000-4000-8000-000000000002",
            "20000000-0000-4000-8000-000000000003",
            "GR",
            "m",
            "API",
        )

        with self.assertRaises(WellLogValidationError) as raised:
            view.submit_curve(
                np.ones((2, 2), dtype=np.float64),
                np.ones(4, dtype=np.float32),
                *arguments,
            )

        self.assertEqual(raised.exception.code, "invalid_buffer")
        self.assertTrue(issubclass(WellLogThreadError, RuntimeError))

    def test_asynchronous_view_failure_is_a_typed_qt_signal(self) -> None:
        view = WellLogView()
        errors: list[tuple[str, str]] = []
        view.viewError.connect(
            lambda code, message: errors.append((code, message))
        )

        view.resize(160, 120)
        view.show()
        QTest.qWait(650)

        self.assertTrue(errors)
        self.assertEqual(errors[-1][0], "capability_unavailable")
        self.assertTrue(errors[-1][1])
        signal_names = {
            bytes(view.metaObject().method(index).name()).decode()
            for index in range(view.metaObject().methodCount())
        }
        self.assertNotIn("frameReady", signal_names)
        self.assertNotIn("frameStats", signal_names)

    def test_document_session_event_crosses_python_as_typed_fields(self) -> None:
        view = WellLogView()
        events: list[tuple[str, int]] = []
        view.documentChanged.connect(
            lambda document_id, revision: events.append(
                (document_id, revision)
            )
        )
        view.submit_curve(
            np.arange(4, dtype=np.float64),
            np.arange(4, dtype=np.float32),
            "40000000-0000-4000-8000-000000000001",
            "40000000-0000-4000-8000-000000000002",
            "40000000-0000-4000-8000-000000000003",
            "GR",
            "m",
            "API",
        )

        QTest.qWait(25)

        self.assertEqual(
            events,
            [("40000000-0000-4000-8000-000000000001", 1)],
        )


if __name__ == "__main__":
    unittest.main()
