# O que eles fizeram por você

Protótipo de site que mostra o que deputados federais e senadores propuseram, o que foi aprovado e como cada um votou, com dados abertos da Câmara dos Deputados e do Senado Federal.

## Estrutura

```
raw/                  dados brutos coletados das APIs em 13/11/2026
  camara.json         proposições (PL, PLP, PEC 2023–2026), autores, temas e votações nominais da Câmara
  senado.json         processos e votações nominais do Senado
  exercicio.json      listas oficiais de deputados e senadores em exercício
  presenca_camara.json  presença nas sessões deliberativas do Plenário e em comissões, por deputado
  presenca_senado.json  comparecimento nos dias de votação nominal e licenças, por senador
scripts/
  build.py            normaliza raw/ e gera site/data/core.json e site/data/props.json
  brazil-map.json     contornos dos estados (SVG Maps, Victor Cazanave, CC BY 4.0)
  shots.py            capturas de tela das páginas para conferência (Playwright)
  shots_home.py       capturas da página inicial (mapa)
  audit.py            percorre todas as páginas e aponta erros, textos quebrados e links sem destino
  assemble.py         remonta exportações em partes feitas pelo navegador (uso interno da coleta)
  extract.py          auxiliar do assemble.py
site/                 o site: uma página só, sem build
  index.html          HTML, CSS e JavaScript
  data/core.json      parlamentares, agregados, subtópicos e votações
  data/props.json     cerca de 25 mil proposições
  data/map.json       mapa do Brasil por estado
```

## Rodar localmente

```bash
python3 scripts/build.py .          # regenera site/data a partir de raw/
python3 -m http.server 8000 --directory site
# abra http://localhost:8000
```

`build.py` usa só a biblioteca padrão do Python.

## Fontes

- Câmara: https://dadosabertos.camara.leg.br (API v2 e arquivos anuais `proposicoes`, `proposicoesTemas`, `proposicoesAutores`, além de `/votacoes` e `/votacoes/{id}/votos`)
- Senado: https://legis.senado.leg.br/dadosabertos (`/processo`, `/processo/{id}`, `/votacao`)

## Regras principais (em build.py)

- Situação: virou lei, passou em uma Casa, em andamento, parado (mais de 180 dias sem movimentação), anexado a outro, encerrado.
- Assuntos: 9 grupos a partir dos temas oficiais da Câmara e das classificações do Senado; subtópicos por palavras-chave da ementa e pelas leis citadas.
- Votações: última votação nominal do texto principal de cada projeto em cada Casa.
- Contagens por parlamentar: projetos em que é autor principal, apresentados desde 01/02/2023.

## Recursos que só funcionam no claude.ai

Os resumos em linguagem simples usam as capacidades `sample` (gera o texto com IA) e `db` (guarda o resumo para os próximos visitantes) do artefato publicado. Rodando localmente, essa seção simplesmente não aparece.

## O que falta

- Coleta automática diária (hoje os dados são uma foto de 13/11/2026)
- Custo dos projetos
- Assembleias estaduais e câmaras municipais
