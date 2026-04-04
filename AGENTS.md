# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Scopo e manutenzione

Questo file e' la source of truth per la conoscenza stabile del progetto: architettura, deploy, vincoli operativi, file chiave e gotcha ricorrenti.

- Inserire qui solo informazioni che resteranno utili anche tra settimane o mesi.
- Non usarlo come diario delle sessioni: incidenti datati, workaround temporanei, lezioni di deploy e scoperte contestuali vanno in `docs/ops-learnings.md`.
- Promuovere in questo file solo le lezioni che diventano ricorrenti o cambiano il modo corretto di lavorare sul progetto.
- Dopo task importanti, classificare le nuove conoscenze in tre categorie: `AGENTS.md`, `docs/ops-learnings.md`, oppure nessun aggiornamento se il dettaglio e' locale o gia' evidente dal codice.

## Architettura

App meteo con ML per previsioni corrette, in due parti separate:

- **Frontend** (`public/`): Vanilla JS deployato su Netlify → https://leprevisioni.netlify.app
- **Backend** (`meteo-backend/`): Python FastAPI su Render → https://meteo-ai-backend.onrender.com
- **Database**: Neon PostgreSQL (produzione) — SQLite locale solo per sviluppo
- **Meteo API**: Open-Meteo come provider primario; fallback pubblico via `met.no` quando Open-Meteo rate-limita Render
- **ML**: correzione temperatura + pioggia + condizione del cielo lato server, auto-training orario

Il modello ML impara correggendo gli errori di previsione: ogni ora lo scheduler raccoglie le temperature reali per ~7.700 comuni italiani, verifica le previsioni passate, e riaddestra il modello se ci sono abbastanza dati verificati (≥500). Il batch Open-Meteo usa pacing prudente e backoff per ridurre i `429 Too Many Requests`.

## Deploy produzione

| Risorsa | URL / Info |
|---------|-----------|
| Frontend | https://leprevisioni.netlify.app |
| Backend | https://meteo-ai-backend.onrender.com |
| GitHub | https://github.com/hagenauwa/meteo-ai-app (pubblico) |
| Database | Neon PostgreSQL, eu-central-1 |

**Workflow deploy**: `git push origin master` dovrebbe triggerare il redeploy su Render, ma in pratica l'auto-deploy non è sempre affidabile. Se il nuovo commit non compare nei deploy Render entro 1-2 minuti, forzare un redeploy manuale o un redeploy via update di una env var innocua. Per il frontend: `npm run deploy`.

## Comandi principali

### Deploy aggiornamento
```bash
git add .
git commit -m "descrizione"
git push                  # Verificare poi in Render che il commit compaia davvero nei deploy
npm run deploy            # Aggiorna frontend su Netlify
```

### Post-deploy backend
```bash
python meteo-backend/scripts/smoke_deploy.py https://meteo-ai-backend.onrender.com
```
Se il push non genera deploy automatico, controllare in Render/GitHub il webhook oppure forzare un redeploy.

### Sviluppo locale (usa SQLite, non tocca il DB di produzione)
```bash
cd meteo-backend
uvicorn main:app --reload   # http://localhost:8000 — docs: /docs
```
Il backend locale usa SQLite se `DATABASE_URL` non è nel `.env`.

### Admin API (produzione)
```bash
curl https://meteo-ai-backend.onrender.com/health
curl https://meteo-ai-backend.onrender.com/api/admin/status
curl -X POST https://meteo-ai-backend.onrender.com/api/admin/run-cycle
curl -X POST https://meteo-ai-backend.onrender.com/api/ml/train?min_samples=100
```

### Caricamento comuni (solo se DB vuoto o reset)
```bash
cd meteo-backend
python cities_loader.py --download   # Scarica CSV + carica in DB (~3 min)
python cities_loader.py              # Ricarica da CSV locale già presente
```
In produzione, il caricamento avviene automaticamente al primo avvio se il DB è vuoto.

## Struttura file chiave

```
meteo-backend/
├── main.py              # FastAPI entry point; auto-carica comuni se DB vuoto all'avvio
├── database.py          # SQLAlchemy models + init DB via Alembic/runtime bootstrap
├── scheduler.py         # APScheduler: ciclo orario; retention; raccolta/verifica forecast target-based
├── ml_model.py          # Temperatura + pioggia + condizione cielo; espone insight giornalieri user-facing
├── weather_service.py   # Open-Meteo batch client + fallback pubblico met.no + cache breve + vento dominante daily
├── cities_loader.py     # Import ~7.700 comuni ISTAT da CSV nel DB
├── config.py            # Config centralizzata env-aware
├── auth.py              # Protezione endpoint admin/train via token
├── alembic.ini
├── db_migrations/       # Migrazioni Alembic
├── scripts/
│   └── smoke_deploy.py  # Smoke test pubblico backend
├── requirements.txt
├── runtime.txt          # Python 3.11.4 (per Render)
├── .env                 # DATABASE_URL / ADMIN_API_TOKEN — non committare mai
└── routers/
    ├── weather.py       # GET /api/weather
    ├── cities.py        # GET /api/cities, GET /api/cities/{id}
    ├── ml.py            # GET /api/ml/correction, GET /api/ml/stats, POST /api/ml/train
    └── admin.py         # GET /api/admin/status, POST /api/admin/run-cycle, load-cities

public/
├── index.html           # window.BACKEND_URL configurato per Render
├── js/
│   ├── main.js          # Bootstrap frontend
│   ├── api.js           # Client API backend
│   ├── autocomplete.js
│   ├── config.js
│   ├── render.js
│   └── storage.js
├── manifest.webmanifest
├── service-worker.js
└── style.css

render.yaml              # Config deploy Render (rootDir: meteo-backend)
```

## Endpoint API

| Metodo | Endpoint | Parametri |
|--------|----------|-----------|
| GET | `/api/weather` | `city=Roma` oppure `lat=41.9&lon=12.5&name=Roma` |
| GET | `/api/cities` | `q=val+di+cornia&limit=8` |
| GET | `/api/cities/{id}` | — |
| GET | `/api/ml/correction` | `city=Roma&temp=23.5&humidity=60&hour=14` |
| GET | `/api/ml/stats` | — |
| POST | `/api/ml/train` | `?min_samples=100` |
| GET | `/api/admin/status` | — |
| POST | `/api/admin/run-cycle` | — |
| POST | `/api/admin/load-cities` | `?reload=false` |

## Database

Quattro modelli SQLAlchemy in `database.py`:
- **City**: comuni ISTAT (name, region, province, lat, lon)
- **WeatherObservation**: temperatura/umidità/vento/precipitazioni orarie per città
- **MlPrediction**: previsioni salvate → verificate con valori reali (verified, actual_temp, error)
- **MlModelStore**: modello Ridge serializzato con pickle (BLOB nel DB)

`database.py` converte automaticamente `postgresql://` → `postgresql+psycopg2://` (Neon usa il prefisso standard che SQLAlchemy non accetta direttamente).
Lo schema reale è ormai gestito da Alembic (`alembic.ini`, `db_migrations/versions/20260404_0001_baseline_schema.py`).

## Configurazione frontend

In `public/index.html` riga 11:
```javascript
window.BACKEND_URL = 'https://meteo-ai-backend.onrender.com';  // produzione
// Per sviluppo locale: 'http://localhost:8000'
```

## ML — come funziona

`ml_model.py` addestra tre componenti:
- **Temperatura**: Ridge Regression sul bias della previsione
- **Pioggia**: classificatore logistico sulla probabilità di precipitazione
- **Condizione cielo**: classificatore logistico su `sereno`, `parzialmente nuvoloso`, `nuvoloso`, `pioggia`

Il training usa storico verificato con feature meteo e geografiche, incluse cloud cover e vento previsto, e promuove i modelli solo se superano un baseline semplice.

## Note importanti

- **Render free tier**: si "addormenta" dopo 15 min senza richieste HTTP esterne.
- **Open-Meteo può rate-limitare Render**: se `/api/weather` torna `502`, controllare prima i log Render per `Open-Meteo` e `429`.
- **Fallback meteo pubblico**: `fetch_single_city()` prova Open-Meteo (`httpx`), poi compat mode, poi `urllib`, infine fallback a `met.no`. Se il sito è su ma Open-Meteo blocca, il pubblico deve continuare a ricevere meteo.
- **Scheduler**: il batch usa pacing prudente (`MAX_CONCURRENCY=1`, delay tra batch, retry/backoff). Evitare di rialzare aggressivamente la concorrenza senza verificare i limiti upstream.
- **Deploy Render**: non fidarsi ciecamente dell'auto-deploy; confermare sempre quale commit è `live` in Render. Se serve, un update di env var innocua può forzare un nuovo deploy.
- **Health check Render**: il path desiderato è `/ready`; verificare in dashboard che sia impostato davvero.
- **Sviluppo locale vs produzione**: il `.env` locale può usare `DATABASE_URL=sqlite:///...` per non toccare il DB Neon durante lo sviluppo.
- `public/ml-model.js` e `public/app.js` sono legacy rimossi; il frontend reale è modulare sotto `public/js/`.
- "Marina di Massa" e "Val di Cornia" non vanno più trattate come fallback solo frontend hardcoded: la risoluzione città passa dal backend/index città.
- Il `README.md` principale è **outdated** (menziona OpenWeatherMap e TensorFlow.js): ignorarlo.
- Le `netlify/functions/` sono **legacy** e non vengono usate.
- Le lezioni operative datate o incident-driven vanno raccolte in `docs/ops-learnings.md`, non aggiunte automaticamente qui.
