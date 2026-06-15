# Deploy

Deploy solo su richiesta esplicita.

## Branch

- Branch di lavoro: `Produzione`.
- Commit locale non equivale a deploy.
- Non fare `git push` senza richiesta.

## Frontend

Sito statico da `public/`.

```bash
npm run build
npm run deploy
```

`npm run deploy` usa Netlify CLI e va eseguito solo quando richiesto.

## Backend

Backend FastAPI su Render da `meteo-backend/`.

Prima di deploy backend:

```bash
npm run check
```

Dopo deploy backend:

- verificare health/readiness;
- considerare cold start Render;
- verificare il commit live quando possibile.

## Produzione DB

Non usare il database Neon di produzione in locale. Qualsiasi modifica a schema/migrazioni richiede verifica mirata e attenzione extra.
