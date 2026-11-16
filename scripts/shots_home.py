import asyncio, sys, subprocess, time, os
from playwright.async_api import async_playwright
ROOT = '/home/claude/oqef'
os.makedirs(ROOT + '/shots', exist_ok=True)
srv = subprocess.Popen([sys.executable, '-m', 'http.server', '8767', '--directory', ROOT + '/site'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='chrome', args=['--no-sandbox'])
        errs = []
        for name, (w, h) in {'d': (1280, 900), 'm': (390, 820)}.items():
            pg = await b.new_page(viewport={'width': w, 'height': h})
            pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
            pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' and '404' not in m.text else None)
            await pg.goto('http://localhost:8767/index.html#inicio')
            await pg.wait_for_timeout(2500)
            await pg.screenshot(path=f'{ROOT}/shots/{name}-home.png', full_page=True)
            if name == 'd':
                await pg.hover('g.uf[data-uf="BA"] .top')
                await pg.wait_for_timeout(400)
                await pg.screenshot(path=f'{ROOT}/shots/d-hover-ba.png')
                await pg.click('g.uf[data-uf="SP"] .top')
                await pg.mouse.move(5, 5)
                await pg.wait_for_timeout(400)
                await pg.screenshot(path=f'{ROOT}/shots/d-sel-sp.png')
            else:
                await pg.click('.uf-chips button[data-uf="DF"]')
                await pg.wait_for_timeout(900)
                await pg.screenshot(path=f'{ROOT}/shots/m-sel-df.png')
            ow = await pg.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth")
            if ow:
                errs.append('OVERFLOW ' + name)
            for hsh in ['parlamentares', 'd-204534', 'p-c2233802', 'tema-saude', 'votacoes', 'estado-mg']:
                await pg.evaluate(f"location.hash='{hsh}'")
                await pg.wait_for_timeout(900)
            await pg.close()
        await b.close()
        print('ERRORS', errs[:10])


asyncio.run(main())
srv.terminate()
