# Architettura

`meteo-ai-app` è divisa in due superfici principali:

- frontend statico Vanilla JS in `public/`, pubblicato come sito statico;
- backend FastAPI in `meteo-backend/`, pubblicato su Render.

## Flusso principale

1. Il browser carica `public/index.html` e i moduli in `public/js/`.
2. La ricerca città usa il backend per indice/autocomplete e fallback Open-Meteo quando previsto.
3. Il meteo base viene normalizzato e renderizzato dal frontend.
4. Il backend fornisce arricchimenti: ML, API avanzate, notifiche, supporter/admin.
5. In produzione il DB è PostgreSQL/Neon; in locale non usare il DB di produzione.

## Regole di manutenzione

- `public/js/` è il frontend reale.
- `netlify/functions/` è legacy: non aggiungere nuove integrazioni lì.
- `meteo-backend/main.py` registra middleware, health/readiness e router.
- `meteo-backend/routers/` contiene gli endpoint pubblici/amministrativi.
- `meteo-backend/*_service.py` contiene logica applicativa e integrazioni esterne.
- Evitare refactor trasversali senza test e senza necessità concreta.
