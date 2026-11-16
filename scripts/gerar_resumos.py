#!/usr/bin/env python3
"""
Gera rascunhos de resumos em linguagem simples para os projetos que viraram lei
ou foram aprovados em uma Casa, usando a API da Anthropic (Claude Haiku 5.5).

O script NÃO publica nada. Ele grava rascunhos em site/data/resumos_rascunho.json.
Depois que uma pessoa revisar, use --publicar para copiar os aprovados para
site/data/resumos.json, que é o arquivo que o site lê.

Uso (no seu computador, com a chave na variável de ambiente ANTHROPIC_API_KEY):

  python scripts/gerar_resumos.py gerar              # gera rascunhos (retoma se parar)
  python scripts/gerar_resumos.py amostra 40         # sorteia 40 rascunhos para revisar
  python scripts/gerar_resumos.py aprovar IDS.txt    # IDS.txt: uma chave por linha, aprovadas
  python scripts/gerar_resumos.py publicar           # grava as aprovadas em resumos.json

Requer apenas a biblioteca padrão do Python 3.9+.
"""
import json, os, random, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA = os.path.join(ROOT, 'site', 'data')
PROPS = os.path.join(DATA, 'props.json')
CORE = os.path.join(DATA, 'core.json')
RASC = os.path.join(DATA, 'resumos_rascunho.json')
PUB = os.path.join(DATA, 'resumos.json')

MODEL = 'claude-haiku-5-5'
API = 'https://api.anthropic.com/v1/messages'
WORKERS = 8

# índices da linha de props.json (mesma ordem de F no index.html)
F_CD, F_SF, F_EM, F_ORI, F_AU, F_BUCKET, F_AP, F_LEG, F_TEMAS = 4, 5, 6, 3, 8, 11, 17, 18, 7
BUCKET_LEI, BUCKET_APR = 0, 1
TEMAS = {'saude': 'Saúde', 'educacao': 'Educação', 'seguranca': 'Segurança', 'economia': 'Economia e trabalho',
         'direitos': 'Direitos e assistência social', 'ambiente': 'Meio ambiente e energia',
         'cidades': 'Cidades e transporte', 'politica': 'Política e serviço público',
         'outros': 'Cultura, esporte, tecnologia e outros'}
SIG = ['PL', 'PLP', 'PEC']
SITUACAO = ['Virou lei', 'Passou em uma Casa', 'Em andamento', 'Parado', 'Anexado a outro', 'Encerrado']  # ordem de BK no site
CASA = ['Câmara', 'Senado']


def chave(r):
    return 'c%s' % r[F_CD] if r[F_CD] else 's%s' % r[F_SF]


def carregar():
    props = json.load(open(PROPS, encoding='utf8'))
    core = json.load(open(CORE, encoding='utf8'))
    return props['rows'], core


def alvos(rows, core):
    """Projetos de leis e aprovados em uma Casa, apresentados desde 2023 por parlamentar."""
    parl = core['parl']
    temas = core['temas']
    out = []
    for r in rows:
        if r[F_BUCKET] not in (BUCKET_LEI, BUCKET_APR) or r[F_LEG] != 1:
            continue
        a = r[F_AU][0] if r[F_AU] else None
        if not isinstance(a, int):
            continue
        if parl[a][1] != r[F_ORI]:          # mesmo critério do site: autor da Casa do projeto
            continue
        bits = r[F_TEMAS]
        tema_nomes = ', '.join(TEMAS[t] for j, t in enumerate(temas) if bits & (1 << j))
        out.append({
            'chave': chave(r),
            'nome': '%s %s/%s' % (SIG[r[0]], r[1], r[2]),
            'ementa': r[F_EM],
            'apelido': r[F_AP] or '',
            'temas': tema_nomes,
            'autor': '%s (%s)' % (parl[a][2], CASA[parl[a][1]]),
            'situacao': SITUACAO[r[F_BUCKET]],
        })
    return out


def prompt(p):
    return f"""Você explica projetos de lei do Congresso brasileiro para qualquer cidadão.
Responda somente com um objeto JSON válido, sem texto antes ou depois, neste formato:
{{"manchete": string, "o_que_muda": [string], "quem_e_afetado": string, "atencao": string}}

Regras:
- Português do Brasil simples, que um adolescente de 14 anos entenda. Frases curtas. Sem juridiquês. Se citar uma lei, diga do que ela trata, em vez do número.
- "manchete": até 14 palavras, começando com verbo no presente, dizendo o que o projeto propõe. Trate como proposta, não como lei em vigor, a menos que a situação diga que virou lei.
- "o_que_muda": de 1 a 3 itens, cada um com até 25 palavras, explicando a mudança concreta na vida das pessoas.
- "quem_e_afetado": uma frase dizendo quem sente a mudança.
- "atencao": uma frase só se algo importante não dá para saber pela ementa (por exemplo, quando ela só cita números de leis). Caso contrário, use "".
- Seja neutro. Não elogie, não critique, não diga se é bom ou ruim, não mencione partido.
- Não invente nada que não esteja nos dados abaixo.

Dados do projeto:
Identificação: {p['nome']}{f" (apelido oficial: {p['apelido']})" if p['apelido'] else ''}
Ementa oficial: {p['ementa']}
Assuntos: {p['temas']}
Autor principal: {p['autor']}
Situação atual: {p['situacao']}"""


def chamar(p, chave_api):
    corpo = json.dumps({
        'model': MODEL, 'max_tokens': 600,
        'messages': [{'role': 'user', 'content': prompt(p)}],
    }).encode('utf8')
    req = urllib.request.Request(API, data=corpo, headers={
        'x-api-key': chave_api, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dados = json.loads(resp.read().decode('utf8'))
    texto = ''.join(b.get('text', '') for b in dados.get('content', []) if b.get('type') == 'text')
    texto = re.sub(r'^```(json)?|```$', '', texto.strip()).strip()
    return json.loads(texto), dados.get('usage', {})


def validar(x):
    """Mesmas regras de limpeza que o site aplica."""
    def s(v, n):
        return re.sub(r'\s+', ' ', v).strip()[:n] if isinstance(v, str) else ''
    if not isinstance(x, dict):
        return None
    m = s(x.get('manchete'), 160)
    if not m:
        return None
    muda = [s(v, 260) for v in (x.get('o_que_muda') or []) if isinstance(v, str)][:4]
    return {'manchete': m, 'o_que_muda': [v for v in muda if v],
            'quem_e_afetado': s(x.get('quem_e_afetado'), 260), 'atencao': s(x.get('atencao'), 260)}


def gerar(alvos_lista, chave_api):
    rascunhos = json.load(open(RASC, encoding='utf8')) if os.path.exists(RASC) else {}
    pendentes = [p for p in alvos_lista if p['chave'] not in rascunhos]
    print(f'{len(alvos_lista)} projetos alvo, {len(pendentes)} faltam gerar.')
    tok_in = tok_out = erros = 0

    def tarefa(p):
        for tentativa in range(3):
            try:
                x, uso = chamar(p, chave_api)
                v = validar(x)
                if v:
                    return p['chave'], v, uso
            except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
                time.sleep(2 + 3 * tentativa)
        return p['chave'], None, {}

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        feitos = 0
        for fut in as_completed([ex.submit(tarefa, p) for p in pendentes]):
            k, v, uso = fut.result()
            feitos += 1
            tok_in += uso.get('input_tokens', 0)
            tok_out += uso.get('output_tokens', 0)
            if v:
                rascunhos[k] = v
            else:
                erros += 1
            if feitos % 100 == 0:
                json.dump(rascunhos, open(RASC, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
                print(f'  {feitos}/{len(pendentes)}')
    json.dump(rascunhos, open(RASC, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    custo = tok_in / 1e6 * 0.10 + tok_out / 1e6 * 0.50
    print(f'Pronto. Rascunhos: {len(rascunhos)}. Falhas: {erros}. '
          f'Tokens: {tok_in} entrada / {tok_out} saída. Custo estimado: US$ {custo:.2f} (preço de tempo real).')


def amostra(n):
    rascunhos = json.load(open(RASC, encoding='utf8'))
    rows, core = carregar()
    por_chave = {p['chave']: p for p in alvos(rows, core)}
    ks = random.sample(sorted(rascunhos), min(n, len(rascunhos)))
    for k in ks:
        p, x = por_chave.get(k, {}), rascunhos[k]
        print('-' * 70)
        print(f"{k}  {p.get('nome','')}  [{p.get('situacao','')}]")
        print('EMENTA:', p.get('ementa', ''))
        print('MANCHETE:', x['manchete'])
        for item in x['o_que_muda']:
            print('  - O que muda:', item)
        print('QUEM:', x['quem_e_afetado'])
        if x['atencao']:
            print('ATENÇÃO:', x['atencao'])
    print('-' * 70)
    print('Para aprovar, salve as chaves que estão corretas em IDS.txt, uma por linha, e rode:')
    print('  python scripts/gerar_resumos.py aprovar IDS.txt')


def aprovar(arq):
    rascunhos = json.load(open(RASC, encoding='utf8'))
    ids = [l.strip() for l in open(arq, encoding='utf8') if l.strip()]
    desconhecidos = [i for i in ids if i not in rascunhos]
    if desconhecidos:
        print('Chaves sem rascunho (ignoradas):', desconhecidos)
    aprovados = json.load(open(PUB, encoding='utf8')) if os.path.exists(PUB) else {}
    hoje = int(date.today().strftime('%Y%m%d'))
    for i in ids:
        if i in rascunhos:
            aprovados[i] = dict(rascunhos[i], rev=hoje)
    json.dump(aprovados, open(PUB, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print(f'{len(aprovados)} resumos publicados em site/data/resumos.json, com revisão em {hoje}.')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'gerar':
        chave_api = os.environ.get('ANTHROPIC_API_KEY')
        if not chave_api:
            sys.exit('Defina a variável ANTHROPIC_API_KEY antes de rodar.')
        rows, core = carregar()
        gerar(alvos(rows, core), chave_api)
    elif cmd == 'amostra':
        amostra(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    elif cmd == 'aprovar':
        aprovar(sys.argv[2])
    else:
        print(__doc__)
