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
- Meteostat esclude i contributi modellistici (`include_model_data=false`), converte
  la nuvolosità da ottavi a percentuale e salva stazione e distanza. Per ogni ora
  cerca una misura valida nelle tre stazioni più vicine entro 35 km. I target in
  attesa vengono recuperati fino a sette giorni, anche per città uscite dal campione.
- Le vecchie righe `meteostat` sono escluse dal training; solo una nuova misura
  indipendente può sostituirne la verifica con la sorgente `meteostat-observed`.
  Le copie della stessa misura sono deduplicate per stazione, ora e orizzonte.
- Una osservazione verifica tutte le previsioni emesse per lo stesso target ai
  diversi orizzonti.
- Il training mantiene un holdout temporale mai usato nel fit; blend e promozione
  richiedono un miglioramento rispetto al provider, non a una baseline costante.
- Ogni previsione del ciclo salva uno snapshot immutabile dell'output servito e
  della coppia candidata V1/V2 disponibile all'emissione. `issued_kpis` e gate
  shadow sono prequential: non ricalcolano il modello corrente sul passato.
- V2 resta in shadow e con rollout zero finché i gate non vengono superati e la
  configurazione di produzione non viene modificata intenzionalmente.
- Lo stato shadow è persistito in `ml_model_store.validation_state`, legato alla
  versione che ha emesso gli snapshot. Le due finestre devono contenere nuovi
  eventi; un riaddestramento azzera il permesso. Il candidato può attendere fino
  a sette giorni per raccogliere prove; una finestra negativa interrompe l'attesa.
- Tutti i KPI della pioggia pubblici usano snapshot precedenti all'evento, senza
  inferenza sul passato. Le feature temporali ML sono UTC; API `hour` e orari
  visualizzati mantengono la convenzione Europe/Rome.
- Le probabilità e le condizioni giornaliere restano quelle del provider: il
  modello orario non è validato sugli accumuli giornalieri.

## Transizione al formato modello 4

La migrazione `20260912_0001` aggiunge cinque colonne nullable, senza riscrivere
lo storico. Il bootstrap DB applica Alembic prima di usare il nuovo schema.
Il formato modello 4 esclude i vecchi modelli, potenzialmente addestrati su
stime o unità errate. Fino a un nuovo training valido le previsioni usano il
provider. La durata dipende dalle misure disponibili; non equivale a un guasto
del servizio meteo. Un ciclo cron fallito ora termina con codice diverso da zero.

## Notifiche Telegram

- Il cron di produzione controlla gli avvisi ogni 15 minuti.
- Gli intervalli orari Open-Meteo sono interpretati come periodi che terminano
  al timestamp restituito. Gli intervalli già conclusi non generano avvisi.
- Gli avvisi ML richiedono una verifica della policy effettiva (probabilità almeno
  50% e soglia del modello): almeno 200 eventi distinti, 20 eventi piovosi,
  precisione e richiamo non inferiori al provider e Brier migliore. In assenza
  di validazione o di una probabilità valida resta attivo il fallback provider.
- Le fasce del promemoria giornaliero sono filtrate sulla data locale richiesta.
- La sottoscrizione conserva coordinate, regione e provincia della località
  selezionata per evitare ambiguità tra città omonime.
- Ogni avviso inviato viene registrato in `telegram_rain_alerts`. Se sono
  disponibili osservazioni da fonti fidate, il cron lo classifica come `hit` o
  `false_alarm` senza usare i valori modellistici come verità osservata.
