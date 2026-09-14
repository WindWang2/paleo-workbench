"""Package the three V12 parallel prompts into a single zip."""
from pathlib import Path
import zipfile

SRC = Path(r"C:\Users\wangj.KEVIN\projects\paleo-workbench\docs\development\parallel-prompts-v12")
OUT = SRC / "parallel-prompts-v12.zip"

FILES = [
    "README.md",
    "prompt-1-ingest-io.md",
    "prompt-2-geopipeline.md",
    "prompt-3-render-increment.md",
]

manifest = []
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for name in FILES:
        p = SRC / name
        if not p.exists():
            raise SystemExit(f"MISSING: {p}")
        zf.write(p, arcname=f"parallel-prompts-v12/{name}")
        manifest.append((name, p.stat().st_size))

print(f"wrote {OUT}")
print(f"size = {OUT.stat().st_size} bytes")
for name, size in manifest:
    print(f"  {name:38s} {size:>8d} bytes")

# verify round-trip
with zipfile.ZipFile(OUT) as zf:
    bad = zf.testzip()
    print("testzip:", "OK" if bad is None else f"BAD -> {bad}")
    print("entries:", zf.namelist())
