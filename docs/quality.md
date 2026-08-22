# Quality pipeline

Questa repository usa una pipeline leggera, divisa in blocchi chiari:

## Gate locale / CI

- `npm run check`
  - `npm run check:py`
  - `npm run check:js`
  - `npm run check:backend`
- `npm run build`

La CI aggiunge inoltre:

- soglia coverage backend del 60%;
- Playwright bloccante, dopo readiness deterministica del frontend;
- `pip-audit` e `npm audit` per vulnerabilità note;
- aggiornamenti settimanali Dependabot per Python, npm e GitHub Actions.

`netlify-cli` non è una dipendenza persistente del progetto. I comandi manuali
la eseguono tramite `npx`, mentre i test E2E avviano il server statico locale.
Questo evita che le dipendenze interne della CLI entrino nell'audit npm del sito.

## Controlli Python

Da eseguire dentro `meteo-backend/`:

- `ruff check .`
- `ruff format --check .`
- `pytest`

La configurazione di Ruff vive in `meteo-backend/pyproject.toml`.

## Controlli JavaScript

- `biome check public/js scripts tests/e2e`

Biome è configurato nel file `biome.json` e copre solo il codice JS rilevante per la manutenzione quotidiana.

## Analisi opzionali con Fallow

Non fanno parte del gate obbligatorio, ma sono utili prima di una PR o quando si valuta refactoring mirato:

- `npm run audit:code`
- `npm run health:code`
- `npm run dead-code`

## Pre-commit

Installazione consigliata:

- `pre-commit install`
- `pre-commit run --all-files`

I hook coprono:

- trailing whitespace
- EOF finale
- mixed line endings
- YAML e JSON validi
- lint e format Python con Ruff

## Line endings

Il repository resta in LF. `gitattributes`, `editorconfig` e i hook pre-commit sono allineati su questo comportamento.
