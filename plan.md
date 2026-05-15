# Piano Modifiche — Meteo AI App (Branch Sviluppo)

## Obiettivi
Implementare le migliorie suggerite con zero regressioni. Ogni stadio è validato prima del successivo.

## Stage 1 — Documentazione (parallelo, sicuro)
- **A. README.md**: Aggiornare stack tecnologico (FastAPI, scikit-learn, Open-Meteo, Render), struttura progetto, deploy.
- **B. AVVIO-RAPIDO.md**: Aggiornare con setup backend Python e dual-deploy (Netlify + Render).

## Stage 2 — Backend Hardening (parallelo, a basso rischio)
- **C. Rate Limiting**: Middleware custom in-memory su `meteo-backend/` senza nuove dipendenze. Limiti: 60 req/min per IP su endpoint pubblici. Esclude `/health`, `/ready`.
- **D. Logging Strutturato**: Sostituire i `print()` critici in `main.py`, `scheduler.py`, `weather_service.py` con `logging` JSON-ready. Mantenere compatibilità output esistente.

## Stage 3 — Nuove Feature (parallelo, isolato)
- **E. Dashboard Admin**: Nuova pagina `public/admin.html` separata. UI glassmorphism che chiama `/ready`, `/api/admin/status` (protetta da token), `/api/ml/stats`. HTML+CSS+JS autonomo, zero impatto su `index.html`.
- **F. API Avanzate**: Nuovo endpoint `/api/weather/advanced` che arricchisce meteo con UV index + qualità aria (Open-Meteo Air Quality API). Aggiungere funzione frontend opzionale che mostra badge UV nella snapshot card.

## Stage 4 — Validazione Anti-Regressione
- **Tester**: Verificare che:
  - `/health` e `/ready` rispondano 200
  - `/api/weather?city=Roma` risponda 200 con blocchi `current`, `hourly`, `daily`, `ml`
  - `/api/admin/status` con token risponda 200
  - `/api/ml/enrich` risponda 200
  - Frontend `index.html` funzioni (ricerca, render, preferiti)
  - Service worker e manifest invariati
  - Nessun nuovo errore CORS
  - Nessun nuovo import mancante

## Regole Anti-Regression
1. Non toccare mai `public/index.html`, `public/js/main.js`, `public/style.css` per le feature esistenti. Solo aggiungere nuovi file o funzioni isolate.
2. Non modificare signature di funzioni esistenti. Wrappare se necessario.
3. Non rimuovere dipendenze esistenti da `requirements.txt` o `package.json`.
4. Ogni modifica backend deve includere testo di fallback identico in caso di errore.
5. Dopo ogni stage, diff dei file modificati per verificare scope.
