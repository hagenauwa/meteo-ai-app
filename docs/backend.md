# Backend

Backend FastAPI in `meteo-backend/`.

## Comandi canonici

```bash
cd meteo-backend
./.venv/bin/python -m pytest -q
```

Dal root repo:

```bash
npm run check:backend
npm run check:py
```

## File principali

- `main.py`: app FastAPI, middleware, router, health/readiness.
- `database.py`: SQLAlchemy, sessioni, bootstrap DB/Alembic.
- `config.py`: settings da ambiente.
- `weather_service.py`: provider meteo e formattazione backend.
- `ml_model.py`: training, inferenza e persistenza ML.
- `scheduler.py`: ciclo ML/notifiche quando abilitato.
- `routers/`: endpoint API.
- `tests/`: regression test backend.

## Regole

- Test backend sempre da `meteo-backend/` o tramite `npm run check:backend`.
- Non usare Neon/prod DB in locale.
- Per `database.py`, `render.yaml` e migrazioni: modifiche piccole e dichiarate.
- Ogni bug sottile dovrebbe avere un regression test mirato.

## Contratto di validazione ML

- `open-meteo-model-current` è un valore modellistico, non una misura reale.
- In produzione `ML_REQUIRE_TRUSTED_OBSERVATIONS=true`: il training accetta solo
  le sorgenti elencate in `ML_TRUSTED_OBSERVATION_SOURCES`.
- Le precipitazioni usate come target devono rappresentare un accumulo di 60 minuti.
- Una osservazione verifica tutte le previsioni emesse per lo stesso target ai
  diversi orizzonti.
- Il training mantiene un holdout temporale mai usato nel fit; blend e promozione
  richiedono un miglioramento rispetto al provider, non a una baseline costante.
- Ogni previsione del ciclo salva uno snapshot immutabile dell'output servito e
  della coppia candidata V1/V2 disponibile all'emissione. `issued_kpis` e gate
  shadow sono prequential: non ricalcolano il modello corrente sul passato.
- V2 resta in shadow e con rollout zero finché i gate non vengono superati e la
  configurazione di produzione non viene modificata intenzionalmente.
