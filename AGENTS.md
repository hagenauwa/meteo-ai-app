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

Il frontend pubblico usa Open-Meteo **direttamente dal browser** sia per i dati meteo (meteo base + forecast) sia per la geocoding delle città, evitando round-trip continui verso Render. Il backend resta nel path utente per funzionalità ML (`/api/ml/enrich`) e per le feature persistenti (supporter/email, admin, training, DB).

Il modello ML impara correggendo gli errori di previsione: in produzione un **Render Cron Job** esegue ogni ora il ciclo ML (`meteo-backend/scripts/run_ml_cycle.py`), raccoglie le temperature reali per ~7.700 comuni italiani, verifica le previsioni passate, e riaddestra il modello se ci sono abbastanza dati verificati (≥500). Il web service FastAPI non deve affidarsi allo scheduler in-process in produzione. Il batch Open-Meteo usa pacing prudente e backoff per ridurre i `429 Too Many Requests`.
Il forecast pubblico di `/api/weather` espone fino a 16 giorni giornalieri quando risponde Open-Meteo; se entra il fallback `met.no`, l'orizzonte giornaliero degrada a 9 giorni. Il dettaglio orario pubblico resta limitato al breve termine (24 ore).

## Deploy produzione

| Risorsa | URL / Info |
|---------|-----------|
| Frontend | https://leprevisioni.netlify.app |
| Backend | https://meteo-ai-backend.onrender.com |
| GitHub | https://github.com/hagenauwa/meteo-ai-app (pubblico) |
| Database | Neon PostgreSQL, eu-central-1 |

**Workflow branch**: usare `Produzione` per tutte le modifiche, i commit e il deploy. Non esiste più un branch separato `Sviluppo`.

**Workflow deploy**: pubblicare in produzione solo da `Produzione`. Un `git push origin Produzione` dovrebbe triggerare il redeploy su Render, ma in pratica l'auto-deploy non e' sempre affidabile. Se il nuovo commit non compare nei deploy Render entro 1-2 minuti, forzare un redeploy manuale o un redeploy via update di una env var innocua. Per il frontend: `npm run deploy`.

**Regola operativa per richieste "deploy"**: quando l'utente chiede semplicemente `deploy`, non aspettare istruzioni aggiuntive.
- Se la modifica tocca il frontend (`public/` o asset Netlify), fare deploy su Netlify con `npm run deploy`.
- Se la modifica tocca il backend (`meteo-backend/`, `render.yaml` o configurazione Render), fare push del commit e verificare/forzare il deploy su Render fino a vedere live il commit corretto.
- Se la modifica tocca entrambe le parti, eseguire entrambi i deploy.
- Dopo il deploy backend, eseguire sempre uno smoke test pubblico (`python meteo-backend/scripts/smoke_deploy.py https://meteo-ai-backend.onrender.com`) e verificare che l'istanza live stia servendo davvero il commit nuovo.

## Comandi principali

### Deploy aggiornamento
```bash
git checkout Produzione
git add .
git commit -m "descrizione"
git push origin Produzione   # Verificare poi in Render che il commit compaia davvero nei deploy
npm run deploy            # Aggiorna frontend su Netlify
```

### Post-deploy backend
```bash
python meteo-backend/scripts/smoke_deploy.py https://meteo-ai-backend.onrender.com
```
Se il push non genera deploy automatico, controllare in Render/GitHub il webhook oppure forzare un redeploy.

### Sviluppo locale (usa SQLite, non tocca il DB di produzione)
```bash
npm install
npm run dev:backend   # backend locale leggero su http://localhost:8000
npm run dev           # frontend Netlify Dev su http://localhost:8888
```
Il backend locale usa SQLite se `DATABASE_URL` non è nel `.env`. In sviluppo locale il default è "leggero": scheduler disattivato e bootstrap automatico città/GeoNames disattivato, per partire più in fretta. Se serve simulare la produzione localmente usare `npm run dev:backend:full`.

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
├── main.py              # FastAPI entry point; in prod espone /ready con stato modello + ultimo ciclo ML
├── database.py          # SQLAlchemy models + init DB via Alembic/runtime bootstrap
├── scheduler.py         # Logica del ciclo ML + stato persistente ultimo ciclo/training; APScheduler utile soprattutto in locale
├── ml_model.py          # Temperatura + pioggia + condizione cielo; espone insight giornalieri user-facing
├── weather_service.py   # Open-Meteo batch client + forecast pubblico 16g/9g fallback + cache breve + vento dominante daily
├── cities_loader.py     # Import ~7.700 comuni ISTAT da CSV nel DB
├── config.py            # Config centralizzata env-aware + flag locali scheduler/bootstrap
├── auth.py              # Protezione endpoint admin/train via token
├── alembic.ini
├── db_migrations/       # Migrazioni Alembic
├── scripts/
│   ├── smoke_deploy.py  # Smoke test pubblico backend
│   └── run_ml_cycle.py  # Entry point del Render Cron Job per il ciclo ML orario
├── requirements.txt
├── runtime.txt          # Python 3.11.4 (per Render)
├── .env                 # DATABASE_URL / ADMIN_API_TOKEN — non committare mai
└── routers/
    ├── weather.py       # GET /api/weather
    ├── cities.py        # GET /api/cities, GET /api/cities/{id}
    ├── ml.py            # GET /api/ml/correction, GET /api/ml/stats, POST /api/ml/train
    └── admin.py         # GET /api/admin/status, POST /api/admin/run-cycle, load-cities

public/
├── index.html           # seleziona automaticamente backend locale su localhost, Render in produzione
├── js/
│   ├── main.js          # Bootstrap frontend
│   ├── api.js           # Meteo + geocoding Open-Meteo client-side + integrazione endpoint backend (ML/supporter)
│   ├── autocomplete.js
│   ├── config.js
│   ├── render.js        # Vista citta + giorno; usa anche `daily[].ml` per insight user-facing
│   └── storage.js
├── manifest.webmanifest
├── service-worker.js    # Cache statica frontend; bump `CACHE_NAME` quando cambia l'inventario asset
└── style.css

render.yaml              # Config deploy Render: web backend + cron job ML orario
```

## Endpoint API

| Metodo | Endpoint | Parametri |
|--------|----------|-----------|
| GET | `/api/weather` | `city=Roma` oppure `lat=41.9&lon=12.5&name=Roma` — include `current`, `hourly`, `daily` e, con `include_ml=true`, insight ML anche su ogni `daily[]` |
| GET | `/api/cities` | `q=val+di+cornia&limit=8` |
| GET | `/api/cities/index` | `scope=comuni|localita|all&version=v2` |
| GET | `/api/cities/{id}` | — |
| POST | `/api/ml/enrich` | body forecast frontend (`city`,`current`,`daily`) → ritorna blocco `ml` + `daily_ml[]` |
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

In `public/index.html` il bootstrap JS sceglie automaticamente il backend:
```javascript
window.BACKEND_URL = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://meteo-ai-backend.onrender.com';
```

## ML — come funziona

`ml_model.py` addestra tre componenti:
- **Temperatura**: Ridge Regression sul bias della previsione
- **Pioggia**: classificatore logistico sulla probabilità di precipitazione
- **Condizione cielo**: classificatore logistico su `sereno`, `parzialmente nuvoloso`, `nuvoloso`, `pioggia`

Il training usa storico verificato con feature meteo e geografiche, incluse cloud cover e vento previsto, e promuove i modelli solo se superano un baseline semplice.
`/api/weather` arricchisce ogni giorno del forecast con un blocco `daily[].ml` user-facing: condizione attesa, confidenza, probabilità pioggia calibrata, range temperatura corretto, badge e summary.

## Note importanti

- **Render free tier**: si "addormenta" dopo 15 min senza richieste HTTP esterne.
- **Open-Meteo può rate-limitare Render**: se `/api/weather` torna `502`, controllare prima i log Render per `Open-Meteo` e `429`.
- **Fallback meteo pubblico**: `fetch_single_city()` prova Open-Meteo (`httpx`), poi compat mode, poi `urllib`, infine fallback a `met.no`. Se il sito è su ma Open-Meteo blocca, il pubblico deve continuare a ricevere meteo.
- **Orizzonte forecast pubblico**: non assumere un numero fisso di giorni nel frontend. `/api/weather` puo' restituire fino a 16 giorni con Open-Meteo o 9 giorni se la risposta arriva dal fallback `met.no`; il dettaglio `hourly` resta di 24 ore.
- **Scheduler**: il batch usa pacing prudente (`MAX_CONCURRENCY=1`, delay tra batch, retry/backoff). Evitare di rialzare aggressivamente la concorrenza senza verificare i limiti upstream.
- **Deploy Render**: non fidarsi ciecamente dell'auto-deploy; confermare sempre quale commit è `live` in Render. Se serve, un update di env var innocua può forzare un nuovo deploy.
- **Service worker frontend**: dopo modifiche agli asset statici o al layout, bumpare `CACHE_NAME` in `public/service-worker.js`; altrimenti alcuni browser possono continuare a mostrare la UI vecchia finché non fanno hard refresh o unregister del service worker.
- **Frontend locale**: su `localhost` il service worker viene disattivato automaticamente per evitare cache stantie durante lo sviluppo.
- **Health check Render**: il path desiderato è `/ready`; verificare in dashboard che sia impostato davvero. `/ready` ora include anche `ml_training` con lo stato dell'ultimo ciclo ML.
- **Produzione scheduler ML**: in produzione il web service deve avere `ENABLE_SCHEDULER=false`; il ciclo ML orario deve girare tramite il cron job Render definito in `render.yaml`.
- **Sviluppo locale vs produzione**: il `.env` locale può usare `DATABASE_URL=sqlite:///...` per non toccare il DB Neon durante lo sviluppo.
- `public/ml-model.js` e `public/app.js` sono legacy rimossi; il frontend reale è modulare sotto `public/js/`.
- "Marina di Massa" e "Val di Cornia" non vanno più trattate come fallback solo frontend hardcoded: la risoluzione città passa dalla geocoding Open-Meteo lato frontend.
- Il `README.md` principale è **outdated** (menziona OpenWeatherMap e TensorFlow.js): ignorarlo.
- Le `netlify/functions/` sono **legacy** e non vengono usate.
- **Commit solo locali per default**: a meno che l'utente non lo richieda esplicitamente, fare sempre e solo commit locali (`git commit`), mai push (`git push`). Questa regola vale per tutte le modifiche future salvo istruzione contraria.
- **NO deploy automatici**: non eseguire mai deploy in produzione (Netlify, Render, ecc.) senza esplicita richiesta dell'utente. Dopo il commit locale, aspettare istruzioni. Il deploy è un'operazione esplicita e deliberata, mai automatica o implicita.
- Le lezioni operative datate o incident-driven vanno raccolte in `docs/ops-learnings.md`, non aggiunte automaticamente qui.
