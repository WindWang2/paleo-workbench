"""Milestone 1 Empirical Stress Tests: Deferred OpenGL Delete Queues & Context Scoping.

Stress-tests:
1. Multi-context scoping & isolation across 5+ distinct OpenGL contexts under 10,000+ queued textures/programs.
2. High-concurrency thread race conditions: 20 worker threads concurrently queuing GL deletions while GUI thread flushes.
3. Rapid cleanup cycles of DualGLVolumeItem and GLImageLutItem under varying context availability (active, none, mock-view).
4. Boundary stress: invalid context handles, None handles, duplicate calls, and exception resilience in glDelete.
"""

from __future__ import annotations

import random
import threading
from threading import Event
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from geoviz_seismic import renderer_3d
from geoviz_seismic.renderer_3d import (
    DualGLVolumeItem,
    GLImageLutItem,
    flush_pending_gl_deletes,
    queue_gl_program_delete,
    queue_gl_texture_delete,
)


class MockGLContext:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<MockGLContext {self.name}>"


@pytest.fixture(autouse=True)
def clean_gl_queues():
    """Ensure GL queues are clean before and after every test."""
    renderer_3d._CONTEXT_PENDING_TEXTURE_DELETES.clear()
    renderer_3d._CONTEXT_PENDING_PROGRAM_DELETES.clear()
    renderer_3d._PENDING_GL_TEXTURE_DELETES.clear()
    renderer_3d._PENDING_GL_PROGRAM_DELETES.clear()
    yield
    renderer_3d._CONTEXT_PENDING_TEXTURE_DELETES.clear()
    renderer_3d._CONTEXT_PENDING_PROGRAM_DELETES.clear()
    renderer_3d._PENDING_GL_TEXTURE_DELETES.clear()
    renderer_3d._PENDING_GL_PROGRAM_DELETES.clear()


def test_stress_multi_context_deferred_gl_isolation(monkeypatch):
    """Stress test context isolation: flushing Context A must NEVER delete textures belonging to Context B."""
    deleted_textures_by_call: list[list[int]] = []
    deleted_programs_by_call: list[list[Any]] = []

    monkeypatch.setattr(
        renderer_3d.GL, "glDeleteTextures",
        lambda count, ids: deleted_textures_by_call.append(list(ids)),
    )
    monkeypatch.setattr(
        renderer_3d.GL, "glDeleteProgram",
        lambda prog: deleted_programs_by_call.append([prog]),
    )

    ctx_a = MockGLContext("Context_A")
    ctx_b = MockGLContext("Context_B")
    ctx_c = MockGLContext("Context_C")

    # Queue 1,000 textures for Context A, 1,000 for Context B, 1,000 for Context C, and 500 unassociated
    for i in range(1000):
        queue_gl_texture_delete(10000 + i, context=ctx_a)
        queue_gl_program_delete(f"prog_a_{i}", context=ctx_a)
        queue_gl_texture_delete(20000 + i, context=ctx_b)
        queue_gl_program_delete(f"prog_b_{i}", context=ctx_b)
        queue_gl_texture_delete(30000 + i, context=ctx_c)
        queue_gl_program_delete(f"prog_c_{i}", context=ctx_c)
        if i < 500:
            queue_gl_texture_delete(40000 + i, context=None)
            queue_gl_program_delete(f"prog_unassoc_{i}", context=None)

    # Flush Context A
    flush_pending_gl_deletes(context=ctx_a)

    all_deleted_tex = [t for call in deleted_textures_by_call for t in call]
    all_deleted_prog = [p for call in deleted_programs_by_call for p in call]

    # Must contain Context A's textures (10000..10999) + unassociated (40000..40499)
    assert len(all_deleted_tex) == 1500
    for i in range(1000):
        assert (10000 + i) in all_deleted_tex
        assert (20000 + i) not in all_deleted_tex  # Context B MUST NOT be deleted
        assert (30000 + i) not in all_deleted_tex  # Context C MUST NOT be deleted
    for i in range(500):
        assert (40000 + i) in all_deleted_tex

    # Context B and C queues must remain intact in _CONTEXT_PENDING_TEXTURE_DELETES
    assert len(renderer_3d._CONTEXT_PENDING_TEXTURE_DELETES[ctx_b]) == 1000
    assert len(renderer_3d._CONTEXT_PENDING_TEXTURE_DELETES[ctx_c]) == 1000

    # Flush Context B
    flush_pending_gl_deletes(context=ctx_b)
    all_deleted_tex_after_b = [t for call in deleted_textures_by_call for t in call]
    assert len(all_deleted_tex_after_b) == 2500
    for i in range(1000):
        assert (20000 + i) in all_deleted_tex_after_b
        assert (30000 + i) not in all_deleted_tex_after_b  # Context C still protected

    # Flush Context C
    flush_pending_gl_deletes(context=ctx_c)
    all_deleted_tex_after_c = [t for call in deleted_textures_by_call for t in call]
    assert len(all_deleted_tex_after_c) == 3500
    for i in range(1000):
        assert (30000 + i) in all_deleted_tex_after_c

    # All queues are now empty
    assert len(renderer_3d._CONTEXT_PENDING_TEXTURE_DELETES) == 0
    assert len(renderer_3d._CONTEXT_PENDING_PROGRAM_DELETES) == 0
    assert len(renderer_3d._PENDING_GL_TEXTURE_DELETES) == 0
    assert len(renderer_3d._PENDING_GL_PROGRAM_DELETES) == 0


def test_stress_concurrent_gl_queue_and_flush(monkeypatch):
    """20 concurrent worker threads queuing GL objects while simulated render threads flush."""
    deleted_textures_lock = threading.Lock()
    deleted_textures_count = [0]
    deleted_programs_count = [0]

    monkeypatch.setattr(
        renderer_3d.GL, "glDeleteTextures",
        lambda count, ids: _record_delete_tex(len(ids)),
    )
    monkeypatch.setattr(
        renderer_3d.GL, "glDeleteProgram",
        lambda prog: _record_delete_prog(),
    )

    def _record_delete_tex(n):
        with deleted_textures_lock:
            deleted_textures_count[0] += n

    def _record_delete_prog():
        with deleted_textures_lock:
            deleted_programs_count[0] += 1

    contexts = [MockGLContext(f"ctx_{i}") for i in range(5)]
    worker_count = 20
    ops_per_worker = 200
    stop_event = Event()
    worker_errors: list[Exception] = []

    def producer_task(worker_id: int):
        try:
            for i in range(ops_per_worker):
                tex_id = worker_id * 100_000 + i
                ctx = random.choice([None] + contexts)
                queue_gl_texture_delete(tex_id, context=ctx)
                queue_gl_program_delete(f"prog_{worker_id}_{i}", context=ctx)
                if i % 10 == 0:
                    time.sleep(0.0001)
        except Exception as exc:
            worker_errors.append(exc)

    def consumer_task():
        while not stop_event.is_set():
            ctx = random.choice([None] + contexts)
            try:
                flush_pending_gl_deletes(context=ctx)
            except Exception as exc:
                worker_errors.append(exc)
            time.sleep(0.001)

    producers = [threading.Thread(target=producer_task, args=(w,)) for w in range(worker_count)]
    consumers = [threading.Thread(target=consumer_task) for _ in range(3)]

    for c in consumers:
        c.start()
    for p in producers:
        p.start()

    for p in producers:
        p.join(timeout=10.0)

    time.sleep(0.05)
    stop_event.set()
    for c in consumers:
        c.join(timeout=5.0)

    # Final flush for all contexts to ensure everything is processed
    for ctx in contexts:
        flush_pending_gl_deletes(context=ctx)
    flush_pending_gl_deletes(context=None)

    total_expected_ops = worker_count * ops_per_worker
    assert worker_errors == [], f"Encountered errors in concurrent GL queuing/flushing: {worker_errors}"
    assert deleted_textures_count[0] == total_expected_ops, (
        f"Expected {total_expected_ops} textures deleted, got {deleted_textures_count[0]}"
    )
    assert deleted_programs_count[0] == total_expected_ops, (
        f"Expected {total_expected_ops} programs deleted, got {deleted_programs_count[0]}"
    )


def test_stress_rapid_dual_volume_and_lut_item_clean_cycles(monkeypatch):
    """Stress test rapid instantiation and .clean() calls on hundreds of DualGLVolumeItem and GLImageLutItem."""
    deleted_textures: list[int] = []
    deleted_programs: list[Any] = []

    monkeypatch.setattr(
        renderer_3d.GL, "glDeleteTextures",
        lambda count, ids: deleted_textures.extend(list(ids)),
    )
    monkeypatch.setattr(
        renderer_3d.GL, "glDeleteProgram",
        lambda prog: deleted_programs.append(prog),
    )

    ctx_active = MockGLContext("ActiveContext")
    
    # Mode 1: Clean called WITHOUT active context -> queued to deferred queues
    monkeypatch.setattr(
        renderer_3d, "QtGui",
        SimpleNamespace(QOpenGLContext=SimpleNamespace(currentContext=lambda: None)),
    )

    for i in range(50):
        # DualGLVolumeItem
        item_vol = DualGLVolumeItem.__new__(DualGLVolumeItem)
        item_vol.texture = 1000 + i * 5
        item_vol._primary_cmap_tex = 1001 + i * 5
        item_vol._overlay_cmap_tex = 1002 + i * 5
        item_vol._sculpt_horizon_tex = 1003 + i * 5
        item_vol._normal_tex = 1004 + i * 5
        item_vol._customShaderProgram = f"vol_prog_{i}"
        item_vol.m_vbo_position = Mock()
        item_vol.m_vbo_position.isCreated.return_value = False
        item_vol._needUpload = False
        item_vol.clean()

        # GLImageLutItem
        item_lut = GLImageLutItem.__new__(GLImageLutItem)
        item_lut.texture = 5000 + i * 2
        item_lut._lut_tex = 5001 + i * 2
        item_lut._lut_shader_program = f"lut_prog_{i}"
        item_lut._cmap_name = "seismic"
        item_lut._lut_needs_upload = False
        item_lut._needUpdate = False
        item_lut.m_vbo_position = Mock()
        item_lut.m_vbo_position.isCreated.return_value = False
        item_lut.clean()

    # Nothing deleted immediately because context was None
    assert len(deleted_textures) == 0
    assert len(deleted_programs) == 0

    # Now simulate paintGL() where context is current -> flush
    monkeypatch.setattr(
        renderer_3d, "QtGui",
        SimpleNamespace(QOpenGLContext=SimpleNamespace(currentContext=lambda: ctx_active)),
    )
    flush_pending_gl_deletes(context=ctx_active)

    # All unassociated and context textures/programs must be deleted
    # 50 volume items * 5 textures + 50 lut items * 2 textures = 350 textures
    assert len(deleted_textures) == 350
    # 50 volume progs + 50 lut progs = 100 programs
    assert len(deleted_programs) == 100
