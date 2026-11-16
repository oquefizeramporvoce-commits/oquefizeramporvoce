"""Percorre as rotas do site e aponta problemas: erros de script, textos quebrados,
vazamento horizontal no celular e links internos que caem em 'Página não encontrada'."""
import asyncio, sys, subprocess, time, json, re
from playwright.async_api import async_playwright

ROOT = '/home/claude/oqef'
PORT = 8770
srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(PORT), '--directory', ROOT + '/site'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)

core = json.load(open(ROOT + '/site/data/core.json'))
props = json.load(open(ROOT + '/site/data/props.json'))
rows = props['rows']
rid = lambda r: ('c' + str(r[4])) if r[4] else ('s' + str(r[5]))
# amostra de projetos: só Câmara, só Senado, nas duas Casas, com votação, virou lei, sem autor
sample = []
sample.append(next(r for r in rows if r[4] and not r[5]))
sample.append(next(r for r in rows if r[5] and not r[4]))
sample.append(next(r for r in rows if r[4] and r[5]))
sample += [rows[v['row']] for v in core['votes'][:3]]
sample.append(next(r for r in rows if r[11] == 0))
sample.append(next((r for r in rows if not r[8]), rows[-1]))
parl = core['parl']
pk = lambda p: ('s' if p[1] else 'd') + '-' + str(p[0])
psample = [parl[0], parl[-1]] + [p for p in parl if p[1] == 1][:2] + [p for p in parl if not p[11]][:1]

ROUTES = ['inicio', 'estado-sp', 'estado-df', 'parlamentares', 'partidos', 'votacoes', 'como-funciona', 'busca',
          'assuntos', 'partido-pt'] + ['tema-' + t for t in core['temas']] + ['tema-saude-s0', 'tema-outros-s70'] + \
         ['p-' + rid(r) for r in sample] + [pk(p) for p in psample] + ['naoexiste']

BAD = re.compile(r'\bundefined\b|\bNaN\b|\bnull\b|\[object Object\]')


async def main():
    out = []
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='chrome', args=['--no-sandbox'])
        for vw in [(1280, 900), (390, 820)]:
            pg = await b.new_page(viewport={'width': vw[0], 'height': vw[1]})
            errs = []
            pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)[:200]))
            pg.on('console', lambda m: errs.append('CONSOLE ' + m.text[:200]) if m.type == 'error' else None)
            await pg.goto(f'http://localhost:{PORT}/index.html#inicio')
            await pg.wait_for_timeout(2500)
            links = set()
            for r in ROUTES:
                errs.clear()
                await pg.evaluate(f"location.hash='{r}'")
                await pg.wait_for_timeout(1300 if r.startswith(('p-', 'd-', 's-', 'tema')) else 700)
                txt = await pg.evaluate("document.getElementById('view').innerText")
                ow = await pg.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth")
                nf = 'Página não encontrada' in txt
                bad = BAD.findall(txt)
                if vw[0] == 1280:
                    hs = await pg.evaluate("[...document.querySelectorAll('#view a[href^=\"#\"]')].map(a=>a.getAttribute('href'))")
                    links.update(hs)
                issues = []
                if errs: issues.append(errs[:3])
                if ow > 1: issues.append(f'overflow {ow}px')
                if nf and r != 'naoexiste': issues.append('NOT FOUND')
                if bad: issues.append(f'texto quebrado: {sorted(set(bad))}')
                if issues: out.append((vw[0], r, issues))
            if vw[0] == 1280:
                # testa uma amostra dos links internos encontrados
                uniq = sorted(links)
                kinds = {}
                for h in uniq:
                    k = re.sub(r'\d+', 'N', h)
                    kinds.setdefault(k, []).append(h)
                test = [v[0] for v in kinds.values()] + [v[-1] for v in kinds.values() if len(v) > 1]
                for h in test:
                    await pg.evaluate(f"location.hash='{h[1:]}'")
                    await pg.wait_for_timeout(900)
                    txt = await pg.evaluate("document.getElementById('view').innerText")
                    if 'Página não encontrada' in txt:
                        out.append(('link', h, ['NOT FOUND']))
                print('links internos distintos:', len(uniq), '| padrões testados:', len(test))
            await pg.close()
        await b.close()
    for o in out:
        print(o)
    print('TOTAL PROBLEMAS', len(out))


asyncio.run(main())
srv.terminate()
