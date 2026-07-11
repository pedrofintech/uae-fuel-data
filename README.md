# uae-fuel-data

Dados dos preços mensais de combustível nos UAE para a página
`/petrol-prices-uae` do BrokerMatch - o equivalente ao `combustiveis-dados`
do Literacia Financeira.

## Como funciona

- `petrol.json` é o ficheiro que a página vai buscar (via `PF_URL` no script
  registado PfData, em raw.githubusercontent.com).
- `scripts/update.py` corre diariamente via GitHub Actions
  (`.github/workflows/update.yml`, 09:10 hora do Golfo):
  1. Dia 1 (ou quando o mês do JSON ficar desatualizado): procura os novos
     preços oficiais nas fontes com URL estável, valida (ordem dos octanas,
     gamas plausíveis) e faz o shift `cur` → `prev` + append ao `hist`.
  2. Dia 28 em diante: procura o anúncio do mês seguinte e preenche
     `next` com os valores anunciados ("Announced: Special 95 will be...").
  3. Nos restantes dias: calcula a tendência do Brent (média do mês corrente
     vs mês anterior, stooq com fallback Yahoo) e preenche `next` como
     previsão (up / down / stable).
- Só há commit quando o JSON muda. A página atualiza-se sem publicar o Webflow.

## Formato do petrol.json

```json
{
  "m": "2026-07",              // mês em vigor
  "updated": "2026-06-30",     // data do anúncio/última alteração
  "cur":  { "s98": 3.40, "s95": 3.29, "e91": 3.21, "d": 3.60 },
  "prev": { "s98": 3.95, "s95": 3.83, "e91": 3.76, "d": 4.33 },
  "hist": [ { "m": "2026-02", "s98": 2.45, "s95": 2.33, "e91": 2.26, "d": 2.52 } ],
  "next": { "dir": "tbd", "note": "" }   // dir: up | down | stable | tbd
}
```

## Correção manual

Edita `petrol.json` diretamente no GitHub. O script nunca reescreve os dados
do mês corrente depois de `m` estar certo - uma correção manual fica intacta.

## Fontes

O parser é genérico (regex por combustível + validação). Se uma fonte mudar
de layout, o script passa à seguinte; para acrescentar/remover fontes edita a
lista `SOURCES` em `scripts/update.py`. O histórico inicial (fev-jul 2026)
veio dos anúncios oficiais reportados pelo Khaleej Times.
