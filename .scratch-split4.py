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
# verify with the exact scaffolding the file uses
scaffold = suffix + prefix
rebuilt = text[text.index(prefix) + len(prefix):text.rindex(suffix)]
rebuilt = rebuilt.replace(scaffold, '')
assert rebuilt == inner, 'byte-level reassembly mismatch'
io.open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='').write(text)
print('OK byte-identical: %d modules, %d packed lines, max %d chars' %
      (len(chunks), len(packed), max(len(x) for x in packed)))
