# AGENTS.md

Guida operativa per agenti. Solo regole e decisioni non deducibili dal codice.

---

## Progetto

App meteo italiana (**leprevisioni**). Frontend Vanilla JS su Netlify, backend FastAPI su Render, DB Neon PostgreSQL in produzione. Open-Meteo come provider primario (chiamato dal browser); `met.no` come fallback.

---

## Non negoziabili

- Rispondere in italiano all'utente, salvo richiesta diversa.
- In caso di dubbi sulla richiesta dell'utente, fare domande prima di procedere con assunzioni operative.
- Prima di modificare codice, esplorare con `rg` / `rg --files`. Non fidarsi del `README.md`: verificare sempre nel codice reale.
- Non committare: `.env`, segreti, DB locali, cache, artifact generati.
- Non fare `git push` né deploy senza richiesta esplicita. La parola `deploy` è richiesta sufficiente — non chiedere conferma aggiuntiva.
- Per modifiche a `render.yaml`, `database.py` o script di migrazione: dichiarare le modifiche prima di committare.
- Non eseguire `git reset --hard` o checkout distruttivi senza richiesta esplicita.
- Non ripristinare modifiche dell'utente senza richiesta esplicita, nemmeno se sembrano errori.
- Non refactorare codice non collegato alla richiesta.
- Se la richiesta è ambigua tra frontend e backend, chiedere prima di procedere.

---

## Decisioni architetturali

- `netlify/functions/` è **legacy**: non usarlo per nuove integrazioni.
- `public/js/` è il frontend reale (modulare). Non reintrodurre `public/app.js` o `public/ml-model.js`.
- Non hardcodare città specifiche: usare sempre la risoluzione via geocoding Open-Meteo.
- `ENABLE_SCHEDULER=false` sul web service Render in produzione — il ciclo ML e le notifiche Telegram girano come cron job separati, non in-process.
- Non usare il DB di produzione (Neon) in locale.
- Non aumentare aggressivamente concorrenza o pacing batch Open-Meteo senza verificare i limiti upstream.

---

## Deploy

- Branch di lavoro: `Produzione`. Solo commit locali per default.
- L'auto-deploy Render non è sempre affidabile: dopo ogni deploy backend, verificare il commit live prima di considerarlo concluso.
- Se deploy frontend + backend, eseguire entrambi.
- Render free tier va in cold start dopo inattività: considerarlo nei timeout e negli smoke test.
- Se `/api/weather` torna `502`: controllare i log Render per `Open-Meteo` e `429` prima di qualsiasi altro intervento.

---

## Verifica

- Definire la verifica più restrittiva applicabile alla modifica, e partire da quella.
- I test backend vanno eseguiti da `meteo-backend/` per evitare problemi di path Alembic.
- Se si modifica service worker, asset statici o file PWA: aggiornare `CACHE_NAME` in `public/service-worker.js`.
- Se la verifica non è eseguibile, dichiararlo esplicitamente con il rischio residuo.

---

## Principi

1. **Minimalità**: la modifica corretta è la più piccola che soddisfa il requisito.
2. **Fonte di verità nel codice**: `render.yaml` e i file di configurazione reali battono qualsiasi documentazione, incluso questo file.
3. **Fail fast esplicito**: se qualcosa non torna, fermarsi e dichiararlo invece di procedere con un'assunzione.
4. **Nessuna regressione silenziosa**: non sovrascrivere lavoro dell'utente senza richiesta esplicita.
