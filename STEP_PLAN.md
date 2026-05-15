# Piano Step-by-Step — Migliorie Meteo AI App

## Regole Globali
- **Una feature alla volta**: implementata, testata, validata, COMMIT, poi si passa alla prossima.
- **Anti-regressione**: dopo ogni step, verificare che:
  - `/health` e `/ready` rispondano 200
  - `/api/weather?city=Roma` risponda con `current`, `hourly`, `daily`, `ml`
  - Frontend `index.html` funzioni (ricerca, preferiti, render)
  - Service worker invariato
- **Zero modifica a file esistenti** se non strettamente necessario.

## Step 1 — API Cities/Autocomplete nel Backend (E)
- Crea `meteo-backend/routers/cities_v2.py` con:
  - `GET /api/cities/autocomplete?q=roma&limit=8` — ricerca fuzzy nel DB + fallback Open-Meteo Geocoding
  - `GET /api/cities/search?q=roma&limit=1` — ricerca esatta per risoluzione città (usato dal frontend invece di chiamare Open-Meteo direttamente)
  - Cache in-memory LRU (5 min) per risultati
- Modifica `public/js/api.js`: funzione `searchCities()` chiama ora il backend invece di Open-Meteo direttamente (con fallback se backend non risponde)
- Beneficio: caching lato server, meno chiamate esterne, geocoding più veloce

## Step 2 — Badge UV/AQI nel Frontend (D)
- Modifica `public/index.html`: aggiungere 2 mini-badges nella `snapshot-card` (adesso) per UV index e AQI
- Modifica `public/js/api.js`: aggiungere funzione `fetchWeatherAdvanced()` che chiama `GET /api/weather/advanced`
- Modifica `public/js/main.js`: dopo `fetchWeatherByCity`, chiamare `fetchWeatherAdvanced` in parallelo e arricchire il payload
- Modifica `public/js/render.js`: aggiungere funzione `renderAdvanced()` per mostrare UV e AQI con color-coding (verde/giallo/rosso)
- CSS: aggiungere 2 mini-badge nella `snapshot-details` con `display: grid` da 2x2 a 2x3

## Step 3 — Mappa Interattiva (B)
- Nuovo file `public/map.html` — pagina autonoma con Leaflet.js
- Pulsante "Mostra sulla mappa" in `index.html` che apre `map.html?q=Roma`
- `map.html` legge `?q=` o `?lat=&lon=`, chiama backend per meteo, mostra marker con popup meteo
- Aggiungere `public/js/map.js` solo se la logica è complessa, altrimenti inline

## Step 4 — Notifiche Push Meteo (A)
- Backend: nuovo endpoint `POST /api/subscriptions/register` per salvare PushSubscription (VAPID)
- Backend: nuovo `routers/notifications.py` con endpoint per inviare notifica test
- Frontend: registrazione service worker aggiornata per push, richiesta permesso browser
- `public/js/push.js`: gestione subscription, toggle notifiche nella UI
- Aggiungere toggle nelle impostazioni (piccolo ingranaggio in header)

## Step 5 — Test E2E & Coverage (C)
- Installare `pytest-cov` nel backend, aggiungere target coverage 70%
- Creare `meteo-backend/tests/test_rate_limiter.py`, `test_advanced.py`
- Frontend: installare Playwright, creare `tests/e2e/search.spec.js`
- Aggiornare `package.json` con script `test:e2e`
- Verifica CI-ready: aggiungere GitHub Actions workflow `.github/workflows/test.yml`

## Stato
- [ ] Step 1 — API Cities Backend
- [ ] Step 2 — Badge UV/AQI Frontend
- [ ] Step 3 — Mappa Interattiva
- [ ] Step 4 — Notifiche Push
- [ ] Step 5 — Test E2E & Coverage
