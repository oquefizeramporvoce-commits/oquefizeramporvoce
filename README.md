# O que eles fizeram por você

Site que mostra o que deputados federais e senadores propuseram, o que foi aprovado e como cada um votou, com dados abertos da Câmara dos Deputados e do Senado Federal.

## Estrutura

```
raw/                    dados brutos das APIs (um registro por linha, para o histórico do Git mostrar o que mudou)
  camara.json           proposições (PL, PLP, PEC desde 2023), autores, temas e votações nominais da Câmara
  senado.json           processos e votações nominais do Senado
  exercicio.json        listas oficiais de deputados e senadores em exercício
  presenca_camara.json  presença nas sessões deliberativas do Plenário e em comissões, por deputado
  presenca_senado.json  comparecimento nos dias de votação nominal e licenças, por senador
  sexo.json             sexo informado pela Câmara e pelo Senado (para "Deputada"/"Deputado")
scripts/
  coletar.py            baixa tudo das APIs e grava raw/
  build.py              normaliza raw/ e gera site/data/core.json e site/data/props.json
  gerar_resumos.py      (opcional) rascunhos de resumos com IA para revisão humana
  audit.py              percorre todas as páginas e aponta erros e links sem destino (Playwright)
  shots.py, shots_home.py  capturas de tela para conferência
site/                   o site: uma página só, sem etapa de build de front-end
.github/workflows/      atualização semanal e publicação no GitHub Pages
```

## Atualização automática

O workflow `.github/workflows/atualizar-e-publicar.yml` roda toda segunda-feira às 6h17 (Brasília):

1. `scripts/coletar.py` baixa os dados das APIs.
2. `scripts/build.py .` gera os arquivos do site.
3. Se algo mudou, grava um commit "Dados atualizados em DD/MM/AAAA".
4. Publica a pasta `site/` no GitHub Pages.

Para rodar na hora: aba **Actions** > **Atualizar dados e publicar** > **Run workflow**.

### Ligar o GitHub Pages (uma vez)

Em **Settings > Pages**, em *Build and deployment*, escolha **Source: GitHub Actions**.

### Proteções

- Se uma fonte voltar com menos de 90% dos registros da coleta anterior (API fora do ar, por exemplo), o coletor para sem sobrescrever nada e o workflow falha. O site continua com os dados da semana anterior.
- O Senado limita o número de pedidos por segundo; o coletor espera entre chamadas e tenta de novo quando recebe recusa.
- No Senado, processos que não mudaram desde a última coleta são reaproveitados, o que deixa as semanas seguintes mais rápidas que a primeira.

## Rodar localmente

```bash
python3 scripts/coletar.py           # opcional: atualiza raw/ (leva de 30 a 60 minutos na primeira vez)
python3 scripts/build.py .
python3 -m http.server 8000 --directory site
# abra http://localhost:8000
```

Os scripts usam só a biblioteca padrão do Python 3.9+.

## Fontes

- Câmara: https://dadosabertos.camara.leg.br — arquivos anuais `proposicoes`, `proposicoesTemas`, `proposicoesAutores`, `votacoes`, `votacoesVotos`, `eventos`, `eventosOrgaos`, `eventosPresencaDeputados`; API v2 para deputados e projetos antigos votados nesta legislatura.
- Senado: https://legis.senado.leg.br/dadosabertos — `/processo`, `/processo/{id}`, `/votacao`, `/senador/lista/atual`, `/senador/{código}/licencas`, `/senador/lista/legislatura/57`.

## Regras principais

- Projetos: PL, PLP e PEC dos arquivos anuais da Câmara a partir de 2023, mais projetos antigos que tiveram votação nominal em Plenário nesta legislatura.
- Situação: virou lei, passou em uma Casa, em andamento, parado (mais de 180 dias sem movimentação, contados da data da coleta), anexado a outro, encerrado.
- Votações: na Câmara, votação nominal em Plenário do texto principal (ou das emendas do Senado na fase final); no Senado, votações nominais de PL, PLP e PEC. O site mostra a última de cada projeto em cada Casa.
- Presença na Câmara: sessões deliberativas do Plenário com lista de presença, entre a primeira e a última presença do deputado. Comissões: reuniões e audiências encerradas fora do Plenário em que o deputado registrou presença.
- Presença no Senado: dias com votação nominal, classificados em presente, ausência justificada e falta sem justificativa.
- Contagens por parlamentar: projetos em que é autor principal, apresentados desde 01/02/2023.

## Pontos de atenção

- **Fevereiro de 2027:** começa a 58ª legislatura. As constantes `LEG_START` e `LEGISLATURA` em `scripts/coletar.py` (e `LEG_START` em `scripts/build.py`) definem o período mostrado. Será preciso decidir se o site passa a mostrar a nova legislatura, a anterior ou as duas.
- A contagem de reuniões de comissão segue a regra acima e pode diferir um pouco de outras contagens publicadas.

## O que falta

- Custo dos projetos
- Assembleias estaduais e câmaras municipais
