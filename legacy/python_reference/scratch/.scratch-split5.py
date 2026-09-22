import io
p = 'libs/workflow_contracts/src/modules_data.inc'
src = io.open(p, encoding='utf-8', errors='surrogateescape').read()
lines = src.splitlines(keepends=True)
big = lines[2]
prefix = 'R"PWB_MODULES_JSON('
suffix = ')PWB_MODULES_JSON"'
inner = big[len(prefix):-len(suffix)]
body = inner[1:-1]
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
assert ','.join(chunks) == body
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
assert ','.join(packed) == body
out = [lines[0], lines[1], prefix + '[']
for i, part in enumerate(packed):
    out.append(part)
    if i != len(packed) - 1:
        out.append(',')
    out.append(suffix)
    if i != len(packed) - 1:
        out.append(prefix)
out.append(']' + suffix + '\n')
text = ''.join(out)
io.open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='').write(text)
# verify by re-reading and stripping ALL scaffolding pairs
back = io.open(p, encoding='utf-8', errors='surrogateescape').read()
payload = back.replace(prefix, '').replace(suffix, '').replace('\n', '').replace('\r', '')
assert payload == inner, 'reassembly mismatch'
print('OK byte-identical after round-trip: %d modules, %d lines, max %d chars'
      % (len(chunks), len(packed), max(len(x) for x in packed)))
