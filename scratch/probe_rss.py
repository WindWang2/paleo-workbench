"""One-off probe: why does the RSS query return None?"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


out = []
try:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    out.append(f"sizeof={ctypes.sizeof(pmc)}")
    kernel32 = ctypes.windll.kernel32
    proc = kernel32.GetCurrentProcess()
    out.append(f"proc={proc!r}")
    try:
        fn = kernel32.K32GetProcessMemoryInfo
        out.append("using K32GetProcessMemoryInfo")
    except AttributeError as exc:
        out.append(f"K32 missing: {exc}")
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
    fn.restype = wintypes.BOOL
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    ok = fn(wintypes.HANDLE(proc), ctypes.byref(pmc), pmc.cb)
    out.append(f"ok={ok} lastError={ctypes.get_last_error()}")
    out.append(f"WorkingSetSize={pmc.WorkingSetSize}")
except Exception as exc:  # noqa: BLE001
    out.append(f"EXC {type(exc).__name__}: {exc}")

# Cross-check via GetProcessTimes-free alternative: PerformanceCounter not used.
try:
    import subprocess

    r = subprocess.run(
        ["tasklist", "/FI", f"PID eq {__import__('os').getpid()}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    out.append(f"tasklist: {r.stdout.strip()}")
except Exception as exc:  # noqa: BLE001
    out.append(f"tasklist EXC {exc}")

print("\n".join(out))
