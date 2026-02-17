# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architettura

App meteo con ML per previsioni corrette, in due parti separate:

- **Frontend** (`public/`): Vanilla JS deployato su Netlify
- **Backend** (`meteo-backend/`): Python FastAPI su Windows locale, porta 8000
- **Database**: SQLite (`meteo-backend/meteo_ai.db`) — default, nessuna configurazione
- **Meteo API**: Open-Meteo (gratuita, no API key richiesta)
- **ML**: scikit-learn Ridge Regression lato server, auto-training orario
- **Chat AI**: Google Gemini 2.0 Flash (`GEMINI_API_KEY` in `.env`)

Il modello ML impara correggendo gli errori di previsione: ogni ora il scheduler raccoglie le temperature reali per ~8.000 comuni italiani, verifica le previsioni passate, e riaddestra il modello se ci sono abbastanza dati verificati (≥500).

## Comandi principali

### Avvio backend (sviluppo)
```batch
cd meteo-backend
uvicorn main:app --reload
# API docs: http://localhost:8000/docs
```

### Avvio backend (doppio click)
```batch
meteo-backend\avvia_backend.bat
```

### Avvio automatico Windows (Task Pianificato, eseguire come Admin)
```powershell
cd meteo-backend
.\installa_servizio_windows.ps1
```

### Frontend locale
```bash
npm run dev   # Netlify dev server su porta 8888
```

### Caricamento comuni italiani (solo prima volta o reset)
```bash
cd meteo-backend
python cities_loader.py --download   # Scarica CSV + carica in DB (~3 min)
python cities_loader.py              # Ricarica da CSV locale già presente
```

### Admin API
```bash
curl http://localhost:8000/api/admin/status
curl -X POST http://localhost:8000/api/admin/run-cycle   # Forza ciclo orario
curl -X POST "http://localhost:8000/api/admin/load-cities?reload=false"
curl -X POST "http://localhost:8000/api/ml/train?min_samples=100"
```

## Struttura file chiave

```
meteo-backend/
├── main.py              # FastAPI entry point, CORS, lifespan, router mounting
├── database.py          # SQLAlchemy models: City, WeatherObservation, MlPrediction, MlModelStore
├── scheduler.py         # APScheduler: ciclo orario auto-learning
├── ml_model.py          # Ridge Regression: train(), predict_correction(), get_stats()
├── weather_service.py   # Open-Meteo API client, batch fetch, WMO codes → icone
├── cities_loader.py     # Import ~7.900 comuni ISTAT da CSV nel DB
├── requirements.txt
├── .env                 # GEMINI_API_KEY (non committare mai)
└── routers/
    ├── weather.py       # GET /api/weather
    ├── cities.py        # GET /api/cities, GET /api/cities/{id}
    ├── ml.py            # GET /api/ml/correction, GET /api/ml/stats, POST /api/ml/train
    ├── chat.py          # POST /api/chat
    └── admin.py         # GET /api/admin/status, POST /api/admin/run-cycle, load-cities

public/
├── index.html           # Configurazione window.BACKEND_URL + struttura HTML
├── app.js               # Tutta la logica UI: search, autocomplete, render meteo, ML stats
└── style.css
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

## Configurazione frontend

In `public/index.html` riga ~10:
```javascript
window.BACKEND_URL = 'http://localhost:8000';
// Per accesso da altri dispositivi: 'http://192.168.x.x:8000'
// Per esposizione pubblica: URL ngrok/localtunnel
```

## Database SQLAlchemy

Quattro modelli in `database.py`:
- **City**: comuni ISTAT (name, region, province, lat, lon)
- **WeatherObservation**: temperatura/umidità/vento/precipitazioni orarie per città
- **MlPrediction**: previsioni salvate → poi verificate con valori reali (verified, actual_temp, error)
- **MlModelStore**: modello serializzato con pickle (model_bytes BLOB nel DB)

Di default usa SQLite. Per PostgreSQL: impostare `DATABASE_URL` in `.env`.

## ML — come funziona

Il modello Ridge Regression in `ml_model.py`:
- **Features**: hour, month, lat, humidity, cloud_cover, region_encoded
- **Target**: `error = actual_temp - predicted_temp` (correge il bias sistematico)
- **Limite sicurezza**: correzione massima ±5°C
- **Training automatico**: si attiva se ≥500 predictions verificate E >6h dall'ultimo training
- Il modello viene serializzato con pickle e salvato nel DB (tabella `MlModelStore`)
- Viene caricato in memoria all'avvio di FastAPI

## Note importanti

- `public/ml-model.js` è un file legacy — il ML è ora tutto server-side in `ml_model.py`
- "Marina di Massa" e "Val di Cornia" sono frazioni non-ISTAT: hardcodate in `CONFIG.ITALIAN_CITIES` in `app.js` (fallback locale)
- L'autocomplete combina ricerca locale (`CONFIG.ITALIAN_CITIES`) + backend (`/api/cities`)
- Il README.md principale è **outdated** (menziona OpenWeatherMap, TensorFlow.js): ignorarlo
- Le `netlify/functions/` sono **legacy** e non vengono usate
- Gemini usa il piano gratuito: 1.500 req/giorno, 15 req/min
