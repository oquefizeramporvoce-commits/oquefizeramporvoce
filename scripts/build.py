"""Normaliza os dados brutos da Câmara e do Senado num modelo único para o site.

Entrada:  raw/camara.json, raw/senado.json (exportados das APIs de dados abertos)
Saída:    site/data/core.json (agregados, parlamentares, votações)
          site/data/props.json (todas as proposições)
"""
import json, re, sys, unicodedata, collections, datetime, os

ROOT = sys.argv[1]
LEG_START = '2023-02-01'
STALL_DAYS = 180

cam = json.load(open(os.path.join(ROOT, 'raw/camara.json'), encoding='utf-8'))
sen = json.load(open(os.path.join(ROOT, 'raw/senado.json'), encoding='utf-8'))
# data de referência: a da coleta (raw/camara.json), para "parado há mais de 6 meses" contar a partir dela
REF = datetime.date.fromisoformat(cam['ref'])

SIGLAS = ['PL', 'PLP', 'PEC']
BUCKETS = ['lei', 'apr', 'and', 'par', 'ape', 'enc']
TEMAS = ['saude', 'educacao', 'seguranca', 'economia', 'direitos', 'ambiente', 'cidades', 'politica', 'outros']

# ---------- helpers ----------
def days_since(d):
    if not d:
        return 99999
    try:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        return (REF - datetime.date(y, m, dd)).days
    except Exception:
        return 99999

def dint(d):
    return int(d[:4] + d[5:7] + d[8:10]) if d and len(d) >= 10 else 0

def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()

PARTY_FIX = {'REPUBLIC': 'REPUBLICANOS', 'SOLIDARI': 'SOLIDARIEDADE', 'PODEMOS': 'PODE', 'S.PART.': 'Sem partido', 'S/Partido': 'Sem partido', '': ''}
def party(p):
    p = (p or '').strip()
    return PARTY_FIX.get(p, p)

# ---------- Câmara: buckets e temas ----------
C_LEI = {'Transformado em Norma Jurídica'}
C_APR = {'Aguardando Apreciação pelo Senado Federal', 'Aguardando Autógrafos na Mesa', 'Aguardando Sanção',
         'Aguardando Apreciação do Veto', 'Aguardando Envio ao Senado Federal', 'Aguardando Envio à Redação Final',
         'Aguardando Redação Final', 'Aguardando Promulgação'}
C_ENC = {'Arquivada', 'Retirado pelo(a) Autor(a)', 'Devolvida ao(à) Autor(a)', 'Transformado em nova proposição',
         'Vetado Totalmente', 'Perdeu a Eficácia', 'Rejeitada'}

def c_bucket(ss, sd):
    if ss in C_LEI: return 'lei'
    if ss in C_APR: return 'apr'
    if ss in C_ENC: return 'enc'
    if ss == 'Tramitando em Conjunto': return 'ape'
    return 'par' if days_since(sd) > STALL_DAYS else 'and'

C_TEMA = {56: 'saude', 46: 'educacao', 57: 'seguranca', 43: 'seguranca', 40: 'economia', 58: 'economia', 66: 'economia',
          70: 'economia', 64: 'economia', 67: 'economia', 51: 'economia', 60: 'economia', 44: 'direitos', 52: 'direitos',
          42: 'direitos', 48: 'ambiente', 54: 'ambiente', 41: 'cidades', 61: 'cidades', 34: 'politica', 53: 'politica',
          74: 'politica', 68: 'politica', 76: 'politica'}

# ---------- Senado: buckets e temas ----------
def s_bucket(sit, tram, sitd):
    s = (sit or '').upper()
    if s.startswith('TRANSFORMADA EM NORMA JUR'): return 'lei'
    if s in ('REMETIDA À CÂMARA DOS DEPUTADOS', 'APROVADA') or 'SANÇÃO' in s or 'PROMULGA' in s: return 'apr'
    if tram == 'Não' or s in ('VETADA', 'REJEITADA', 'PREJUDICADA', 'RETIRADA PELO AUTOR', 'IMPUGNADA', 'ARQUIVADA'): return 'enc'
    return 'par' if days_since(sitd) > STALL_DAYS else 'and'

S_RULES = [
    ('saude', ['saúde']),
    ('educacao', ['educação']),
    ('seguranca', ['segurança pública', 'direito penal', 'soberania, defesa nacional', 'defesa nacional', 'penitenci']),
    ('ambiente', ['meio ambiente', 'minas e energia', 'recursos hídricos', 'energia']),
    ('cidades', ['transporte', 'trânsito', 'desenvolvimento urbano', 'habitação', 'saneamento', 'viação', 'política urbana']),
    ('economia', ['trabalho e emprego', 'tribut', 'agricultura', 'pecuária', 'finanças públicas', 'indústria, comércio',
                  'desenvolvimento regional', 'atividade econômica', 'consumidor', 'turismo', 'sistema financeiro',
                  'orçamento', 'política fundiária', 'economia e desenvolvimento']),
    ('direitos', ['proteção social', 'previdência', 'assistência social', 'direitos humanos', 'direito civil', 'família',
                  'idosos', 'pessoas com deficiência', 'crianças', 'mulher', 'minorias']),
    ('politica', ['administração pública', 'organização do estado', 'eleitoral', 'processo legislativo', 'jurídico',
                  'partidos', 'licitação']),
]
def s_temas(cls):
    out = []
    for h in cls or []:
        low = h.lower()
        hit = None
        # ciência e tecnologia, cultura, esporte e comunicações ficam em "outros" mesmo sob Economia/Política Social
        if any(k in low for k in ['ciência, tecnologia', 'cultura', 'desporto', 'comunicaç', 'honor', 'relações internacionais', 'datas comemorativas']):
            hit = 'outros'
        else:
            for tema, keys in S_RULES:
                if any(k in low for k in keys):
                    hit = tema; break
        hit = hit or 'outros'
        if hit not in out: out.append(hit)
    return out or ['outros']

# ---------- subtópicos (palavras-chave da ementa) ----------
SUBS = {
 'saude': [('SUS, hospitais e atendimento', r'sistema unico de saude|\bsus\b|hospita|atencao (basica|primaria)|unidades? (basicas? )?de saude|pronto.?socorro|atendimento'),
           ('Remédios e vacinas', r'medicament|farmac|remedio|vacin|imuniza'),
           ('Doenças e tratamentos', r'doenca|cancer|oncolog|diabet|sindrome|alzheimer|\bhiv\b|esclerose|fibromialg|autis|tratamento|diagnost|rastreamento'),
           ('Saúde mental', r'saude mental|psicolog|psiquiatr|suicid|depress|dependencia quimica'),
           ('Planos de saúde', r'planos? (privados? )?de (assistencia a )?saude|operadoras?'),
           ('Profissionais de saúde', r'\bmedic[oa]s?\b|enfermag|profissionais (da|de) saude|agentes? comunitari|piso salarial'),
           ('Gestantes, mães e bebês', r'gestante|gravidez|parto|matern|amamenta|recem.?nascid|neonat|teste do pezinho')],
 'educacao': [('Escolas e educação básica', r'educacao basica|ensino fundamental|ensino medio|escola|educacao infantil|creche'),
           ('Universidades', r'ensino superior|universidad|faculdade|\bfies\b|prouni|pos.?graduacao|bolsas? de estudo'),
           ('Professores', r'professor|magisterio|docente|profissionais da educacao'),
           ('Inclusão e educação especial', r'deficiencia|inclus|autis|educacao especial|libras|altas habilidades'),
           ('Currículo e conteúdo', r'curricul|disciplina|conteudo|diretrizes e bases|9\.394|base nacional comum|alfabetiza'),
           ('Merenda, transporte e material', r'merenda|alimentacao escolar|transporte escolar|uniforme|material escolar|livro didatico'),
           ('Ensino técnico', r'profissional e tecnolog|ensino tecnico|aprendiz|qualificacao profissional')],
 'seguranca': [('Crimes e penas', r'codigo penal|2\.848|\bpenas?\b|crime|tipifica|homicid|hediondo|furto|roubo|estelionato'),
           ('Armas', r'\barmas?\b|municao|desarmamento|10\.826'),
           ('Violência contra a mulher', r'violencia domestica|maria da penha|11\.340|feminicid|violencia contra a mulher|medidas? protetiva'),
           ('Proteção de crianças', r'crianca|adolescente|pedofil|abuso sexual|vulneravel|8\.069'),
           ('Polícias e guardas', r'polic|guardas? municipa|bombeir|seguranca publica|agentes de seguranca|militar'),
           ('Drogas', r'droga|entorpecente|trafico|11\.343'),
           ('Prisões', r'prisao|prisional|penitenci|execucao penal|7\.210|presos?\b|detent|carcer'),
           ('Crimes na internet', r'internet|digital|ciber|redes sociais|inteligencia artificial|eletronic|golpe|dados pessoais')],
 'economia': [('Impostos', r'imposto|tribut|aliquota|contribuic|icms|\bipi\b|imposto de renda|simples nacional|isencao|incentivo fiscal'),
           ('Trabalho e salário', r'trabalh|\bclt\b|consolidacao das leis do trabalho|emprego|salari|ferias|jornada|sindic|fgts|seguro.?desemprego'),
           ('Agro e pesca', r'agricult|agropecu|\brural|produtor|pesca|safra|agrotox|pecuar|cooperativ'),
           ('Consumidor, bancos e crédito', r'consumidor|8\.078|\bbancos?\b|bancari|credito|juros|cartao|tarifa|financiament|endividamento'),
           ('Empresas e comércio', r'microempres|empreend|\bmei\b|empresa|comerci|industria|franquia|startup'),
           ('Contas públicas', r'orcament|fiscal|responsabilidade fiscal|divida|despesas?|receita|fundos?\b|precatori'),
           ('Turismo', r'turis')],
 'direitos': [('Pessoas com deficiência', r'deficiencia|autis|\btea\b|acessibil|libras|mobilidade reduzida'),
           ('Idosos', r'idos|terceira idade|10\.741'),
           ('Crianças e jovens', r'crianca|adolescente|infan|8\.069|juventude|jove(m|ns)'),
           ('Mulheres', r'mulher|gestante|matern|violencia domestica|igualdade salarial|genero'),
           ('Aposentadoria e benefícios', r'previd|aposent|\binss\b|beneficio|assistencia social|bolsa familia|\bbpc\b|loas|8\.742|8\.213|pensao por morte'),
           ('Família e direito civil', r'codigo civil|10\.406|familia|casamento|divorcio|alimentos|heranca|adocao|registro civil|guarda'),
           ('Igualdade e minorias', r'racial|racismo|indigen|quilombol|lgbt|discrimina|povos e comunidades|ciganos')],
 'ambiente': [('Energia e combustíveis', r'energia|eletric|combustiv|petroleo|gas natural|solar|biocombust|hidrel|hidrogenio'),
           ('Mineração', r'minera|mineral|garimp'),
           ('Florestas e clima', r'flores|desmat|amazon|clima|carbono|emiss|queimad|incendio|bioma|cerrado|pantanal'),
           ('Animais', r'anima|fauna|maus.?tratos|\bcaes\b|gatos|pet\b|silvestre'),
           ('Água, lixo e saneamento', r'\bagua|saneamento|residuos|lixo|recursos hidricos|esgoto|\brios?\b|reciclage|plastico'),
           ('Licenças e áreas protegidas', r'licenciamento|unidades? de conservacao|preservacao permanente|codigo florestal|12\.651|reserva legal')],
 'cidades': [('Trânsito e motoristas', r'transito|9\.503|\bcnh\b|habilitacao|multa|veicul|motorista|motocic|bicicleta|pedestre'),
           ('Transporte e estradas', r'transporte|onibus|metro|rodovi|ferrovi|aviacao|aeroport|aere|portos?\b|frete|aquavi'),
           ('Moradia e imóveis', r'habitac|moradia|minha casa|imove|aluguel|locac|condomin|regularizacao fundiaria'),
           ('Vida na cidade', r'urban|municipi|cidade|plano diretor|mobilidade|calcad|iluminacao|desastre|defesa civil'),
           ('Nomes de rodovias e obras', r'denomina|\bnome\b')],
 'politica': [('Eleições e partidos', r'eleit|eleic|partid|campanha|9\.504|4\.737|candidat'),
           ('Servidores públicos', r'servidor|cargos?\b|concurso|carreira|remuneracao|8\.112|funcoes comissionadas'),
           ('Transparência e combate à corrupção', r'transparen|acesso a informacao|improbid|corrup|licitac|14\.133|tribunal de contas|fiscaliza|controle'),
           ('Justiça e tribunais', r'processo civil|processo penal|judici|tribunal|\bjuiz|magistra|ministerio publico|defensoria|advoca|varas?\b'),
           ('Constituição e Congresso', r'constituicao|congresso|parlament|regimento|mandato'),
           ('Organização do governo', r'administracao publica|orgaos?\b|autarquia|agencia reguladora|ministerio|estatal|federativ')],
 'outros': [('Homenagens e datas', r'denomina|declara|patrono|heroi|dia nacional|semana nacional|calendario|data comemorativa|institui o dia|capital nacional|inscreve o nome|livro dos herois|honor'),
           ('Cultura', r'cultur|artist|patrimonio|musica|cinema|livro|leitura|audiovisual|festa'),
           ('Esporte e apostas', r'esport|desport|atleta|futebol|apost|olimp|loteri'),
           ('Tecnologia e internet', r'tecnolog|internet|digital|dados pessoais|inteligencia artificial|telecom|ciencia|pesquisa|inovac|software|plataformas?'),
           ('Rádio, TV e imprensa', r'radio|televis|radiodifus|imprensa|jornal|publicidade'),
           ('Religião', r'relig|igreja|templo|culto|evangel|catolic'),
           ('Relações com outros países', r'internacional|estrangeir|tratado|exterior|fronteir|migra')],
}
SUB_CAT = []           # [indice do assunto, nome]
SUB_RX = {}
for t in TEMAS:
    SUB_RX[t] = []
    for label, rx in SUBS[t]:
        SUB_RX[t].append((len(SUB_CAT), re.compile(rx)))
        SUB_CAT.append([TEMAS.index(t), label])
    SUB_RX[t].append((len(SUB_CAT), None))
    SUB_CAT.append([TEMAS.index(t), 'Outros'])

LAWS = {'9.656':'planos de saude','2.848':'codigo penal crime','8.213':'previdencia aposentadoria','14.133':'licitacao',
 '9.503':'transito','8.906':'advocacia tribunal','14.790':'apostas','9.394':'diretrizes e bases escola','7.565':'aviacao',
 '8.069':'crianca adolescente','13.146':'deficiencia','8.742':'assistencia social','101':'responsabilidade fiscal orcamento',
 '11.340':'violencia domestica','5.452':'clt trabalho','7.210':'execucao penal prisao','64':'eleicoes candidato','9.605':'crimes ambientais fauna flores',
 '10.741':'idoso','13.105':'processo civil','3.689':'processo penal','8.080':'sistema unico de saude','8.072':'crime hediondo','6.015':'registro civil',
 '8.078':'consumidor','9.250':'imposto de renda','7.713':'imposto de renda','5.172':'tributario imposto','9.294':'publicidade','11.343':'drogas',
 '4.595':'bancos credito','12.529':'concorrencia empresas','8.429':'improbidade','12.846':'corrupcao','9.613':'lavagem crime','4.737':'eleicoes',
 '9.504':'eleicoes','9.096':'partidos','8.112':'servidor','10.406':'codigo civil familia','9.099':'juizados tribunal','13.709':'dados pessoais',
 '12.965':'internet','14.601':'bolsa familia beneficio','6.001':'indigenas','11.445':'saneamento','9.434':'transplantes tratamento',
 '9.433':'recursos hidricos','12.305':'residuos','6.938':'licenciamento','10.257':'urbana cidade','9.472':'telecom','9.615':'desporto',
 '14.597':'esporte','10.826':'armas','13.756':'loterias fundo seguranca publica','12.587':'mobilidade urbana','9.430':'eleicoes'}
LAW_RX = re.compile(r'(?:lei|decreto-lei)s?(?: complementar)?\s*n[^\d]{0,4}([\d\.]+)')

def subtopics(temas, ementa):
    txt = norm_keep(ementa)
    txt += ' ' + ' '.join(LAWS.get(m.rstrip('.'), '') for m in LAW_RX.findall(txt))
    out = []
    for t in temas:
        hit = [i for i, rx in SUB_RX[t] if rx is not None and rx.search(txt)]
        out += hit or [SUB_RX[t][-1][0]]
    return out

def norm_keep(s):
    s = unicodedata.normalize('NFD', s or '')
    return ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn').lower()

# ---------- tabela de parlamentares ----------
parl = {}       # ('CD', id) / ('SF', cod) -> dict
def add_parl(casa, pid, nome, pt, uf, strong=False):
    if not pid: return None
    k = (casa, int(pid))
    cur = parl.get(k)
    if cur is None:
        parl[k] = {'casa': casa, 'id': int(pid), 'nome': nome, 'pt': party(pt), 'uf': uf or '', 'strong': strong}
    else:
        if strong or not cur['strong']:
            if nome: cur['nome'] = nome
            if pt: cur['pt'] = party(pt)
            if uf: cur['uf'] = uf
            cur['strong'] = cur['strong'] or strong
    return k

# autores (registro mais fraco: partido da época da apresentação)
for p in cam['props']:
    for a in p[10]:
        if a[3] == 'D' and a[4]:
            add_parl('CD', a[4], a[0], a[1], a[2])
for pr in sen['procs']:
    for a in pr['aut']:
        if a[2] == 'SENADOR' and a[3]:
            add_parl('SF', a[3], a[0], a[1], a[4])
# votantes (registro mais forte e mais recente; a lista já vem em ordem cronológica)
for did, (nome, pt, uf) in cam['deps'].items():
    add_parl('CD', did, nome, pt, uf, strong=True)
for v in sorted(sen['vots'], key=lambda v: (v['data'], v['seq'] or 0)):
    for cod, nome, pt, uf, voto in v['v']:
        add_parl('SF', cod, nome, pt, uf, strong=True)

by_name = {}
for k, d in parl.items():
    by_name.setdefault((k[0], norm(d['nome'])), k)

# ---------- linhas ----------
rows = {}   # key -> row dict
def key_of(sigla, num, ano):
    return (sigla, int(num), int(ano))

collisions = 0
# Câmara
for p in cam['props']:
    pid, t, n, a, e, da, sd, ss, so, temas, aus, naut = p
    if t not in SIGLAS: continue
    tipo = aus[0][3] if aus else 'O'
    origem = {'D': 'CD', 'S': 'SF'}.get(tipo, 'OUT')
    autores = []
    for nome, pt, uf, tp, did in aus:
        if tp == 'D' and did:
            autores.append(('CD', int(did)))
        elif tp == 'S':
            nm = re.sub(r'^Senado Federal\s*-\s*', '', nome).strip()
            k = by_name.get(('SF', norm(nm)))
            autores.append(k if k else [nm if nm != nome else nome, party(pt), uf])
        else:
            autores.append([nome, party(pt), uf])
    macro = []
    for c in temas:
        m = C_TEMA.get(c, 'outros')
        if m not in macro: macro.append(m)
    r = {'sigla': t, 'num': int(n), 'ano': int(a), 'origem': origem, 'idCD': pid, 'codSF': 0, 'ementa': e,
         'temas': macro or ['outros'], 'autores': autores, 'naut': naut, 'da': da, 'tipo1': tipo,
         'cs': ss, 'cd': sd, 'co': so, 'cb': c_bucket(ss, sd), 'ss': None, 'sd': '', 'sb': None, 'apelido': ''}
    k = key_of(t, n, a)
    if k in rows:
        collisions += 1
        k = k + (pid,)
    rows[k] = r

# Senado: agrupa fases (Iniciadora/Revisora + Substitutivo/Emenda) pela identificação
sgroups = collections.defaultdict(list)
for pr in sen['procs']:
    if pr['sigla'] not in SIGLAS or not pr['num'] or not pr['ano']: continue
    sgroups[key_of(pr['sigla'], pr['num'], pr['ano'])].append(pr)

idp_to_key = {}
merged = sen_only = unlinked = 0
for k, grp in sgroups.items():
    main = [g for g in grp if g['obj'] in ('Iniciadora', 'Revisora')] or grp
    main = sorted(main, key=lambda g: g['sitd'] or '')[-1]
    latest = sorted(grp, key=lambda g: g['sitd'] or '')[-1]
    # se alguma fase virou lei, vale ela
    for g in grp:
        if s_bucket(g['sit'], g['tram'], g['sitd']) == 'lei':
            latest = g
    sb = s_bucket(latest['sit'], latest['tram'], latest['sitd'])
    tipo1 = (main['aut'][0][2] if main['aut'] else '')
    if not tipo1 and main.get('autoria', '').startswith('Senador'): tipo1 = 'SENADOR'
    if not tipo1 and main.get('autoria', '').startswith('Câmara'): tipo1 = 'DEPUTADO'
    s_origem = 'SF' if tipo1 == 'SENADOR' else ('CD' if (tipo1 in ('DEPUTADO', 'COMISSAO_CAMARA') or main['obj'] == 'Revisora' and main.get('casaIni') == 'CD') else 'OUT')
    row = rows.get(k)
    link = False
    if row is not None:
        if row['tipo1'] == 'S' and main['obj'] == 'Iniciadora': link = True
        elif row['tipo1'] != 'S' and main['obj'] == 'Revisora': link = True
    if link:
        merged += 1
        row['codSF'] = main['cod']; row['ss'] = latest['sit']; row['sd'] = latest['sitd'] or ''; row['sb'] = sb
        row['apelido'] = main['apelido'] or ''
        if row['tipo1'] == 'S':
            # autoria mais completa vem do Senado
            aut = []
            for nome, pt, tp, cod, uf in main['aut']:
                if tp == 'SENADOR' and cod: aut.append(('SF', int(cod)))
                else: aut.append([nome, party(pt), uf])
            if aut: row['autores'] = aut; row['naut'] = main['nAut'] or len(aut)
            if main['da']: row['da'] = main['da']
        for t in s_temas(main['cls']):
            if t not in row['temas'] and row['temas'] == ['outros']:
                row['temas'] = [t]
        tk = k
    else:
        if row is not None: unlinked += 1
        sen_only += 1
        aut = []
        for nome, pt, tp, cod, uf in main['aut']:
            if tp == 'SENADOR' and cod: aut.append(('SF', int(cod)))
            elif tp == 'DEPUTADO':
                kk = by_name.get(('CD', norm(nome)))
                aut.append(kk if kk else [nome, party(pt), uf])
            else: aut.append([nome, party(pt), uf])
        if not aut and main.get('autoria'):
            aut = [[main['autoria'][:80], '', '']]
        r = {'sigla': main['sigla'], 'num': int(main['num']), 'ano': int(main['ano']), 'origem': s_origem, 'idCD': 0,
             'codSF': main['cod'], 'ementa': main['ementa'], 'temas': s_temas(main['cls']), 'autores': aut,
             'naut': main['nAut'] or len(aut), 'da': main['da'] or '', 'tipo1': {'SENADOR': 'S', 'DEPUTADO': 'D'}.get(tipo1, 'O'),
             'cs': None, 'cd': '', 'co': '', 'cb': None, 'ss': latest['sit'], 'sd': latest['sitd'] or '', 'sb': sb,
             'apelido': main['apelido'] or ''}
        tk = k if row is None else k + ('s',)
        rows[tk] = r
    for g in grp:
        idp_to_key[g['id']] = tk

# bucket final
def final_bucket(r):
    cb, sb = r['cb'], r['sb']
    if 'lei' in (cb, sb): return 'lei'
    if r['origem'] == 'SF': ob, xb = sb, cb
    else:
        ob, xb = cb, sb
        if ob is not None and not (r['ss'] or '').strip(): xb = None   # Senado sem situação informada: vale a da Câmara
    if ob is None:            # só existe na Casa revisora: a Casa de origem já aprovou
        return 'enc' if xb == 'enc' else 'apr'
    if xb is None: return ob
    if xb == 'enc' or ob == 'enc': return 'enc'
    return 'apr'

for r in rows.values():
    r['b'] = final_bucket(r)
    has_origin = (r['origem'] == 'SF' and r['codSF']) or (r['origem'] == 'CD' and r['idCD']) or r['origem'] == 'OUT'
    r['leg'] = 1 if (r['da'] or '') >= LEG_START and r['ano'] >= 2023 and has_origin else 0

# ---------- ordenação e índices ----------
order = sorted(rows.keys(), key=lambda k: (-rows[k]['ano'], SIGLAS.index(rows[k]['sigla']), -rows[k]['num']))
row_index = {k: i for i, k in enumerate(order)}
cd_row = {rows[k]['idCD']: i for k, i in row_index.items() if rows[k]['idCD']}

# garante que todo autor referenciado esteja na tabela
for r in rows.values():
    for a in r['autores']:
        if isinstance(a, tuple): assert a in parl, a

parl_keys = sorted(parl.keys(), key=lambda k: (norm(parl[k]['nome']), k[0], k[1]))
parl_idx = {k: i for i, k in enumerate(parl_keys)}
house_list = {'CD': [k for k in parl_keys if k[0] == 'CD'], 'SF': [k for k in parl_keys if k[0] == 'SF']}
house_pos = {h: {k: i for i, k in enumerate(lst)} for h, lst in house_list.items()}

# ---------- agregados ----------
def zero(): return [0] * 6
agg = {h: {'tot': zero(), 'temas': {t: zero() for t in TEMAS}} for h in ('CD', 'SF')}
pstats = {k: zero() for k in parl_keys}
ptemas = {k: [0] * len(TEMAS) for k in parl_keys}
for r in rows.values():
    if not r['leg'] or not r['autores']: continue
    a0 = r['autores'][0]
    if not isinstance(a0, tuple): continue
    h = a0[0]
    if r['origem'] != h: continue
    bi = BUCKETS.index(r['b'])
    agg[h]['tot'][bi] += 1
    for t in r['temas']:
        agg[h]['temas'][t][bi] += 1
    pstats[a0][bi] += 1
    for t in r['temas']:
        ptemas[a0][TEMAS.index(t)] += 1

# ---------- votações ----------
def c_is_pl(v):
    i = cd_row.get(v['pid'])
    return i is not None
c_last = {}
for v in cam['vots']:
    if not c_is_pl(v): continue
    c_last[v['pid']] = v          # lista em ordem cronológica: fica a última votação do texto principal
votes = []
for pid, v in c_last.items():
    arr = ['0'] * len(house_list['CD'])
    pairs = v['v']
    for i in range(0, len(pairs), 2):
        arr[house_pos['CD'][('CD', int(pairs[i]))]] = str(pairs[i + 1])
    votes.append({'id': 'c' + v['id'], 'casa': 0, 'row': cd_row[pid], 'data': dint(v['data']), 'desc': v['desc'],
                  'res': 1 if v['apr'] == 1 else 0, 'v': ''.join(arr)})

S_CODE = {'Sim': '1', 'Não': '2', 'Abstenção': '3', 'Presidente (art. 51 RISF)': '5', 'P-NRV': '6',
          'AP': '7', 'LS': '7', 'MIS': '7', 'LP': '7', 'LAP': '7', 'NA': '7', 'NCom': '8'}
def s_is_main(v):
    d = v['desc']
    if re.search(r'destacad|Requerimento', d, re.I): return False
    if re.search(r'Emenda', d) and 'Substitutiv' not in d and 'Emenda à Constituição' not in d: return False
    if re.search(r'Emendas? nº', d) and 'Substitutiv' not in d: return False
    return True
s_last = {}
for v in sorted(sen['vots'], key=lambda v: (v['data'], v['seq'] or 0)):
    if not s_is_main(v) or v['idp'] not in idp_to_key: continue
    s_last[idp_to_key[v['idp']]] = v
for k, v in s_last.items():
    arr = ['0'] * len(house_list['SF'])
    for cod, nome, pt, uf, voto in v['v']:
        arr[house_pos['SF'][('SF', int(cod))]] = S_CODE.get(voto, '0')
    votes.append({'id': 's' + str(v['seq']), 'casa': 1, 'row': row_index[k], 'data': dint(v['data']), 'desc': v['desc'],
                  'res': 1 if v['res'] == 'A' else 0, 'v': ''.join(arr)})
votes.sort(key=lambda v: -v['data'])

# ---------- saída ----------
sit_tab, org_tab = [], []
def tab(lst, s):
    if s is None or s == '': return -1
    try: return lst.index(s)
    except ValueError:
        lst.append(s); return len(lst) - 1

def trim(s, n=160):
    s = s or ''
    if len(s) <= n: return s
    t = s[:n]; k = t.rfind(' ')
    return (t[:k] if k > n * 0.6 else t).rstrip(' ,;.…') + '…'

def cap_first(s):
    s = s or ''
    return s[:1] + s[1:].lower() if s.isupper() else s

out_rows = []
for k in order:
    r = rows[k]
    mask = 0
    for t in r['temas']: mask |= 1 << TEMAS.index(t)
    aut = [parl_idx[a] if isinstance(a, tuple) else a for a in r['autores'][:3]]
    out_rows.append([SIGLAS.index(r['sigla']), r['num'], r['ano'], {'CD': 0, 'SF': 1, 'OUT': 2}[r['origem']], r['idCD'], r['codSF'] or 0,
                     r['ementa'], mask, aut, r['naut'], dint(r['da']), BUCKETS.index(r['b']),
                     tab(sit_tab, r['cs']), dint(r['cd']), tab(org_tab, r['co']),
                     tab(sit_tab, cap_first(r['ss']) if r['ss'] else None), dint(r['sd']), r['apelido'], r['leg'], subtopics(r['temas'], r['ementa'] + ' ' + r['apelido'])])

# lista oficial de quem está em exercício (Câmara /deputados e Senado /senador/lista/atual)
EXE = {}
_ex_path = os.path.join(ROOT, 'raw/exercicio.json')
if os.path.exists(_ex_path):
    _ex = json.load(open(_ex_path, encoding='utf-8'))
    for i, nome, pt, uf in _ex['dep']: EXE[('CD', int(i))] = (party(pt), uf)
    for i, nome, pt, uf in _ex['sen']: EXE[('SF', int(i))] = (party(pt), uf)
# presença: Câmara (sessões deliberativas do Plenário) e Senado (dias com votação nominal + licenças)
PRES_C, PRES_S, PRES_REF = {}, {}, {}
_pc = os.path.join(ROOT, 'raw/presenca_camara.json')
if os.path.exists(_pc):
    _d = json.load(open(_pc, encoding='utf-8'))
    PRES_C = {int(k): v for k, v in _d['dep'].items()}
    PRES_REF['cd'] = {'sessoes': _d['sessoes'], 'porAno': _d['porAno'], 'ultima': _d['ultimaSessao']}
_ps = os.path.join(ROOT, 'raw/presenca_senado.json')
if os.path.exists(_ps):
    _d = json.load(open(_ps, encoding='utf-8'))
    PRES_S = {int(k): v for k, v in _d['sen'].items()}
    LIC_S = {int(k): v for k, v in _d['lic'].items()}
    PRES_REF['sf'] = {'dias': _d['diasVotacao'], 'votacoes': _d['votacoes']}
else:
    LIC_S = {}

_sx = os.path.join(ROOT, 'raw/sexo.json')
SEXO = json.load(open(_sx)) if os.path.exists(_sx) else {'dep': {}, 'sen': {}}
def sexo(k):
    v = (SEXO['dep'] if k[0] == 'CD' else SEXO['sen']).get(str(k[1]))
    return 'F' if v == 'F' else ('M' if v == 'M' else '')

def presenca(k):
    casa, pid = k
    if casa == 'CD':
        v = PRES_C.get(pid)
        return [0, v[0], v[1], v[4]] if v else None
    v = PRES_S.get(pid); l = LIC_S.get(pid) or {}
    if not v and not l: return None
    v = v or {'pres': 0, 'just': 0, 'falta': 0, 'dias': 0}
    return [1, v['pres'], v['just'], v['falta'], v['dias'], l.get('saude', 0), l.get('particular', 0), l.get('missao', 0), l.get('outra', 0)]

out_parl = []
for k in parl_keys:
    d = parl[k]
    ex = EXE.get(k)
    if ex: d['pt'], d['uf'] = ex[0] or d['pt'], ex[1] or d['uf']
    out_parl.append([d['id'], 0 if k[0] == 'CD' else 1, d['nome'], d['pt'], d['uf']] + pstats[k] + [1 if (ex or d['strong'] or sum(pstats[k])) else 0, ptemas[k], 1 if ex else 0, presenca(k), sexo(k)])

core = {'ref': REF.isoformat(), 'legStart': LEG_START, 'stallDays': STALL_DAYS, 'temas': TEMAS, 'buckets': BUCKETS,
        'agg': {'cd': agg['CD'], 'sf': agg['SF']}, 'parl': out_parl, 'votes': votes,
        'nRows': len(out_rows), 'subs': SUB_CAT, 'presRef': PRES_REF}
os.makedirs(os.path.join(ROOT, 'site/data'), exist_ok=True)
json.dump(core, open(os.path.join(ROOT, 'site/data/core.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
json.dump({'sit': sit_tab, 'org': org_tab, 'rows': out_rows}, open(os.path.join(ROOT, 'site/data/props.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

# ---------- relatório ----------
print('linhas', len(out_rows), '| colisões CD', collisions, '| fundidas CD+SF', merged, '| só Senado', sen_only, '| mesma chave sem vínculo', unlinked)
print('parlamentares', len(out_parl), {h: len(l) for h, l in house_list.items()})
print('votações', len(votes), collections.Counter(v['casa'] for v in votes))
for h in ('CD', 'SF'):
    print(h, 'total', sum(agg[h]['tot']), dict(zip(BUCKETS, agg[h]['tot'])))
    for t in TEMAS: print('   ', t, agg[h]['temas'][t])
print('origem', collections.Counter(r['origem'] for r in rows.values()))
print('bucket geral', collections.Counter(r['b'] for r in rows.values()))
print('temas Senado não mapeados (outros):', collections.Counter(h for pr in sen['procs'] for h in pr['cls'] if s_temas([h]) == ['outros']).most_common(25))
print('tamanhos', os.path.getsize(os.path.join(ROOT, 'site/data/core.json')), os.path.getsize(os.path.join(ROOT, 'site/data/props.json')))


cnt = collections.Counter(i for r in out_rows for i in r[19])
for t in TEMAS:
    ids=[i for i,(ti,l) in enumerate(SUB_CAT) if TEMAS[ti]==t]
    tot=sum(1 for r in out_rows if r[7] & (1<<TEMAS.index(t)))
    print(t, tot, ' | '.join(f"{SUB_CAT[i][1]}={cnt[i]}" for i in ids))
