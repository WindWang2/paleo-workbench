import io, json
src = io.open('.scratch-modules-orig.inc', encoding='utf-8', errors='surrogateescape').read()
lines = src.splitlines(keepends=True)
big = lines[2]
prefix = 'R"PWB_MODULES_JSON('
suffix = ')PWB_MODULES_JSON"'
inner = big[len(prefix):-len(suffix)]
obj, idx = json.JSONDecoder().raw_decode(inner)
array_text = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
body = array_text[1:-1]
# top-level objects
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
# pack
MAX = 7000
packed, buf = [], ''
for c in chunks:
    add = c if not buf else ',' + c
    if len(buf) + len(add) > MAX and buf:
        packed.append(buf); buf = c
    else:
        buf += add
if buf:
    packed.append(buf)
out = [lines[0], lines[1]]
out.append(prefix + '[')
for i, part in enumerate(packed):
    out.append(part)
    if i != len(packed) - 1:
        out.append(',')
    out.append(suffix)
    if i != len(packed) - 1:
        out.append(prefix)
out.append(']' + suffix + '\n')
text = ''.join(out)
# verify
s = text.index(prefix) + len(prefix)
e = text.index(suffix)
rebuilt = text[s:e].replace(suffix + prefix, '')
assert json.loads(rebuilt) == obj
io.open('libs/workflow_contracts/src/modules_data.inc', 'w', encoding='utf-8', errors='surrogateescape', newline='').write(text)
print('OK modules=%d lines=%d max=%d' % (len(obj), len(packed), max(len(p) for p in packed)))
