# Deploy Checklist — Meteo AI

## Backend Render

1. Verifica che il servizio usi il `render.yaml` aggiornato.
2. Configura queste env vars in Render:
   - `DATABASE_URL`
   - `GEMINI_API_KEY`
   - `ADMIN_API_TOKEN`
   - `FRONTEND_ORIGIN=https://leprevisioni.netlify.app`
   - `APP_ENV=production`
   - `CHAT_REQUESTS_PER_MINUTE=15`
   - `CHAT_REQUESTS_PER_DAY=300`
3. Conferma che lo start command esegua prima:
   - `python -m alembic -c alembic.ini upgrade head`
4. Verifica health check:
   - `GET /health`
   - `GET /ready`

## Frontend Netlify

1. Deploy della cartella `public`.
2. Verifica che siano pubblicati:
   - `index.html`
   - `style.css`
   - `js/*`
   - `manifest.webmanifest`
   - `service-worker.js`
3. Controlla che `window.BACKEND_URL` punti al backend Render di produzione.

## Smoke Test Post Deploy

1. Backend:
   - `GET https://meteo-ai-backend.onrender.com/health`
   - `GET https://meteo-ai-backend.onrender.com/ready`
   - `GET https://meteo-ai-backend.onrender.com/api/weather?city=Roma`
2. Frontend:
   - ricerca città
   - meteo attuale
   - widget ML
   - chat
   - preferiti/recenti
   - service worker registrato
3. Sicurezza:
   - `POST /api/ml/train` senza `x-admin-token` deve restituire `403`
   - `GET /api/admin/status` senza token deve restituire `403`

## Rollout Suggerito

1. Push del backend.
2. Attendere deploy Render e validare `/ready`.
3. Deploy Netlify.
4. Eseguire smoke test end-to-end.
