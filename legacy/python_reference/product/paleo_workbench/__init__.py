"""Paleogeography map compilation workbench."""

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, load_local_env

__version__ = "0.2.17a0"

# V10 M-A：vendored-QGIS loader 必须先于 geoviz bootstrap 执行。
# ensure_geoviz_on_path() 会 import geoviz → numpy——numpy 的裁剪版
# msvcp140/自有 Qt 会抢先占住进程 DLL 槽位，之后再做 conda Qt 预载就
# 是「ENTRYPOINT_NOT_FOUND」（V10 loader 二分定位：仅 import 本包即可
# 复现）。load_local_env 先行，使 .env 里的机器配方变量
# （PALEO_QGIS_CONDA_QT / PALEO_QGIS_BUILD_DIR / PALEO_QGIS_DEPS_DIR）
# 参与配方选择；prepare_bridge_load 幂等，main.py 的启动钩子只是冗余
# 保险。默认配方在无 vendor 目录的机器上是近似 no-op（诚实降级）。
load_local_env()

from paleo_workbench.qgis_runtime import loader as _qgis_runtime_loader  # noqa: E402

_qgis_runtime_loader.prepare_bridge_load()

# ISS-ENV-01: prefer editable installs; fall back to checkout package roots.
ensure_geoviz_on_path()
