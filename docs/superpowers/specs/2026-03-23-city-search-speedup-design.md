# Design: Velocizzazione ricerca città (pre-fetch indice locale)

**Data:** 2026-03-23
**Stato:** Approvato

## Problema

La ricerca autocomplete città ha una latenza percepita di ~650-900ms dopo ogni digitazione:
- 250ms di debounce artificiale
- ~400ms di round-trip HTTP verso il backend Render free tier

L'utente deve aspettare quasi 1 secondo dopo aver finito di digitare prima di vedere i suggerimenti.

## Soluzione

Pre-fetch dell'indice completo dei comuni al caricamento della pagina. La ricerca autocomplete diventa 100% locale in JS, eliminando le chiamate HTTP durante la digitazione.

## Architettura

### Backend — nuovo endpoint

`GET /api/cities/index`

Restituisce tutti i record della tabella `City` come array JSON compatto:
```json
[
  {"name": "Roma", "region": "Lazio", "lat": 41.9028, "lon": 12.4964, "locality_type": "comune"},
  ...
]
```

- Nessun parametro
- GZip middleware comprime automaticamente la risposta (~200KB → ~60KB)
- Aggiungere `GZipMiddleware` in `main.py` se non presente

### Frontend — modifiche a `app.js`

**Caricamento indice:**
- Variabile modulo `_cityIndex = null`
- Funzione `loadCityIndex()` chiamata all'avvio dell'app:
  1. Controlla `localStorage` per chiave `city_index` con TTL 24h
  2. Se valido: carica da localStorage (istantaneo)
  3. Se scaduto o assente: fetch da `/api/cities/index`, salva in localStorage con timestamp

**Schema localStorage:**
```json
{ "data": [...], "ts": 1711123456789 }
```
TTL: `Date.now() - ts > 86_400_000` (24h)

**Ricerca locale — funzione `searchLocalIndex(query)`:**
1. Prima passata: nomi che iniziano con la query (`name_lower.startsWith(q)`)
   - Ordine: comuni ISTAT prima (`locality_type === "comune"`), poi per lunghezza nome crescente
2. Seconda passata: nomi che contengono la query (se risultati < 8), escludendo già trovati
3. Unione con `CONFIG.ITALIAN_CITIES` (frazioni hardcoded) senza duplicati
4. Slice a 8 risultati

**Debounce:** 250ms → 80ms (utile ancora per non cercare a ogni tasto su digitazione veloce)

**Fallback:** se `_cityIndex === null` (indice non ancora scaricato), usa la chiamata backend esistente

## File modificati

| File | Modifica |
|------|----------|
| `meteo-backend/routers/cities.py` | Aggiunge endpoint `GET /api/cities/index` |
| `meteo-backend/main.py` | Aggiunge `GZipMiddleware` se assente |
| `public/app.js` | `loadCityIndex()`, `searchLocalIndex()`, modifica `initAutocomplete()`, debounce 80ms |

## Impatto atteso

| Metrica | Prima | Dopo |
|---------|-------|------|
| Latenza ricerca | ~650-900ms | ~0ms (dopo caricamento indice) |
| Download iniziale | 0KB | ~60KB (compresso) |
| Chiamate HTTP per autocomplete | 1 per keystroke | 0 |
| Funzionamento offline | No | Sì (dopo primo caricamento) |

## Non incluso

- Nessuna modifica agli altri endpoint
- Nessun refactoring del codice non coinvolto
- Nessuna modifica al flusso di ricerca meteo (solo autocomplete)
