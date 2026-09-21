import io
p = 'libs/workflow_contracts/src/modules_data.inc'
data = io.open(p, encoding='utf-8', errors='surrogateescape').read()
nl = '\r\n' if '\r\n' in data else '\n'
lines = data.split(nl)
big = lines[2]
prefix = 'R"PWB_MODULES_JSON('
suffix = ')PWB_MODULES_JSON"'
inner = big[len(prefix):-len(suffix)]
# Split the payload into <12k slices at any position (raw literals can hold
# anything except the exact terminator sequence, which cannot occur here
# because the payload contains no ')' followed by 'PWB_MODULES_JSON"').
assert ')PWB_MODULES_JSON"' not in inner
SIZE = 12000
parts = [inner[i:i + SIZE] for i in range(0, len(inner), SIZE)]
out_lines = [lines[0], lines[1]]
for i, part in enumerate(parts):
    suffix_line = (' +' if i != len(parts) - 1 else '')
    out_lines.append(prefix + part + suffix + suffix_line)
out_lines.append('')
text = nl.join(out_lines)
with open(p, 'wb') as f:
    f.write(text.encode('utf-8'))
# verify reassembly
back = io.open(p, encoding='utf-8', errors='surrogateescape').read()
blines = back.split(nl)
payload = ''.join(l.replace(prefix, '').replace(suffix, '').rstrip().rstrip('+')
                  for l in blines[2:] if l.strip())
assert payload == inner, 'reassembly mismatch'
print('OK: %d parts, max line %d chars, reassembly verified'
      % (len(parts), max(len(x) for x in out_lines)))
