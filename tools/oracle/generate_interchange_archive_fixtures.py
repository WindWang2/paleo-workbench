#!/usr/bin/env python3
"""Frozen Python oracle for the interchange archive/OS/container/adapters
kernel (conv-14b).

Imports the REAL paleo_workbench modules (path_safety zip halves,
package.builder, package.verifier, package.verifier_zip,
resources.exporters.atomic_output, adapters.model_adapter,
viz.geomodel.exporters) and freezes their observed behavior into
libs/interchange/interchange_tests/fixtures/interchange_archive_oracle.json,
replayed by the ctest target `interchange.archive`.

No hand-written expectations: every "expected" value below is whatever the
real Python module returned. The only shims are (a) a stub catalog feeding
the real PackageBuilder where a live catalog service would sit, and (b) a
frozen datetime stamping manifest created_at — mirroring the C++
created_at-provider seam. Absolute paths are frozen as "{ROOT}" placeholders.

Interpreter-specific tails (json.JSONDecodeError text, OSError strerror) are
not replayable in C++: those cases set "prefix": true and the C++ side
compares the frozen stable prefix only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench  # noqa: E402
import paleo_workbench.interchange.package.builder as builder_mod  # noqa: E402
from paleo_workbench.catalog.models import DataStage  # noqa: E402
from paleo_workbench.interchange.adapters.model_adapter import (  # noqa: E402
    AbaqusAdapter,
    Flac3dAdapter,
    parse_abaqus,
    parse_flac3d,
)
from paleo_workbench.interchange.contracts import FormatNotSupportedError  # noqa: E402
from paleo_workbench.interchange.package.builder import (  # noqa: E402
    ExternalPolicy,
    PackageBuilder,
    PackageOptions,
    zip_package_dir,
)
from paleo_workbench.interchange.package.verifier import (  # noqa: E402
    materialize_package,
    open_package,
    verify_package,
)
from paleo_workbench.interchange.package.verifier_zip import (  # noqa: E402
    verify_zip_container,
)
from paleo_workbench.interchange.path_safety import (  # noqa: E402
    UnsafePathError,
    extract_archive,
    os_replace_atomic,
    safe_members,
)
from paleo_workbench.resources.exporters import atomic_output  # noqa: E402

FIXTURE = (
    REPO_ROOT / "libs" / "interchange" / "interchange_tests"
    / "fixtures" / "interchange_archive_oracle.json"
)

FROZEN_NOW = datetime(2020, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)


class _FixedDateTime(datetime):
    """builder.datetime replacement freezing created_at (14b decisions D2)."""

    @classmethod
    def now(cls, tz=None):  # noqa: N805 - mirrors datetime.now signature
        return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def sub_root(text: str, root: Path) -> str:
    return text.replace(str(root), "{ROOT}")


def deep_sub(value, root: Path):
    if isinstance(value, str):
        return sub_root(value, root)
    if isinstance(value, list):
        return [deep_sub(v, root) for v in value]
    if isinstance(value, dict):
        return {k: deep_sub(v, root) for k, v in value.items()}
    return value


def make_zip(members, method=zipfile.ZIP_DEFLATED) -> bytes:
    """members: list of (name, bytes) or (ZipInfo, bytes)."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", method, allowZip64=True) as bundle:
        for entry in members:
            info, payload = entry
            if isinstance(info, str):
                meta = zipfile.ZipInfo(info, date_time=(1980, 1, 1, 0, 0, 0))
                meta.compress_type = method
                meta.external_attr = 0o100644 << 16
                meta.create_system = 3
                info, payload = meta, payload
            bundle.writestr(info, payload)
    return buffer.getvalue()


def symlink_member(name: str, target: str = "/etc/passwd"):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (0o120777 << 16)  # S_IFLNK | 0777
    info.create_system = 3
    return (info, target.encode("utf-8"))


def craft_cp437_zip() -> bytes:
    """Hand-built container whose entry name is CP437-encoded with the UTF-8
    flag clear (pre-4.6-zipfile layout); the oracle is what CPython's zipfile
    decodes from it."""
    raw_name = "caf\xe9.txt".encode("cp437")
    payload = b"content\n"
    crc = zipfile.zlib.crc32(payload) & 0xFFFFFFFF

    local = struct.pack(
        "<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21, crc,
        len(payload), len(payload), len(raw_name), 0,
    )
    central = struct.pack(
        "<IHHHHHHIIIHHHHHII", 0x02014B50, (3 << 8) | 20, 20, 0, 0, 0, 0x21,
        crc, len(payload), len(payload), len(raw_name), 0, 0, 0, 0,
        (0o100644 << 16), 0,
    )
    eocd = struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, 1, 1,
        len(central) + len(raw_name), 30 + len(raw_name) + len(payload), 0,
    )
    return local + raw_name + payload + central + raw_name + eocd


HAND_MANIFEST_BASE = {
    "kind": "paleo-package", "schema_version": 2,
    "project": {"name": "p", "file": "p.paleo.json"},
    "created_at": "2020-01-02T03:04:05.678901+00:00",
    "application": {"name": "paleo-workbench", "version": "0.2.17a0"},
    "entries": [],
    "external_dependencies": [], "missing_dependencies": [],
    "generated_outputs": [], "provenance": {},
    "options": {}, "total_size_bytes": 0,
}


def hand_manifest(entries, total=0, **overrides) -> bytes:
    manifest = {**HAND_MANIFEST_BASE, "entries": entries,
                "total_size_bytes": total, **overrides}
    return json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")


def entry(path, digest, size, kind="artifact") -> dict:
    return {"path": path, "sha256": digest, "size_bytes": size, "kind": kind}


# ---------------------------------------------------------------------------


def main() -> None:
    oracle = {
        "meta": {
            "generator": "tools/oracle/generate_interchange_archive_fixtures.py",
            "python": sys.version.split()[0],
            "package_version": paleo_workbench.__version__,
            "frozen_created_at": FROZEN_NOW.isoformat(),
        }
    }

    # ------------------------------------------------- safe_members/extract
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)

        clean_members = [
            ("manifest.json", b'{"kind": "paleo-package"}'),
            ("proj.paleo.json", b"{}\n"),
            ("proj.artifacts/raw/a.bin", bytes(range(256))),
            ("proj.artifacts/derived/b.txt", b"hello\n" * 10),
            ("proj.artifacts/metadata/catalog.json", b"[]"),
            ("data/\u5730\u8d28/\u5c42.dat", b"\x00\x01\x02zip"),
        ]
        safe_cases = []

        def safe_case(case_id, zip_bytes, what="archive"):
            bundle = zipfile.ZipFile(BytesIO(zip_bytes))
            try:
                names = safe_members(bundle, what=what)
                safe_cases.append({
                    "id": case_id, "what": what, "zip_b64": b64(zip_bytes),
                    "expect": {"ok": True, "names": names},
                })
            except UnsafePathError as exc:
                safe_cases.append({
                    "id": case_id, "what": what, "zip_b64": b64(zip_bytes),
                    "expect": {"ok": False, "message": str(exc)},
                })

        safe_case("clean_nested", make_zip(clean_members))
        safe_case("stored_method", make_zip(clean_members, zipfile.ZIP_STORED))
        safe_case("what_prefix", make_zip([("../evil.txt", b"x")]), what="package zip")
        safe_case("traversal", make_zip([("../evil.txt", b"x")]))
        safe_case("traversal_deep", make_zip([("a/b/../../../evil.txt", b"x")]))
        safe_case("absolute_posix", make_zip([("/etc/passwd", b"x")]))
        safe_case("absolute_windows", make_zip([("C:\\evil.txt", b"x")]))
        safe_case("unc_path", make_zip([("\\\\server\\share/x.txt", b"x")]))
        safe_case("symlink_entry", make_zip([symlink_member("link.txt")]))
        safe_case("symlink_dir_entry", make_zip([symlink_member("dir/link")]))
        safe_case("nfc_ok", make_zip([("caf\u00e9.txt", b"x"), ("data/\u5730.txt", b"y")]))
        safe_case("nfd_rejected", make_zip([("cafe\u0301.txt", b"x")]))
        safe_case("casefold_collision", make_zip([("Data/file.txt", b"a"), ("data/file.txt", b"b")]))
        safe_case("casefold_unicode", make_zip([("BAK/\u00c4.txt", b"a"), ("bak/\u00e4.txt", b"b")]))
        safe_case("duplicate_exact", make_zip([("a.bin", b"1"), ("a.bin", b"2")]))
        safe_case("reserved_con", make_zip([("CON.txt", b"x")]))
        safe_case("reserved_aux", make_zip([("aux", b"x")]))
        safe_case("reserved_com1", make_zip([("COM1.log", b"x")]))
        safe_case("trailing_dot", make_zip([("file.txt.", b"x")]))
        safe_case("trailing_space", make_zip([("com1 ", b"x")]))
        safe_case("empty_name", make_zip([("", b"x")]))
        safe_case("dot_only", make_zip([(".", b"x")]))
        safe_case("nul_byte", make_zip([("bad\x00name.txt", b"x")]))
        safe_case("bad_char", make_zip([("a<b.txt", b"x")]))
        safe_case("component_too_long", make_zip([("\u4e2d" * 201, b"x")]))
        safe_case("path_too_long", make_zip([("/".join(["d" * 90] * 11), b"x")]))
        safe_case("dot_component_folded", make_zip([("a/./b.txt", b"x")]))
        safe_case("backslash_folded", make_zip([("a\\b.txt", b"x")]))
        safe_case("dir_entry", make_zip([("only_dir/", b"")]))
        safe_case("cp437_name", craft_cp437_zip())
        safe_case("empty_archive", make_zip([]))
        oracle["safe_members"] = safe_cases

        cp437_bytes = craft_cp437_zip()
        cp437_bundle = zipfile.ZipFile(BytesIO(cp437_bytes))

        zip64_buffer = BytesIO()
        with zipfile.ZipFile(zip64_buffer, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=True) as z64:
            with z64.open("zip64/member.bin", "w", force_zip64=True) as sink:
                sink.write(bytes(range(256)) * 8)
            z64.writestr("zip64/small.txt", "z64")
        zip64_bytes = zip64_buffer.getvalue()
        zip64_bundle = zipfile.ZipFile(BytesIO(zip64_bytes))
        oracle["zip_reader"] = [
            {
                "id": "cp437_decode",
                "zip_b64": b64(cp437_bytes),
                "expect": {
                    "names": [i.filename for i in cp437_bundle.infolist()],
                    "sizes": [i.file_size for i in cp437_bundle.infolist()],
                    "crcs": [i.CRC for i in cp437_bundle.infolist()],
                },
            },
            {
                "id": "zip64_extra_fields",
                "zip_b64": b64(zip64_bytes),
                "expect": {
                    "names": [i.filename for i in zip64_bundle.infolist()],
                    "sizes": [i.file_size for i in zip64_bundle.infolist()],
                    "crcs": [i.CRC for i in zip64_bundle.infolist()],
                },
            },
        ]

        writer_members = [
            ("manifest.json", b'{"a": 1}\n'),
            ("\u5730\u8d28/data.bin", bytes(range(128)) * 4),
            ("docs/readme.md", b"# pkg\n" * 3),
        ]
        meta_bundle = zipfile.ZipFile(BytesIO(make_zip(writer_members)))
        oracle["zip_writer"] = {
            "members": [
                {"name": name, "content_b64": b64(payload),
                 "crc32": next(i.CRC for i in meta_bundle.infolist()
                               if i.filename == name),
                 "size": next(i.file_size for i in meta_bundle.infolist()
                              if i.filename == name),
                 "flag_bits": next(i.flag_bits for i in meta_bundle.infolist()
                                   if i.filename == name),
                 "date_time": list(next(i.date_time for i in meta_bundle.infolist()
                                        if i.filename == name))}
                for name, payload in writer_members
            ]
        }

        extract_cases = []

        def extract_case(case_id, zip_bytes):
            dest = root / ("extract_" + case_id)
            dest.mkdir(parents=True, exist_ok=True)
            bundle = zipfile.ZipFile(BytesIO(zip_bytes))
            try:
                written = extract_archive(bundle, dest, what="package")
                rels = sorted(str(p.relative_to(dest)) for p in written)
                digests = {}
                for path in dest.rglob("*"):
                    if path.is_file():
                        digests[str(path.relative_to(dest))] = sha256_bytes(
                            path.read_bytes())
                extract_cases.append({
                    "id": case_id, "zip_b64": b64(zip_bytes),
                    "expect": {"ok": True, "written": rels, "digests": digests},
                })
            except UnsafePathError as exc:
                residue = sorted(str(p.relative_to(dest)) for p in dest.rglob("*"))
                extract_cases.append({
                    "id": case_id, "zip_b64": b64(zip_bytes),
                    "expect": {"ok": False, "message": str(exc), "residue": residue},
                })

        extract_case("ok_clean", make_zip(clean_members))
        extract_case("ok_zip64", zip64_bytes)
        extract_case("ok_dir_entries", make_zip([
            ("docs/", b""),
            ("docs/readme.txt", b"hi\n"),
            ("data.bin", b"\x01\x02"),
        ]))
        extract_case("ok_streaming", make_zip([
            ("big_stored.bin", b"\xab\xcd" * 600001),
            ("big_deflated.bin", bytes(2 * 1024 * 1024 + 511)),
        ], zipfile.ZIP_STORED))
        extract_case("reject_traversal", make_zip([("../evil.txt", b"x")]))
        extract_case("reject_symlink", make_zip([
            ("safe.txt", b"ok"), symlink_member("evil"),
        ]))
        extract_case("reject_collision", make_zip([
            ("A/x.txt", b"1"), ("a/x.txt", b"2"),
        ]))
        extract_case("reject_after_clean_prefix", make_zip([
            ("safe.txt", b"ok"), ("../late.txt", b"x"),
        ]))
        oracle["extract"] = extract_cases

        # ------------------------------------------------------------- atomic
        atomic_cases = []
        target = root / "atomic_target.txt"
        temp = root / ".atomic_target.txt.tmp123"
        temp.write_bytes(b"temp payload")
        target.unlink(missing_ok=True)
        os_replace_atomic(temp, target)
        atomic_cases.append({
            "id": "replace_ok",
            "expect": {"decision": "ok",
                       "temp_absent": not temp.exists(),
                       "target_digest": sha256_bytes(target.read_bytes())},
        })
        missing_temp = root / ".atomic_missing.tmp"
        try:
            os_replace_atomic(missing_temp, root / "atomic_out2.txt")
            atomic_cases.append({"id": "replace_missing_src",
                                 "expect": {"decision": "ok"}})
        except OSError:
            atomic_cases.append({"id": "replace_missing_src",
                                 "expect": {"decision": "error"}})

        out_path = root / "ao_out.dat"
        with atomic_output(out_path) as tmp:
            Path(tmp).write_bytes(b"atomic-bytes-\x00\x01")
            atomic_cases.append({
                "id": "atomic_output_pending",
                "expect": {"target_absent": not out_path.exists()},
            })
        atomic_cases[-1]["expect"]["target_digest"] = sha256_bytes(
            out_path.read_bytes())
        leftovers = [p.name for p in root.iterdir()
                     if p.name.startswith(".ao_out.dat.")]
        atomic_cases[-1]["expect"]["temp_cleaned"] = leftovers == []

        failed_target = root / "ao_failed.dat"
        try:
            with atomic_output(failed_target) as tmp:
                Path(tmp).write_bytes(b"partial")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        failed_leftovers = [p.name for p in root.iterdir()
                            if p.name.startswith(".ao_failed.dat.")]
        atomic_cases.append({
            "id": "atomic_output_rollback",
            "expect": {"target_absent": not failed_target.exists(),
                       "temp_cleaned": failed_leftovers == []},
        })
        oracle["atomic"] = atomic_cases

    # ---------------------------------------------------------- verify_zip
    builder_mod.datetime = _FixedDateTime
    try:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)

            def project_tree(base: Path) -> Path:
                proj_dir = base / "proj"
                (proj_dir / "proj.artifacts/raw").mkdir(parents=True)
                (proj_dir / "proj.artifacts/metadata").mkdir(parents=True)
                (proj_dir / "proj.artifacts/outputs").mkdir(parents=True)
                (proj_dir / "proj.artifacts/working").mkdir(parents=True)
                (proj_dir / "proj.paleo.json").write_text(
                    json.dumps({
                        "name": "proj",
                        "resources": [
                            {"id": "r1", "name": "ext table",
                             "path": "table.csv", "external": True},
                        ],
                    }, ensure_ascii=False), encoding="utf-8")
                (proj_dir / "proj.artifacts/raw/a.bin").write_bytes(
                    b"\x01\x02\x03raw")
                (proj_dir / "proj.artifacts/metadata/catalog.json").write_text(
                    '{"assets": []}', encoding="utf-8")
                (proj_dir / "proj.artifacts/outputs/out.dat").write_bytes(b"OUT")
                (proj_dir / "proj.artifacts/working/scratch.tmp").write_bytes(
                    b"scratch")
                return proj_dir

            proj_dir = project_tree(root)
            out_dir = root / "out"
            builder = PackageBuilder(
                proj_dir / "proj.paleo.json",
                options=PackageOptions(external_policy=ExternalPolicy.KEEP),
            )
            result = builder.build(out_dir)
            zip_path = zip_package_dir(result.package_dir,
                                       root / "built.paleopkg.zip")
            good_zip = zip_path.read_bytes()

            def read_members(zip_bytes: bytes):
                bundle = zipfile.ZipFile(BytesIO(zip_bytes))
                return [(i.filename, bundle.read(i))
                        for i in bundle.infolist()]

            def report_of(case_id: str, zip_bytes: bytes,
                          deep: bool = True) -> dict:
                container = root / (case_id + ".zip")
                container.write_bytes(zip_bytes)
                report = verify_zip_container(container, deep=deep).to_dict()
                return {"id": case_id, "deep": deep,
                        "zip_b64": b64(zip_bytes),
                        "expect": deep_sub(report, root)}

            verify_cases = [report_of("ok_full", good_zip),
                            report_of("ok_shallow", good_zip, deep=False)]

            def mutate_manifest(zip_bytes: bytes, transform) -> bytes:
                manifest = json.loads(zipfile.ZipFile(BytesIO(zip_bytes))
                                      .read("manifest.json").decode("utf-8"))
                transform(manifest)
                entries = read_members(zip_bytes)
                rewritten = []
                for name, payload in entries:
                    if name == "manifest.json":
                        payload = json.dumps(
                            manifest, ensure_ascii=False,
                            indent=1).encode("utf-8")
                    rewritten.append((name, payload))
                return make_zip(rewritten)

            verify_cases.append(report_of(
                "wrong_kind",
                mutate_manifest(good_zip, lambda m: m.update(kind="other"))))
            verify_cases.append(report_of(
                "unsupported_schema",
                mutate_manifest(good_zip, lambda m: m.update(schema_version=3))))
            verify_cases.append(report_of(
                "missing_project",
                mutate_manifest(good_zip,
                                lambda m: m["project"].update(file="absent.json"))))
            verify_cases.append(report_of(
                "missing_entry",
                mutate_manifest(good_zip, lambda m: m["entries"].pop(0))))

            extra_entries = read_members(good_zip) + [("extra.txt", b"surprise")]
            verify_cases.append(report_of("unknown_extra", make_zip(extra_entries)))
            known_entries = read_members(good_zip) + [
                ("delivery-report.json", b'{"ok": true}'),
                ("delivery-report.md", b"# report"),
            ]
            verify_cases.append(report_of("known_extra_files",
                                          make_zip(known_entries)))
            verify_cases.append(report_of(
                "corrupt_manifest",
                make_zip([("manifest.json", b"{not json"),
                          ("proj.paleo.json", b"{}")])))
            verify_cases.append(report_of(
                "no_manifest",
                make_zip([("proj.paleo.json", b"{}")])))
            verify_cases.append(report_of(
                "unsafe_entry",
                make_zip([("manifest.json", hand_manifest(
                    [entry("../escape.bin", "x" * 64, 1)])),
                    ("p.paleo.json", b"{}")])))
            verify_cases.append(report_of(
                "symlink_member",
                make_zip([symlink_member("proj.paleo.json")])))
            verify_cases.append(report_of(
                "entry_is_directory",
                make_zip([
                    ("manifest.json", hand_manifest(
                        [entry("stuff", "x" * 64, 0)])),
                    ("p.paleo.json", b"{}"),
                    ("stuff/", b"")])))
            verify_cases.append(report_of(
                "manifest_is_directory",
                make_zip([
                    ("manifest.json/", b""),
                    ("proj.paleo.json", b"{}")])))

            base_entries = read_members(good_zip)

            def rewrite_entry(entries, name, payload):
                return [(n, payload if n == name else p) for n, p in entries]

            verify_cases.append(report_of(
                "size_mismatch",
                make_zip(rewrite_entry(base_entries, "proj.artifacts/raw/a.bin",
                                       b"\x01\x02\x03raw!"))))
            verify_cases.append(report_of(
                "checksum_mismatch",
                make_zip(rewrite_entry(base_entries, "proj.artifacts/raw/a.bin",
                                       b"\x01\x02\x03RAw"))))
            verify_cases.append(report_of(
                "corrupt_project",
                make_zip(rewrite_entry(base_entries, "proj.paleo.json",
                                       b"{bad"))))
            verify_cases.append(report_of(
                "corrupt_catalog",
                make_zip(rewrite_entry(base_entries,
                                       "proj.artifacts/metadata/catalog.json",
                                       b"no-json-here"))))
            verify_cases.append(report_of(
                "bad_zip", b"PK\x03\x04 not really a zip"))
            oracle["verify_zip"] = verify_cases

        # ----------------------------------------------------------- verify_dir
        verify_dir_cases = []
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)

            def dump_tree(case_id: str, ops, deep: bool = True) -> dict:
                tree_root = root / case_id
                tree_root.mkdir(parents=True)
                for op in ops:
                    kind = op[0]
                    if kind == "mkdir":
                        (tree_root / op[1]).mkdir(parents=True, exist_ok=True)
                    elif kind == "file":
                        path = tree_root / op[1]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(op[2])
                    elif kind == "symlink":
                        path = tree_root / op[1]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.symlink_to(op[2])
                report = verify_package(tree_root, deep=deep).to_dict()
                encoded = []
                for op in ops:
                    if op[0] == "file":
                        encoded.append({"op": "file", "path": op[1],
                                        "content_b64": b64(op[2])})
                    else:
                        encoded.append({"op": op[0], "path": op[1],
                                        "target": op[2]})
                return {"id": case_id, "deep": deep, "tree": encoded,
                        "expect": deep_sub(report, root)}

            base_entries = [
                entry("p.paleo.json", sha256_bytes(b"{}\n"), 3, "project"),
                entry("data/payload.bin", sha256_bytes(b"PAYLOAD"), 7),
            ]
            base_ops = [
                ("file", "p.paleo.json", b"{}\n"),
                ("file", "data/payload.bin", b"PAYLOAD"),
                ("file", "p.artifacts/metadata/catalog.json", b"[]"),
            ]
            verify_dir_cases.append(dump_tree("ok_dir", [
                ("file", "manifest.json",
                 hand_manifest(base_entries, total=10)),
                *base_ops,
            ]))
            verify_dir_cases.append(dump_tree("missing_manifest", [
                ("file", "p.paleo.json", b"{}\n"),
            ]))
            absent = root / "absent_package"
            report = verify_package(absent, deep=True).to_dict()
            verify_dir_cases.append({"id": "absent_package", "deep": True,
                                     "tree": [],
                                     "expect": deep_sub(report, root)})
            verify_dir_cases.append(dump_tree("corrupt_manifest", [
                ("file", "manifest.json", b"{oops"),
            ]))
            verify_dir_cases.append(dump_tree("unsafe_manifest_entry", [
                ("file", "manifest.json", hand_manifest(
                    [entry("../out.bin", "x" * 64, 1)])),
                ("file", "p.paleo.json", b"{}\n"),
            ]))
            verify_dir_cases.append(dump_tree("symlink_entry", [
                ("file", "manifest.json", hand_manifest(
                    [entry("p.paleo.json", sha256_bytes(b"{}\n"), 3,
                           "project")], total=3)),
                ("symlink", "p.paleo.json", "/etc/hostname"),
            ]))
            verify_dir_cases.append(dump_tree("symlink_extra", [
                ("file", "manifest.json", hand_manifest(base_entries, total=10)),
                *base_ops,
                ("symlink", "sneaky.bin", "/etc/hostname"),
            ]))
            verify_dir_cases.append(dump_tree("missing_entry", [
                ("file", "manifest.json", hand_manifest(
                    [base_entries[0],
                     entry("data/absent.bin", sha256_bytes(b"x"), 1)], total=4)),
                ("file", "p.paleo.json", b"{}\n"),
            ]))
            verify_dir_cases.append(dump_tree("size_mismatch", [
                ("file", "manifest.json", hand_manifest(
                    [base_entries[0],
                     entry("data/payload.bin", sha256_bytes(b"PAYLOAD!"), 8)],
                    total=11)),
                ("file", "p.paleo.json", b"{}\n"),
                ("file", "data/payload.bin", b"PAYLOAD!"),
            ]))
            verify_dir_cases.append(dump_tree("checksum_mismatch", [
                ("file", "manifest.json", hand_manifest(
                    [base_entries[0],
                     entry("data/payload.bin", sha256_bytes(b"OTHER!"), 7)],
                    total=10)),
                ("file", "p.paleo.json", b"{}\n"),
                ("file", "data/payload.bin", b"PAYLOAD"),
            ]))
            verify_dir_cases.append(dump_tree("unknown_file", [
                ("file", "manifest.json", hand_manifest(base_entries, total=10)),
                *base_ops,
                ("file", "data/payload.bin.", b"trailing"),
            ]))
            verify_dir_cases.append(dump_tree("total_size_mismatch", [
                ("file", "manifest.json", hand_manifest(base_entries, total=999)),
                *base_ops,
            ]))
            verify_dir_cases.append(dump_tree("corrupt_project", [
                ("file", "manifest.json", hand_manifest(
                    [entry("p.paleo.json", sha256_bytes(b"{bad"), 4,
                           "project")], total=4)),
                ("file", "p.paleo.json", b"{bad"),
            ]))
            verify_dir_cases.append(dump_tree("wrong_kind", [
                ("file", "manifest.json", hand_manifest(
                    base_entries, total=10, kind="not-a-package")),
                *base_ops,
            ]))
            verify_dir_cases.append(dump_tree("unsupported_schema", [
                ("file", "manifest.json", hand_manifest(
                    base_entries, total=10, schema_version=3)),
                *base_ops,
            ]))
            oracle["verify_dir"] = verify_dir_cases

        # --------------------------------------------------------- materialize
        materialize_cases = []
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            good_zip_bytes = make_zip([
                ("manifest.json", b"{}\n"),
                ("pkg.paleo.json", b"{}\n"),
                ("pkg.artifacts/raw/a.bin", b"A" * 300),
            ])

            def encode_ops(ops):
                out = []
                for op in ops:
                    if op[0] == "file":
                        out.append({"op": "file", "path": op[1],
                                    "content_b64": b64(op[2])})
                    elif op[0] == "mkdir":
                        out.append({"op": "mkdir", "path": op[1]})
                    else:
                        out.append({"op": op[0], "path": op[1],
                                    "target": op[2]})
                return out

            def materialize_case(case_id, source_name, spec) -> None:
                dest = root / ("dest_" + case_id)
                dest.mkdir(parents=True)
                source = root / source_name
                if "zip_b64" in spec:
                    source.write_bytes(base64.b64decode(spec["zip_b64"]))
                elif "tree" in spec:
                    build_tree(source, spec["tree"])
                # else: the source is intentionally absent (unrecognized)
                encoded_spec = dict(spec)
                if "tree" in spec:
                    encoded_spec["tree"] = encode_ops(spec["tree"])
                if "pre_dest" in spec:
                    encoded_spec["pre_dest"] = encode_ops(spec["pre_dest"])
                case = {"id": case_id, "source_name": source_name,
                        "spec": encoded_spec}
                for op in spec.get("pre_dest", ()):
                    op_path = dest / op[1]
                    if op[0] == "mkdir":
                        op_path.mkdir(parents=True, exist_ok=True)
                    elif op[0] == "file":
                        op_path.parent.mkdir(parents=True, exist_ok=True)
                        op_path.write_bytes(op[2])
                try:
                    target = materialize_package(source, dest)
                    rels = sorted(str(p.relative_to(target))
                                  for p in target.rglob("*") if p.is_file())
                    case["expect"] = {"ok": True, "target_name": target.name,
                                      "files": rels}
                except Exception as exc:  # noqa: BLE001 - decision frozen
                    case["expect"] = {
                        "ok": False,
                        "message": str(exc).replace(str(root), "{ROOT}"),
                    }
                    residue = sorted(str(p.relative_to(dest))
                                     for p in dest.rglob("*"))
                    case["expect"]["residue"] = residue
                materialize_cases.append(case)

            def build_tree(tree_root: Path, ops) -> None:
                import shutil as _shutil
                first = ops[0][1].split("/", 1)[0] if ops and "/" in ops[0][1] else None
                if first and (tree_root / first).exists():
                    _shutil.rmtree(tree_root / first)  # cases reuse proj/
                for op in ops:
                    if op[0] == "mkdir":
                        (tree_root / op[1]).mkdir(parents=True, exist_ok=True)
                    elif op[0] == "file":
                        path = tree_root / op[1]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(op[2])
                    elif op[0] == "symlink":
                        path = tree_root / op[1]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.symlink_to(op[2])

            materialize_case("zip_ok", "good.paleopkg.zip",
                             {"zip_b64": b64(good_zip_bytes)})
            materialize_case("zip_traversal", "evil.zip",
                             {"zip_b64": b64(make_zip([("../evil.txt", b"x")]))})
            materialize_case("zip_symlink", "link.zip",
                             {"zip_b64": b64(make_zip([symlink_member("link.bin")]))})
            materialize_case("existing_target", "good.paleopkg.zip",
                             {"zip_b64": b64(good_zip_bytes),
                              "pre_dest": [("file", "good", b"occupied")]})
            materialize_case("unrecognized", "plain.txt", {})
            materialize_case("dir_ok", "dirpkg",
                             {"tree": [("mkdir", "inner"),
                                       ("file", "manifest.json", b"{}"),
                                       ("file", "inner/data.bin", b"DATA")]})
            materialize_case("dir_symlink", "dirlink",
                             {"tree": [("file", "manifest.json", b"{}"),
                                       ("symlink", "escape.bin",
                                        "/etc/hostname")]})

            dest3 = root / "dest_open"
            dest3.mkdir()
            pkg_dir, report = open_package(root / "good.paleopkg.zip",
                                           dest3, deep=True)
            materialize_cases.append({
                "id": "open_package", "source_name": "good.paleopkg.zip",
                "spec": {"zip_b64": b64(good_zip_bytes)},
                "expect": {"ok": True, "target_name": pkg_dir.name,
                           "report_ok": report.ok,
                           "checked_entries": report.checked_entries},
            })

            # open_package on a package whose verify FAILS: extraction stays
            # (documented), the report says exactly why it is not openable.
            tampered = make_zip([
                ("manifest.json", hand_manifest(
                    [entry("payload.bin", sha256_bytes(b"ORIGINAL"), 8)],
                    total=8)),
                ("payload.bin", b"TAMPERED"),
            ])
            (root / "tampered.paleopkg.zip").write_bytes(tampered)
            dest4 = root / "dest_open_fail"
            dest4.mkdir()
            pkg_dir2, report2 = open_package(root / "tampered.paleopkg.zip",
                                             dest4, deep=True)
            materialize_cases.append({
                "id": "open_fail_closed", "source_name": "tampered.paleopkg.zip",
                "spec": {"zip_b64": b64(tampered)},
                "expect": {"ok": True, "target_name": pkg_dir2.name,
                           "report_ok": report2.ok,
                           "issue_codes": [i.code for i in report2.errors()],
                           "checked_entries": report2.checked_entries},
            })
            oracle["materialize"] = materialize_cases

        # -------------------------------------------------------- build_package
        build_cases = []
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)

            class StubAsset:
                def __init__(self, asset_id, name, type_="table"):
                    self.id = asset_id
                    self.name = name
                    self.type = type_

            class StubVersion:
                def __init__(self, version_id, path, stage=DataStage.RAW,
                             managed=True, size_bytes=None, format_="csv"):
                    self.id = version_id
                    self.path = path
                    self.stage = stage
                    self.managed = managed
                    self.size_bytes = size_bytes
                    self.format = format_
                    self.metadata = {}

            class StubRun:
                def __init__(self, run_id, operation, status):
                    self.id = run_id
                    self.operation = operation
                    self.status = status

            class StubCatalog:
                """Narrow stand-in for the live catalog service: exactly the
                surface PackageBuilder consumes."""

                def __init__(self, spec, root):
                    self._assets = [StubAsset(a["id"], a["name"],
                                              a.get("type", "table"))
                                    for a in spec["assets"]]
                    versions_by_asset = {}
                    for v in spec["versions"]:
                        versions_by_asset.setdefault(v["asset_id"], []).append(
                            StubVersion(
                                v["id"], v["path"],
                                stage=DataStage(v["stage"]),
                                managed=v["managed"],
                                size_bytes=v.get("size_bytes"),
                                format_=v.get("format", "csv")))
                    self._versions = versions_by_asset
                    self._payloads = {k: root / rel
                                      for k, rel in spec["payloads"].items()}
                    self._runs = [StubRun(r["id"], r["operation"],
                                          r["status"])
                                  for r in spec.get("runs", [])]
                    self.exported = 0

                def list_assets(self):
                    return list(self._assets)

                def list_versions(self, asset_id):
                    return list(self._versions.get(asset_id, ()))

                def resolve_path(self, version):
                    return Path(self._payloads[version.id])

                def export_manifest(self):
                    self.exported += 1

                def list_runs(self):
                    return list(self._runs)

            def encode_ops(ops):
                out = []
                for op in ops:
                    if op[0] == "file":
                        out.append({"op": "file", "path": op[1],
                                    "content_b64": b64(op[2])})
                    elif op[0] == "mkdir":
                        out.append({"op": "mkdir", "path": op[1]})
                    else:
                        out.append({"op": op[0], "path": op[1],
                                    "target": op[2]})
                return out

            def build_tree(tree_root: Path, ops) -> None:
                import shutil as _shutil
                first = ops[0][1].split("/", 1)[0] if ops and "/" in ops[0][1] else None
                if first and (tree_root / first).exists():
                    _shutil.rmtree(tree_root / first)  # cases reuse proj/
                for op in ops:
                    if op[0] == "mkdir":
                        (tree_root / op[1]).mkdir(parents=True, exist_ok=True)
                    elif op[0] == "file":
                        path = tree_root / op[1]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(op[2])
                    elif op[0] == "symlink":
                        path = tree_root / op[1]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.symlink_to(op[2])

            def options_dict(options: PackageOptions) -> dict:
                return {
                    "external_policy": options.external_policy.value,
                    "include_outputs_only": options.include_outputs_only,
                    "include_formats": (list(options.include_formats)
                                        if options.include_formats else None),
                    "include_provenance": options.include_provenance,
                }

            def record_build(case_id, project_file, opts, catalog_root,
                             catalog_spec=None, tree=None) -> None:
                out_dir = root / ("out_" + case_id)
                catalog = (StubCatalog(catalog_spec, catalog_root)
                           if catalog_spec is not None else None)
                builder = PackageBuilder(project_file, catalog=catalog,
                                         options=opts)
                plan = builder.plan()
                result = builder.build(out_dir)
                manifest_text = (result.package_dir / "manifest.json").read_text(
                    encoding="utf-8")
                verify = verify_package(result.package_dir, deep=True)
                files = sorted(
                    str(p.relative_to(result.package_dir))
                    for p in result.package_dir.rglob("*") if p.is_file())
                build_cases.append({
                    "id": case_id,
                    "flow": "build",
                    "options": options_dict(opts),
                    "catalog": catalog_spec,
                    "tree": encode_ops(tree) if tree else None,
                    "expect": {
                        "plan_summary": plan.summary(),
                        "manifest_json": json.loads(manifest_text),
                        "manifest_text": manifest_text,
                        "files": files,
                        "verify_ok": verify.ok,
                        "verify_issues": [i.as_dict() for i in verify.issues],
                        "package_dir_name": result.package_dir.name,
                    },
                })

            def catalog_spec_standard():
                return {
                    "assets": [{"id": "a1", "name": "table", "type": "table"}],
                    "versions": [
                        {"id": "v1", "asset_id": "a1", "path": "shared_table.csv",
                         "stage": "raw", "managed": False, "size_bytes": 4},
                        {"id": "v2", "asset_id": "a1", "path": "out_table.csv",
                         "stage": "output", "managed": True, "size_bytes": 4,
                         "format": "csv"},
                    ],
                    "payloads": {"v1": "shared_table.csv",
                                 "v2": "out_table.csv"},
                    "runs": [{"id": "run1", "operation": "export",
                              "status": "done"}],
                }

            def tree_standard():
                return [
                    ("file", "proj/proj.paleo.json",
                     json.dumps({"name": "proj", "resources": []},
                                ensure_ascii=False).encode("utf-8")),
                    ("mkdir", "proj/proj.artifacts/raw"),
                    ("file", "proj/proj.artifacts/raw/a.bin", b"\x01\x02\x03raw"),
                    ("mkdir", "proj/proj.artifacts/outputs"),
                    ("file", "proj/proj.artifacts/outputs/result.csv", b"x,y\n"),
                    ("mkdir", "proj/proj.artifacts/metadata"),
                    ("file", "proj/proj.artifacts/metadata/catalog.json",
                     b'{"assets": []}'),
                    ("file", "proj/proj.artifacts/metadata/catalog.sqlite",
                     b"sqlite"),
                    ("mkdir", "proj/proj.artifacts/working"),
                    ("file", "proj/proj.artifacts/working/scratch.bin",
                     b"scratch"),
                    ("file", "shared_table.csv", b"k,v\n"),
                    ("file", "out_table.csv", b"out\n"),
                ]

            standard_opts = [
                ("externals_keep", ExternalPolicy.KEEP, PackageOptions()),
                ("externals_vendor", ExternalPolicy.VENDOR, PackageOptions()),
                ("externals_exclude", ExternalPolicy.EXCLUDE, PackageOptions()),
                ("outputs_only", ExternalPolicy.KEEP,
                 PackageOptions(include_outputs_only=True)),
                ("formats_filter", ExternalPolicy.KEEP,
                 PackageOptions(include_formats=["csv"])),
                ("no_provenance", ExternalPolicy.KEEP,
                 PackageOptions(include_provenance=False)),
            ]
            for case_id, policy, opts in standard_opts:
                tree = tree_standard()
                build_tree(root, tree)
                record_build(case_id, root / "proj/proj.paleo.json", opts,
                             root, catalog_spec_standard(), tree)

            # catalog-less: project resources fallback
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({
                     "name": "proj",
                     "resources": [
                         {"id": "r1", "name": "ext table",
                          "path": "table.csv", "external": True},
                         {"id": "r2", "name": "managed set",
                          "path": "missing_managed.bin", "external": False},
                     ],
                 }, ensure_ascii=False).encode("utf-8")),
                ("file", "proj/table.csv", b"a,b\n1,2\n"),
            ]
            build_tree(root, tree)
            record_build("catalogless", root / "proj/proj.paleo.json",
                         PackageOptions(), root, tree=tree)

            # missing managed payload via catalog
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({"name": "proj", "resources": []},
                            ensure_ascii=False).encode("utf-8")),
                ("mkdir", "proj/proj.artifacts"),
            ]
            build_tree(root, tree)
            missing_spec = {
                "assets": [{"id": "a1", "name": "table", "type": "table"}],
                "versions": [{"id": "v1", "asset_id": "a1", "path": "gone.bin",
                              "stage": "raw", "managed": True}],
                "payloads": {"v1": "proj/gone.bin"},
                "runs": [{"id": "run1", "operation": "export",
                          "status": "done"}],
            }
            record_build("missing_payload", root / "proj/proj.paleo.json",
                         PackageOptions(), root, missing_spec, tree)

            # stale size still ships, flagged
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({"name": "proj", "resources": []},
                            ensure_ascii=False).encode("utf-8")),
                ("mkdir", "proj/proj.artifacts/raw"),
                ("file", "proj/proj.artifacts/raw/stale.bin", b"12345678"),
            ]
            build_tree(root, tree)
            stale_spec = {
                "assets": [{"id": "a1", "name": "table", "type": "table"}],
                "versions": [{"id": "v1", "asset_id": "a1",
                              "path": "proj.artifacts/raw/stale.bin",
                              "stage": "raw", "managed": True,
                              "size_bytes": 3, "format": "bin"}],
                "payloads": {"v1": "proj/proj.artifacts/raw/stale.bin"},
                "runs": [],
            }
            record_build("stale_size", root / "proj/proj.paleo.json",
                         PackageOptions(), root, stale_spec, tree)

            # publish conflict: building twice must fail loudly, no residue
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({"name": "proj", "resources": []},
                            ensure_ascii=False).encode("utf-8")),
                ("mkdir", "proj/proj.artifacts/raw"),
                ("file", "proj/proj.artifacts/raw/a.bin", b"data"),
            ]
            build_tree(root, tree)
            out_dir = root / "out_conflict"
            builder = PackageBuilder(root / "proj/proj.paleo.json",
                                     options=PackageOptions())
            result = builder.build(out_dir)
            conflict_expect = {}
            try:
                builder.build(out_dir)
                conflict_expect["ok"] = True
            except Exception as exc:  # noqa: BLE001
                conflict_expect["ok"] = False
                conflict_expect["message"] = sub_root(str(exc), root)
            conflict_expect["dir_listing"] = sorted(
                p.name for p in out_dir.iterdir())
            build_cases.append({
                "id": "publish_conflict", "flow": "build_twice",
                "options": options_dict(PackageOptions()), "catalog": None,
                "tree": encode_ops(tree),
                "expect": conflict_expect,
            })

            # symlinked artifact aborts the build, staging cleaned
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({"name": "proj", "resources": []},
                            ensure_ascii=False).encode("utf-8")),
                ("mkdir", "proj/proj.artifacts/raw"),
                ("file", "proj/proj.artifacts/raw/a.bin", b"data"),
                ("symlink", "proj/proj.artifacts/raw/link.bin",
                 "/etc/hostname"),
            ]
            build_tree(root, tree)
            fail_expect = {}
            try:
                PackageBuilder(root / "proj/proj.paleo.json",
                               options=PackageOptions()).build(
                    root / "out_symlink")
                fail_expect["ok"] = True
            except Exception as exc:  # noqa: BLE001
                fail_expect["ok"] = False
                fail_expect["message"] = sub_root(str(exc), root)
            out_dir_s = root / "out_symlink"
            fail_expect["residue"] = sorted(
                p.name for p in out_dir_s.iterdir()) if out_dir_s.exists() else []
            build_cases.append({
                "id": "symlink_artifact", "flow": "build_fail",
                "options": options_dict(PackageOptions()), "catalog": None,
                "tree": encode_ops(tree),
                "expect": fail_expect,
            })

            # zip container of a built package verifies clean (round trip)
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({"name": "proj", "resources": []},
                            ensure_ascii=False).encode("utf-8")),
                ("mkdir", "proj/proj.artifacts/raw"),
                ("file", "proj/proj.artifacts/raw/a.bin", b"\x01\x02\x03"),
            ]
            build_tree(root, tree)
            builder = PackageBuilder(root / "proj/proj.paleo.json",
                                     options=PackageOptions())
            result = builder.build(root / "out_zip")
            zip_path = zip_package_dir(result.package_dir,
                                       root / "proj.paleopkg.zip")
            bundle = zipfile.ZipFile(zip_path)
            build_cases.append({
                "id": "zip_round_trip", "flow": "build_zip",
                "options": options_dict(PackageOptions()), "catalog": None,
                "tree": encode_ops(tree),
                "expect": {
                    "zip_name": zip_path.name,
                    "members": sorted(i.filename for i in bundle.infolist()),
                    "crcs": {i.filename: i.CRC for i in bundle.infolist()},
                    "verify_ok": verify_zip_container(zip_path).ok,
                    "staging_removed": not (
                        root / "out_zip" / ".proj.staging").exists(),
                },
            })

            # zip_package_dir rejects a symlink inside the package dir
            tree = [
                ("file", "proj/proj.paleo.json",
                 json.dumps({"name": "proj", "resources": []},
                            ensure_ascii=False).encode("utf-8")),
                ("mkdir", "proj/proj.artifacts/raw"),
                ("file", "proj/proj.artifacts/raw/a.bin", b"\x01"),
            ]
            build_tree(root, tree)
            builder = PackageBuilder(root / "proj/proj.paleo.json",
                                     options=PackageOptions())
            result = builder.build(root / "out_zipsym")
            (result.package_dir / "proj.artifacts/raw/link.bin").symlink_to(
                "/etc/hostname")
            zipsym_expect = {}
            try:
                zip_package_dir(result.package_dir,
                                root / "proj-sym.paleopkg.zip")
                zipsym_expect["ok"] = True
            except Exception as exc:  # noqa: BLE001
                zipsym_expect["ok"] = False
                zipsym_expect["message"] = sub_root(str(exc), root)
            zipsym_expect["zip_absent"] = not (
                root / "proj-sym.paleopkg.zip").exists()
            zipsym_expect["tmp_absent"] = not (
                root / ".proj-sym.paleopkg.zip.tmp").exists()
            build_cases.append({
                "id": "zip_dir_symlink", "flow": "build_zip_symlink",
                "options": options_dict(PackageOptions()), "catalog": None,
                "tree": encode_ops(tree),
                "expect": zipsym_expect,
            })

            oracle["build_package"] = [
                {"id": case["id"],
                 "flow": case["flow"],
                 "options": case.get("options"),
                 "catalog": case.get("catalog"),
                 "tree": case.get("tree"),
                 "expect": deep_sub(case["expect"], root)}
                for case in build_cases
            ]

        # ------------------------------------------------------------ model core
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            model_cases = []

            def model_case(case_id: str, fmt: str, payload: bytes) -> None:
                path = root / f"{case_id}.{fmt}"
                path.write_bytes(payload)
                parse = parse_abaqus if fmt == "inp" else parse_flac3d
                facts = parse(path)
                model_cases.append({
                    "id": case_id, "format": fmt,
                    "content_b64": b64(payload),
                    "expect": {
                        "gridpoints": facts.gridpoints,
                        "zones": facts.zones,
                        "problems": list(facts.problems),
                    },
                })

            def model_case_text(case_id: str, fmt: str, text: str) -> None:
                model_case(case_id, fmt, text.encode("utf-8"))

            from paleo_workbench.viz.geomodel.exporters import (  # noqa: E402
                export_to_abaqus,
                export_to_flac3d,
            )
            writer_root = root / "writer"
            writer_root.mkdir(parents=True)
            f3_path = writer_root / "grid.f3grid"
            assert export_to_flac3d(str(f3_path), nx=2, ny=2, nz=2, dx=2.0,
                                    dy=3.0, dz=4.0)
            facts = parse_flac3d(f3_path)
            model_cases.append({
                "id": "writer_flac3d", "format": "f3grid",
                "content_b64": b64(f3_path.read_bytes()),
                "expect": {"gridpoints": facts.gridpoints,
                           "zones": facts.zones,
                           "problems": list(facts.problems)},
            })
            inp_path = writer_root / "grid.inp"
            assert export_to_abaqus(str(inp_path), nx=2, ny=2, nz=2, dx=1.5,
                                    dy=2.5, dz=0.5)
            facts = parse_abaqus(inp_path)
            model_cases.append({
                "id": "writer_abaqus", "format": "inp",
                "content_b64": b64(inp_path.read_bytes()),
                "expect": {"gridpoints": facts.gridpoints,
                           "zones": facts.zones,
                           "problems": list(facts.problems)},
            })

            model_case_text("flac3d_empty", "f3grid", "")
            model_case_text("flac3d_unrelated", "f3grid",
                            "hello world\nnothing here\n")
            model_case_text("flac3d_comments_only", "f3grid",
                            "* FLAC3D grid exported by PaleoWorkbench\n* more\n")
            model_case_text("flac3d_g_bad_len", "f3grid", "G 1 1.0 2.0\n")
            model_case_text("flac3d_g_bad_value", "f3grid", "G 1 1.0 x 3.0\n")
            model_case_text("flac3d_nan_coord", "f3grid", "G 1 1.0 nan 3.0\n")
            model_case_text("flac3d_inf_coord", "f3grid", "G 1 1.0 -inf 3.0\n")
            model_case_text("flac3d_z_keyword", "f3grid",
                            "Z HEX 1 1 2 3 4 5 6 7 8\n")
            model_case_text("flac3d_z_short", "f3grid",
                            "G 1 0 0 0\nG 2 1 0 0\nG 3 1 1 0\nG 4 0 1 0\n"
                            "G 5 0 0 1\nG 6 1 0 1\nG 7 1 1 1\nG 8 0 1 1\n"
                            "Z B8 1 1 2 3 4 5 6 7\n")
            model_case_text("flac3d_z_bad_ref", "f3grid",
                            "Z B8 1 1 2 x 4 5 6 7 8\n")
            model_case_text("flac3d_missing_refs", "f3grid",
                            "G 1 0 0 0\nG 2 1 0 0\nG 3 1 1 0\nG 4 0 1 0\n"
                            "G 5 0 0 1\nG 6 1 0 1\nG 7 1 1 1\nG 8 0 1 1\n"
                            "Z B8 1 1 2 3 4 5 6 7 9\n")
            model_case_text("flac3d_gap_ids", "f3grid", "G 1 0 0 0\nG 3 1 0 0\n")
            model_case_text("flac3d_underscore_float", "f3grid",
                            "G 1 1_0.0 2.0 3.0\n")
            model_case_text("flac3d_underscore_id", "f3grid",
                            "G 1_0 0.0 0.0 0.0\nG 1_1 1.0 0.0 0.0\n")
            model_case_text("flac3d_bad_underscore", "f3grid",
                            "G 1 1__0.0 2.0 3.0\n")
            model_case_text("abaqus_underscore", "inp",
                            "*NODE\n1, 0, 0, 0\n2, 1_0.5, 0, 0\n")
            model_case_text("flac3d_crlf", "f3grid",
                            "G 1 0.0 0.0 0.0\r\nG 2 1.0 0.0 0.0\r\n")
            model_case("flac3d_invalid_utf8", "f3grid",
                       b"G 1 0.0 0.0 0.0\nG 2 \xff\xfe 0.0 0.0\n")
            model_case_text("abaqus_empty", "inp", "")
            model_case_text("abaqus_headers", "inp",
                            "*HEADING\n** comment\n*PART, NAME=GEOMODEL\n"
                            "*END PART\n")
            model_case_text("abaqus_node_bad_count", "inp", "*NODE\n1, 1.0, 2.0\n")
            model_case_text("abaqus_node_bad_value", "inp",
                            "*NODE\n1, 1.0, x, 2.0\n")
            model_case_text("abaqus_nan", "inp", "*NODE\n1, 1.0, INF, 2.0\n")
            model_case_text("abaqus_elem_bad_count", "inp",
                            "*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n"
                            "*ELEMENT, TYPE=C3D8\n1, 1, 2\n")
            model_case_text("abaqus_elem_bad_value", "inp",
                            "*NODE\n1, 0, 0, 0\n"
                            "*ELEMENT, TYPE=C3D8\n1, 1, 2, 3, 4, 5, 6, 7, x\n")
            model_case_text("abaqus_end_resets", "inp",
                            "*NODE\n1, 0, 0, 0\n*END PART\n1, 2, 3\n")
            model_case_text("abaqus_data_outside_section", "inp", "1, 2, 3\n")
            model_case_text("abaqus_missing_refs", "inp",
                            "*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n"
                            "*ELEMENT, TYPE=C3D8\n1, 1, 2, 3, 4, 5, 6, 7, 9\n")
            model_case_text("abaqus_gap_ids", "inp",
                            "*NODE\n1, 0, 0, 0\n3, 1, 0, 0\n"
                            "*ELEMENT, TYPE=C3D8\n")
            oracle["model_parse"] = model_cases

            # ------------------------------------------------------- model adapter
            root2 = root / "adapter_work"
            # ---- model adapter: explicit inputs per case
            root2 = root / "adapter_work"
            root2.mkdir()
            adapter_cases = []
            flac = Flac3dAdapter()
            abaq = AbaqusAdapter()

            def capability_dict(adapter):
                cap = adapter.capability()
                return {
                    "read": cap.read,
                    "inspect": cap.inspect,
                    "import_data": cap.import_data,
                    "export": cap.export,
                    "roundtrip_verify": cap.roundtrip_verify,
                    "notes": cap.notes,
                }

            adapter_cases.append({
                "id": "capability_flac3d", "kind": "capability",
                "format_id": flac.format_id,
                "expect": {"capability": capability_dict(flac)},
            })
            adapter_cases.append({
                "id": "capability_abaqus", "kind": "capability",
                "format_id": abaq.format_id,
                "expect": {"capability": capability_dict(abaq)},
            })

            good = writer_root / "plan.f3grid"
            assert export_to_flac3d(str(good), nx=2, ny=2, nz=2)

            def case_ok(case_id, kind, value, prefix=False, **extra):
                case = {"id": case_id, "kind": kind, **extra,
                        "expect": {"ok": True, "value": value,
                                   "prefix": prefix}}
                adapter_cases.append(case)

            def case_err(case_id, kind, exc, prefix=False, **extra):
                adapter_cases.append({
                    "id": case_id, "kind": kind, **extra,
                    "expect": {"ok": False,
                               "error": ("format-not-supported"
                                         if isinstance(exc, FormatNotSupportedError)
                                         else type(exc).__name__),
                               "message": sub_root(str(exc), root),
                               "prefix": prefix},
                })

            P = "{ROOT}/writer/plan.f3grid"
            W = "{ROOT}/adapter_work"

            try:
                value = flac.plan_export(good, root2 / "out.f3grid",
                                         options={"nx": 2, "ny": 2, "nz": 2,
                                                  "dx": 2.0}).to_dict()
                case_ok("plan_export_ok", "plan_export", value,
                        format_id=flac.format_id,
                        target=W + "/out.f3grid",
                        options={"nx": 2, "ny": 2, "nz": 2, "dx": 2.0})
            except Exception as exc:  # noqa: BLE001
                case_err("plan_export_ok", "plan_export", exc,
                         format_id=flac.format_id,
                         target=W + "/out.f3grid",
                         options={"nx": 2, "ny": 2, "nz": 2, "dx": 2.0})
            try:
                flac.plan_export(good, root2 / "out.inp",
                                 options={"nx": 2, "ny": 2, "nz": 2})
                raise AssertionError("unreachable")
            except Exception as exc:  # noqa: BLE001
                case_err("plan_export_bad_suffix", "plan_export", exc,
                         format_id=flac.format_id,
                         target=W + "/out.inp",
                         options={"nx": 2, "ny": 2, "nz": 2})
            try:
                flac.plan_export(good, root2 / "out.f3grid",
                                 options={"nx": 2, "nz": 2})
                raise AssertionError("unreachable")
            except Exception as exc:  # noqa: BLE001
                case_err("plan_export_missing_dims", "plan_export", exc,
                         format_id=flac.format_id,
                         target=W + "/out.f3grid",
                         options={"nx": 2, "nz": 2})
            try:
                flac.plan_export(good, root2 / "out.f3grid",
                                 options={"nx": 0, "ny": 2, "nz": 2})
                raise AssertionError("unreachable")
            except Exception as exc:  # noqa: BLE001
                case_err("plan_export_zero_dim", "plan_export", exc,
                         format_id=flac.format_id,
                         target=W + "/out.f3grid",
                         options={"nx": 0, "ny": 2, "nz": 2})
            try:
                flac.plan_export(good, root2 / "out.f3grid",
                                 options={"nx": 200, "ny": 200, "nz": 201})
                raise AssertionError("unreachable")
            except Exception as exc:  # noqa: BLE001
                case_err("plan_export_too_big", "plan_export", exc,
                         format_id=flac.format_id,
                         target=W + "/out.f3grid",
                         options={"nx": 200, "ny": 200, "nz": 201})
            case_ok("plan_export_boundary_ok", "plan_export",
                    flac.plan_export(good, root2 / "out.f3grid",
                                     options={"nx": 200, "ny": 200,
                                              "nz": 200}).to_dict(),
                    format_id=flac.format_id, target=W + "/out.f3grid",
                    options={"nx": 200, "ny": 200, "nz": 200})
            case_ok("plan_export_dims_coercion", "plan_export",
                    abaq.plan_export(good, root2 / "out.inp",
                                     options={"nx": "3", "ny": 2.9,
                                              "nz": True}).to_dict(),
                    format_id=abaq.format_id, target=W + "/out.inp",
                    options={"nx": "3", "ny": 2.9, "nz": True})
            case_ok("plan_import_unsupported", "plan_import",
                    flac.plan_import(good, flac.inspect(good),
                                     managed=True).to_dict(),
                    format_id=flac.format_id, source=P, managed=True)
            try:
                flac.import_data(good, None, work_dir=root2, catalog=None)
                raise AssertionError("unreachable")
            except Exception as exc:  # noqa: BLE001
                case_err("import_unsupported", "import", exc,
                         format_id=flac.format_id)

            EXPORT_OPTS = {"nx": 2, "ny": 2, "nz": 2,
                           "dx": 3.0, "dy": 1.0, "dz": 2.0}

            def export_case():
                plan = flac.plan_export(good, root2 / "exported.f3grid",
                                        options=EXPORT_OPTS)
                target = flac.export_data(good, plan, work_dir=root2)
                payload = target.read_bytes()
                leftovers = [p.name for p in root2.iterdir()
                             if p.name.startswith(".exported.f3grid.")]
                facts = parse_flac3d(target)
                return {
                    "target_name": target.name,
                    "digest": sha256_bytes(payload),
                    "temp_cleaned": leftovers == [],
                    "facts": {"gridpoints": facts.gridpoints,
                              "zones": facts.zones,
                              "problems": list(facts.problems)},
                }
            case_ok("export_data_flac3d", "export", export_case(),
                    format_id=flac.format_id, target=W + "/exported.f3grid",
                    options=EXPORT_OPTS)

            def verify_case(case_id, file_name, file_content, options):
                path = root2 / file_name
                if file_content is not None:
                    path.write_bytes(file_content)
                plan = flac.plan_export(good, path, options=options)
                value = flac.verify_output(path, plan).summary()
                case_ok(case_id, "verify_output", value,
                        format_id=flac.format_id,
                        target=W + "/" + file_name,
                        options=options,
                        file_content=(b64(file_content)
                                      if file_content is not None else None))

            verify_case("verify_output_ok", "exported.f3grid", None,
                        EXPORT_OPTS)
            verify_case("verify_output_structural", "bad.f3grid",
                        b"G 1 0.0 0.0 0.0\nG 2 1.0 0.0 nan\n",
                        {"nx": 2, "ny": 2, "nz": 2})
            verify_case("verify_output_missing", "absent.f3grid", None,
                        {"nx": 1, "ny": 1, "nz": 1})
            verify_case("verify_output_empty", "empty.f3grid", b"",
                        {"nx": 1, "ny": 1, "nz": 1})

            case_ok("inspect_ok", "inspect", flac.inspect(good).summary(),
                    format_id=flac.format_id, source=P)
            garbage = root2 / "garbage.f3grid"
            garbage.write_text("nothing to see\n", encoding="utf-8")
            case_ok("inspect_garbage", "inspect",
                    flac.inspect(garbage).summary(),
                    format_id=flac.format_id,
                    source=W + "/garbage.f3grid",
                    file_content=b64(garbage.read_bytes()))
            # inspect() returns ok=false with an OSError-text error; the
            # strerror tail is platform-specific, so freeze the summary and
            # let the C++ side compare the stable Chinese prefix only.
            case_ok("inspect_missing_file", "inspect",
                    flac.inspect(root2 / "nope.f3grid").summary(),
                    prefix=True, format_id=flac.format_id,
                    source=W + "/nope.f3grid")

            from paleo_workbench.interchange.registry import (  # noqa: E402
                InterchangeRegistry,
            )
            registry = InterchangeRegistry()
            registry.register(flac)
            registry.register(abaq)
            case_ok("capability_matrix", "registry_matrix",
                    registry.capability_matrix())

            oracle["model_adapter_pre_files"] = {
                "writer/plan.f3grid": b64(good.read_bytes()),
            }
            oracle["model_adapter"] = [
                {"id": case["id"], "kind": case["kind"],
                 "format_id": case.get("format_id"),
                 "source": case.get("source"),
                 "target": case.get("target"),
                 "options": case.get("options"),
                 "managed": case.get("managed"),
                 "file_content": case.get("file_content"),
                 "prefix": case.get("prefix"),
                 "expect": deep_sub(case["expect"], root)}
                for case in adapter_cases
            ]
    finally:
        builder_mod.datetime = datetime

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8")
    print(f"frozen {FIXTURE}")
    for key, value in oracle.items():
        if key == "meta":
            continue
        print(f"  {key}: {len(value)}")


if __name__ == "__main__":
    main()
