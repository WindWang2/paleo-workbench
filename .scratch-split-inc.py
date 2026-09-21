import io, json
src = io.open('.scratch-modules-orig.inc', encoding='utf-8', errors='surrogateescape').read()
lines = src.splitlines(keepends=True)
big = lines[2]
assert big.startswith('R"PWB_MODULES_JSON(')
assert big.rstrip().endswith(')PWB_MODULES_JSON"')
inner = big[len('R"PWB_MODULES_JSON('):-len(')PWB_MODULES_JSON"')]
obj, idx = json.JSONDecoder().raw_decode(inner)
assert inner[idx:].strip() == ')'
modules = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
# Rebuild a single JSON array string, then split it between top-level
# elements at '},{' boundaries into <8k chunks.
array_text = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
assert array_text.startswith('[') and array_text.endswith(']')
body = array_text[1:-1]
# split top-level objects on ',{' at depth 0
chunks, depth, cur = [], 0, []
for ch in body:
    cur.append(ch)
    if ch in '[{':
        depth += 1
    elif ch in ']}':
        depth -= 1
    elif ch == ',' and depth == 0:
        cur.pop()
        chunks.append(''.join(cur))
        cur = []
if ''.join(cur).strip():
    chunks.append(''.join(cur))
# pack chunks into lines under 8000 chars, joining with the object separator
MAX = 7000
packed, buf = [], ''
for c in chunks:
    add = c if not buf else ',' + c
    if len(buf) + len(add) > MAX and buf:
        packed.append(buf)
        buf = c
    else:
        buf += add
if buf:
    packed.append(buf)
out = [lines[0], lines[1], 'R"PWB_MODULES_JSON(']
out.append('[')
for i, part in enumerate(packed):
    out.append(part)
    if i != len(packed) - 1:
        out.append(',')
    out.append(']') if False else None
    out.append(')PWB_MODULES_JSON"')
    out.append('R"PWB_MODULES_JSON(')
out.append(']')
out.append(')PWB_MODULES_JSON"')
text = ''.join(out)
# verify: strip the literal scaffolding and re-parse
start = text.index('R"PWB_MODULES_JSON(') + len('R"PWB_MODULES_JSON(')
end = text.index(')PWB_MODULES_JSON"')
rebuilt = text[start:end]
rebuilt = rebuilt.replace(')PWB_MODULES_JSON"R"PWB_MODULES_JSON(', '')
assert json.loads(rebuilt) == obj, 'reassembly mismatch'
io.open('libs/workflow_contracts/src/modules_data.inc', 'w', encoding='utf-8', errors='surrogateescape', newline='').write(text)
print('OK: %d modules in %d packed lines (max %d chars)' % (len(obj), len(packed), max(len(p) for p in packed)))
