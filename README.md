# 🌤️ Meteo AI App

Applicazione web di previsioni meteo con Machine Learning server-side. Il frontend è una PWA leggera in Vanilla JS; il backend in Python gestisce dati, modelli ML e integrazioni meteo.

## 🎯 Caratteristiche

- ✅ **Previsioni meteo accurate** per tutta l'Italia
- 🤖 **Machine Learning server-side** (scikit-learn) che impara dagli errori di previsione
- 📱 **Design responsive** con glassmorphism (mobile, tablet e desktop)
- ⚙️ **PWA installabile** con service worker per esperienza offline
- ⚡ **Gratuito e open source**
- 🗺️ **Geocoding** automatico tramite Open-Meteo Geocoding API
- 💳 **Supporto sviluppo** tramite Stripe Checkout ("Buy me a Coffee")
- 🔒 **Pannello admin protetto** con token HMAC

## 🛠️ Stack Tecnologico

| Componente | Tecnologia | Note |
|------------|-----------|------|
| Frontend | Vanilla JS + CSS3 (glassmorphism) | Nessun framework da imparare; PWA con service worker |
| Backend | Python 3.11, FastAPI, Uvicorn | API REST async; deploy su Render |
| Database | PostgreSQL (prod) / SQLite (dev) | SQLAlchemy 2.0 + Alembic per le migrazioni |
| ML | scikit-learn | Ridge, LogisticRegression, Pipeline; addestramento server-side ogni ora |
| API Meteo | Open-Meteo (primaria), met.no (fallback) | Entrambe gratuite, nessuna API key richiesta per l'uso base |
| Geocoding | Open-Meteo Geocoding API | Ricerca città e comuni italiani |
| Pagamenti | Stripe Checkout | Flusso "Buy me a Coffee" |
| Auth Admin | Token HMAC | Header `x-admin-token` |
| Scheduler | APScheduler | Cron job su Render per auto-training ML |

## 📁 Struttura del Progetto

```
meteo-ai-app/
├── public/                    # Frontend statico (deploy su Netlify)
│   ├── index.html
│   ├── style.css
│   ├── js/
│   │   ├── main.js
│   │   ├── api.js
│   │   ├── render.js
│   │   ├── storage.js
│   │   ├── config.js
│   │   ├── autocomplete.js
│   │   └── supporter.js
│   ├── manifest.webmanifest
│   └── service-worker.js
├── netlify/
│   └── functions/             # Serverless functions (legacy/optional)
├── netlify.toml               # Configurazione Netlify
├── render.yaml                # Configurazione Render (web + cron)
├── package.json               # Dipendenze Node (netlify-cli, cross-env)
├── meteo-backend/             # Backend Python (deploy su Render)
│   ├── main.py                # FastAPI app
│   ├── config.py              # Settings env-based
│   ├── database.py            # SQLAlchemy + Alembic
│   ├── ml_model.py            # Modelli ML scikit-learn
│   ├── scheduler.py           # Ciclo orario ML
│   ├── weather_service.py     # Integrazione Open-Meteo
│   ├── cities_loader.py       # Caricamento comuni ISTAT
│   ├── auth.py                # Auth admin
│   ├── supporters_service.py  # Stripe + cifratura email supporter
│   ├── routers/               # weather, cities, ml, admin, supporters
│   ├── db_migrations/         # Versioni Alembic
│   ├── tests/                 # Suite Pytest
│   └── requirements.txt       # Dipendenze Python
└── docs/
    └── deploy-checklist-2026-04.md
```

## 🔐 Variabili d'Ambiente

Le seguenti variabili sono richieste o consigliate per l'esecuzione in produzione:

| Variabile | Scopo | Richiesta? |
|-----------|-------|------------|
| `DATABASE_URL` | Connessione PostgreSQL (prod) o SQLite (dev) | Sì |
| `FRONTEND_ORIGIN` | Origine frontend per CORS (es. `https://leprevisioni.netlify.app`) | Sì (prod) |
| `ADMIN_API_TOKEN` | Token segreto per accesso pannello admin | Sì (admin) |
| `STRIPE_SECRET_KEY` | Chiave segreta Stripe per pagamenti | Sì (donazioni) |
| `STRIPE_WEBHOOK_SECRET` | Segreto webhook Stripe per conferma pagamenti | Sì (donazioni) |
| `SUPPORTER_EMAIL_ENCRYPTION_KEY` | Chiave per cifratura email supporter | Sì (donazioni) |
| `SUPPORTER_EMAIL_HASH_KEY` | Chiave per hashing email supporter | Sì (donazioni) |
| `OPENWEATHER_API_KEY` | Legacy, non più utilizzata | No |

## 🚀 Installazione Locale

### Prerequisiti

- Python 3.11+
- Node.js (per Netlify CLI, opzionale)
- Account Stripe (opzionale, solo per testare i pagamenti)

### 1. Clona il repository

```bash
git clone <repository-url>
cd meteo-ai-app
```

### 2. Backend

```bash
cd meteo-backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Avvia le migrazioni del database:

```bash
alembic upgrade head
```

Avvia il server di sviluppo:

```bash
uvicorn main:app --reload --port 8000
```

L'API sarà disponibile su `http://localhost:8000`. La documentazione interattiva (Swagger UI) è su `/docs`.

### 3. Frontend

Dalla cartella `public/` puoi servire i file statici con qualsiasi server locale, oppure usare Netlify CLI:

```bash
cd public
npx serve .
```

Se hai installato il backend in locale, assicurati che il frontend punti a `http://localhost:8000` (configurabile in `js/config.js`).

## 🌐 Deploy

### Frontend — Netlify

Il frontend è un sito statico. Configura su Netlify:

- **Build command:** (lascia vuoto)
- **Publish directory:** `public`
- Aggiungi la variabile `FRONTEND_ORIGIN` nelle impostazioni del sito

### Backend — Render

Il backend è configurato tramite `render.yaml`:

- **Web Service:** avvia `meteo-backend/main.py` con Uvicorn
- **Cron Job:** esegue `scheduler.py` per l'addestramento orario del modello ML

Assicurati di impostare tutte le variabili d'ambiente elencate sopra nel dashboard di Render.

### Database

In produzione usa PostgreSQL. In sviluppo SQLite è sufficiente: imposta `DATABASE_URL` di conseguenza (es. `sqlite:///./meteo.db`).

## 🤖 Architettura Machine Learning

Il sistema ML è interamente server-side:

1. **Raccolta dati:** Ogni ricerca meteo salva la previsione API nel database.
2. **Verifica:** Dopo alcune ore, il sistema confronta la previsione con le osservazioni reali.
3. **Addestramento:** Il cron job su Render esegue l'auto-training ogni ora usando scikit-learn (Pipeline con Ridge per regressione e LogisticRegression per classificazione).
4. **Correzione:** Le previsioni successive includono una correzione ML calcolata dal backend (es. "+1.2°C basandosi sui dati storici").

L'addestramento richiede un minimo di dati verificati; finché non ce ne sono abbastanza, il modello restituisce la previsione grezza API.

## 🎓 Admin

L'accesso al pannello admin avviene inviando nell'header delle richieste:

```
x-admin-token: <ADMIN_API_TOKEN>
```

Gli endpoint admin permettono di monitorare metriche ML, gestire supporter e forzare l'addestramento del modello.

## 🆘 Supporto

Se incontri problemi:

1. Controlla la console del browser (F12 → Console) per errori frontend.
2. Verifica i log del backend Render/FastAPI.
3. Assicurati che tutte le variabili d'ambiente siano configurate correttamente.
4. Controlla che le migrazioni Alembic siano state eseguite (`alembic current`).

## 📚 Documentazione Utile

- [Open-Meteo API Docs](https://open-meteo.com/en/docs)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Docs](https://docs.sqlalchemy.org/en/20/)
- [Alembic Docs](https://alembic.sqlalchemy.org/en/latest/)
- [Stripe Docs](https://stripe.com/docs)
- [Netlify Docs](https://docs.netlify.com/)
- [Render Docs](https://render.com/docs)

## 📄 Licenza

MIT License — Libero di usare, modificare e distribuire!

---

**Creato con ❤️ per rendere il meteo più intelligente e accessibile a tutti.**

Se trovi utile questo progetto, considera di lasciare una ⭐ sul repository!
