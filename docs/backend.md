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
