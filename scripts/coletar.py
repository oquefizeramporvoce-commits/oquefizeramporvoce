#!/usr/bin/env python3
"""
Coleta os dados abertos da Câmara dos Deputados e do Senado Federal e grava os
arquivos de raw/ que o scripts/build.py lê.

Uso:
    python scripts/coletar.py                 # coleta tudo e grava em raw/
    python scripts/coletar.py --so camara     # só uma parte: camara, senado, exercicio, sexo
    python scripts/coletar.py --saida /tmp/x  # grava em outra pasta

Só usa a biblioteca padrão do Python 3.9+.

Segurança contra dado ruim: se uma fonte voltar muito menor que a coleta anterior
(por exemplo, uma API fora do ar devolvendo lista vazia), o arquivo antigo é mantido
e o script termina com erro, para o agendamento não publicar um site quebrado.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

# ---------------------------------------------------------------- parâmetros
LEG_START = '2023-02-01'          # início da 57ª legislatura
LEGISLATURA = 57
SIGLAS = ('PL', 'PLP', 'PEC')
CAM_FILES = 'https://dadosabertos.camara.leg.br/arquivos/'
CAM_API = 'https://dadosabertos.camara.leg.br/api/v2/'
SEN_API = 'https://legis.senado.leg.br/dadosabertos/'
UA = 'oquefizeramporvoce-coletor/1.0 (contato: oquefizeramporvoce@gmail.com)'
TZ_BR = dt.timezone(dt.timedelta(hours=-3))
MIN_RATIO = 0.9                   # nova coleta precisa ter pelo menos 90% dos registros da anterior

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ---------------------------------------------------------------- HTTP
class Http:
    """GET de JSON com novas tentativas. O Senado limita o ritmo (HTTP 429), então
    há um intervalo mínimo entre chamadas ao mesmo servidor."""

    def __init__(self, min_interval=None):
        self.min_interval = min_interval or {}
        self.last = defaultdict(float)
        self.calls = 0

    def get_json(self, url, tries=6, timeout=180):
        host = url.split('/')[2]
        for attempt in range(tries):
            wait = self.min_interval.get(host, 0) - (time.time() - self.last[host])
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
            self.calls += 1
            req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': UA})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    ra = e.headers.get('Retry-After')
                    time.sleep(float(ra) if ra and ra.isdigit() else 3 * (attempt + 1) ** 2)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
                if attempt < tries - 1:
                    time.sleep(3 * (attempt + 1) ** 2)
                    continue
                raise


# ---------------------------------------------------------------- utilidades
def trim(s, n=200):
    """Mesmo corte das coletas anteriores: até 200 caracteres, sem quebrar palavra."""
    s = re.sub(r'\s+', ' ', s or '').strip()
    if len(s) <= n:
        return s
    t = s[:n]
    k = t.rfind(' ')
    return (t[:k] if k > n * 0.6 else t).rstrip(' ') + '…'


def d10(s):
    return (s or '')[:10]


def in_range(d, ref):
    return LEG_START <= d10(d) <= ref


def years(ref):
    return range(int(LEG_START[:4]), int(ref[:4]) + 1)


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data):
    """JSON válido com um registro por linha: o histórico do Git mostra o que mudou em cada coleta."""
    def dump(x):
        return json.dumps(x, ensure_ascii=False, separators=(',', ':'))
    parts = []
    for k, v in data.items():
        if isinstance(v, list) and len(v) > 20:
            body = '[\n' + ',\n'.join(dump(x) for x in v) + '\n]'
        elif isinstance(v, dict) and len(v) > 20:
            body = '{\n' + ',\n'.join(dump(str(kk)) + ':' + dump(vv) for kk, vv in v.items()) + '\n}'
        else:
            body = dump(v)
        parts.append(dump(k) + ':' + body)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('{\n' + ',\n'.join(parts) + '\n}\n')
    os.replace(tmp, path)


class DadoSuspeito(Exception):
    pass


def check(nome, novo, antigo):
    """Recusa uma coleta que encolheu demais em relação à anterior."""
    if antigo and novo < antigo * MIN_RATIO:
        raise DadoSuspeito(f'{nome}: {novo} registros contra {antigo} na coleta anterior.')


# ================================================================ CÂMARA
def cam_tipo_autor(cod, nome):
    cod = int(cod or 0)
    if cod == 10000:
        return 'D'
    if cod in (20000, 40000) or (nome or '').startswith('Senado Federal'):
        return 'S'
    if cod == 30000:
        return 'E'
    return 'O'


def cam_autores(rows):
    """rows: registros do arquivo proposicoesAutores de uma proposição.
    Devolve [[nome, partido, uf, tipo, idDeputado]] na ordem de assinatura, sem repetir."""
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: int(r.get('ordemAssinatura') or 999)):
        nome = re.sub(r'\s+', ' ', r.get('nomeAutor') or '').strip()
        did = int(r.get('idDeputadoAutor') or 0)
        if (nome, did) in seen:
            continue
        seen.add((nome, did))
        out.append([nome, r.get('siglaPartidoAutor') or '', r.get('siglaUFAutor') or '',
                    cam_tipo_autor(r.get('codTipoAutor'), nome), did])
    return out


def cam_prop_row(p, status, temas, autores):
    """Formato de raw/camara.json, campo props."""
    return [p['id'], p['siglaTipo'], int(p['numero']), int(p['ano']), trim(p.get('ementa')),
            d10(p.get('dataApresentacao')), d10(status.get('data') or status.get('dataHora')),
            status.get('descricaoSituacao') or '', status.get('siglaOrgao') or '',
            list(reversed(temas)), autores[:3], len(autores)]


_SUBJ_BAD = re.compile(r'^\s*(Aprovad|Rejeitad)[oa]s?,?\s+(o|a|os|as)\s+'
                       r'(Requerimento|requerimento|Destaque|destaque|Prefer|prefer|Reda|reda|inclus|Art\b|art\b|Parecer|parecer)')
_MAIN = re.compile(r'^\s*(Aprovad|Rejeitad)[oa]s?\b')
_OBJ = re.compile(r'Projeto de Lei|Proposta de Emenda|Emenda Constitucional|Emenda à Constituição|Lei de Convers|Medida Provis', re.I)


def cam_is_main_vote(desc):
    """Votação do texto principal (ou da fase final com as emendas do Senado).
    Ficam fora requerimentos, destaques, preferências, redação final e emendas avulsas."""
    d = (desc or '').split('Sim:')[0]
    if not _MAIN.match(d) or _SUBJ_BAD.match(d) or not _OBJ.search(d):
        return False
    if re.match(r'^\s*(Aprovad|Rejeitad)[oa]s?\s+(a|as)\s+Emendas?\s+n', d):
        return False
    if re.match(r'^\s*(Aprovad|Rejeitad)[oa]s?\s+(a|as)\s+Emendas?\b', d) and 'Senado' not in d:
        return False
    return True


CAM_VOTO = {'Sim': 1, 'Não': 2, 'Abstenção': 3, 'Obstrução': 4, 'Artigo 17': 5}


def cam_presenca(eventos, orgaos, presencas, ref):
    """eventos: {id: evento}; orgaos: {idEvento: [siglas]}; presencas: {idEvento: [idDeputado]}.
    Plenário: sessões deliberativas com lista de presença, contadas entre a primeira e a
    última presença de cada deputado. Comissões: reuniões e audiências encerradas fora do Plenário."""
    sess = []
    sem_lista = 0
    for eid, e in eventos.items():
        if e.get('descricaoTipo') != 'Sessão Deliberativa' or 'PLEN' not in orgaos.get(eid, []):
            continue
        if not in_range(e.get('dataHoraInicio'), ref):
            continue
        if presencas.get(eid):
            sess.append(e)
        elif (e.get('situacao') or '').startswith('Encerrada'):
            sem_lista += 1
    sess.sort(key=lambda e: e['dataHoraInicio'])
    dates = [d10(e['dataHoraInicio']) for e in sess]
    por_ano = defaultdict(int)
    for d in dates:
        por_ano[d[:4]] += 1

    pres_dates = defaultdict(list)
    for e in sess:
        for dep in set(presencas[e['id']]):
            pres_dates[str(dep)].append(d10(e['dataHoraInicio']))

    com = defaultdict(int)
    for eid, deps in presencas.items():
        e = eventos.get(eid)
        if not e or 'PLEN' in orgaos.get(eid, []):
            continue
        if not in_range(e.get('dataHoraInicio'), ref):
            continue
        if not re.match(r'^(Reunião|Audiência)', e.get('descricaoTipo') or ''):
            continue
        if not (e.get('situacao') or '').startswith('Encerrada'):
            continue
        for dep in set(deps):
            com[str(dep)] += 1

    out = {}
    for dep in set(pres_dates) | set(com):
        ds = sorted(pres_dates.get(dep, []))
        if ds:
            first, last = ds[0], ds[-1]
            total = sum(1 for d in dates if first <= d <= last)
            out[dep] = [len(ds), total, first, last, com.get(dep, 0)]
        else:
            out[dep] = [0, 0, '', '', com.get(dep, 0)]
    return {'ref': ref, 'sessoes': len(sess), 'semLista': sem_lista, 'porAno': dict(sorted(por_ano.items())),
            'ultimaSessao': dates[-1] if dates else '', 'dep': out}


def coletar_camara(http, ref, raw_dir):
    props, temas_by, autores_by = {}, defaultdict(list), defaultdict(list)
    votacoes, votos = {}, defaultdict(list)
    eventos, orgaos, presencas = {}, defaultdict(list), defaultdict(list)

    for y in years(ref):
        log(f'Câmara {y}: proposições')
        for p in http.get_json(f'{CAM_FILES}proposicoes/json/proposicoes-{y}.json')['dados']:
            if p.get('siglaTipo') in SIGLAS:
                props[p['id']] = p
        for t in http.get_json(f'{CAM_FILES}proposicoesTemas/json/proposicoesTemas-{y}.json')['dados']:
            pid = int(t['uriProposicao'].rstrip('/').split('/')[-1])
            temas_by[pid].append(t)
        for a in http.get_json(f'{CAM_FILES}proposicoesAutores/json/proposicoesAutores-{y}.json')['dados']:
            autores_by[int(a['idProposicao'])].append(a)
        log(f'Câmara {y}: votações')
        for v in http.get_json(f'{CAM_FILES}votacoes/json/votacoes-{y}.json')['dados']:
            if v.get('siglaOrgao') == 'PLEN':
                votacoes[v['id']] = v
        for v in http.get_json(f'{CAM_FILES}votacoesVotos/json/votacoesVotos-{y}.json')['dados']:
            votos[v['idVotacao']].append(v)
        log(f'Câmara {y}: eventos e presença')
        for e in http.get_json(f'{CAM_FILES}eventos/json/eventos-{y}.json')['dados']:
            eventos[e['id']] = e
        for o in http.get_json(f'{CAM_FILES}eventosOrgaos/json/eventosOrgaos-{y}.json')['dados']:
            orgaos[o['idEvento']].append(o.get('siglaOrgao'))
        for p in http.get_json(f'{CAM_FILES}eventosPresencaDeputados/json/eventosPresencaDeputados-{y}.json')['dados']:
            presencas[p['idEvento']].append(p['idDeputado'])

    def temas_de(pid):
        seen = []
        for t in temas_by.get(pid, []):
            if t['codTema'] not in seen:
                seen.append(t['codTema'])
        return seen

    rows = {pid: cam_prop_row(p, p.get('ultimoStatus') or {}, temas_de(pid), cam_autores(autores_by.get(pid, [])))
            for pid, p in props.items()}

    # votações nominais do texto principal em Plenário
    sel = []
    for vid, v in votacoes.items():
        if not in_range(v.get('data'), ref):
            continue
        if (v.get('votosSim') or 0) + (v.get('votosNao') or 0) + (v.get('votosOutros') or 0) <= 0:
            continue
        if not cam_is_main_vote(v.get('descricao')):
            continue
        sel.append(v)

    # projetos antigos (anteriores a 2023) que só aparecem por terem sido votados agora
    deps = {}
    for v in sorted(sel, key=lambda v: (v['data'], int(v['id'].split('-')[1]))):
        for x in votos.get(v['id'], []):
            d = x.get('deputado_') or {}
            deps[str(d.get('id'))] = [d.get('nome') or '', d.get('siglaPartido') or '', d.get('siglaUf') or '']
    for pid in sorted({int(v['id'].split('-')[0]) for v in sel} - set(rows)):
        det = http.get_json(f'{CAM_API}proposicoes/{pid}')
        if not det or det['dados'].get('siglaTipo') not in SIGLAS:
            continue
        p = det['dados']
        au = (http.get_json(f'{CAM_API}proposicoes/{pid}/autores') or {}).get('dados', [])
        te = (http.get_json(f'{CAM_API}proposicoes/{pid}/temas') or {}).get('dados', [])
        autores = []
        for a in sorted(au, key=lambda a: a.get('ordemAssinatura') or 999):
            did = int(a['uri'].rstrip('/').split('/')[-1]) if '/deputados/' in (a.get('uri') or '') else 0
            pt, uf = (deps.get(str(did)) or ['', '', ''])[1:] if did else ('', '')
            autores.append([re.sub(r'\s+', ' ', a.get('nome') or '').strip(), pt, uf, cam_tipo_autor(a.get('codTipo'), a.get('nome')), did])
        rows[pid] = cam_prop_row(p, p.get('statusProposicao') or {}, [t['codTema'] for t in te][::-1], autores)
        log(f'  incluído projeto antigo votado: {p["siglaTipo"]} {p["numero"]}/{p["ano"]}')

    vots = []
    for v in sorted(sel, key=lambda v: (v['data'], int(v['id'].split('-')[1]))):
        pid = int(v['id'].split('-')[0])
        if pid not in rows:
            continue
        pairs = []
        for x in votos.get(v['id'], []):
            code = CAM_VOTO.get(x.get('voto'))
            did = (x.get('deputado_') or {}).get('id')
            if code and did:
                pairs += [int(did), code]
        if not pairs:
            continue
        vots.append({'id': v['id'], 'pid': pid, 'data': d10(v['data']), 'desc': v.get('descricao') or '',
                     'apr': 1 if v.get('aprovacao') == 1 else 0, 'v': pairs})

    camara = {'ref': ref, 'fonte': 'dadosabertos.camara.leg.br', 'props': list(rows.values()), 'vots': vots, 'deps': deps}
    pres = cam_presenca(eventos, orgaos, presencas, ref)

    old = load_json(os.path.join(raw_dir, 'camara.json'), {}) or {}
    check('Câmara, proposições', len(camara['props']), len(old.get('props', [])))
    check('Câmara, votações', len(camara['vots']), len(old.get('vots', [])))
    oldp = load_json(os.path.join(raw_dir, 'presenca_camara.json'), {}) or {}
    check('Câmara, sessões', pres['sessoes'], oldp.get('sessoes', 0))
    write_json(os.path.join(raw_dir, 'camara.json'), camara)
    write_json(os.path.join(raw_dir, 'presenca_camara.json'), pres)
    log(f'Câmara: {len(camara["props"])} proposições, {len(vots)} votações, {pres["sessoes"]} sessões')


# ================================================================ SENADO
def sen_parse_proc(d, item=None):
    """Detalhe de /processo/{id} (e o item da lista, se houver) no formato de raw/senado.json."""
    item = item or {}
    doc = d.get('documento') or {}
    ai = sorted(d.get('autoriaIniciativa') or [], key=lambda a: a.get('ordem') or 0)
    aut = [[a.get('autor') or '', a.get('siglaPartido') or '', a.get('siglaTipo') or '',
            int(a.get('codigoParlamentar') or 0), a.get('uf') or ''] for a in ai]
    return {
        'id': d['id'], 'cod': d.get('codigoMateria'), 'sigla': d.get('sigla'),
        'num': str(int(d.get('numero') or 0)), 'ano': int(d.get('ano') or 0),
        'apelido': re.sub(r'\s+', ' ', d.get('apelido') or '').strip(),
        'obj': d.get('objetivo') or '', 'ementa': trim((d.get('conteudo') or {}).get('ementa') or item.get('ementa')),
        'da': d10(doc.get('dataApresentacao') or item.get('dataApresentacao')),
        'tram': d.get('tramitando') or item.get('tramitando') or '',
        'sit': d.get('situacaoAtual') or item.get('situacaoAtual') or '',
        'sitd': d10(d.get('dataSituacaoAtual') or item.get('dataSituacaoAtual')),
        'cls': [c.get('descricaoHierarquia') for c in d.get('classificacoes') or [] if c.get('descricaoHierarquia')],
        'aut': aut[:3], 'nAut': len(aut),
        'autoria': item.get('autoria') or doc.get('resumoAutoria') or '',
        'casaIni': d.get('siglaCasaIniciadora') or '',
        'upd': item.get('dataUltimaAtualizacao') or d.get('dthUltimaAtualizacao') or '',
        'norma': json.dumps(d.get('normaGerada') or {}, ensure_ascii=False, separators=(',', ':')),
    }


def sen_from_list(item):
    """Quando o detalhe falha: registro mínimo a partir da lista (sem autores nem classificação)."""
    m = re.match(r'(\w+)\s+(\d+)/(\d{4})', item.get('identificacao') or '')
    return {'id': item['id'], 'cod': item.get('codigoMateria'), 'sigla': m.group(1) if m else '',
            'num': str(int(m.group(2))) if m else '', 'ano': int(m.group(3)) if m else 0, 'apelido': '',
            'obj': item.get('objetivo') or '', 'ementa': trim(item.get('ementa')), 'da': d10(item.get('dataApresentacao')),
            'tram': item.get('tramitando') or '', 'sit': item.get('situacaoAtual') or '',
            'sitd': d10(item.get('dataSituacaoAtual')), 'cls': [], 'aut': [], 'nAut': 0,
            'autoria': item.get('autoria') or '', 'casaIni': item.get('casaIdentificadora') or '',
            'upd': '', 'norma': '{}', 'noDet': True}


def sen_vote(v):
    return {'idp': v.get('idProcesso'), 'cod': v.get('codigoMateria'), 'ident': v.get('identificacao'),
            'sigla': v.get('sigla'), 'num': str(int(v.get('numero') or 0)), 'ano': int(v.get('ano') or 0),
            'data': d10(v.get('dataSessao')), 'seq': v.get('codigoVotacaoSve') or v.get('codigoSessaoVotacao'),
            'desc': v.get('descricaoVotacao') or '', 'res': v.get('resultadoVotacao') or '',
            'secreta': v.get('votacaoSecreta') or '',
            'v': [[x.get('codigoParlamentar'), x.get('nomeParlamentar') or '', x.get('siglaPartidoParlamentar') or '',
                   x.get('siglaUFParlamentar') or '', x.get('siglaVotoParlamentar') or ''] for x in v.get('votos') or []]}


S_PRES = {'Sim', 'Não', 'Abstenção', 'Votou', 'P-NRV', 'Presidente (art. 51 RISF)'}
S_JUST = {'AP', 'LS', 'MIS', 'LP', 'LAP'}
S_FALTA = {'NCom'}


def sen_presenca(votacoes, ref):
    """Dia de votação nominal: presente se votou ou registrou presença em alguma votação do dia;
    ausência justificada (licença, missão, atividade parlamentar); falta sem justificativa (NCom)."""
    vs = [v for v in votacoes if in_range(v.get('dataSessao'), ref)]
    per = defaultdict(dict)
    for v in vs:
        d = d10(v['dataSessao'])
        for x in v.get('votos') or []:
            per[str(x['codigoParlamentar'])].setdefault(d, set()).add(x.get('siglaVotoParlamentar'))
    sen = {}
    for cod, dd in per.items():
        pres = just = falta = 0
        for votos in dd.values():
            if votos & S_PRES:
                pres += 1
            elif votos & S_JUST:
                just += 1
            elif votos & S_FALTA:
                falta += 1
        sen[cod] = {'pres': pres, 'just': just, 'falta': falta, 'dias': pres + just + falta, 'first': min(dd), 'last': max(dd)}
    return {'ref': ref, 'diasVotacao': len({d10(v['dataSessao']) for v in vs}), 'votacoes': len(vs), 'sen': sen}


def sen_licencas(lista, ref):
    """lista: licenças do senador. Soma os dias (inclusive) dentro da legislatura, por tipo."""
    out = {'saude': 0, 'particular': 0, 'missao': 0, 'outra': 0, 'n': 0}
    lo, hi = dt.date.fromisoformat(LEG_START), dt.date.fromisoformat(ref)
    for l in lista:
        try:
            a = dt.date.fromisoformat(d10(l.get('DataInicio')))
            b = dt.date.fromisoformat(d10(l.get('DataFim') or l.get('DataFimPrevista') or l.get('DataInicio')))
        except ValueError:
            continue
        a, b = max(a, lo), min(b, hi)
        if b < a:
            continue
        dias = (b - a).days + 1
        tipo = l.get('SiglaTipoAfastamento') or ''
        k = 'saude' if 'SAUDE' in tipo else 'particular' if 'INTER_PARTIC' in tipo else 'missao' if 'ATIVIDADE_PARLAMENTAR' in tipo else 'outra'
        out[k] += dias
        out['n'] += 1
    return out


def sen_windows(ref):
    for y in years(ref):
        for a, b in (('01-01', '06-30'), ('07-01', '12-31')):
            if f'{y}-{a}' <= ref:
                yield f'{y}-{a}', f'{y}-{b}'


def coletar_senado(http, ref, raw_dir, exercicio_sen=()):
    old = load_json(os.path.join(raw_dir, 'senado.json'), {}) or {}
    old_by = {p['id']: p for p in old.get('procs', [])}

    lista = {}
    for s in SIGLAS:
        for y in years(ref):
            for item in http.get_json(f'{SEN_API}processo?sigla={s}&ano={y}&v=1') or []:
                lista[item['id']] = item
    log(f'Senado: {len(lista)} processos nas listas')

    votacoes = []
    for a, b in sen_windows(ref):
        votacoes += http.get_json(f'{SEN_API}votacao?dataInicio={a}&dataFim={b}&v=1') or []
    votacoes = [v for v in votacoes if in_range(v.get('dataSessao'), ref)]
    log(f'Senado: {len(votacoes)} votações nominais')

    alvo = set(lista) | {v['idProcesso'] for v in votacoes if v.get('sigla') in SIGLAS and v.get('idProcesso')}
    procs, reus, falhas = [], 0, 0
    for i, pid in enumerate(sorted(alvo)):
        item = lista.get(pid)
        prev = old_by.get(pid)
        if item and prev and 'noDet' not in prev and prev.get('upd') == item.get('dataUltimaAtualizacao'):
            procs.append(prev)
            reus += 1
            continue
        try:
            d = http.get_json(f'{SEN_API}processo/{pid}?v=1')
        except Exception as e:  # noqa: BLE001 - registra e segue com o mínimo da lista
            log(f'  falha no detalhe {pid}: {e}')
            d = None
        if d:
            procs.append(sen_parse_proc(d, item))
        elif item:
            procs.append(sen_from_list(item))
            falhas += 1
        if (i + 1) % 250 == 0:
            log(f'  {i + 1}/{len(alvo)} processos')
    log(f'Senado: {len(procs)} processos ({reus} sem mudança, {falhas} sem detalhe)')

    vots = sorted((sen_vote(v) for v in votacoes if v.get('sigla') in SIGLAS),
                  key=lambda v: (v['data'], v['seq'] or 0))
    pres = sen_presenca(votacoes, ref)

    lic = {}
    for cod in sorted(set(pres['sen']) | {str(c) for c in exercicio_sen}, key=int):
        j = http.get_json(f'{SEN_API}senador/{cod}/licencas.json') or {}
        ls = (((j.get('LicencaParlamentar') or {}).get('Parlamentar') or {}).get('Licencas') or {}).get('Licenca') or []
        lic[cod] = sen_licencas(ls if isinstance(ls, list) else [ls], ref)
    pres['lic'] = lic

    check('Senado, processos', len(procs), len(old.get('procs', [])))
    check('Senado, votações', len(vots), len(old.get('vots', [])))
    oldp = load_json(os.path.join(raw_dir, 'presenca_senado.json'), {}) or {}
    check('Senado, votações para presença', pres['votacoes'], oldp.get('votacoes', 0))
    write_json(os.path.join(raw_dir, 'senado.json'), {'ref': ref, 'fonte': 'legis.senado.leg.br/dadosabertos', 'procs': procs, 'vots': vots})
    write_json(os.path.join(raw_dir, 'presenca_senado.json'), pres)


# ================================================================ EXERCÍCIO E SEXO
def coletar_exercicio(http, ref, raw_dir):
    dep, url = [], f'{CAM_API}deputados?itens=100&ordem=ASC&ordenarPor=nome'
    while url:
        j = http.get_json(url)
        dep += [[d['id'], d['nome'], d.get('siglaPartido') or '', d.get('siglaUf') or ''] for d in j['dados']]
        url = next((l['href'] for l in j.get('links', []) if l.get('rel') == 'next'), None)
    j = http.get_json(f'{SEN_API}senador/lista/atual.json')
    ps = j['ListaParlamentarEmExercicio']['Parlamentares']['Parlamentar']
    sen = [[int(p['IdentificacaoParlamentar']['CodigoParlamentar']), p['IdentificacaoParlamentar']['NomeParlamentar'],
            p['IdentificacaoParlamentar'].get('SiglaPartidoParlamentar') or '', p['IdentificacaoParlamentar'].get('UfParlamentar') or '']
           for p in (ps if isinstance(ps, list) else [ps])]
    if not (480 <= len(dep) <= 513 and 75 <= len(sen) <= 81):
        raise DadoSuspeito(f'Em exercício: {len(dep)} deputados e {len(sen)} senadores fora do esperado.')
    write_json(os.path.join(raw_dir, 'exercicio.json'), {'dep': dep, 'sen': sen, 'ref': ref})
    log(f'Em exercício: {len(dep)} deputados, {len(sen)} senadores')
    return dep, sen


def coletar_sexo(http, ref, raw_dir):
    path = os.path.join(raw_dir, 'sexo.json')
    cache = load_json(path, {}) or {}
    dep, sen = dict(cache.get('dep', {})), dict(cache.get('sen', {}))
    ids, url = [], f'{CAM_API}deputados?idLegislatura={LEGISLATURA}&itens=100&ordem=ASC&ordenarPor=id'
    while url:
        j = http.get_json(url)
        ids += [str(d['id']) for d in j['dados']]
        url = next((l['href'] for l in j.get('links', []) if l.get('rel') == 'next'), None)
    novos = [i for i in dict.fromkeys(ids) if i not in dep]
    for i in novos:
        d = (http.get_json(f'{CAM_API}deputados/{i}') or {}).get('dados') or {}
        if d.get('sexo') in ('F', 'M'):
            dep[i] = d['sexo']
    j = http.get_json(f'{SEN_API}senador/lista/legislatura/{LEGISLATURA}.json')
    for p in j['ListaParlamentarLegislatura']['Parlamentares']['Parlamentar']:
        idp = p['IdentificacaoParlamentar']
        sen[str(idp['CodigoParlamentar'])] = 'F' if idp.get('SexoParlamentar') == 'Feminino' else 'M'
    write_json(path, {'ref': ref, 'dep': dep, 'sen': sen})
    log(f'Sexo: {len(dep)} deputados ({len(novos)} novos), {len(sen)} senadores')


# ================================================================ principal
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--so', choices=['camara', 'senado', 'exercicio', 'sexo'], action='append',
                    help='coleta só esta parte (pode repetir)')
    ap.add_argument('--saida', default=os.path.join(ROOT, 'raw'))
    ap.add_argument('--ref', help='data de referência AAAA-MM-DD (padrão: hoje, horário de Brasília)')
    args = ap.parse_args()
    ref = args.ref or dt.datetime.now(TZ_BR).date().isoformat()
    partes = args.so or ['exercicio', 'camara', 'senado', 'sexo']
    os.makedirs(args.saida, exist_ok=True)
    http = Http(min_interval={'legis.senado.leg.br': 0.35, 'dadosabertos.camara.leg.br': 0.05})
    log(f'Coleta com data de referência {ref}: {", ".join(partes)}')
    try:
        sen_ex = []
        if 'exercicio' in partes:
            _, sen = coletar_exercicio(http, ref, args.saida)
            sen_ex = [s[0] for s in sen]
        else:
            sen_ex = [s[0] for s in (load_json(os.path.join(args.saida, 'exercicio.json'), {}) or {}).get('sen', [])]
        if 'camara' in partes:
            coletar_camara(http, ref, args.saida)
        if 'senado' in partes:
            coletar_senado(http, ref, args.saida, sen_ex)
        if 'sexo' in partes:
            coletar_sexo(http, ref, args.saida)
    except DadoSuspeito as e:
        log(f'PARADO, nada foi sobrescrito nesta parte: {e}')
        sys.exit(2)
    log(f'Concluído com {http.calls} chamadas.')


if __name__ == '__main__':
    main()
