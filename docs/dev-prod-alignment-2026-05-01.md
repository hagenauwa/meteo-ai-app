# Verifica allineamento sviluppo/produzione (2026-05-01)

## Esito

✅ Configurazione **allineata** tra sviluppo e produzione.

## Controlli effettuati

1. **Risoluzione backend frontend**
   - In locale (`localhost`, `127.0.0.1`, IP privati, `.local`) il frontend usa `http://<host>:8000`.
   - In produzione usa `https://meteo-ai-backend.onrender.com`.
   - È supportato override manuale via query string `?backend=` e persistenza in localStorage.

2. **Variabili ambiente deploy frontend (Netlify)**
   - `NODE_ENV=production` in contesto produzione.
   - `NODE_ENV=development` in contesto sviluppo.

3. **Variabili ambiente deploy backend (Render)**
   - `APP_ENV=production`.
   - `FRONTEND_ORIGIN=https://leprevisioni.netlify.app`.
   - Parametri ML condivisi e coerenti tra web service e cron service.

4. **Coerenza documentazione deploy**
   - Checklist operativa coerente con URL backend Render e `window.BACKEND_URL` lato frontend.

## Note operative

- Per verifica runtime post-deploy usare `GET /health` e `GET /ready` sul backend Render.
- In caso di anomalie frontend, controllare prima eventuali override backend memorizzati (`meteo_backend_override`).
