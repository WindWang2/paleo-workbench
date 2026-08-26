# ISSUE-022: Module Import Side-Effects & Filesystem Mutation in `build_catalog.py`

- **Severity**: Medium
- **Subproject**: `scripts` (`build_catalog.py`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/build_catalog.py#L5-L8,L71-L418`

---

## Defect Description & Root Cause Analysis

In the root script `build_catalog.py`, directory creation and over 300 icon catalog registration calls are executed at top-level module scope upon import:

```python
OUTDIR = str(Path(__file__).resolve().parent / "svg_output")
DESCDIR = os.path.join(OUTDIR, "descriptions")
os.makedirs(DESCDIR, exist_ok=True)
# ...
T = "岩石纹理"
add(T, "tex_sandstone_fine", "细砂岩", "Fine Sandstone", "附录F.1 表F.1", "TEX-F1-1H/C", "#E8D5B5", "细砂颗粒点状填充(2×2 tile)，沉积岩-砂岩类。")
# ...
```

Each invocation of `add()` performs `os.path.exists()` filesystem checks, mutates the global `catalog` list, and prints warnings to standard output for any missing SVG files.

Because this code runs unconditionally upon module import, merely importing `build_catalog` (e.g. from tests, linters, or documentation generators) involuntarily creates directories on disk and triggers file I/O side-effects. This design was so problematic that `tests/test_build_catalog.py:9` had to explicitly document:
`# Do not import build_catalog: the module writes catalog.json on import.`

---

## Impact Analysis

- **Unwanted Filesystem Mutation**: Importing the module creates `svg_output/descriptions/` and modifies disk state unexpectedly.
- **Test Inflexibility**: Unit testing tools and static analyzers cannot safely inspect helper functions in `build_catalog.py` without triggering side-effects.

---

## Reproduction Scenario & Execution Proof

### Command Execution Trace
```bash
# Ensure clean state:
rm -rf svg_output/descriptions/

# Import the module:
python -c "import build_catalog"

# Check filesystem:
test -d svg_output/descriptions && echo "Directory was created on import!"
# Output: Directory was created on import!
```

---

## Concrete Suggested Fix

Encapsulate catalog generation and filesystem I/O into a `main()` function guarded by `if __name__ == "__main__":`.

### Patch (`build_catalog.py`)
```python
def populate_catalog() -> list[dict]:
    catalog_list = []
    def add(cat, fname, zh, en, spec, code, color, usage):
        # build entry ...
        catalog_list.append(entry)
    # Execute registrations into catalog_list
    # ...
    return catalog_list

def main():
    os.makedirs(DESCDIR, exist_ok=True)
    catalog_data = populate_catalog()
    with open(os.path.join(OUTDIR, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(catalog_data, f, ensure_ascii=False, indent=2)
    for entry in catalog_data:
        write_desc(entry)

if __name__ == "__main__":
    main()
```
