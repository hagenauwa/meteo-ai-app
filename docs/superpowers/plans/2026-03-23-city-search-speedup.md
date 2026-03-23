# Velocizzazione Ricerca Città — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare la latenza dell'autocomplete città spostando la ricerca dal backend al client tramite pre-fetch dell'indice completo dei comuni.

**Architecture:** Il backend espone un nuovo endpoint `GET /api/cities/index` che restituisce tutti i comuni in formato compatto; il frontend scarica l'indice al caricamento (con cache localStorage 24h) e fa la ricerca interamente in JS durante la digitazione, senza chiamate HTTP aggiuntive.

**Tech Stack:** FastAPI (Python), GZipMiddleware, Vanilla JS, localStorage

---

## File Map

| File | Operazione | Responsabilità |
|------|-----------|----------------|
| `meteo-backend/main.py` | Modifica | Aggiunge `GZipMiddleware` |
| `meteo-backend/routers/cities.py` | Modifica | Aggiunge endpoint `GET /api/cities/index` |
| `meteo-backend/tests/test_cities_index.py` | Crea | Test pytest per il nuovo endpoint |
| `public/app.js` | Modifica | `_cityIndex`, `loadCityIndex()`, `searchLocalIndex()`, `initAutocomplete()` aggiornato |

---

## Task 1: Backend — GZipMiddleware

**Files:**
- Modify: `meteo-backend/main.py:81-86`

- [ ] **Step 1: Aggiungi GZipMiddleware in main.py**

Apri `meteo-backend/main.py`. Dopo l'import di `CORSMiddleware` (riga ~13) aggiungi:

```python
from fastapi.middleware.gzip import GZipMiddleware
```

Poi dopo il blocco `app.add_middleware(CORSMiddleware, ...)` (riga ~86) aggiungi:

```python
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

- [ ] **Step 2: Verifica che il server si avvii senza errori**

```bash
cd meteo-backend
uvicorn main:app --reload
```

Atteso: `[OK] Backend pronto` senza errori. Poi Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add meteo-backend/main.py
git commit -m "feat: aggiunge GZipMiddleware al backend"
```

---

## Task 2: Backend — endpoint /api/cities/index

**Files:**
- Modify: `meteo-backend/routers/cities.py`
- Create: `meteo-backend/tests/test_cities_index.py`

- [ ] **Step 1: Scrivi il test**

Crea il file `meteo-backend/tests/test_cities_index.py`:

```python
"""Test per l'endpoint GET /api/cities/index"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Importa l'app — assicurati di essere nella directory meteo-backend
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app

client = TestClient(app)


def make_fake_city(name="Roma", region="Lazio", lat=41.9, lon=12.5, locality_type="comune"):
    city = MagicMock()
    city.name = name
    city.region = region
    city.lat = lat
    city.lon = lon
    city.locality_type = locality_type
    return city


def test_cities_index_returns_list():
    """L'endpoint restituisce una lista JSON."""
    fake_cities = [make_fake_city("Roma"), make_fake_city("Milano", "Lombardia", 45.4, 9.1)]
    with patch("routers.cities.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = fake_cities
        mock_get_db.return_value = iter([mock_db])
        response = client.get("/api/cities/index")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_cities_index_item_shape():
    """Ogni elemento ha name, region, lat, lon, locality_type — senza id."""
    fake_cities = [make_fake_city()]
    with patch("routers.cities.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = fake_cities
        mock_get_db.return_value = iter([mock_db])
        response = client.get("/api/cities/index")
    item = response.json()[0]
    assert "name" in item
    assert "region" in item
    assert "lat" in item
    assert "lon" in item
    assert "locality_type" in item
    assert "id" not in item
```

- [ ] **Step 2: Esegui il test — attendi FAIL**

```bash
cd meteo-backend
pytest tests/test_cities_index.py -v
```

Atteso: FAIL — `404 Not Found` o `ImportError` perché l'endpoint non esiste ancora.

- [ ] **Step 3: Aggiungi l'endpoint in cities.py**

In `meteo-backend/routers/cities.py`, dopo la classe `CityResult`, aggiungi il nuovo schema e l'endpoint **prima** del router `/cities` esistente:

```python
class CityIndexItem(BaseModel):
    name:          str
    region:        str | None
    lat:           float
    lon:           float
    locality_type: str | None = "comune"

    class Config:
        from_attributes = True  # necessario per serializzare oggetti ORM SQLAlchemy


@router.get("/cities/index", response_model=List[CityIndexItem])
def get_cities_index(db: Session = Depends(get_db)):
    """
    Restituisce tutti i comuni in formato compatto per il pre-fetch frontend.
    Usato da app.js per la ricerca autocomplete locale (zero latency).
    """
    cities = db.query(City).all()
    return cities
```

> **ATTENZIONE:** l'endpoint `/cities/index` deve essere dichiarato **prima** di `/cities/{city_id}`, altrimenti FastAPI interpreta "index" come un `city_id` intero e restituisce 422.

- [ ] **Step 4: Esegui il test — attendi PASS**

```bash
cd meteo-backend
pytest tests/test_cities_index.py -v
```

Atteso: tutti i test PASS.

- [ ] **Step 5: Verifica manuale con il server acceso**

```bash
uvicorn main:app --reload
# In un altro terminale:
curl -s http://localhost:8000/api/cities/index | python -c "import sys,json; d=json.load(sys.stdin); print(f'Records: {len(d)}, primo: {d[0]}')"
```

Atteso: stampa il numero di records e il primo elemento senza campo `id`.

- [ ] **Step 6: Commit**

```bash
git add meteo-backend/routers/cities.py meteo-backend/tests/test_cities_index.py
git commit -m "feat: aggiunge endpoint GET /api/cities/index per pre-fetch frontend"
```

---

## Task 3: Frontend — loadCityIndex() e searchLocalIndex()

**Files:**
- Modify: `public/app.js`

Lavora sul file `public/app.js`. Tutte le modifiche sono in questo file.

- [ ] **Step 1: Aggiungi la variabile _cityIndex a livello modulo**

Subito dopo la dichiarazione di `BACKEND_URL` (riga ~14), aggiungi:

```javascript
// Indice città pre-fetchato al caricamento — null finché non è pronto
let _cityIndex = null;
```

- [ ] **Step 2: Aggiungi la funzione loadCityIndex()**

Subito prima della funzione `initAutocomplete()` (cerca `function initAutocomplete()`), aggiungi:

```javascript
/**
 * Carica l'indice completo delle città dal backend (o da localStorage se valido).
 * Chiamata una volta all'avvio. Popola _cityIndex.
 * TTL: 24h. Chiave: meteo_city_index_v1
 */
async function loadCityIndex() {
    const CACHE_KEY = 'meteo_city_index_v1';
    const TTL_MS = 86_400_000; // 24 ore

    try {
        const cached = localStorage.getItem(CACHE_KEY);
        if (cached) {
            const parsed = JSON.parse(cached);
            if (parsed.ts && (Date.now() - parsed.ts) < TTL_MS) {
                _cityIndex = parsed.data;
                console.log(`[CityIndex] Caricato da cache: ${_cityIndex.length} città`);
                return;
            }
        }
    } catch (_) {
        // localStorage non disponibile o JSON corrotto — procedi con fetch
    }

    try {
        const resp = await fetch(`${BACKEND_URL}/api/cities/index`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _cityIndex = data;
        try {
            localStorage.setItem(CACHE_KEY, JSON.stringify({ data, ts: Date.now() }));
        } catch (_) {
            // localStorage pieno — ignora, _cityIndex è comunque in memoria
        }
        console.log(`[CityIndex] Scaricato dal backend: ${_cityIndex.length} città`);
    } catch (e) {
        console.warn('[CityIndex] Pre-fetch fallito, uso backend per autocomplete:', e.message);
        // _cityIndex rimane null → initAutocomplete userà il fallback backend
    }
}
```

- [ ] **Step 3: Aggiungi la funzione searchLocalIndex()**

Subito dopo `loadCityIndex()`, aggiungi:

```javascript
/**
 * Ricerca locale nell'indice pre-fetchato.
 * Algoritmo speculare al backend cities.py:
 *   1. Comuni che iniziano con la query (comuni ISTAT prima, poi per lunghezza)
 *   2. Comuni che contengono la query (se risultati < limit)
 * @param {string} query - testo cercato (già lowercase e trimmed)
 * @param {number} limit - max risultati (default 8)
 * @returns {Array} array di oggetti {name, region, lat, lon, locality_type}
 */
function searchLocalIndex(query, limit = 8) {
    if (!_cityIndex) return [];

    const q = query.toLowerCase().trim();
    if (!q) return [];

    const scoreType = c => c.locality_type === 'comune' ? 0 : 1;

    // Passata 1: inizia con la query
    const startsWith = _cityIndex
        .filter(c => c.name.toLowerCase().startsWith(q))
        .sort((a, b) => scoreType(a) - scoreType(b) || a.name.length - b.name.length)
        .slice(0, limit);

    if (startsWith.length >= limit) return startsWith;

    // Passata 2: contiene la query (escludi già trovati)
    const foundNames = new Set(startsWith.map(c => c.name.toLowerCase()));
    const contains = _cityIndex
        .filter(c => !foundNames.has(c.name.toLowerCase()) && c.name.toLowerCase().includes(q))
        .sort((a, b) => scoreType(a) - scoreType(b) || a.name.length - b.name.length)
        .slice(0, limit - startsWith.length);

    return [...startsWith, ...contains];
}
```

- [ ] **Step 4: Modifica initAutocomplete() — usa la ricerca locale**

Trova la funzione `initAutocomplete()` e sostituisci il blocco interno dell'event listener `input` (il `setTimeout` con la logica di ricerca). Il timer passa da 250ms a 80ms e la chiamata backend viene sostituita dalla ricerca locale con fallback.

Trova questo blocco:

```javascript
        clearTimeout(_autocompleteTimer);
        _autocompleteTimer = setTimeout(async () => {
            try {
                const valLower = val.toLowerCase();

                // Cerca nel dizionario locale (frazioni, mete turistiche non nei comuni ISTAT)
                const localMatches = Object.keys(CONFIG.ITALIAN_CITIES)
                    .filter(k => k.startsWith(valLower) || k.includes(valLower))
                    .slice(0, 4)
                    .map(k => ({
                        name: k.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
                        region: CITY_REGIONS[k] || '',
                        local: true
                    }));

                // Cerca nel backend (8.000 comuni ISTAT)
                let backendCities = [];
                try {
                    const resp = await apiFetch(
                        `${CONFIG.API_ENDPOINTS.cities}?q=${encodeURIComponent(val)}&limit=8`
                    );
                    if (resp.ok) backendCities = await resp.json();
                } catch (_) {}

                // Unisci: locale prima, poi backend (senza duplicati)
                const backendNames = new Set(backendCities.map(c => c.name.toLowerCase()));
                const localUnique = localMatches.filter(c => !backendNames.has(c.name.toLowerCase()));
                const combined = [...localUnique, ...backendCities].slice(0, 8);
```

Sostituiscilo con:

```javascript
        clearTimeout(_autocompleteTimer);
        _autocompleteTimer = setTimeout(async () => {
            try {
                const valLower = val.toLowerCase();

                // Frazioni hardcoded (CONFIG.ITALIAN_CITIES) — hanno priorità
                const localMatches = Object.keys(CONFIG.ITALIAN_CITIES)
                    .filter(k => k.startsWith(valLower) || k.includes(valLower))
                    .slice(0, 4)
                    .map(k => ({
                        name: k.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
                        region: CITY_REGIONS[k] || '',
                        local: true
                    }));

                // Indice pre-fetchato (preferito) oppure fallback al backend
                let indexCities = [];
                if (_cityIndex) {
                    indexCities = searchLocalIndex(valLower);
                } else {
                    try {
                        const resp = await apiFetch(
                            `${CONFIG.API_ENDPOINTS.cities}?q=${encodeURIComponent(val)}&limit=8`
                        );
                        if (resp.ok) indexCities = await resp.json();
                    } catch (_) {}
                }

                // Unisci: frazioni hardcoded prima (hanno priorità), poi indice (senza duplicati)
                const indexNames = new Set(indexCities.map(c => c.name.toLowerCase()));
                const localUnique = localMatches.filter(c => !indexNames.has(c.name.toLowerCase()));
                const combined = [...localUnique, ...indexCities].slice(0, 8);
```

- [ ] **Step 5: Cambia il debounce da 250ms a 80ms**

Nella stessa funzione `initAutocomplete()`, l'ultima riga del `setTimeout` mostra `}, 250);`.
Cambiala in:

```javascript
        }, 80);
```

- [ ] **Step 6: Chiama loadCityIndex() all'avvio**

Cerca la funzione di inizializzazione principale. Probabilmente è `initApp()` o simile. Cerca il punto dove vengono chiamati `initAutocomplete()` e altri `init*`.

Aggiungi **prima** di `initAutocomplete()`:

```javascript
    loadCityIndex(); // pre-fetch indice comuni in background (non blocca l'UI)
```

- [ ] **Step 7: Test manuale nel browser**

1. Avvia il backend: `cd meteo-backend && uvicorn main:app --reload`
2. Apri `public/index.html` nel browser (o tramite Live Server)
3. Apri DevTools → Console: deve apparire `[CityIndex] Scaricato dal backend: NNNNN città`
4. Digita "Roma" nel campo di ricerca: i suggerimenti devono apparire in meno di 100ms
5. Ricarica la pagina: nella console deve apparire `[CityIndex] Caricato da cache: NNNNN città` (nessuna nuova richiesta HTTP a `/api/cities/index`)
6. Verifica che "Marina di Massa" (frazione hardcoded) appaia ancora nei suggerimenti quando digiti "marina"

- [ ] **Step 8: Commit**

```bash
git add public/app.js
git commit -m "feat: autocomplete città istantaneo con pre-fetch indice locale (0ms latenza)"
```

---

## Task 4: Deploy

- [ ] **Step 1: Push al repository**

```bash
git push origin master
```

Render rileva il push e si aggiorna automaticamente (~3-5 min).

- [ ] **Step 2: Deploy frontend**

```bash
npm run deploy
```

- [ ] **Step 3: Verifica in produzione**

1. Apri https://leprevisioni.netlify.app
2. DevTools → Network: cerca la richiesta `GET /api/cities/index` al caricamento
3. Digita nel campo ricerca: i suggerimenti devono apparire quasi istantaneamente
4. Ricarica: nessuna nuova richiesta a `/api/cities/index` (usa localStorage)

---

## Note per l'implementatore

- L'endpoint `/cities/index` **deve** essere dichiarato prima di `/cities/{city_id}` in `cities.py` — altrimenti FastAPI tenta di parsare "index" come intero e restituisce 422
- Il `GZipMiddleware` deve avere `minimum_size=1000` per non comprimere risposte piccole inutilmente
- `loadCityIndex()` è fire-and-forget: non blocca il caricamento della pagina. Se fallisce, `_cityIndex` rimane `null` e `initAutocomplete()` usa il fallback backend
- La chiave localStorage `meteo_city_index_v1` include versione: se cambia lo schema, basta cambiare la chiave per forzare il re-fetch
