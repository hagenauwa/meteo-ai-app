/**
 * ============================================
 * APP.JS - APPLICAZIONE METEO PRINCIPALE
 * Gestione UI, API OpenWeatherMap, Integrazione ML
 * ============================================
 */

// ============================================
// CONFIGURAZIONE
// ============================================
// URL del backend Python sul VPS — modifica con il tuo dominio/IP
const BACKEND_URL = (typeof window !== 'undefined' && window.BACKEND_URL)
    ? window.BACKEND_URL
    : 'http://localhost:8000';

const CONFIG = {
    // Manteniamo un piccolo set di città per fallback offline (opzionale)
    // La lista completa (~8.000 comuni) arriva dal backend
    ITALIAN_CITIES: {
        // Regioni Nord
        'roma': { lat: 41.9028, lon: 12.4964 },
        'milano': { lat: 45.4642, lon: 9.1900 },
        'torino': { lat: 45.0703, lon: 7.6869 },
        'genova': { lat: 44.4056, lon: 8.9463 },
        'venezia': { lat: 45.4408, lon: 12.3155 },
        'bologna': { lat: 44.4949, lon: 11.3426 },
        'verona': { lat: 45.4384, lon: 10.9916 },
        'padova': { lat: 45.4064, lon: 11.8768 },
        'trieste': { lat: 45.6495, lon: 13.7768 },
        'brescia': { lat: 45.5416, lon: 10.2118 },
        'parma': { lat: 44.8015, lon: 10.3279 },
        'prato': { lat: 43.8800, lon: 11.0976 },
        'modena': { lat: 44.6471, lon: 10.9252 },
        'reggio emilia': { lat: 44.6983, lon: 10.6313 },
        'bergamo': { lat: 45.6983, lon: 9.6773 },
        'monza': { lat: 45.5806, lon: 9.2735 },
        'como': { lat: 45.8094, lon: 9.0820 },
        'varese': { lat: 45.8206, lon: 8.8251 },
        'pavia': { lat: 45.1847, lon: 9.1582 },
        'alessandria': { lat: 44.9090, lon: 8.6103 },
        'asti': { lat: 44.9008, lon: 8.2065 },
        'novara': { lat: 45.4455, lon: 8.6182 },
        'cuneo': { lat: 44.3932, lon: 7.5460 },
        'savona': { lat: 44.3080, lon: 8.3740 },
        'albenga': { lat: 44.0501, lon: 8.2138 },
        'alassio': { lat: 44.0077, lon: 8.1718 },
        'sanremo': { lat: 43.8157, lon: 7.7758 },
        'imperia': { lat: 43.8839, lon: 8.0247 },
        'bordighera': { lat: 43.7807, lon: 7.6679 },
        'ventimiglia': { lat: 43.7893, lon: 7.6090 },
        'finale ligure': { lat: 44.1700, lon: 8.3437 },
        'sestri levante': { lat: 44.2714, lon: 9.3955 },
        'rapallo': { lat: 44.3514, lon: 9.2299 },
        'santa margherita ligure': { lat: 44.3348, lon: 9.2131 },
        'portofino': { lat: 44.3037, lon: 9.2099 },
        'chiavari': { lat: 44.3178, lon: 9.3255 },
        'levanto': { lat: 44.1700, lon: 9.6101 },
        'la spezia': { lat: 44.1024, lon: 9.8241 },
        'trento': { lat: 46.0748, lon: 11.1217 },
        'bolzano': { lat: 46.4983, lon: 11.3548 },
        'udine': { lat: 46.0711, lon: 13.2347 },
        'pordenone': { lat: 45.9627, lon: 12.6555 },
        'gorizia': { lat: 45.9402, lon: 13.6206 },
        'biella': { lat: 45.5728, lon: 8.0542 },
        'verbania': { lat: 45.9332, lon: 8.5420 },
        'lecco': { lat: 45.8554, lon: 9.3970 },
        'lodi': { lat: 45.3145, lon: 9.5038 },
        'cremona': { lat: 45.1340, lon: 10.0224 },
        'mantova': { lat: 45.1564, lon: 10.7914 },
        'ferrara': { lat: 44.8372, lon: 11.6214 },
        'ravenna': { lat: 44.4184, lon: 12.2035 },
        'forli': { lat: 44.2227, lon: 12.0407 },
        'cesena': { lat: 44.1392, lon: 12.2432 },
        'rimini': { lat: 44.0595, lon: 12.5684 },
        'riccione': { lat: 44.0044, lon: 12.6566 },
        'cattolica': { lat: 43.9638, lon: 12.7344 },
        'misano adriatico': { lat: 43.9796, lon: 12.6962 },
        'cesenatico': { lat: 44.2022, lon: 12.3960 },
        'cervia': { lat: 44.2608, lon: 12.3523 },
        'marina di ravenna': { lat: 44.4833, lon: 12.2833 },
        'pesaro': { lat: 43.9098, lon: 12.9131 },
        'ancona': { lat: 43.6158, lon: 13.5189 },
        'ascoli piceno': { lat: 42.8536, lon: 13.5745 },
        'macerata': { lat: 43.3002, lon: 13.4532 },
        'fermo': { lat: 43.1600, lon: 13.7180 },
        'camerino': { lat: 43.1356, lon: 13.0688 },
        'rovigo': { lat: 45.0727, lon: 11.7907 },
        'vicenza': { lat: 45.5493, lon: 11.5487 },
        'treviso': { lat: 45.6669, lon: 12.2450 },
        'belluno': { lat: 46.1426, lon: 12.2157 },
        'rovigo': { lat: 45.0727, lon: 11.7907 },

        // Regioni Centro
        'firenze': { lat: 43.7696, lon: 11.2558 },
        'livorno': { lat: 43.5528, lon: 10.3087 },
        'pisa': { lat: 43.7228, lon: 10.4017 },
        'lucca': { lat: 43.8429, lon: 10.5027 },
        'siena': { lat: 43.3188, lon: 11.3308 },
        'arezzo': { lat: 43.4633, lon: 11.8796 },
        'pistoia': { lat: 43.9336, lon: 10.9174 },
        'massa': { lat: 44.0383, lon: 10.1447 },
        'marina di massa': { lat: 44.0167, lon: 10.0667 },
        'marina di carrara': { lat: 44.0354, lon: 10.0520 },
        'carrara': { lat: 44.0793, lon: 10.0976 },
        'forte dei marmi': { lat: 43.9632, lon: 10.1702 },
        'viareggio': { lat: 43.8677, lon: 10.2509 },
        'lido di camaiore': { lat: 43.9133, lon: 10.2283 },
        'camaiore': { lat: 43.9352, lon: 10.3100 },
        'pietrasanta': { lat: 43.9608, lon: 10.2277 },
        'montignoso': { lat: 44.0100, lon: 10.1400 },
        'piombino': { lat: 42.9250, lon: 10.5259 },
        'val di cornia': { lat: 43.0500, lon: 10.6167 },
        'san vincenzo': { lat: 43.0967, lon: 10.5372 },
        'campiglia marittima': { lat: 43.0618, lon: 10.6126 },
        'suvereto': { lat: 43.0753, lon: 10.6901 },
        'grosseto': { lat: 42.7597, lon: 11.1137 },
        'perugia': { lat: 43.1107, lon: 12.3908 },
        'terni': { lat: 42.5636, lon: 12.6437 },
        'foligno': { lat: 42.9563, lon: 12.7033 },
        'citta di castello': { lat: 43.4563, lon: 12.2379 },
        'orvieto': { lat: 42.7201, lon: 12.1113 },
        'viterbo': { lat: 42.4207, lon: 12.1077 },
        'rieti': { lat: 42.4044, lon: 12.8626 },
        'frosinone': { lat: 41.6400, lon: 13.3400 },
        'latina': { lat: 41.4676, lon: 12.9037 },
        'pomezia': { lat: 41.6694, lon: 12.5012 },
        'civitavecchia': { lat: 42.0933, lon: 11.7974 },
        'anzio': { lat: 41.4479, lon: 12.6271 },
        'nettuno': { lat: 41.4580, lon: 12.6637 },
        'ostia': { lat: 41.7286, lon: 12.2826 },
        'fiumicino': { lat: 41.7757, lon: 12.2354 },
        'terracina': { lat: 41.2935, lon: 13.2469 },
        'sabaudia': { lat: 41.3000, lon: 13.0167 },
        'sperlonga': { lat: 41.2564, lon: 13.4301 },
        'gaeta': { lat: 41.2134, lon: 13.5720 },
        'formia': { lat: 41.2567, lon: 13.6167 },
        'l aquila': { lat: 42.3498, lon: 13.3995 },
        'aquila': { lat: 42.3498, lon: 13.3995 },
        'chieti': { lat: 42.3510, lon: 14.1675 },
        'pescara': { lat: 42.4618, lon: 14.2161 },
        'teramo': { lat: 42.6589, lon: 13.7039 },
        'campobasso': { lat: 41.5595, lon: 14.6674 },
        'isernia': { lat: 41.5952, lon: 14.2336 },

        // Regioni Sud
        'napoli': { lat: 40.8518, lon: 14.2681 },
        'salerno': { lat: 40.6824, lon: 14.7681 },
        'caserta': { lat: 41.0724, lon: 14.3316 },
        'avellino': { lat: 40.9142, lon: 14.7884 },
        'benevento': { lat: 41.1298, lon: 14.7826 },
        'pozzuoli': { lat: 40.8518, lon: 14.0858 },
        'sorrento': { lat: 40.6262, lon: 14.3757 },
        'amalfi': { lat: 40.6340, lon: 14.6027 },
        'positano': { lat: 40.6281, lon: 14.4831 },
        'ravello': { lat: 40.6499, lon: 14.6122 },
        'ischia': { lat: 40.7318, lon: 13.9444 },
        'capri': { lat: 40.5500, lon: 14.2375 },
        'procida': { lat: 40.7667, lon: 14.0167 },
        'paestum': { lat: 40.4218, lon: 15.0036 },
        'agropoli': { lat: 40.3497, lon: 14.9932 },
        'torre del greco': { lat: 40.7899, lon: 14.3689 },
        'giugliano': { lat: 40.9319, lon: 14.1956 },
        'casoria': { lat: 40.9017, lon: 14.2950 },
        'castellammare': { lat: 40.6942, lon: 14.4817 },
        'bari': { lat: 41.1171, lon: 16.8719 },
        'foggia': { lat: 41.4622, lon: 15.5430 },
        'lecce': { lat: 40.3515, lon: 18.1740 },
        'taranto': { lat: 40.4692, lon: 17.2400 },
        'brindisi': { lat: 40.6327, lon: 17.9418 },
        'andria': { lat: 41.2242, lon: 16.2969 },
        'trani': { lat: 41.2775, lon: 16.4182 },
        'barletta': { lat: 41.3193, lon: 16.2832 },
        'altamura': { lat: 40.8267, lon: 16.5495 },
        'molfetta': { lat: 41.2004, lon: 16.6000 },
        'monopoli': { lat: 40.9492, lon: 17.2973 },
        'polignano': { lat: 40.9946, lon: 17.2220 },
        'matera': { lat: 40.6668, lon: 16.6044 },
        'potenza': { lat: 40.6422, lon: 15.7991 },
        'melfi': { lat: 40.9980, lon: 15.6515 },
        'reggio calabria': { lat: 38.1105, lon: 15.6613 },
        'catanzaro': { lat: 38.9098, lon: 16.5877 },
        'cosenza': { lat: 39.3088, lon: 16.2502 },
        'crotone': { lat: 39.0808, lon: 17.1272 },
        'vibo valentia': { lat: 38.6773, lon: 16.0949 },
        'lamezia terme': { lat: 38.9644, lon: 16.3092 },
        'catanzaro lido': { lat: 38.8170, lon: 16.6170 },

        // Isole
        'palermo': { lat: 38.1157, lon: 13.3615 },
        'catania': { lat: 37.5079, lon: 15.0830 },
        'messina': { lat: 38.1938, lon: 15.5540 },
        'siracusa': { lat: 37.0754, lon: 15.2866 },
        'ragusa': { lat: 36.9269, lon: 14.7278 },
        'trapani': { lat: 38.0176, lon: 12.5370 },
        'marsala': { lat: 37.8040, lon: 12.4344 },
        'mazzara': { lat: 37.6542, lon: 12.5883 },
        'agrigento': { lat: 37.3111, lon: 13.5765 },
        'enna': { lat: 37.2574, lon: 14.2845 },
        'caltanissetta': { lat: 37.4901, lon: 14.0624 },
        'gela': { lat: 37.0657, lon: 14.2406 },
        'cagliari': { lat: 39.2238, lon: 9.1217 },
        'sassari': { lat: 40.7259, lon: 8.5556 },
        'nuoro': { lat: 40.3193, lon: 9.3254 },
        'olbia': { lat: 40.9230, lon: 9.4920 },
        'alghero': { lat: 40.5579, lon: 8.3180 },
        'oristano': { lat: 39.9064, lon: 8.5884 },
        'quartu': { lat: 39.2342, lon: 9.2530 },
        'olbia': { lat: 40.9230, lon: 9.4920 },
        'tempio': { lat: 40.9434, lon: 9.1063 },

        // San Marino e Vaticano
        // Laghi
        'lago di garda': { lat: 45.6389, lon: 10.6697 },
        'desenzano': { lat: 45.4672, lon: 10.5373 },
        'sirmione': { lat: 45.4928, lon: 10.5999 },
        'peschiera del garda': { lat: 45.4394, lon: 10.6840 },
        'riva del garda': { lat: 45.8866, lon: 10.8413 },
        'malcesine': { lat: 45.7636, lon: 10.8109 },
        'stresa': { lat: 45.8820, lon: 8.5341 },
        'arona': { lat: 45.7600, lon: 8.5600 },
        'como centro': { lat: 45.8083, lon: 9.0861 },
        'bellagio': { lat: 45.9878, lon: 9.2558 },
        'cernobbio': { lat: 45.8408, lon: 9.0734 },
        // Montagna
        'courmayeur': { lat: 45.7965, lon: 6.9706 },
        'cervinia': { lat: 45.9361, lon: 7.6339 },
        'sestriere': { lat: 44.9579, lon: 6.8819 },
        'cortina d ampezzo': { lat: 46.5361, lon: 12.1356 },
        'madonna di campiglio': { lat: 46.2341, lon: 10.8234 },
        'livigno': { lat: 46.5364, lon: 10.1364 },
        'bormio': { lat: 46.4667, lon: 10.3667 },
        'val gardena': { lat: 46.5674, lon: 11.6972 },
        'ortisei': { lat: 46.5773, lon: 11.6723 },
        'merano': { lat: 46.6691, lon: 11.1572 },
        'canazei': { lat: 46.4765, lon: 11.7718 },
        'san martino di castrozza': { lat: 46.2530, lon: 11.8010 },
        // Puglia costa
        'vieste': { lat: 41.8814, lon: 16.1777 },
        'peschici': { lat: 41.9488, lon: 16.0150 },
        'rodi garganico': { lat: 41.9241, lon: 15.8850 },
        'otranto': { lat: 40.1482, lon: 18.4887 },
        'gallipoli': { lat: 40.0564, lon: 17.9904 },
        'santa maria di leuca': { lat: 39.7981, lon: 18.3526 },
        'alberobello': { lat: 40.7849, lon: 17.2396 },
        'ostuni': { lat: 40.7273, lon: 17.5756 },
        'fasano': { lat: 40.8400, lon: 17.3600 },
        // Sicilia costa
        'taormina': { lat: 37.8517, lon: 15.2877 },
        'cefalù': { lat: 38.0388, lon: 14.0221 },
        'mondello': { lat: 38.2204, lon: 13.3288 },
        'sciacca': { lat: 37.5086, lon: 13.0818 },
        'san vito lo capo': { lat: 38.1742, lon: 12.7328 },
        'lampedusa': { lat: 35.5008, lon: 12.6000 },
        // Sardegna costa
        'villasimius': { lat: 39.1543, lon: 9.5251 },
        'pula': { lat: 38.9989, lon: 8.9797 },
        'santa teresa gallura': { lat: 41.2344, lon: 9.1872 },
        'palau': { lat: 41.1800, lon: 9.3833 },
        'porto cervo': { lat: 41.1333, lon: 9.5333 },
        'arzachena': { lat: 41.0833, lon: 9.3833 },
        'bosa': { lat: 40.2985, lon: 8.4979 },
        'castelsardo': { lat: 40.9178, lon: 8.7147 },
        // San Marino e Vaticano
        'san marino': { lat: 43.9424, lon: 12.4578 },
        'citta del vaticano': { lat: 41.9029, lon: 12.4534 }
    },
    
    // Endpoint del backend Python
    API_ENDPOINTS: {
        weather:    `${BACKEND_URL}/api/weather`,
        cities:     `${BACKEND_URL}/api/cities`,
        mlCorrection:     `${BACKEND_URL}/api/ml/correction`,
        mlRainPrediction: `${BACKEND_URL}/api/ml/rain-prediction`,
        mlStats:          `${BACKEND_URL}/api/ml/stats`,
        chat:             `${BACKEND_URL}/api/chat`,
    },
    
    // Icone meteo mapping (OpenWeather -> Font Awesome)
    WEATHER_ICONS: {
        '01d': 'fa-sun',           // Cielo sereno (giorno)
        '01n': 'fa-moon',          // Cielo sereno (notte)
        '02d': 'fa-cloud-sun',     // Poche nuvole (giorno)
        '02n': 'fa-cloud-moon',    // Poche nuvole (notte)
        '03d': 'fa-cloud',         // Nuvole sparse
        '03n': 'fa-cloud',
        '04d': 'fa-cloud',         // Nuvole rotte
        '04n': 'fa-cloud',
        '09d': 'fa-cloud-showers-heavy',  // Pioggia
        '09n': 'fa-cloud-showers-heavy',
        '10d': 'fa-cloud-rain',    // Pioggia (giorno)
        '10n': 'fa-cloud-rain',    // Pioggia (notte)
        '11d': 'fa-bolt',          // Temporale
        '11n': 'fa-bolt',
        '13d': 'fa-snowflake',     // Neve
        '13n': 'fa-snowflake',
        '50d': 'fa-smog',          // Nebbia
        '50n': 'fa-smog'
    }
};

// ============================================
// HELPER FETCH — aggiunge header per bypass tunnel localtunnel
// ============================================
async function apiFetch(url, options = {}) {
    const headers = { 'bypass-tunnel-reminder': 'true', ...(options.headers || {}) };
    return fetch(url, { ...options, headers });
}

// ============================================
// STATO APPLICAZIONE
// ============================================
const appState = {
    currentCity: null,
    currentWeather: null,
    forecast: null,
    isLoading: false
};

// ============================================
// UTILITIES
// ============================================

/**
 * Formatta data in italiano
 */
function formatDate(date, options = {}) {
    const defaultOptions = { 
        weekday: 'long', 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric',
        ...options 
    };
    return new Date(date).toLocaleDateString('it-IT', defaultOptions);
}

/**
 * Formatta ora
 */
function formatTime(date) {
    return new Date(date).toLocaleTimeString('it-IT', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

/**
 * Ottiene icona meteo Font Awesome da codice OpenWeather
 */
function getWeatherIcon(iconCode) {
    return CONFIG.WEATHER_ICONS[iconCode] || 'fa-cloud';
}

/**
 * Traduce descrizione meteo in italiano
 */
function translateWeather(description) {
    const translations = {
        'clear sky': 'cielo sereno',
        'few clouds': 'poche nuvole',
        'scattered clouds': 'nuvole sparse',
        'broken clouds': 'nuvoloso',
        'overcast clouds': 'coperto',
        'shower rain': 'rovesci',
        'rain': 'pioggia',
        'light rain': 'pioggia leggera',
        'moderate rain': 'pioggia moderata',
        'heavy rain': 'pioggia intensa',
        'thunderstorm': 'temporale',
        'snow': 'neve',
        'light snow': 'neve leggera',
        'mist': 'foschia',
        'fog': 'nebbia',
        'haze': 'caligine'
    };
    
    return translations[description.toLowerCase()] || description;
}

// ============================================
// GESTIONE API
// ============================================

/**
 * Ottiene coordinate città (geocoding)
 */
async function getCityCoordinates(cityName) {
    const normalizedCity = cityName.toLowerCase().trim();

    // Fallback locale (poche città hardcodate)
    if (CONFIG.ITALIAN_CITIES[normalizedCity]) {
        return {
            ...CONFIG.ITALIAN_CITIES[normalizedCity],
            name: cityName.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
        };
    }

    // Cerca nel backend (DB ISTAT ~8.000 comuni)
    try {
        const response = await apiFetch(
            `${CONFIG.API_ENDPOINTS.cities}?q=${encodeURIComponent(cityName)}&limit=1`
        );
        if (!response.ok) throw new Error('Città non trovata');
        const data = await response.json();
        if (!data.length) throw new Error(`Città "${cityName}" non trovata`);
        return { lat: data[0].lat, lon: data[0].lon, name: data[0].name };
    } catch (error) {
        throw new Error(`Impossibile trovare la città "${cityName}"`);
    }
}

/**
 * Recupera dati meteo completi
 */
async function fetchWeatherData(coords) {
    try {
        const url = `${CONFIG.API_ENDPOINTS.weather}?lat=${coords.lat}&lon=${coords.lon}&name=${encodeURIComponent(coords.name || '')}`;
        const response = await apiFetch(url);

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Errore nel recupero dati meteo');
        }

        return await response.json();
    } catch (error) {
        console.error('Errore API meteo:', error);
        throw error;
    }
}

// ============================================
// UI - RENDERING
// ============================================

/**
 * Mostra stato di caricamento
 */
function showLoading(show) {
    const loadingEl = document.getElementById('loadingState');
    const resultsEl = document.getElementById('weatherResults');
    const errorEl = document.getElementById('errorMessage');
    
    if (show) {
        loadingEl.classList.remove('hidden');
        resultsEl.classList.add('hidden');
        errorEl.classList.add('hidden');
    } else {
        loadingEl.classList.add('hidden');
    }
}

/**
 * Mostra messaggio di errore
 */
function showError(message) {
    const errorEl = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    
    errorText.textContent = message;
    errorEl.classList.remove('hidden');
    showLoading(false);
}

/**
 * Nasconde messaggio di errore
 */
function hideError() {
    document.getElementById('errorMessage').classList.add('hidden');
}

/**
 * Renderizza meteo attuale con correzione ML
 */
async function renderCurrentWeather(weather, coords) {
    // Chiedi correzione ML al backend Python
    let mlCorrection = 0;
    try {
        const params = new URLSearchParams({
            city:     coords.name,
            temp:     weather.temp,
            humidity: weather.humidity || 50,
            hour:     new Date().getHours()
        });
        const mlResp = await apiFetch(`${CONFIG.API_ENDPOINTS.mlCorrection}?${params}`);
        if (mlResp.ok) {
            const mlData = await mlResp.json();
            if (mlData.model_ready) mlCorrection = mlData.correction || 0;
        }
    } catch (e) {
        // ML non disponibile: continua senza correzione
    }

    const correctedTemp = Math.round(weather.temp + mlCorrection);

    // Aggiorna UI
    document.getElementById('cityName').textContent = coords.name;
    document.getElementById('currentDate').textContent = formatDate(new Date());
    document.getElementById('currentTemp').textContent = correctedTemp;
    document.getElementById('weatherIcon').className = `fas ${getWeatherIcon(weather.icon)}`;
    document.getElementById('weatherDescription').textContent = translateWeather(weather.description);

    // Mostra correzione ML se significativa (> 0.2°C)
    const correctionEl = document.getElementById('aiCorrection');
    if (Math.abs(mlCorrection) > 0.2) {
        correctionEl.classList.remove('hidden');
        const sign = mlCorrection > 0 ? '+' : '';
        document.getElementById('correctionValue').textContent = `${sign}${mlCorrection.toFixed(1)}`;
    } else {
        correctionEl.classList.add('hidden');
    }

    // Widget previsione pioggia ML
    const rainWidget = document.getElementById('mlRainPrediction');
    try {
        const rainParams = new URLSearchParams({
            city:        coords.name,
            humidity:    weather.humidity || 60,
            hour:        new Date().getHours(),
            cloud_cover: weather.clouds || 50
        });
        const rainResp = await apiFetch(`${CONFIG.API_ENDPOINTS.mlRainPrediction}?${rainParams}`);
        if (rainResp.ok) {
            const rainData = await rainResp.json();
            if (rainData.model_ready) {
                const pct = Math.round(rainData.rain_probability * 100);
                document.getElementById('rainPct').textContent = `${pct}%`;
                const rainBar = document.getElementById('rainBar');
                rainBar.style.width = `${pct}%`;
                if (pct < 30) rainBar.style.background = '#10b981';
                else if (pct < 60) rainBar.style.background = '#f59e0b';
                else rainBar.style.background = '#3b82f6';
                const label = rainData.will_rain
                    ? `Probabile pioggia — confidenza ${rainData.confidence}`
                    : `Cielo tendenzialmente asciutto — confidenza ${rainData.confidence}`;
                document.getElementById('rainLabel').textContent = label;
                rainWidget.classList.remove('hidden');
            } else {
                rainWidget.classList.add('hidden');
            }
        } else {
            rainWidget.classList.add('hidden');
        }
    } catch (e) {
        rainWidget.classList.add('hidden');
    }

    // Dettagli (wind_speed già in km/h dal backend Open-Meteo)
    document.getElementById('humidity').textContent = `${weather.humidity}%`;
    document.getElementById('windSpeed').textContent = `${Math.round(weather.windSpeed)} km/h`;
    document.getElementById('visibility').textContent = `${(weather.visibility / 1000).toFixed(1)} km`;
    document.getElementById('pressure').textContent = `${weather.pressure} hPa`;
}

/**
 * Renderizza previsioni orarie
 */
function renderHourlyForecast(hourlyData) {
    const container = document.getElementById('hourlyForecast');
    container.innerHTML = '';
    
    // Mostra prossime 24 ore
    const next24h = hourlyData.slice(0, 24);
    
    next24h.forEach(hour => {
        // Open-Meteo restituisce ISO string ("2026-02-15T10:00"), non Unix timestamp
        const dateObj = typeof hour.dt === 'number' ? new Date(hour.dt * 1000) : new Date(hour.dt);
        const card = document.createElement('div');
        card.className = 'hour-card';
        card.innerHTML = `
            <div class="time">${formatTime(dateObj)}</div>
            <i class="fas ${getWeatherIcon(hour.weather[0].icon)}"></i>
            <div class="temp">${Math.round(hour.temp)}°</div>
        `;
        container.appendChild(card);
    });
}

/**
 * Renderizza previsioni giornaliere
 */
function renderDailyForecast(dailyData) {
    const container = document.getElementById('dailyForecast');
    container.innerHTML = '';
    
    // Salta oggi (index 0), mostra prossimi 5 giorni
    const next5days = dailyData.slice(1, 6);
    
    next5days.forEach(day => {
        // Open-Meteo restituisce ISO date string ("2026-02-15"), non Unix timestamp
        const date = typeof day.dt === 'number' ? new Date(day.dt * 1000) : new Date(day.dt);
        const dayName = date.toLocaleDateString('it-IT', { weekday: 'short' });
        const dayDate = date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        
        const card = document.createElement('div');
        card.className = 'day-card';
        card.innerHTML = `
            <div class="day-name">${dayName}</div>
            <div class="day-date">${dayDate}</div>
            <i class="fas ${getWeatherIcon(day.weather[0].icon)}"></i>
            <div class="temp-range">
                <span class="temp-max">${Math.round(day.temp.max)}°</span>
                <span class="temp-min">${Math.round(day.temp.min)}°</span>
            </div>
        `;
        container.appendChild(card);
    });
}

/**
 * Disegna grafico errori ML
 */
async function renderErrorChart() {
    const canvas = document.getElementById('errorChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // Carica statistiche ML dal backend
    let errors = [];
    try {
        const resp = await apiFetch(CONFIG.API_ENDPOINTS.mlStats);
        if (resp.ok) {
            const stats = await resp.json();
            // Aggiorna le stat card
            const countEl = document.getElementById('predictionsCount');
            const avgErrEl = document.getElementById('avgError');
            const statusEl = document.getElementById('modelStatus');
            if (countEl) countEl.textContent = stats.verified_predictions || 0;
            if (avgErrEl) avgErrEl.textContent = stats.avg_error_celsius !== null ? stats.avg_error_celsius : '--';
            if (statusEl) statusEl.textContent = stats.model_ready ? 'Attivo' : 'In addestramento';
        }
    } catch (e) { /* backend non disponibile */ }

    const errorsData = errors;
    
    // Pulisci canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (errorsData.length === 0) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Nessun dato disponibile. Verifica delle previsioni in corso...', 
                     canvas.width / 2, canvas.height / 2);
        return;
    }
    
    // Configura grafico
    const padding = 40;
    const chartWidth = canvas.width - padding * 2;
    const chartHeight = canvas.height - padding * 2;
    const maxError = Math.max(...errorsData.map(e => e.error), 1);
    const barWidth = chartWidth / errorsData.length;
    
    // Disegna assi
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, canvas.height - padding);
    ctx.lineTo(canvas.width - padding, canvas.height - padding);
    ctx.stroke();
    
    // Disegna barre
    errorsData.forEach((err, index) => {
        const barHeight = (err.error / maxError) * chartHeight;
        const x = padding + index * barWidth + barWidth * 0.1;
        const y = canvas.height - padding - barHeight;
        const width = barWidth * 0.8;
        
        // Colore gradiente in base all'errore
        const intensity = err.error / maxError;
        ctx.fillStyle = `hsl(${120 - intensity * 120}, 70%, 50%)`;
        ctx.fillRect(x, y, width, barHeight);
    });
    
    // Label asse Y
    ctx.fillStyle = '#64748b';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(maxError.toFixed(1) + '°C', padding - 5, padding + 5);
    ctx.fillText('0°C', padding - 5, canvas.height - padding);
}

// ============================================
// FUNZIONI PRINCIPALI
// ============================================

/**
 * Cerca meteo per città
 */
async function searchWeather(cityName) {
    if (!cityName.trim()) {
        showError('Inserisci il nome di una città');
        return;
    }
    
    hideError();
    showLoading(true);
    
    try {
        // 1. Ottieni coordinate
        const coords = await getCityCoordinates(cityName);
        appState.currentCity = coords;
        
        // 2. Recupera dati meteo
        const weatherData = await fetchWeatherData(coords);
        
        // 3. Estrai dati rilevanti
        const current = {
            temp: weatherData.current.temp,
            humidity: weatherData.current.humidity,
            pressure: weatherData.current.pressure,
            windSpeed: weatherData.current.wind_speed,
            visibility: weatherData.current.visibility || 10000,
            description: weatherData.current.weather[0].description,
            icon: weatherData.current.weather[0].icon
        };
        
        appState.currentWeather = current;
        appState.forecast = {
            hourly: weatherData.hourly,
            daily: weatherData.daily
        };
        
        // 4. Renderizza UI
        await renderCurrentWeather(current, coords);
        renderHourlyForecast(weatherData.hourly);
        renderDailyForecast(weatherData.daily);
        
        // 5. Aggiorna grafico statistiche ML dal backend
        renderErrorChart();
        
        // 6. Mostra risultati
        document.getElementById('weatherResults').classList.remove('hidden');
        showLoading(false);
        
    } catch (error) {
        console.error('Errore ricerca:', error);
        showError(error.message || 'Errore durante la ricerca. Riprova.');
    }
}

// ============================================
// EVENT LISTENERS
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    // Accordion sezione ML
    const mlToggleHeader = document.getElementById('mlToggleHeader');
    const mlBody = document.getElementById('mlBody');
    if (mlToggleHeader && mlBody) {
        mlToggleHeader.addEventListener('click', () => {
            const isOpen = mlBody.classList.toggle('open');
            mlToggleHeader.classList.toggle('open', isOpen);
        });
    }

    // Pulisce il campo di ricerca e la chat ad ogni caricamento pagina
    const cityInputClear = document.getElementById('cityInput');
    if (cityInputClear) cityInputClear.value = '';
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) chatMessages.innerHTML = '';
    const chatInputClear = document.getElementById('chatInput');
    if (chatInputClear) chatInputClear.value = '';

    // Input ricerca
    const cityInput = document.getElementById('cityInput');
    const searchBtn = document.getElementById('searchBtn');
    
    // Bottone cerca
    searchBtn.addEventListener('click', () => {
        searchWeather(cityInput.value);
    });
    
    // Enter su input
    cityInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            searchWeather(cityInput.value);
        }
    });
    
    // Città rapide (chip)
    document.querySelectorAll('.city-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const city = chip.dataset.city;
            cityInput.value = city;
            searchWeather(city);
        });
    });
    
    // Controlli ML
    const trainBtn = document.getElementById('trainModelBtn');
    const resetBtn = document.getElementById('resetModelBtn');
    const verifyBtn = document.getElementById('verifyPredictionsBtn');
    
    if (trainBtn) {
        trainBtn.addEventListener('click', async () => {
            trainBtn.disabled = true;
            trainBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Allenamento...';
            try {
                const resp = await apiFetch(`${BACKEND_URL}/api/ml/train`, { method: 'POST' });
                const result = await resp.json();
                if (result.success) {
                    alert(`🎓 Modello addestrato!\nCampioni: ${result.n_samples}\nMAE: ${result.mae?.toFixed(3)}°C`);
                    renderErrorChart();
                } else {
                    alert('⚠️ ' + (result.message || 'Errore training'));
                }
            } catch (e) {
                alert('⚠️ Backend non raggiungibile');
            }
            trainBtn.disabled = false;
            trainBtn.innerHTML = '<i class="fas fa-graduation-cap"></i> Allena modello ora';
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            alert('ℹ️ Il reset dei dati ML avviene dal server. Contatta l\'amministratore del backend.');
        });
    }

    if (verifyBtn) {
        verifyBtn.addEventListener('click', async () => {
            try {
                const resp = await apiFetch(`${BACKEND_URL}/api/admin/run-cycle`, { method: 'POST' });
                if (resp.ok) {
                    alert('✅ Ciclo di verifica avviato in background. Aggiorna la pagina tra qualche minuto.');
                }
            } catch (e) {
                alert('⚠️ Backend non raggiungibile');
            }
        });
    }
    
    // Inizializza autocompletamento
    initAutocomplete();
    
    // Inizializza chat
    initChat();
    
    // Focus su input all'avvio
    cityInput.focus();
});

// ============================================
// AUTOCOMPLETAMENTO CITTÀ
// ============================================

// Mappa città -> regione per i suggerimenti
const CITY_REGIONS = {
    'roma': 'Lazio', 'milano': 'Lombardia', 'napoli': 'Campania', 'torino': 'Piemonte',
    'firenze': 'Toscana', 'venezia': 'Veneto', 'bologna': 'Emilia-Romagna', 'palermo': 'Sicilia',
    'genova': 'Liguria', 'bari': 'Puglia', 'catania': 'Sicilia', 'verona': 'Veneto',
    'messina': 'Sicilia', 'padova': 'Veneto', 'trieste': 'Friuli-Venezia Giulia',
    'taranto': 'Puglia', 'brescia': 'Lombardia', 'prato': 'Toscana', 'parma': 'Emilia-Romagna',
    'modena': 'Emilia-Romagna', 'reggio emilia': 'Emilia-Romagna', 'bergamo': 'Lombardia',
    'monza': 'Lombardia', 'como': 'Lombardia', 'varese': 'Lombardia', 'pavia': 'Lombardia',
    'alessandria': 'Piemonte', 'asti': 'Piemonte', 'novara': 'Piemonte', 'cuneo': 'Piemonte',
    'savona': 'Liguria', 'la spezia': 'Liguria', 'trento': 'Trentino-Alto Adige',
    'bolzano': 'Trentino-Alto Adige', 'udine': 'Friuli-Venezia Giulia',
    'pordenone': 'Friuli-Venezia Giulia', 'gorizia': 'Friuli-Venezia Giulia',
    'biella': 'Piemonte', 'verbania': 'Piemonte', 'lecco': 'Lombardia',
    'lodi': 'Lombardia', 'cremona': 'Lombardia', 'mantova': 'Lombardia',
    'ferrara': 'Emilia-Romagna', 'ravenna': 'Emilia-Romagna', 'forli': 'Emilia-Romagna',
    'cesena': 'Emilia-Romagna', 'rimini': 'Emilia-Romagna', 'pesaro': 'Marche',
    'ancona': 'Marche', 'ascoli piceno': 'Marche', 'macerata': 'Marche',
    'fermo': 'Marche', 'rovigo': 'Veneto', 'vicenza': 'Veneto', 'treviso': 'Veneto',
    'belluno': 'Veneto', 'livorno': 'Toscana', 'pisa': 'Toscana', 'lucca': 'Toscana',
    'siena': 'Toscana', 'arezzo': 'Toscana', 'pistoia': 'Toscana', 'massa': 'Toscana',
    'carrara': 'Toscana', 'piombino': 'Toscana', 'val di cornia': 'Toscana',
    'san vincenzo': 'Toscana', 'campiglia marittima': 'Toscana', 'suvereto': 'Toscana',
    'grosseto': 'Toscana',
    'perugia': 'Umbria', 'terni': 'Umbria', 'foligno': 'Umbria',
    'citta di castello': 'Umbria', 'orvieto': 'Umbria', 'viterbo': 'Lazio',
    'rieti': 'Lazio', 'frosinone': 'Lazio', 'latina': 'Lazio',
    'pomezia': 'Lazio', 'civitavecchia': 'Lazio', 'l aquila': 'Abruzzo',
    'aquila': 'Abruzzo', 'chieti': 'Abruzzo', 'pescara': 'Abruzzo',
    'teramo': 'Abruzzo', 'campobasso': 'Molise', 'isernia': 'Molise',
    'salerno': 'Campania', 'caserta': 'Campania', 'avellino': 'Campania',
    'benevento': 'Campania', 'pozzuoli': 'Campania', 'torre del greco': 'Campania',
    'giugliano': 'Campania', 'casoria': 'Campania', 'castellammare': 'Campania',
    'foggia': 'Puglia', 'lecce': 'Puglia', 'brindisi': 'Puglia',
    'andria': 'Puglia', 'trani': 'Puglia', 'barletta': 'Puglia',
    'altamura': 'Puglia', 'molfetta': 'Puglia', 'monopoli': 'Puglia',
    'polignano': 'Puglia', 'matera': 'Basilicata', 'potenza': 'Basilicata',
    'melfi': 'Basilicata', 'reggio calabria': 'Calabria', 'catanzaro': 'Calabria',
    'cosenza': 'Calabria', 'crotone': 'Calabria', 'vibo valentia': 'Calabria',
    'lamezia terme': 'Calabria', 'catanzaro lido': 'Calabria',
    'siracusa': 'Sicilia', 'ragusa': 'Sicilia', 'trapani': 'Sicilia',
    'marsala': 'Sicilia', 'mazzara': 'Sicilia', 'agrigento': 'Sicilia',
    'enna': 'Sicilia', 'caltanissetta': 'Sicilia', 'gela': 'Sicilia',
    'cagliari': 'Sardegna', 'sassari': 'Sardegna', 'nuoro': 'Sardegna',
    'olbia': 'Sardegna', 'alghero': 'Sardegna', 'oristano': 'Sardegna',
    'quartu': 'Sardegna', 'tempio': 'Sardegna', 'san marino': 'San Marino',
    'citta del vaticano': 'Vaticano'
};

let currentFocus = -1;

function initAutocomplete() {
    const input = document.getElementById('cityInput');
    const list = document.getElementById('autocompleteList');
    
    if (!input || !list) return;
    
    let _autocompleteTimer = null;

    // Quando l'utente digita — debounce 250ms per non spammare il backend
    input.addEventListener('input', function() {
        const val = this.value.trim();
        closeAllLists();
        if (!val || val.length < 2) return;
        currentFocus = -1;

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

                if (!combined.length) return;

                list.classList.remove('hidden');
                list.innerHTML = '';

                combined.forEach((city, index) => {
                    const item = document.createElement('div');
                    item.className = 'autocomplete-item';
                    item.setAttribute('data-city', city.name);
                    item.setAttribute('data-index', index);

                    item.innerHTML = `
                        <i class="fas fa-map-marker-alt"></i>
                        <span class="city-name">${city.name}</span>
                        ${city.region ? `<span class="region">${city.region}</span>` : ''}
                    `;

                    item.addEventListener('click', function() {
                        input.value = city.name;
                        closeAllLists();
                        searchWeather(city.name);
                    });

                    list.appendChild(item);
                });
            } catch (e) {
                // Backend non disponibile: fallback silenzioso
            }
        }, 250);
    });
    
    // Navigazione con tastiera
    input.addEventListener('keydown', function(e) {
        const items = list.getElementsByClassName('autocomplete-item');
        
        if (e.key === 'ArrowDown') {
            currentFocus++;
            addActive(items);
            e.preventDefault();
        } else if (e.key === 'ArrowUp') {
            currentFocus--;
            addActive(items);
            e.preventDefault();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (currentFocus > -1 && items[currentFocus]) {
                items[currentFocus].click();
            } else {
                // Se non è selezionato nulla, cerca con il testo attuale
                closeAllLists();
                searchWeather(input.value);
            }
        } else if (e.key === 'Escape') {
            closeAllLists();
        }
    });
    
    // Chiudi lista quando si clicca fuori
    document.addEventListener('click', function(e) {
        if (e.target !== input && e.target !== list) {
            closeAllLists();
        }
    });
}

function addActive(items) {
    if (!items) return;
    
    removeActive(items);
    
    if (currentFocus >= items.length) currentFocus = 0;
    if (currentFocus < 0) currentFocus = items.length - 1;
    
    items[currentFocus].classList.add('active');
}

function removeActive(items) {
    for (let i = 0; i < items.length; i++) {
        items[i].classList.remove('active');
    }
}

function closeAllLists() {
    const list = document.getElementById('autocompleteList');
    if (list) {
        list.classList.add('hidden');
        list.innerHTML = '';
    }
    currentFocus = -1;
}

// ============================================
// CHAT DOMANDE LINGUAGGIO NATURALE
// ============================================

function initChat() {
    const chatToggle = document.getElementById('chatToggle');
    const chatBox = document.getElementById('chatBox');
    const chatInput = document.getElementById('chatInput');
    const chatSendBtn = document.getElementById('chatSendBtn');
    
    if (!chatToggle || !chatBox) return;
    
    chatToggle.addEventListener('click', () => {
        chatBox.classList.toggle('hidden');
        chatToggle.classList.toggle('active');
    });
    
    const sendMessage = async () => {
        const question = chatInput.value.trim();
        if (!question) return;
        
        addChatMessage('user', question);
        chatInput.value = '';
        
        const answer = await parseWeatherQuestion(question);
        addChatMessage('bot', answer.text, answer.weather);
    };
    
    chatSendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
}

function addChatMessage(type, text, weatherData = null) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
    const msg = document.createElement('div');
    msg.className = `chat-message ${type}${weatherData ? ' weather-result' : ''}`;
    
    const icon = type === 'bot' ? 'fa-robot' : 'fa-user';
    
    let content = `<i class="fas ${icon}"></i><div class="message-content">${text}`;
    
    if (weatherData) {
        content += `
            <div class="weather-mini">
                <i class="fas ${getWeatherIcon(weatherData.icon)}"></i>
                <div>
                    <div class="temp-big">${weatherData.temp}°C</div>
                    <div class="condition">${weatherData.condition}</div>
                </div>
            </div>
        `;
    }
    
    content += '</div>';
    msg.innerHTML = content;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

async function parseWeatherQuestion(question) {
    const q = question.toLowerCase();

    // Cerca la città nella domanda confrontando con la lista delle città note
    let city = null;
    let cityCoords = null;
    const cityNames = Object.keys(CONFIG.ITALIAN_CITIES);

    // Ordina per lunghezza decrescente per trovare prima i nomi più specifici
    // (es. "marina di massa" prima di "massa")
    cityNames.sort((a, b) => b.length - a.length);

    for (const c of cityNames) {
        if (q.includes(c)) {
            city = c.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
            cityCoords = CONFIG.ITALIAN_CITIES[c];
            break;
        }
    }

    // Se trovata la città, scarica i dati meteo da passare all'AI
    let weatherData = null;
    if (city && cityCoords) {
        try {
            weatherData = await fetchWeatherData(cityCoords);
        } catch (e) {
            console.warn('Impossibile scaricare dati meteo per la chat AI:', e.message);
        }
    }

    // Chiama il backend Python con la domanda e i dati meteo come contesto
    try {
        const response = await apiFetch(CONFIG.API_ENDPOINTS.chat, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, weatherData, city })
        });

        if (!response.ok) throw new Error('Risposta non valida dal server');

        const data = await response.json();
        return { text: data.text || 'Nessuna risposta ricevuta.' };

    } catch (error) {
        return { text: 'Mi dispiace, non riesco a contattare l\'AI in questo momento. Riprova tra poco.' };
    }
}

// ============================================
// AUTO-LEARNING SYSTEM
// Sistema di apprendimento automatico autonomo
// Funziona ogni ora mentre il browser è aperto
// ============================================

class AutoLearningSystem {
    constructor() {
        this.storageKey = 'meteoAI_autoLearning';
        this.citiesKey = 'meteoAI_trackedCities';
        this.intervalId = null;
        this.intervalMinutes = 60; // Ogni ora
        this.isRunning = false;
        this.lastRunTime = null;
        this.nextRunTime = null;
        this.currentCityIndex = 0;

        // Carica stato salvato
        this.enabled = localStorage.getItem(this.storageKey) === 'true';
        this.trackedCities = JSON.parse(localStorage.getItem(this.citiesKey) || '[]');
    }

    enable() {
        this.enabled = true;
        localStorage.setItem(this.storageKey, 'true');
        this._startTimer();
        this._updateUI();
        console.log('🤖 Auto-learning abilitato');
    }

    disable() {
        this.enabled = false;
        localStorage.setItem(this.storageKey, 'false');
        this._stopTimer();
        this._updateUI();
        console.log('🤖 Auto-learning disabilitato');
    }

    addCity(cityName) {
        const normalized = cityName.trim().toLowerCase();
        if (!normalized) return false;
        if (this.trackedCities.includes(normalized)) return false;
        this.trackedCities.push(normalized);
        localStorage.setItem(this.citiesKey, JSON.stringify(this.trackedCities));
        this._updateCityList();
        return true;
    }

    removeCity(cityName) {
        const normalized = cityName.trim().toLowerCase();
        this.trackedCities = this.trackedCities.filter(c => c !== normalized);
        localStorage.setItem(this.citiesKey, JSON.stringify(this.trackedCities));
        this._updateCityList();
    }

    // Avvia il sistema se era già abilitato
    init() {
        if (this.enabled && this.trackedCities.length > 0) {
            this._startTimer();
        }
        this._updateUI();
        this._updateCityList();
    }

    _startTimer() {
        if (this.intervalId) clearInterval(this.intervalId);
        const msInterval = this.intervalMinutes * 60 * 1000;
        this.intervalId = setInterval(() => this._runCycle(), msInterval);
        this.nextRunTime = new Date(Date.now() + msInterval);
        // Esegui subito al primo avvio se le città sono configurate
        if (this.trackedCities.length > 0) {
            setTimeout(() => this._runCycle(), 5000); // 5 secondi di ritardo iniziale
        }
    }

    _stopTimer() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
        this.nextRunTime = null;
    }

    async _runCycle() {
        if (!this.enabled || this.trackedCities.length === 0 || this.isRunning) return;

        this.isRunning = true;
        this.lastRunTime = new Date();
        this.nextRunTime = new Date(Date.now() + this.intervalMinutes * 60 * 1000);

        this._updateStatus('In esecuzione...');
        console.log('🔄 Auto-learning: avvio ciclo per', this.trackedCities.length, 'città');

        let processed = 0;
        for (const cityName of this.trackedCities) {
            try {
                await this._processCityBackground(cityName);
                processed++;
                await new Promise(r => setTimeout(r, 2000)); // 2s tra una città e l'altra
            } catch (e) {
                console.warn(`Auto-learning: errore per ${cityName}:`, e.message);
            }
        }

        // Auto-addestramento se ci sono abbastanza dati
        if (weatherML) {
            const verifiedCount = weatherML.predictionsHistory.filter(p => p.verified).length;
            if (verifiedCount >= 5) {
                console.log('🎓 Auto-learning: avvio addestramento automatico...');
                this._updateStatus('Addestrando modello...');
                const result = await weatherML.trainModel();
                if (result.success) {
                    console.log('✅ Auto-learning: modello aggiornato, loss:', result.loss?.toFixed(4));
                }
            }
        }

        this.isRunning = false;
        this._updateStatus(`Ultimo ciclo: ${this._formatTime(this.lastRunTime)} (${processed} città)`);
        if (typeof renderErrorChart === 'function') renderErrorChart();
        console.log('✅ Auto-learning: ciclo completato');
    }

    async _processCityBackground(cityName) {
        // Recupera coordinate (dal database locale o geocoding)
        let coords = null;
        const normalized = cityName.toLowerCase();
        if (CONFIG.ITALIAN_CITIES[normalized]) {
            coords = { ...CONFIG.ITALIAN_CITIES[normalized], name: cityName };
        } else {
            // Geocoding fallback
            const response = await apiFetch(`${CONFIG.API_ENDPOINTS.cities}?q=${encodeURIComponent(cityName)}&limit=1`);
            if (!response.ok) throw new Error('Geocoding fallito');
            coords = await response.json();
        }

        // Scarica dati meteo
        const weatherData = await fetchWeatherData(coords);
        const current = {
            temp: weatherData.current.temp,
            humidity: weatherData.current.humidity,
        };

        // Verifica previsioni passate per questa città
        if (weatherML) {
            weatherML.verifyPredictions({ city: coords.name || cityName, temp: current.temp });
            // Salva nuova previsione
            weatherML.savePrediction({
                city: coords.name || cityName,
                temp: current.temp,
                humidity: current.humidity
            });
        }

        console.log(`📡 Auto-learning: aggiornato ${cityName} → ${current.temp}°C`);
    }

    _formatTime(date) {
        if (!date) return '--';
        return date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
    }

    _updateUI() {
        const toggle = document.getElementById('autoLearningToggle');
        const statusDot = document.getElementById('autoLearningDot');
        const nextRunEl = document.getElementById('autoLearningNext');

        if (toggle) toggle.checked = this.enabled;
        if (statusDot) {
            statusDot.className = 'status-dot ' + (this.enabled ? 'active' : 'inactive');
        }
        if (nextRunEl) {
            nextRunEl.textContent = this.enabled && this.nextRunTime
                ? `Prossimo ciclo: ${this._formatTime(this.nextRunTime)}`
                : 'Disabilitato';
        }
    }

    _updateStatus(msg) {
        const el = document.getElementById('autoLearningStatus');
        if (el) el.textContent = msg;
    }

    _updateCityList() {
        const container = document.getElementById('trackedCitiesList');
        if (!container) return;
        container.innerHTML = '';
        if (this.trackedCities.length === 0) {
            container.innerHTML = '<span class="no-cities">Nessuna città monitorata</span>';
            return;
        }
        this.trackedCities.forEach(city => {
            const item = document.createElement('div');
            item.className = 'tracked-city-item';
            const displayName = city.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
            item.innerHTML = `<span>${displayName}</span><button class="remove-city-btn" data-city="${city}" title="Rimuovi">×</button>`;
            item.querySelector('.remove-city-btn').addEventListener('click', (e) => {
                this.removeCity(e.target.dataset.city);
            });
            container.appendChild(item);
        });
    }
}

// Istanza globale auto-learning
const autoLearning = new AutoLearningSystem();

// Inizializza dopo il caricamento DOM
document.addEventListener('DOMContentLoaded', () => {
    autoLearning.init();

    // Toggle abilitazione auto-learning
    const toggle = document.getElementById('autoLearningToggle');
    if (toggle) {
        toggle.addEventListener('change', () => {
            if (toggle.checked) autoLearning.enable();
            else autoLearning.disable();
        });
    }

    // Aggiunta nuova città da monitorare
    const addCityInput = document.getElementById('addTrackedCityInput');
    const addCityBtn = document.getElementById('addTrackedCityBtn');
    if (addCityBtn && addCityInput) {
        const doAdd = () => {
            const name = addCityInput.value.trim();
            if (!name) return;
            const added = autoLearning.addCity(name);
            if (added) {
                addCityInput.value = '';
            } else {
                addCityInput.style.borderColor = '#ef4444';
                setTimeout(() => addCityInput.style.borderColor = '', 1500);
            }
        };
        addCityBtn.addEventListener('click', doAdd);
        addCityInput.addEventListener('keypress', e => { if (e.key === 'Enter') doAdd(); });
    }

    // Ciclo manuale immediato
    const runNowBtn = document.getElementById('autoLearningRunNow');
    if (runNowBtn) {
        runNowBtn.addEventListener('click', () => {
            if (autoLearning.trackedCities.length === 0) {
                alert('Aggiungi almeno una città da monitorare prima di eseguire il ciclo.');
                return;
            }
            autoLearning._runCycle();
        });
    }
});
