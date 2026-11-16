import asyncio, sys, subprocess, time, os
from playwright.async_api import async_playwright
ROOT='/home/claude/oqef'
os.makedirs(ROOT+'/shots', exist_ok=True)
srv=subprocess.Popen([sys.executable,'-m','http.server','8765','--directory',ROOT+'/site'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(1)
PAGES=[('inicio','inicio',True),('tema','tema-saude',True),('temasub','tema-saude-s3',False),('projeto','p-c2233802',True),('parl','d-204534',True),('parlamentares','parlamentares',True),('partidos','partidos',False),('votacoes','votacoes',False),('como','como-funciona',False)]
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(channel='chrome',args=['--no-sandbox'])
        errs=[]
        for name,(w,h,scheme) in {'d':(1280,900,'light'),'m':(390,800,'light'),'k':(1280,900,'dark')}.items():
            ctx=await b.new_context(viewport={'width':w,'height':h},color_scheme=scheme)
            pg=await ctx.new_page()
            pg.on('console',lambda m: errs.append(m.text) if m.type=='error' else None)
            pg.on('pageerror',lambda e: errs.append('PAGEERROR '+str(e)))
            await pg.goto('http://localhost:8765/index.html')
            for nm,hsh,full in PAGES:
                if name!='d' and nm not in ('parlamentares','parl'): continue
                await pg.evaluate(f"location.hash='{hsh}'")
                await pg.wait_for_timeout(1500)
                await pg.screenshot(path=f'{ROOT}/shots/{name}-{nm}.png',full_page=full and name=='d')
                ow=await pg.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth")
                if ow: errs.append(f'OVERFLOW-X {name} {nm}')
            if name=='d':
                await pg.evaluate("location.hash='parlamentares'")
                await pg.wait_for_timeout(800)
                await pg.select_option('#puf','SP')
                await pg.wait_for_timeout(800)
                await pg.screenshot(path=f'{ROOT}/shots/d-uf.png')
                await pg.fill('#busca-q','escala')
                await pg.click('#busca-form button')
                await pg.wait_for_timeout(1500)
                await pg.screenshot(path=f'{ROOT}/shots/d-busca.png')
            await ctx.close()
        await b.close()
        print('ERRORS',[e for e in errs if 'fonts.g' not in e and 'ERR_' not in e][:20], 'net-errs', sum(1 for e in errs if 'ERR_' in e or 'fonts.g' in e))
asyncio.run(main())
srv.terminate()
