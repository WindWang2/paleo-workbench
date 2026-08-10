"""Global CPU / GPU performance dials for trend-surface compute.

- CPU slider 0–100 → multi-core thread count (always CPU)
- Master switch: 硬件加速 = GPU 加速（不是 CPU）
- GPU strength 0–100 → how hard to push the GPU when switch is on
- GPU backends (auto-detect, first usable wins):
    CuPy CUDA/ROCm, PyTorch CUDA/MPS/XPU, OpenCL (iGPU/dGPU)
- No GPU found → switch stays informational; compute falls back to multi-core CPU only
"""

from __future__ import annotations

import os
import re
import string
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_lock = threading.RLock()
_instance: Optional["ComputeSettings"] = None
_ascii_path_ready = False


def _cpu_count() -> int:
    try:
        n = os.cpu_count() or 2
    except Exception:
        n = 2
    return max(1, int(n))


def _has_non_ascii(path: str) -> bool:
    try:
        path.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def ensure_ascii_project_path_for_cuda(project_root: Optional[str] = None) -> Optional[str]:
    """Windows: NVRTC 无法在含中文路径下编译 CuPy 内核。

    将项目根目录 SUBST 到纯 ASCII 盘符（默认 P:），并把 sys.path 中对应前缀
    改写为盘符路径。返回映射后的根路径；无需映射则返回原路径。
    """
    global _ascii_path_ready
    if os.name != "nt":
        return project_root

    if project_root is None:
        # drawing/compute/performance.py → Drawing/
        project_root = str(Path(__file__).resolve().parents[2])
    project_root = os.path.abspath(project_root)

    if not _has_non_ascii(project_root):
        _ascii_path_ready = True
        return project_root

    # 优先使用已存在的 SUBST 映射
    mapped = _find_existing_subst(project_root)
    if mapped is None:
        mapped = _create_subst(project_root)
    if mapped is None:
        return project_root

    # 重写 sys.path，使后续 import cupy 的 __file__ 落在 ASCII 路径
    root_norm = os.path.normcase(os.path.normpath(project_root))
    mapped_norm = os.path.normpath(mapped)
    new_path: List[str] = []
    for p in sys.path:
        try:
            ap = os.path.normcase(os.path.abspath(p))
        except Exception:
            new_path.append(p)
            continue
        if ap == root_norm or ap.startswith(root_norm + os.sep):
            rel = os.path.relpath(os.path.abspath(p), project_root)
            if rel == ".":
                new_path.append(mapped_norm)
            else:
                new_path.append(os.path.normpath(os.path.join(mapped_norm, rel)))
        else:
            new_path.append(p)
    sys.path[:] = new_path

    # CUDA 临时目录也放到 ASCII 路径，避免中文 TEMP
    ascii_tmp = r"C:\PaleoDrawing\tmp"
    try:
        os.makedirs(ascii_tmp, exist_ok=True)
        os.environ["TEMP"] = ascii_tmp
        os.environ["TMP"] = ascii_tmp
        os.environ["CUPY_CACHE_DIR"] = r"C:\PaleoDrawing\cupy_cache"
        os.makedirs(os.environ["CUPY_CACHE_DIR"], exist_ok=True)
    except Exception:
        pass

    _ascii_path_ready = True
    return mapped


def _find_existing_subst(project_root: str) -> Optional[str]:
    try:
        out = subprocess.check_output(["subst"], text=True, errors="ignore")
    except Exception:
        return None
    root_norm = os.path.normcase(os.path.normpath(project_root))
    for line in out.splitlines():
        # e.g. P:\: => M:\项目内容\Drawing
        m = re.match(r"^([A-Za-z]:)\\:\s*=>\s*(.+)$", line.strip())
        if not m:
            continue
        drive, target = m.group(1), m.group(2).strip().rstrip("\\")
        if os.path.normcase(os.path.normpath(target)) == root_norm:
            return drive + "\\"
    return None


def _create_subst(project_root: str) -> Optional[str]:
    # 选用空闲盘符 P–Z
    try:
        existing = subprocess.check_output(["subst"], text=True, errors="ignore")
    except Exception:
        existing = ""
    used = {m.group(1).upper() for m in re.finditer(r"^([A-Za-z]):\\:", existing, re.M)}
    for letter in "PQRSTUVWXYZ":
        drive = f"{letter}:"
        if letter in used:
            continue
        # 盘符是否已被占用
        if os.path.exists(drive + "\\"):
            continue
        try:
            subprocess.check_call(
                ["subst", drive, project_root],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return drive + "\\"
        except Exception:
            continue
    return None


def _cupy_warmup(cp) -> bool:
    """Compile a tiny kernel; fails on non-ASCII include paths or missing arch."""
    try:
        a = cp.arange(256, dtype=cp.float32)
        b = cp.sqrt(a * a + 1.0)
        cp.cuda.Stream.null.synchronize()
        float(b[0])
        return True
    except Exception:
        return False


def _probe_backends() -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (all_found, preferred). preferred is first that can run array ops."""
    found: List[Dict[str, Any]] = []
    preferred: Optional[Dict[str, Any]] = None

    # 中文路径 → SUBST，否则 CuPy NVRTC 无法编译
    try:
        ensure_ascii_project_path_for_cuda()
    except Exception:
        pass

    # 1) CuPy — CUDA or ROCm (HIP)
    try:
        import cupy as cp  # type: ignore

        n = 0
        backend_tag = "cupy"
        detail = ""
        try:
            n = int(cp.cuda.runtime.getDeviceCount())
            if n > 0:
                try:
                    name = cp.cuda.runtime.getDeviceProperties(0).get("name", b"GPU")
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="ignore")
                    detail = str(name)
                except Exception:
                    detail = f"{n} device(s)"
                backend_tag = "cupy-cuda"
        except Exception:
            # ROCm / other
            try:
                n = int(getattr(cp, "cuda", cp).runtime.getDeviceCount())  # type: ignore
                backend_tag = "cupy-rocm"
                detail = f"{n} device(s)"
            except Exception:
                n = 0
        if n > 0:
            # 必须通过 kernel 热身，否则“检测到设备但不能算”
            if _cupy_warmup(cp):
                info = {
                    "id": backend_tag,
                    "label": f"CuPy ({'CUDA' if 'cuda' in backend_tag else 'ROCm'})",
                    "detail": detail,
                    "module": cp,
                    "kind": "cupy",
                }
                found.append(info)
                if preferred is None:
                    preferred = info
            else:
                # 记录为不可用，状态里可提示
                found.append(
                    {
                        "id": backend_tag + "-unavailable",
                        "label": "CuPy(设备在线但内核编译失败)",
                        "detail": detail + " · 请检查路径/驱动",
                        "module": None,
                        "kind": "cupy-broken",
                    }
                )
    except Exception:
        pass

    # 2) PyTorch — CUDA / MPS / XPU / HIP
    try:
        import torch  # type: ignore

        torch_dev = None
        tag = None
        label = None
        detail = ""
        if torch.cuda.is_available():
            torch_dev = torch.device("cuda")
            tag = "torch-cuda"
            label = "PyTorch CUDA"
            try:
                detail = torch.cuda.get_device_name(0)
            except Exception:
                detail = "cuda"
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            torch_dev = torch.device("mps")
            tag = "torch-mps"
            label = "PyTorch MPS (Apple)"
            detail = "mps"
        else:
            # Intel XPU / other
            try:
                if hasattr(torch, "xpu") and torch.xpu.is_available():  # type: ignore
                    torch_dev = torch.device("xpu")
                    tag = "torch-xpu"
                    label = "PyTorch XPU"
                    detail = "xpu"
            except Exception:
                pass
        if torch_dev is not None and tag:
            info = {
                "id": tag,
                "label": label,
                "detail": detail,
                "module": torch,
                "device": torch_dev,
                "kind": "torch",
            }
            found.append(info)
            # Prefer cupy for drop-in numpy API; torch only if no cupy
            if preferred is None:
                preferred = info
    except Exception:
        pass

    # 3) OpenCL (pyopencl) — any vendor GPU/iGPU
    try:
        import pyopencl as cl  # type: ignore

        plats = cl.get_platforms()
        devices = []
        for p in plats:
            for d in p.get_devices():
                devices.append((p, d))
        if devices:
            # Prefer GPU type
            devices.sort(
                key=lambda pd: 0 if pd[1].type & cl.device_type.GPU else 1
            )
            _p, d = devices[0]
            detail = f"{d.name.strip()} ({_p.name.strip()})"
            info = {
                "id": "opencl",
                "label": "OpenCL",
                "detail": detail,
                "module": cl,
                "device": d,
                "kind": "opencl",
            }
            found.append(info)
            if preferred is None:
                preferred = info
    except Exception:
        pass

    return found, preferred


@dataclass
class ComputeSettings:
    """Runtime knobs for multi-core CPU parallel compute.

    当前产品仅使用 CPU 多线程；GPU 路径保留接口但默认永久关闭。
    """

    cpu_percent: int = 60
    gpu_percent: int = 0
    hardware_accel: bool = False  # 始终保持 False（产品关闭 GPU 模式）
    _backends_cache: Optional[List[Dict[str, Any]]] = field(default=None, repr=False)
    _preferred_cache: Optional[Dict[str, Any]] = field(default=None, repr=False)
    _probed: bool = field(default=False, repr=False)

    def set_cpu_percent(self, value: int) -> None:
        self.cpu_percent = max(0, min(100, int(value)))

    def set_gpu_percent(self, value: int) -> None:
        # GPU 模式已下线：忽略非零设置，强制为 0
        self.gpu_percent = 0

    def set_hardware_accel(self, enabled: bool) -> None:
        # GPU 模式已下线：始终关闭
        self.hardware_accel = False

    def cpu_workers(self) -> int:
        """Map 0–100 → 1 … cpu_count (0% still uses 1 thread). CPU only."""
        n = _cpu_count()
        if self.cpu_percent <= 0:
            return 1
        workers = max(1, int(round(n * self.cpu_percent / 100.0)))
        if self.cpu_percent >= 95:
            return n
        # Leave one free core for UI when not maxed
        if n >= 4 and workers >= n:
            workers = n - 1
        return max(1, min(n, workers))

    def _ensure_probed(self) -> None:
        # GPU 模式已下线：不做设备探测，加快启动
        if self._probed:
            return
        self._probed = True
        self._backends_cache = []
        self._preferred_cache = None

    def refresh_backends(self) -> None:
        self._probed = False
        self._backends_cache = None
        self._preferred_cache = None
        self._ensure_probed()

    def list_backends(self) -> List[Dict[str, Any]]:
        self._ensure_probed()
        return list(self._backends_cache or [])

    def preferred_backend(self) -> Optional[Dict[str, Any]]:
        self._ensure_probed()
        return self._preferred_cache

    def device_available(self) -> bool:
        return False

    def gpu_available(self) -> bool:
        return False

    def use_hardware_accel(self) -> bool:
        """GPU 模式已关闭，始终 False。"""
        return False

    def use_gpu(self) -> bool:
        """GPU 模式已关闭，始终走 CPU。"""
        return False

    def use_enhanced_cpu(self) -> bool:
        """No longer treat CPU as 'hardware accel' — always False."""
        return False

    def use_float32(self) -> bool:
        """float32 only on real GPU path (faster device kernels)."""
        return self.use_gpu() and self.gpu_percent >= 20

    def gpu_fraction(self) -> float:
        if not self.use_hardware_accel():
            return 0.0
        return max(0.0, min(1.0, float(self.gpu_percent) / 100.0))

    def cupy(self):
        b = self.preferred_backend()
        if b and b.get("kind") == "cupy":
            return b.get("module")
        for info in self.list_backends():
            if info.get("kind") == "cupy":
                return info.get("module")
        return None

    def array_module(self):
        """NumPy-compatible module for IDW (CuPy on GPU or None→NumPy CPU)."""
        if self.use_gpu():
            cp = self.cupy()
            if cp is not None:
                return cp
        return None

    def backend_label(self) -> str:
        return "CPU多线程"

    def idw_row_block(self, cols: int, n_wells: int) -> int:
        """Adaptive row block size to keep (block * cols * n_wells) memory moderate."""
        n_wells = max(1, int(n_wells))
        cols = max(1, int(cols))
        target = 4_000_000 + int(12_000_000 * (self.cpu_percent / 100.0))
        per_row = cols * n_wells
        block = max(1, target // max(per_row, 1))
        workers = self.cpu_workers()
        return max(1, min(block, 128 if workers > 1 else 256))

    def summary_text(self) -> str:
        n = _cpu_count()
        return (
            f"工作线程 {self.cpu_workers()}/{n} "
            f"（比例 {self.cpu_percent}% · 非系统占用率）"
        )


def get_compute_settings() -> ComputeSettings:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ComputeSettings()
            _load_from_qsettings(_instance)
        return _instance


def set_cpu_percent(value: int) -> None:
    s = get_compute_settings()
    s.set_cpu_percent(value)
    _save_to_qsettings(s)


def set_gpu_percent(value: int) -> None:
    s = get_compute_settings()
    s.set_gpu_percent(value)
    _save_to_qsettings(s)


def set_hardware_accel(enabled: bool) -> None:
    s = get_compute_settings()
    s.set_hardware_accel(enabled)
    _save_to_qsettings(s)


def _load_from_qsettings(settings: ComputeSettings) -> None:
    try:
        from PyQt6.QtCore import QSettings

        qs = QSettings("PaleoDrawing", "Compute")
        cpu = qs.value("cpu_percent", 60)
        settings.set_cpu_percent(int(cpu))
        # GPU 模式已下线
        settings.hardware_accel = False
        settings.gpu_percent = 0
    except Exception:
        pass


def _save_to_qsettings(settings: ComputeSettings) -> None:
    try:
        from PyQt6.QtCore import QSettings

        qs = QSettings("PaleoDrawing", "Compute")
        qs.setValue("cpu_percent", int(settings.cpu_percent))
        qs.setValue("gpu_percent", 0)
        qs.setValue("hardware_accel", False)
    except Exception:
        pass
