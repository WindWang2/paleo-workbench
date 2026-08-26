# ISSUE-017: Unchecked Vector Row Access in C++ LAS Parser `accept_row`

- **Severity**: Medium
- **Subproject**: `well-log-engine` (`welllog_io` C++ SDK)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/well-log-engine/src/io/las.cpp#L270-L323`

---

## Defect Description & Root Cause Analysis

Inside `LasSourceAdapter::parse` in `well-log-engine/src/io/las.cpp`, the lambda `accept_row` processes tokenized ASCII rows into numerical curve data:

```cpp
const auto accept_row = [&](const std::vector<Token> &row) {
    std::vector<ParsedNumber> parsed;
    parsed.reserve(row.size());
    for (const auto &token : row) {
        parsed.push_back(parse_number(token.lexeme));
    }
    const auto depth = parsed[*depth_index];
    // ...
    std::size_t curve_index = 0;
    for (std::size_t i = 0; i < parsed.size(); ++i) {
        if (i == *depth_index) continue;
        curve_values[curve_index].push_back(parsed[i]);
        ++curve_index;
    }
};
```

While outer parsing loops perform coarse checks against `definitions.size()`, `accept_row` itself does not assert or verify that `row.size() == definitions.size()` or that `*depth_index < row.size()`.

If `accept_row` is called with truncated or corrupted row vectors (e.g. trailing lines, comment delimiters parsed as empty tokens, or malformed wrap-mode rows), `parsed[*depth_index]` executes an out-of-bounds `std::vector::operator[]` access, leading to undefined memory reads, garbage depth indexing, or segmentation faults.

---

## Impact Analysis

- **Memory Safety / Stability**: Truncated lines in malformed LAS 2.0 files cause buffer over-reads or fatal crashes during fast native parsing.
- **Data Integrity**: Under undefined reads, arbitrary memory values could be interpreted as valid depth points.

---

## Reproduction Scenario & Execution Proof

### Code Trace
1. Construct a LAS file where a curve data line is truncated with fewer tokens than the curve definition header count (e.g., 5 curves defined, but line has only 1 token).
2. Pass the file to `LasSourceAdapter::parse()`.
3. `accept_row` executes with `row.size() == 1` while `*depth_index == 2`.
4. `parsed[2]` causes an out-of-bounds vector read.

---

## Concrete Suggested Fix

Add bounds validation at the entry of `accept_row`:

### Patch (`well-log-engine/src/io/las.cpp`)
```cpp
const auto accept_row = [&](const std::vector<Token> &row) {
    if (row.size() != definitions.size() || *depth_index >= row.size()) {
        return;
    }
    std::vector<ParsedNumber> parsed;
    parsed.reserve(row.size());
    for (const auto &token : row) {
        parsed.push_back(parse_number(token.lexeme));
    }
    // ...
```
