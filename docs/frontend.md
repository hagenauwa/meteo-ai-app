# Frontend

Frontend statico Vanilla JS in `public/`.

## Comandi canonici

```bash
npm run check:js
npm run format:js
npm run test:e2e
```

## File principali

- `public/index.html`: pagina principale e bootstrap runtime.
- `public/js/main.js`: orchestrazione UI.
- `public/js/api.js`: chiamate API/meteo e normalizzazione dati.
- `public/js/render.js`: rendering delle previsioni.
- `public/js/autocomplete.js`: ricerca città.
- `public/js/storage.js`: persistenza locale.
- `public/js/telegram.js`: collegamento Telegram.
- `public/js/supporter.js`: widget supporter.
- `public/service-worker.js`: cache/PWA/push.

## Regole

- Non reintrodurre vecchi monoliti come `public/app.js`.
- Non aggiungere funzioni serverless Netlify: le API vivono nel backend FastAPI.
- Se si modifica service worker, asset statici o PWA, aggiornare `CACHE_NAME`.
- Biome è il formatter/linter JS canonico.
- Playwright va usato per flussi UI critici, non per ogni micro-modifica.
