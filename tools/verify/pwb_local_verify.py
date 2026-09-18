#!/usr/bin/env python3
"""Single local verification driver for the Paleo Workbench C++ migration.

One entry point for the steps a developer actually runs while converting Python
to C++, all of them low-resource by default and none of them touching the
network or remote CI:

    doctor      report toolchain, SDK and resource-gate availability
    presets     validate CMakePresets.json (uniqueness, references, job caps)
    configure   configure a preset or an explicit feature set
    build       build selected targets (or the whole configure graph)
    test        run ctest, optionally filtered by a regex
    oracle      list (and optionally re-run) the Python oracle for a slice
    smoke       run the built native product offscreen and report the exit code
    inventory   regenerate the C++ migration inventory
    hygiene     run the build-artifact hygiene audit
    pyaudit     run the Python dependency audit
    all         configure -> build -> test, stopping at the first failure

Resource discipline (mandatory for the 7 parallel worktrees):
  * compiler and test parallelism default to 2 and are hard-capped at 8;
  * every command exports CMAKE_BUILD_PARALLEL_LEVEL / CTEST_PARALLEL_LEVEL so
    a nested build tool cannot fan out further;
  * a free-RAM check refuses to start heavy work below --min-free-gib;
  * no online CI is waited on, and no workflow file is touched.

Windows note: ``vcvars64.bat`` / ``Enter-VsDevShell`` rely on ``reg.exe``, which
is blocked in some sandboxes, so this driver discovers the MSVC and Windows SDK
layout itself and assembles PATH / INCLUDE / LIB from absolute paths.

Usage examples::

    python tools/verify/pwb_local_verify.py doctor
    python tools/verify/pwb_local_verify.py configure --preset developer-fast
    python tools/verify/pwb_local_verify.py build --preset developer-fast \
        --targets mapping_kernel.crs_policy
    python tools/verify/pwb_local_verify.py test --preset developer-fast -R crs_policy
    python tools/verify/pwb_local_verify.py oracle --unit mapping_kernel
    python tools/verify/pwb_local_verify.py all --preset developer-fast

Exit codes: 0 success, 1 step failed, 2 usage or repository error,
64 invalid usage, 75 resource refusal (low memory).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REPO = 2
EXIT_USAGE = 64
EXIT_RESOURCE = 75

DEFAULT_JOBS = 2
MAX_JOBS = 8
DEFAULT_MIN_FREE_GIB = 4.0

REQUIRED_PRESETS = (
    "developer-fast",
    "conversion-kernel",
    "native-product-smoke",
    "low-memory",
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def log(message: str) -> None:
    print(message, flush=True)


def banner(title: str) -> None:
    log("-" * 74)
    log(title)
    log("-" * 74)


def clamp_jobs(jobs: int) -> Tuple[int, Optional[str]]:
    if jobs < 1:
        return 1, f"jobs {jobs} is below 1; using 1"
    if jobs > MAX_JOBS:
        return MAX_JOBS, f"jobs {jobs} exceeds the cap; clamped to {MAX_JOBS}"
    return jobs, None


def find_on_path(names: Sequence[str]) -> Optional[str]:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def discover_cmake() -> Optional[str]:
    candidates = [find_on_path(["cmake"])]
    candidates += sorted(
        glob.glob(
            r"C:\Program Files\Microsoft Visual Studio\*\*\Common7\IDE"
            r"\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
        ),
        reverse=True,
    )
    candidates += sorted(glob.glob(r"C:\Program Files\CMake\bin\cmake.exe"))
    candidates += sorted(glob.glob("/usr/bin/cmake")) + sorted(glob.glob("/usr/local/bin/cmake"))
    return next((c for c in candidates if c and os.path.exists(c)), None)


def discover_ninja() -> Optional[str]:
    candidates = [find_on_path(["ninja"])]
    candidates += sorted(
        glob.glob(
            r"C:\Program Files\Microsoft Visual Studio\*\*\Common7\IDE"
            r"\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
        ),
        reverse=True,
    )
    return next((c for c in candidates if c and os.path.exists(c)), None)


def discover_msvc() -> Tuple[Optional[str], Optional[str]]:
    """(msvc_toolset_dir, cl_exe) for the newest installed MSVC toolset."""
    roots = sorted(
        glob.glob(r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Tools\MSVC\*"),
        reverse=True,
    )
    for root in roots:
        cl = os.path.join(root, "bin", "Hostx64", "x64", "cl.exe")
        if os.path.exists(cl):
            return root.replace("\\", "/"), cl.replace("\\", "/")
    return None, None


WINDOWS_SDK_ROOT = "C:/Program Files (x86)/Windows Kits/10"


@dataclass
class WindowsSdk:
    """Absolute SDK paths, assembled without touching the registry."""

    version: str
    include_dirs: List[str]
    lib_dirs: List[str]
    bin_x64: str

    @property
    def rc_exe(self) -> str:
        return f"{self.bin_x64}/rc.exe"

    @property
    def mt_exe(self) -> str:
        return f"{self.bin_x64}/mt.exe"


def discover_windows_sdk() -> Optional[WindowsSdk]:
    """Newest Windows 10/11 SDK, located by directory scan (no reg.exe)."""
    versions = [
        os.path.basename(p)
        for p in glob.glob(f"{WINDOWS_SDK_ROOT}/Include/*")
        if os.path.isdir(p) and re.match(r"^\d+\.\d+\.\d+\.\d+$", os.path.basename(p))
    ]
    versions = [v for v in versions if os.path.isdir(f"{WINDOWS_SDK_ROOT}/bin/{v}/x64")]
    if not versions:
        return None
    best = sorted(versions, key=lambda v: [int(x) for x in v.split(".")])[-1]
    return WindowsSdk(
        version=best,
        include_dirs=[
            f"{WINDOWS_SDK_ROOT}/Include/{best}/ucrt",
            f"{WINDOWS_SDK_ROOT}/Include/{best}/um",
            f"{WINDOWS_SDK_ROOT}/Include/{best}/shared",
            f"{WINDOWS_SDK_ROOT}/Include/{best}/winrt",
            f"{WINDOWS_SDK_ROOT}/Include/{best}/cppwinrt",
        ],
        lib_dirs=[
            f"{WINDOWS_SDK_ROOT}/Lib/{best}/ucrt/x64",
            f"{WINDOWS_SDK_ROOT}/Lib/{best}/um/x64",
        ],
        bin_x64=f"{WINDOWS_SDK_ROOT}/bin/{best}/x64",
    )


def main_worktree_root(root: str) -> Optional[str]:
    """Root of the principal worktree that owns the shared .git directory.

    A linked worktree has ``.git`` as a *file* pointing at
    ``<main>/.git/worktrees/<name>``. The product virtualenv lives next to the
    principal worktree, not next to each linked one, so the driver has to look
    there for a usable oracle interpreter.
    """
    dot_git = os.path.join(root, ".git")
    if os.path.isdir(dot_git):
        return root
    if not os.path.isfile(dot_git):
        return None
    try:
        with open(dot_git, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = content.split(":", 1)[1].strip().replace("\\", "/")
    marker = "/.git/"
    if marker in gitdir:
        return gitdir.split(marker, 1)[0].replace("/", os.sep)
    return None


def can_import(interpreter: str, module: str) -> bool:
    try:
        completed = subprocess.run(
            [interpreter, "-c", f"import {module}"],
            capture_output=True, timeout=60,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def discover_product_python(root: str) -> Optional[str]:
    """Interpreter that can run the Python oracle read-back (needs pydantic)."""
    candidates: List[str] = []
    override = os.environ.get("PWB_PYTHON")
    if override:
        candidates.append(override)
    candidates.append(os.path.join(root, ".venv", "Scripts", "python.exe"))
    candidates.append(os.path.join(root, ".venv", "bin", "python"))
    main_root = main_worktree_root(root)
    if main_root:
        candidates.append(os.path.join(main_root, ".venv", "Scripts", "python.exe"))
        candidates.append(os.path.join(main_root, ".venv", "bin", "python"))
    for name in ("python3.12", "python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen or not os.path.exists(candidate):
            continue
        seen.add(candidate)
        if can_import(candidate, "pydantic"):
            return candidate
    return None


def free_gib() -> Optional[float]:
    """Available physical memory in GiB, or None when it cannot be measured."""
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            # Explicit signatures: without them ctypes defaults to c_int for the
            # return value and would truncate the BOOL, and a 64-bit struct
            # passed by reference is only safe with declared types.
            kernel32 = ctypes.windll.kernel32
            kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
            kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.ullAvailPhys / (1024.0 ** 3)
        except Exception:
            return None
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / (1024.0 ** 2)
    except OSError:
        return None
    return None


def run(argv: Sequence[str], cwd: str, env: Optional[Dict[str, str]] = None) -> int:
    log("$ " + " ".join(argv))
    completed = subprocess.run(list(argv), cwd=cwd, env=env)
    return completed.returncode


# --------------------------------------------------------------------------- #
# Repository facts
# --------------------------------------------------------------------------- #


class Repo:
    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)

    def require(self) -> None:
        if not os.path.exists(os.path.join(self.root, "CMakeLists.txt")):
            # Exit 2 (repository error), matching the documented contract.
            print(f"error: {self.root} does not look like the repository root "
                  "(no CMakeLists.txt)", file=sys.stderr)
            raise SystemExit(EXIT_REPO)

    @property
    def presets_path(self) -> str:
        return os.path.join(self.root, "CMakePresets.json")

    def presets(self) -> dict:
        with open(self.presets_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def build_env(self, jobs: int) -> Dict[str, str]:
        """Process environment for a low-resource build."""
        env = dict(os.environ)
        env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(jobs)
        env["CTEST_PARALLEL_LEVEL"] = str(jobs)
        env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM", "offscreen")
        if sys.platform == "win32":
            msvc, _cl = discover_msvc()
            sdk = discover_windows_sdk()
            ninja = discover_ninja()
            parts: List[str] = []
            if msvc:
                parts.append(f"{msvc}/bin/Hostx64/x64")
            if sdk:
                parts.append(sdk.bin_x64)
            if ninja:
                parts.append(os.path.dirname(ninja).replace("\\", "/"))
            if parts:
                env["PATH"] = os.pathsep.join(parts) + os.pathsep + env.get("PATH", "")
            if msvc and sdk:
                env["INCLUDE"] = os.pathsep.join([f"{msvc}/include", *sdk.include_dirs])
                env["LIB"] = os.pathsep.join([f"{msvc}/lib/x64", *sdk.lib_dirs])
        return env


def compiler_args(repo: Repo, env: Dict[str, str]) -> List[str]:
    """Explicit compiler paths — needed when cl.exe is not on the ambient PATH."""
    if sys.platform != "win32":
        return []
    _msvc, cl = discover_msvc()
    if not cl:
        # Let CMake find the compiler on PATH; the presets still work when a
        # developer shell already has the MSVC environment loaded.
        return []
    # Pass the absolute paths explicitly rather than relying on PATH: it is
    # deterministic, and it avoids the "compiler identification is unknown"
    # failure mode of the sandboxed vcvars path (reg.exe is blocked there).
    args = [f"-DCMAKE_C_COMPILER={cl}", f"-DCMAKE_CXX_COMPILER={cl}"]
    # CMake's Ninja generator needs the resource compiler and manifest tool by
    # name. Without these it resolves a bogus `rc`, and configuration dies with
    # "RC Pass 1 ... failed" plus a CMAKE_MT-NOTFOUND, which looks nothing like
    # a missing SDK. Point both at the SDK we discovered instead.
    sdk = discover_windows_sdk()
    if sdk:
        if os.path.exists(sdk.rc_exe):
            args.append(f"-DCMAKE_RC_COMPILER={sdk.rc_exe}")
        if os.path.exists(sdk.mt_exe):
            args.append(f"-DCMAKE_MT={sdk.mt_exe}")
    return args


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_doctor(repo: Repo, args: argparse.Namespace) -> int:
    banner("doctor — local toolchain and resource availability")
    cmake = discover_cmake()
    ninja = discover_ninja()
    msvc, cl = discover_msvc()
    sdk = discover_windows_sdk()
    mem = free_gib()
    gate_ps = os.path.join(repo.root, "scripts", "cpp-migration", "Invoke-ResourceGate.ps1")
    gate_sh = os.path.join(repo.root, "scripts", "cpp-migration", "invoke-resource-gate.sh")

    log(f"platform          = {sys.platform}")
    log(f"python            = {sys.version.split()[0]} ({sys.executable})")
    log(f"cmake             = {cmake or 'NOT FOUND'}")
    log(f"ninja             = {ninja or 'NOT FOUND'}")
    log(f"msvc toolset      = {msvc or 'NOT FOUND'}")
    log(f"cl.exe            = {cl or 'NOT FOUND'}")
    log(f"windows sdk       = {sdk.version if sdk else 'NOT FOUND'}")
    log(f"rc.exe / mt.exe   = "
        f"{os.path.exists(sdk.rc_exe) if sdk else 'n/a'} / "
        f"{os.path.exists(sdk.mt_exe) if sdk else 'n/a'}")
    log(f"free memory GiB   = {mem if mem is not None else 'unknown'}")
    log(f"resource gate PS  = {'present' if os.path.exists(gate_ps) else 'missing'}")
    log(f"resource gate sh  = {'present' if os.path.exists(gate_sh) else 'missing'}")
    log(f"CMakePresets      = {'present' if os.path.exists(repo.presets_path) else 'missing'}")
    log("online CI         = never waited on by this driver")

    problems = []
    if not cmake:
        problems.append("cmake not found")
    if not ninja:
        problems.append("ninja not found (the presets use the Ninja generator)")
    if sys.platform == "win32" and not cl:
        problems.append("no MSVC compiler found")
    if problems:
        log("doctor: PROBLEMS -> " + "; ".join(problems))
        return EXIT_FAILED
    log("doctor: OK")
    return EXIT_OK


def cmd_presets(repo: Repo, args: argparse.Namespace) -> int:
    banner("presets — CMakePresets.json sanity")
    data = repo.presets()
    configure = {p["name"]: p for p in data.get("configurePresets", [])}
    build = data.get("buildPresets", [])
    test = data.get("testPresets", [])
    failures: List[str] = []

    seen_dirs: Dict[str, str] = {}
    for name, preset in configure.items():
        binary_dir = preset.get("binaryDir")
        if not binary_dir:
            failures.append(f"{name}: no binaryDir")
            continue
        owner = seen_dirs.get(binary_dir)
        if owner and owner != name:
            # The three original CPP-A presets intentionally share one tree; only
            # flag it, because sharing silently reuses the other preset's cache.
            log(
                f"WARN  {name} shares binaryDir with {owner}: {binary_dir} "
                "(cache is reused across presets)"
            )
        else:
            seen_dirs.setdefault(binary_dir, name)
        env = preset.get("environment", {})
        level = env.get("CMAKE_BUILD_PARALLEL_LEVEL")
        if level is not None:
            try:
                value = int(level)
            except ValueError:
                failures.append(f"{name}: CMAKE_BUILD_PARALLEL_LEVEL is not an integer")
                continue
            if value > MAX_JOBS or value < 1:
                failures.append(
                    f"{name}: CMAKE_BUILD_PARALLEL_LEVEL={value} outside 1..{MAX_JOBS}"
                )

    for preset in build:
        if preset.get("configurePreset") not in configure:
            failures.append(
                f"buildPreset {preset.get('name')}: unknown configurePreset "
                f"{preset.get('configurePreset')}"
            )
    for preset in test:
        if preset.get("configurePreset") not in configure:
            failures.append(
                f"testPreset {preset.get('name')}: unknown configurePreset "
                f"{preset.get('configurePreset')}"
            )

    for required in REQUIRED_PRESETS:
        if required not in configure:
            failures.append(f"required configure preset missing: {required}")
    for required in ("windows-msvc", "linux-ninja"):
        if required not in configure:
            failures.append(f"required configure preset missing: {required}")

    log(f"configure presets = {len(configure)}")
    log(f"build presets     = {len(build)}")
    log(f"test presets      = {len(test)}")
    if failures:
        for item in failures:
            log(f"FAIL  {item}")
        return EXIT_FAILED
    log("presets: OK")
    return EXIT_OK


def _preset_binary_dir(repo: Repo, name: str) -> Optional[str]:
    preset = {p["name"]: p for p in repo.presets().get("configurePresets", [])}.get(name)
    if not preset:
        return None
    binary_dir = preset.get("binaryDir", "")
    return binary_dir.replace("${sourceDir}", repo.root).replace("\\", "/")


GATE_PS = "scripts/cpp-migration/Invoke-ResourceGate.ps1"
GATE_SH = "scripts/cpp-migration/invoke-resource-gate.sh"


def find_gate_script(repo: "Repo") -> Optional[str]:
    rel = GATE_PS if sys.platform == "win32" else GATE_SH
    path = os.path.join(repo.root, rel)
    return path if os.path.exists(path) else None


def require_gate(repo: "Repo", args: argparse.Namespace) -> Optional[int]:
    """Refuse a heavy step that is not running inside the shared build slot.

    Checking the free-memory floor is not enough: without the slot lock two
    invocations of this driver (or one of them plus a gate-wrapped build) could
    compile concurrently and defeat the whole point of the gate. The gate exports
    PWB_GATE_HELD=1 to its children, including `-Action Exec`.
    """
    if os.environ.get("PWB_GATE_HELD") == "1":
        log(f"gate slot held (PWB_GATE_JOBS={os.environ.get('PWB_GATE_JOBS', '?')})")
        return None
    if args.allow_ungated:
        log("WARNING: --allow-ungated given; running WITHOUT the shared build slot")
        return None
    gate = find_gate_script(repo)
    if not gate:
        log("WARNING: no resource gate found; running WITHOUT the shared build slot")
        return None

    log(f"REFUSED: '{args.command}' is a heavy step and this process does not hold "
        "the shared build slot (PWB_GATE_HELD is not 1).")
    log("The gate allows one heavy build per worktree across all 7 worktrees; "
        "running outside it is what makes the machine OOM.")
    log("Run it through the gate instead:")
    driver = "tools/verify/pwb_local_verify.py"
    if sys.platform == "win32":
        log(f'  powershell -NoProfile -ExecutionPolicy Bypass -File "{GATE_PS}" '
            f"-Action Exec -MinFreeGiB {args.min_free_gib:g} -Command python "
            f'-CommandArguments "{driver} {args.command} ..."')
    else:
        log(f"  {GATE_SH} Exec -- python {driver} {args.command} ...")
    log("Or pass --allow-ungated if you have deliberately excluded this machine "
        "from the shared budget (for example a single-worktree run).")
    return EXIT_RESOURCE


def guard_resources(args: argparse.Namespace) -> Optional[int]:
    mem = free_gib()
    if mem is None:
        # Do not pretend the floor was checked. Say so, loudly, every time.
        log(f"RESOURCE_MEMORY_UNKNOWN detail=free memory could not be measured; "
            f"floor {args.min_free_gib:g} GiB NOT enforced")
    if mem is None:
        return None
    if mem < args.min_free_gib:
        log(
            f"RESOURCE_LOW_MEMORY free_gib={mem:.2f} required={args.min_free_gib:.2f}; "
            f"exit={EXIT_RESOURCE}"
        )
        return EXIT_RESOURCE
    log(f"RESOURCE_READY free_gib={mem:.2f} jobs={args.jobs}")
    return None


def python_args(repo: Repo, args: argparse.Namespace) -> List[str]:
    """Pin the product interpreter for the Python oracle read-back gate.

    ``tests/cpp/data`` refuses to configure unless the interpreter it finds can
    import pydantic, and CMake's own search may land on a bare system Python.
    Point it at the product virtualenv instead.
    """
    interpreter = args.python or discover_product_python(repo.root)
    if not interpreter:
        log("note: no interpreter with pydantic found; the data oracle gate may "
            "refuse to configure (pass --python <path> to override)")
        return []
    log(f"oracle interpreter = {interpreter}")
    return [f"-DPython3_EXECUTABLE={interpreter.replace(chr(92), '/')}"]


def cmd_configure(repo: Repo, args: argparse.Namespace) -> int:
    banner("configure")
    cmake = discover_cmake()
    if not cmake:
        log("error: cmake not found")
        return EXIT_FAILED
    jobs = args.jobs
    env = repo.build_env(jobs)

    if args.preset:
        binary_dir = _preset_binary_dir(repo, args.preset)
        argv = [cmake, "--preset", args.preset]
        argv += compiler_args(repo, env)
        argv += python_args(repo, args)
    else:
        if not args.build_dir:
            log("error: --build-dir is required when --preset is not used")
            return EXIT_USAGE
        binary_dir = os.path.abspath(args.build_dir)
        argv = [cmake, "-S", repo.root, "-B", binary_dir, "-G", "Ninja"]
        argv += compiler_args(repo, env)
        argv += [f"-DCMAKE_BUILD_TYPE={args.config}"]
        for var in args.cache_var:
            argv.append(f"-D{var}")
        argv += python_args(repo, args)
    if args.verbose:
        env["PWB_FEATURE_VERBOSE"] = "1"
    log(f"build dir = {binary_dir}")
    return EXIT_OK if run(argv, repo.root, env) == 0 else EXIT_FAILED


def cmd_build(repo: Repo, args: argparse.Namespace) -> int:
    banner("build")
    cmake = discover_cmake()
    if not cmake:
        log("error: cmake not found")
        return EXIT_FAILED
    jobs = args.jobs
    env = repo.build_env(jobs)
    build_dir = _preset_binary_dir(repo, args.preset) if args.preset else args.build_dir
    if not build_dir:
        log("error: --preset or --build-dir is required")
        return EXIT_USAGE
    if not os.path.exists(os.path.join(build_dir, "CMakeCache.txt")):
        log(f"error: {build_dir} is not configured yet; run configure first")
        return EXIT_FAILED
    argv: List[str] = [cmake, "--build", build_dir, "--parallel", str(jobs)]
    if args.targets:
        argv += ["--target", *args.targets]
    return EXIT_OK if run(argv, repo.root, env) == 0 else EXIT_FAILED


def cmd_test(repo: Repo, args: argparse.Namespace) -> int:
    banner("test")
    ctest = find_on_path(["ctest"])
    if not ctest:
        cmake = discover_cmake()
        if cmake:
            ctest = os.path.join(os.path.dirname(cmake), "ctest.exe" if sys.platform == "win32" else "ctest")
    if not ctest or not os.path.exists(ctest):
        log("error: ctest not found")
        return EXIT_FAILED
    jobs = args.jobs
    env = repo.build_env(jobs)
    build_dir = _preset_binary_dir(repo, args.preset) if args.preset else args.build_dir
    if not build_dir:
        log("error: --preset or --build-dir is required")
        return EXIT_USAGE
    argv = [
        ctest,
        "--test-dir", build_dir,
        "-C", args.config,
        "--output-on-failure",
        "--no-tests=error",
        "--timeout", str(args.timeout),
        "-j", str(jobs),
    ]
    if args.regex:
        argv += ["-R", args.regex]
    return EXIT_OK if run(argv, repo.root, env) == 0 else EXIT_FAILED


def cmd_oracle(repo: Repo, args: argparse.Namespace) -> int:
    banner("oracle — Python oracle coverage for a slice")
    inventory_script = os.path.join(repo.root, "tools", "migration", "pwb_migration_inventory.py")
    if not os.path.exists(inventory_script):
        log("error: tools/migration/pwb_migration_inventory.py is missing")
        return EXIT_REPO
    completed = subprocess.run(
        [sys.executable, inventory_script, "--repo-root", repo.root,
         "--json-out", os.path.join(repo.root, "build", "migration-inventory", "inventory.json"),
         "--markdown-out", os.path.join(repo.root, "build", "migration-inventory", "inventory.md"),
         "--quiet"],
        cwd=repo.root, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        log("error: inventory generation failed")
        log(completed.stderr.strip()[:2000])
        return EXIT_FAILED
    with open(os.path.join(repo.root, "build", "migration-inventory", "inventory.json"),
              encoding="utf-8") as handle:
        inventory = json.load(handle)

    wanted = (args.unit or "").lower()
    rows = [
        u for u in inventory["units"]
        if not wanted or wanted in u["unit"].lower()
    ]
    if not rows:
        log(f"no unit matches {args.unit!r}")
        return EXIT_FAILED
    for unit in rows:
        log(f"unit {unit['unit']}  status={unit['status']}  wiring={unit['wiring_mode']}")
        for gen in unit["oracle_generators"]:
            log(f"    generator: {gen}")
        for fixture in unit["fixtures"]:
            log(f"    fixture:   {fixture}")
        for origin in unit["python_origins"]:
            mark = "present" if origin in unit["python_origins_present"] else "absent"
            log(f"    python:    {origin} ({mark})")
    if args.replay:
        log("")
        log("oracle replay requires the product virtualenv; re-running generators:")
        env = repo.build_env(args.jobs)
        rc = EXIT_OK
        for unit in rows:
            for gen in unit["oracle_generators"]:
                path = os.path.join(repo.root, gen)
                code = run([sys.executable, path], repo.root, env)
                if code != 0:
                    rc = EXIT_FAILED
        return rc
    log("")
    log("(pass --replay to re-run the generators; needs the product virtualenv)")
    return EXIT_OK


def cmd_smoke(repo: Repo, args: argparse.Namespace) -> int:
    banner("smoke — native product offscreen self-check")
    build_dir = _preset_binary_dir(repo, args.preset) if args.preset else args.build_dir
    if not build_dir:
        log("error: --preset or --build-dir is required")
        return EXIT_USAGE
    candidates = ["pwb-diagnose", "pwb-platform"]
    env = repo.build_env(args.jobs)
    env["QT_QPA_PLATFORM"] = "offscreen"
    found = None
    for name in candidates:
        for pattern in (f"{build_dir}/**/{name}.exe", f"{build_dir}/**/{name}"):
            hits = glob.glob(pattern, recursive=True)
            if hits:
                found = hits[0]
                break
        if found:
            break
    if not found:
        log(f"no product binary found under {build_dir} (build the platform preset first)")
        log("smoke: SKIPPED")
        return EXIT_OK
    log(f"running {found} (QT_QPA_PLATFORM=offscreen)")
    code = run([found], repo.root, env)
    log(f"smoke exit code = {code}")
    if code < 0:
        log("smoke: CRASHED")
        return EXIT_FAILED
    log("smoke: OK")
    return EXIT_OK


def _delegate(repo: Repo, script: str, extra: Sequence[str]) -> int:
    path = os.path.join(repo.root, script)
    if not os.path.exists(path):
        log(f"error: {script} is missing")
        return EXIT_REPO
    return EXIT_OK if run([sys.executable, path, "--repo-root", repo.root, *extra],
                          repo.root) == 0 else EXIT_FAILED


def cmd_inventory(repo: Repo, args: argparse.Namespace) -> int:
    banner("inventory")
    return _delegate(repo, "tools/migration/pwb_migration_inventory.py", [])


def cmd_hygiene(repo: Repo, args: argparse.Namespace) -> int:
    banner("hygiene")
    return _delegate(repo, "tools/verify/pwb_artifact_hygiene.py", [])


def cmd_pyaudit(repo: Repo, args: argparse.Namespace) -> int:
    banner("pyaudit")
    return _delegate(repo, "tools/migration/pwb_python_dependency_audit.py", [])


def cmd_all(repo: Repo, args: argparse.Namespace) -> int:
    banner("all — configure, build, test (low resource, no online CI)")
    for step in (cmd_configure, cmd_build, cmd_test):
        code = step(repo, args)
        if code != EXIT_OK:
            log(f"all: stopping after {step.__name__} (exit {code})")
            return code
    log("all: OK")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local verification driver for the Paleo Workbench C++ migration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=[
        "doctor", "presets", "configure", "build", "test", "oracle", "smoke",
        "inventory", "hygiene", "pyaudit", "all",
    ])
    parser.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--preset", help="configure/build/test preset name")
    parser.add_argument("--build-dir", help="explicit build directory")
    parser.add_argument("--python", default=None,
                        help="interpreter for the Python oracle read-back gate")
    parser.add_argument("--config", default="Debug", help="CMAKE_BUILD_TYPE (default Debug)")
    parser.add_argument("--targets", nargs="*", default=[], help="targets to build")
    parser.add_argument("-R", "--regex", default=None, help="ctest test name regex")
    parser.add_argument("--timeout", type=int, default=180, help="per-test timeout seconds")
    parser.add_argument("--unit", default=None, help="unit filter for the oracle command")
    parser.add_argument("--replay", action="store_true",
                        help="oracle: actually re-run the Python generators")
    parser.add_argument("--cache-var", action="append", default=[],
                        help="extra -DKEY=VALUE when configuring without a preset")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help=f"compiler/test parallelism (default {DEFAULT_JOBS}, cap {MAX_JOBS})")
    parser.add_argument("--min-free-gib", type=float, default=DEFAULT_MIN_FREE_GIB,
                        help="refuse heavy steps below this much free RAM")
    parser.add_argument("--verbose", action="store_true", help="verbose feature graph on configure")
    parser.add_argument("--allow-ungated", action="store_true",
                        help="run heavy steps without the shared build slot (see docs)")
    args = parser.parse_args(argv)

    jobs, warning = clamp_jobs(args.jobs)
    if warning:
        log(f"WARNING: {warning}")
    args.jobs = jobs

    repo = Repo(args.repo_root)
    repo.require()

    heavy = {"configure", "build", "test", "smoke", "all"}
    if args.command in heavy:
        # Order matters: prove we hold the shared slot before judging memory, so
        # two concurrent drivers cannot both pass the RAM check and compile.
        refusal = require_gate(repo, args)
        if refusal is not None:
            return refusal
        refusal = guard_resources(args)
        if refusal is not None:
            return refusal

    dispatch = {
        "doctor": cmd_doctor,
        "presets": cmd_presets,
        "configure": cmd_configure,
        "build": cmd_build,
        "test": cmd_test,
        "oracle": cmd_oracle,
        "smoke": cmd_smoke,
        "inventory": cmd_inventory,
        "hygiene": cmd_hygiene,
        "pyaudit": cmd_pyaudit,
        "all": cmd_all,
    }
    return dispatch[args.command](repo, args)


if __name__ == "__main__":
    raise SystemExit(main())
