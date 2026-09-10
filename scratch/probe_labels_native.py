"""标注不显示诊断探针（只读产品代码；写操作仅限 /tmp 副本与截图）。

Usage (repo root):
  QT_QPA_PLATFORM=offscreen .venv/bin/python scratch/probe_labels_native.py

流程：/tmp/probe_labels 重建副本 → offscreen 原生桥 CompositeDocument →
  A 相：wire 截获（labels 段）+ 桥侧自省（tree/schema/features/XML labeling）
        + 画布截图 A 像素分析 →
  B 相：设 target_horizon + dispatch load_initial_facies → stacking 顺序 +
        截图 B 对比 → 打印证据表与启发式 VERDICT 行。

真实工程目录只读（结尾校验 mtime）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REAL_JSON = "/home/kevin/projects/paleo_project/data/project_area/project_area.paleo.json"
COPY_DIR = "/tmp/probe_labels"
COPY_JSON = os.path.join(COPY_DIR, "project_area.paleo.json")
SHOT_A = os.path.join(COPY_DIR, "shot_before.png")
SHOT_B = os.path.join(COPY_DIR, "shot_after.png")


def main() -> int:
    real_mtime_before = os.stat(REAL_JSON).st_mtime_ns
    shutil.rmtree(COPY_DIR, ignore_errors=True)
    shutil.copytree(os.path.dirname(REAL_JSON), COPY_DIR,
                    symlinks=False, ignore_dangling_symlinks=True)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from paleo_workbench.mapping import qgis_mirror as _qm
    from paleo_workbench.mapping.workarea_map_snapshot import (
        build_workarea_map_snapshot,
    )
    from paleo_workbench.project.manager import ProjectManager
    from paleo_workbench.ui.workstation.composite_document import (
        CompositeDocument,
    )

    project = ProjectManager(COPY_JSON).load()
    doc = CompositeDocument(project)
    doc.resize(900, 600)
    doc.show()

    def pump(seconds: float = 1.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)

    pump(2.5)
    stack = doc.canvas.stack
    addr = doc.canvas.canvas_address

    print("=== P0 快照层（Python 侧事实） ===")
    snap = build_workarea_map_snapshot(project)
    print(f"project_crs={snap.project_crs!r}")
    for layer in snap.layers:
        style = dict(getattr(layer, "style", None) or {})
        labels = style.get("labels")
        names = [str((f.get("properties") or {}).get("name") or "")
                 for f in (layer.features or [])]
        print(f"[{layer.id}] name={layer.name!r} visible={layer.visible} "
              f"opacity={layer.opacity} nfeat={len(layer.features or [])}")
        print(f"  labels={json.dumps(labels, ensure_ascii=False)}")
        print(f"  name值(前5)={names[:5]!r} 空name数="
              f"{sum(1 for n in names if not n.strip())}")

    # ---- P2/P3/P4 先行：以下均为打开后原始态自省（任何重发实验必须在
    # ---- 截图之后做，否则重发会改写桥侧状态，污染“修复是否生效”的读数）
    def tree_walk():
        payload = json.loads(stack.tree_snapshot_json())
        rows: list[tuple[int, str, str, object]] = []

        def _walk(node, depth: int) -> None:
            if not isinstance(node, dict):
                return
            nid = node.get("id")
            if node.get("type") == "group":
                rows.append((depth, "GROUP", str(nid),
                             node.get("visible")))
                for ch in node.get("children", []) or []:
                    _walk(ch, depth + 1)
            elif node.get("type") == "layer":
                rows.append((depth, "layer", str(nid),
                             node.get("visible")))
            else:
                if nid:
                    rows.append((depth, node.get("type"), str(nid),
                                 node.get("visible")))
                for ch in node.get("children", []) or []:
                    _walk(ch, depth + 1)

        for ch in payload.get("children", []) or []:
            _walk(ch, 0)
        return rows

    print("=== P2 桥侧 tree（文档顺序 = 自顶向下绘制序） ===")
    for depth, kind, nid, vis in tree_walk():
        print(f"{'  ' * depth}{kind} {nid} visible={vis}")

    print("=== P3 桥侧逐层自省 ===")
    for doc_id in [r[2] for r in tree_walk() if r[1] == "layer"]:
        try:
            vis = stack.mirror_layer_visibility(doc_id)
        except Exception as exc:
            vis = f"<err {exc}>"
        try:
            schema = json.loads(stack.mirror_layer_schema_json(doc_id))
            fields = [f.get("name") for f in schema.get("fields", [])]
        except Exception as exc:
            fields = [f"<err {exc}>"]
        try:
            feats = json.loads(stack.mirror_features_json(doc_id, 4))
            items = feats.get("features", feats) if isinstance(
                feats, dict) else feats
            props = [(it.get("id"), it.get("properties")) for it in
                     (items or [])[:3]]
        except Exception as exc:
            props = [f"<err {exc}>"]
        n = "?"  # wire 计数在 P1（截图后）给出，此处保持原始态只读
        print(f"[{doc_id}] bridge_visible={vis} nfeat_wire={n} "
              f"fields={fields}")
        for fid, pr in props:
            print(f"    feat {fid}: {json.dumps(pr, ensure_ascii=False)[:220]}")

    print("=== P4 桥侧 project XML labeling 段 ===")
    labeling_evidence: dict[str, dict] = {}
    try:
        xml_text = stack.write_project_xml()
        if not isinstance(xml_text, str):
            xml_text = str(xml_text)
        with open(os.path.join(COPY_DIR, "project.xml"), "w",
                  encoding="utf-8") as fh:
            fh.write(xml_text)
        # 注：XML 内嵌 style_sig 含原始控制字符，ET 严格解析会失败；用正则
        # 提取 labeling 事实（与 ET 等价，仅为诊断读数）。
        import re as _re

        for block in xml_text.split("<maplayer")[1:]:
            m = _re.search(r'name="pwb/doc_id"[^>]*value="([^"]*)"', block)
            doc_id = m.group(1) if m else "?"
            lt = _re.search(r'<labeling[^>]*type="([^"]*)"', block)
            en = _re.search(r'labelsEnabled="([01])"', block)
            fn = _re.search(r'<text-style[^>]*fieldName="([^"]*)"', block)
            fs = _re.search(r'<text-style[^>]*fontSize="([^"]*)"', block)
            info = {
                "labeling_type": lt.group(1) if lt else None,
                "labels_enabled": en.group(1) if en else None,
                "field": fn.group(1) if fn else None,
                "font_size": fs.group(1) if fs else None,
            }
            labeling_evidence[doc_id] = info
            print(f"  doc={doc_id!r} {info}")
    except Exception as exc:
        print(f"  <write_project_xml err {exc!r}>")

    print(f"mirror_failures={getattr(doc.canvas, '_mirror_failures', None)}")
    try:
        print(f"backend_status={doc.canvas.backend_status!r}")
    except Exception as exc:
        print(f"backend_status err: {exc!r}")

    print("=== P4b fields_json 路径（base 层有无 schema） ===")
    try:
        from paleo_workbench.mapping.qgis_mirror import (
            _fields_json_for_metadata,
            _stack_supports_fields_json,
        )
        print(f"stack_supports_fields_json(真实桥)="
              f"{_stack_supports_fields_json(stack)} "
              f"（inspect.signature 对 pybind 方法抛 ValueError 即为 False）")
        for layer in snap.layers:
            md = getattr(layer, "metadata", None) or {}
            print(f"[{layer.id}] metadata={dict(md)!r} "
                  f"fields_json={_fields_json_for_metadata(md)!r}")
    except Exception as exc:
        print(f"  <fields_json introspection err {exc!r}>")

    def shot(path: str) -> dict | None:
        try:
            doc.canvas.export_png(path)
        except Exception as exc:
            print(f"shot {path} export err: {exc!r}")
            return None
        return analyze(path)

    def analyze(path: str) -> dict | None:
        from PySide6.QtGui import QImage

        img = QImage(path)
        if img.isNull():
            print(f"shot {path}: QImage null")
            return None
        img = img.convertToFormat(QImage.Format.Format_RGB32)
        w, h = img.width(), img.height()
        try:
            import numpy as np

            ptr = img.constBits()
            arr = np.frombuffer(ptr, dtype=np.uint8)
            bpl = img.bytesPerLine()
            arr = (np.ascontiguousarray(
                arr[:h * bpl].reshape(h, bpl)[:, :w * 4])
                .reshape(h, w, 4)[:, :, :3].astype(np.int32))  # BGRA→BGR
            rgb = arr[:, :, ::-1]
            step = 2
            px = rgb[::step, ::step].reshape(-1, 3)

            def near(t, tol):
                import numpy as _np

                return (int((_np.abs(px - _np.array(t)).sum(axis=1)
                             <= tol).sum()))

            stats = {
                "size": f"{w}x{h}",
                "dark_text(#0f172a,tol90)": near((15, 23, 42), 90),
                "near_white(tol36)": near((248, 250, 252), 36),
                "well_blue(#409cff,tol90)": near((64, 156, 255), 90),
                "flagged_orange(#f59e0b,tol90)": near((245, 158, 11), 90),
                "survey_teal(#0d9488,tol90)": near((13, 148, 136), 90),
            }
            # 主导色（降采样直方图 top5）
            import numpy as _np

            q = (px // 32 * 32 + 16)
            keys, counts = _np.unique(
                q[:, 0] * 65536 + q[:, 1] * 256 + q[:, 2], return_counts=True)
            top = sorted(zip(counts, keys), reverse=True)[:5]
            stats["top_colors"] = [
                (f"#{k % 65536 // 256 * 0 + (k // 65536):02x}"
                 f"{(k % 65536) // 256:02x}{k % 256:02x}", int(c))
                for c, k in top]
            stats["sampled_px"] = int(px.shape[0])
            return stats
        except Exception as exc:
            print(f"shot {path}: numpy分析失败 {exc!r}，改粗采样")
            from PySide6.QtGui import QColor

            dark = 0
            n = 0
            for y in range(0, h, 6):
                for x in range(0, w, 6):
                    c: QColor = img.pixelColor(x, y)
                    n += 1
                    if (abs(c.red() - 15) + abs(c.green() - 23)
                            + abs(c.blue() - 42) <= 90):
                        dark += 1
            return {"size": f"{w}x{h}",
                    "dark_text(#0f172a,tol90)": dark, "sampled_px": n}

    print("=== P5 截图 A（空白相层之前） ===")
    stats_a = shot(SHOT_A)
    print(json.dumps(stats_a, ensure_ascii=False))

    # ---- P1 wire 截获（截图之后做）：代理 stack 记录真实上桥参数后委托
    # ----（pybind 对象不可直接挂 spy）。代理方法必须显式声明
    # ---- fields_json 等 kwarg，否则 inspect 能力探测失败、镜像走 legacy
    # ---- 路径并触发桥侧“schema 漂移到无”丢列。清 ledger 强制全量重发。
    print("=== P1 上桥 wire（spy 截获，截图后重发） ===")
    wire: dict[str, dict] = {}

    class _ProxyStack:
        def __init__(self, real):
            object.__setattr__(self, "_real", real)

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_real"), name)

        def upsert_mirror_layer(
                self, doc_id, display_name, geom, crs, geojson,
                renderer_xml="", labeling_xml="", legacy_style=None,
                visible=True, opacity=1.0, is_reference=False,
                is_editable=False, reference_snap=False,
                data_revision=0, delta="", fields_json=""):
            try:
                feats = json.loads(geojson).get("features", [])
            except Exception:
                feats = "<unparseable>"
            wire[str(doc_id)] = {
                "display": display_name, "geom": geom, "crs": crs,
                "nfeat": len(feats) if isinstance(feats, list) else feats,
                "renderer_xml?": bool((renderer_xml or "").strip()),
                "labeling_xml?": bool((labeling_xml or "").strip()),
                "legacy_labels": (
                    dict((legacy_style or {}).get("labels") or {})
                    if isinstance(legacy_style, dict) else None),
                "visible": visible, "opacity": opacity,
                "fields_json?": bool(str(fields_json or "").strip()),
            }
            real = object.__getattribute__(self, "_real")
            return real.upsert_mirror_layer(
                doc_id, display_name, geom, crs, geojson,
                renderer_xml, labeling_xml, legacy_style,
                visible, opacity, is_reference, is_editable,
                reference_snap, data_revision, delta, fields_json)

    last = getattr(doc.canvas, "_last_snapshot", None)
    if last is not None:
        _qm._MIRROR_LEDGER.clear()
        proxy = _ProxyStack(stack)
        _diags: list = []
        _mirrored, _seen, _failures = _qm.mirror_snapshot_to_stack(
            proxy, addr, last, _diags, groups=bool(
                getattr(doc.canvas, "layer_groups_enabled", False)))
        print(f"wire重发: mirrored={len(_mirrored)} failures={_failures}")
        pump(1.5)
    for doc_id, w in wire.items():
        print(f"[{doc_id}] display={w['display']!r} geom={w['geom']} "
              f"nfeat={w['nfeat']} visible={w['visible']} "
              f"renderer_xml={w['renderer_xml?']} "
              f"labeling_xml={w['labeling_xml?']} "
              f"fields_json={w.get('fields_json?')}")
        print(f"  legacy.labels={json.dumps(w['legacy_labels'], ensure_ascii=False)}")

    # ---- B 相：创建初始相图层 ----
    print("=== P6 dispatch load_initial_facies ===")
    project.stratigraphy.target_horizon = "Sq1"
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    n_before = len(doc.stage_controller.state.layers_with_role(
        __import__("paleo_workbench.mapping_workspace.layer_roles",
                   fromlist=["LayerRole"]).LayerRole.INITIAL_FACIES_SOURCE))
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    pump(1.5)
    print(f"status={messages[-1:]!r}")

    print("=== P7 叠加后 tree（关注空白相层相对位置） ===")
    rows_b = tree_walk()
    for depth, kind, nid, vis in rows_b:
        print(f"{'  ' * depth}{kind} {nid} visible={vis}")
    try:
        order = list(stack.mirror_order_top_first())
        print(f"mirror_order_top_first={order}")
    except Exception as exc:
        print(f"mirror_order_top_first err: {exc!r}")
        order = []

    print("=== P8 截图 B（空白相层之后） ===")
    stats_b = shot(SHOT_B)
    print(json.dumps(stats_b, ensure_ascii=False))

    # ---- 启发式 VERDICT（事实行，结论见回报） ----
    print("=== VERDICT 行 ===")
    _NO_LABEL_BY_DESIGN = {"home_workarea:boundary", "home_workarea:surveys"}
    for doc_id, w in wire.items():
        lab = w["legacy_labels"] or {}
        shipped = bool(lab.get("field")) and bool(lab.get("visible", True))
        tag = "SKIP" if doc_id in _NO_LABEL_BY_DESIGN else (
            "PASS" if shipped else "FAIL")
        print(f"[{tag}] wire.labels "
              f"{doc_id} field={lab.get('field')!r} "
              f"visible={lab.get('visible')}")
    for doc_id, info in labeling_evidence.items():
        en = (info["labeling_type"] == "simple"
              and str(info["labels_enabled"]) == "1"
              and bool(info["field"]))
        tag = "SKIP" if doc_id in _NO_LABEL_BY_DESIGN else (
            "PASS" if en else "FAIL")
        print(f"[{'PASS' if en else 'FAIL'}] bridge.labeling "
              f"{doc_id} type={info['labeling_type']} "
              f"enabled={info['labels_enabled']} field={info['field']!r} "
              f"font_size={info['font_size']!r}")
    if stats_a:
        print(f"[{'PASS' if (stats_a.get('dark_text(#0f172a,tol90)') or 0) > 50 else 'FAIL'}] "
              f"shotA_dark_text_px={stats_a.get('dark_text(#0f172a,tol90)')}")
    if stats_b and stats_a:
        ka = stats_a.get('dark_text(#0f172a,tol90)') or 0
        kb = stats_b.get('dark_text(#0f172a,tol90)') or 0
        print(f"[{'PASS' if kb >= ka * 0.5 and kb > 50 else 'FAIL'}] "
              f"shotB_dark_text_px={kb} (A={ka})")

    after = os.stat(REAL_JSON).st_mtime_ns
    print(f"[{'PASS' if after == real_mtime_before else 'FAIL'}] "
          f"真实工程 mtime 不变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
