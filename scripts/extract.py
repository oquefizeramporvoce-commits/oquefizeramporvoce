import sys, json, re, base64
src, dst = sys.argv[1], sys.argv[2]
raw = open(src, encoding='utf-8').read()
try:
    arr = json.loads(raw)
    text = ''.join(x.get('text','') for x in arr if isinstance(x, dict))
except Exception:
    text = raw
m = re.search(r'@@START@@(\d+)@@([A-Za-z0-9+/=]+)@@END@@', text)
if not m:
    print('NO MARKERS', len(text)); sys.exit(1)
n = int(m.group(1)); data = base64.b64decode(m.group(2)).decode('utf-8')
print('expected chars', n, 'got chars', len(data), 'utf16 units', len(data.encode('utf-16-le'))//2)
open(dst, 'w', encoding='utf-8').write(data)
