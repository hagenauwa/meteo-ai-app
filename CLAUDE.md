# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architettura

App meteo con ML per previsioni corrette, in due parti separate:

- **Frontend** (`public/`): Vanilla JS deployato su Netlify → https://leprevisioni.netlify.app
- **Backend** (`meteo-backend/`): Python FastAPI su Render → https://meteo-ai-backend.onrender.com
- **Database**: Neon PostgreSQL (produzione) — SQLite locale solo per sviluppo
- **Meteo API**: Open-Meteo (gratuita, no API key richiesta)
- **ML**: scikit-learn Ridge Regression lato server, auto-training orario
- **Chat AI**: Google Gemini 2.0 Flash (`GEMINI_API_KEY` in `.env`)

Il modello ML impara correggendo gli errori di previsione: ogni ora lo scheduler raccoglie le temperature reali per ~7.700 comuni italiani, verifica le previsioni passate, e riaddestra il modello se ci sono abbastanza dati verificati (≥500).

## Deploy produzione

| Risorsa | URL / Info |
|---------|-----------|
| Frontend | https://leprevisioni.netlify.app |
| Backend | https://meteo-ai-backend.onrender.com |
| GitHub | https://github.com/hagenauwa/meteo-ai-app (pubblico) |
| Database | Neon PostgreSQL, eu-central-1 |

**Workflow deploy**: ogni `git push origin master` triggera automaticamente il redeploy su Render. Per il frontend: `npm run deploy`.

## Comandi principali

### Deploy aggiornamento
```bash
git add .
git commit -m "descrizione"
git push                  # Render si aggiorna in automatico (~3-5 min)
npm run deploy            # Aggiorna frontend su Netlify
```

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
├── database.py          # SQLAlchemy models + fix URL postgresql:// → postgresql+psycopg2://
├── scheduler.py         # APScheduler: ciclo orario + keepalive ping ogni 10 min
├── ml_model.py          # Ridge Regression: train(), predict_correction(), get_stats()
├── weather_service.py   # Open-Meteo API client, batch fetch, WMO codes → icone
├── cities_loader.py     # Import ~7.700 comuni ISTAT da CSV nel DB
├── requirements.txt
├── runtime.txt          # Python 3.11.4 (per Render)
├── .env                 # GEMINI_API_KEY — non committare mai
└── routers/
    ├── weather.py       # GET /api/weather
    ├── cities.py        # GET /api/cities, GET /api/cities/{id}
    ├── ml.py            # GET /api/ml/correction, GET /api/ml/stats, POST /api/ml/train
    ├── chat.py          # POST /api/chat
    └── admin.py         # GET /api/admin/status, POST /api/admin/run-cycle, load-cities

public/
├── index.html           # window.BACKEND_URL configurato per Render
├── app.js               # Tutta la logica UI: search, autocomplete, render meteo, ML stats
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
| POST | `/api/chat` | body JSON: `{question, city, weatherData}` |
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

## Configurazione frontend

In `public/index.html` riga 11:
```javascript
window.BACKEND_URL = 'https://meteo-ai-backend.onrender.com';  // produzione
// Per sviluppo locale: 'http://localhost:8000'
```

## ML — come funziona

Il modello Ridge Regression in `ml_model.py`:
- **Features**: hour, month, lat, humidity, cloud_cover, region_encoded
- **Target**: `error = actual_temp - predicted_temp` (corregge il bias sistematico)
- **Limite sicurezza**: correzione massima ±5°C
- **Training automatico**: ≥500 predictions verificate E >6h dall'ultimo training
- Serializzato con pickle, salvato in `MlModelStore`, caricato in memoria all'avvio

## Note importanti

- **Render free tier**: si "addormenta" dopo 15 min senza richieste HTTP esterne. Il `_keepalive_ping()` in `scheduler.py` pinga `RENDER_EXTERNAL_URL/health` ogni 10 min per tenerlo sveglio (variabile impostata automaticamente da Render).
- **Sviluppo locale vs produzione**: il `.env` locale può usare `DATABASE_URL=sqlite:///...` per non toccare il DB Neon durante lo sviluppo.
- `public/ml-model.js` è legacy — il ML è tutto server-side in `ml_model.py`.
- "Marina di Massa" e "Val di Cornia" sono frazioni non-ISTAT: hardcodate in `CONFIG.ITALIAN_CITIES` in `app.js` (fallback locale).
- Il `README.md` principale è **outdated** (menziona OpenWeatherMap e TensorFlow.js): ignorarlo.
- Le `netlify/functions/` sono **legacy** e non vengono usate.
- Gemini usa il piano gratuito: 1.500 req/giorno, 15 req/min.
