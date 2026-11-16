import sys, json, re, base64, gzip, hashlib, glob, os
name, sha, dst = sys.argv[1], sys.argv[2], sys.argv[3]
parts = {}; total = None
for f in glob.glob('/tmp/claude-tool-results/*/mcp-remote-devices-*.txt'):
    raw = open(f, encoding='utf-8').read()
    try:
        arr = json.loads(raw); text = ''.join(x.get('text','') for x in arr if isinstance(x, dict))
    except Exception:
        text = raw
    m = re.search(r'@@START@@(\w+)@@(\d+)@@(\d+)@@([A-Za-z0-9+/=]*)@@END@@', text)
    if not m or m.group(1) != name: continue
    parts[int(m.group(2))] = m.group(4); total = int(m.group(3))
print('parts', sorted(parts), 'of', total)
assert total is not None and len(parts) == total, 'missing parts'
b64 = ''.join(parts[i] for i in range(total))
data = gzip.decompress(base64.b64decode(b64))
h = hashlib.sha256(data).hexdigest()
print('bytes', len(data), 'sha', h, 'OK' if h == sha else 'MISMATCH')
assert h == sha
open(dst, 'wb').write(data)
