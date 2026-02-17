/**
 * Netlify Function: ai-chat.js
 * Risponde a domande meteo in linguaggio naturale usando Google Gemini.
 * Se la città non è nella lista hardcodata del frontend, la estrae dalla
 * domanda, la geocodifica con OpenWeatherMap e scarica i dati meteo
 * prima di rispondere.
 *
 * Endpoint: /api/ai-chat
 * Metodo: POST
 * Body: { question: string, weatherData: object|null, city: string|null }
 */

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const OPENWEATHER_API_KEY = process.env.OPENWEATHER_API_KEY;
const GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent';
const OW_BASE = 'https://api.openweathermap.org/data/2.5';
const OW_GEO = 'https://api.openweathermap.org/geo/1.0';

const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Content-Type': 'application/json'
};

// Chiede a Gemini il nome della città italiana menzionata nella domanda
async function extractCityFromQuestion(question) {
    const prompt = `Dalla seguente domanda in italiano, estrai SOLO il nome della località italiana menzionata (città, comune, frazione, marina, lago, montagna, ecc.). Rispondi con SOLO il nome, senza punteggiatura, senza altre parole. Se non c'è nessuna località italiana, rispondi con la parola "NESSUNA".

Domanda: ${question}`;

    const res = await fetch(`${GEMINI_URL}?key=${GEMINI_API_KEY}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0, maxOutputTokens: 30 }
        })
    });

    if (!res.ok) return null;
    const data = await res.json();
    const name = data.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
    if (!name || name === 'NESSUNA') return null;
    return name;
}

// Geocodifica un nome di località con OpenWeatherMap
async function geocodeCity(cityName) {
    const url = `${OW_GEO}/direct?q=${encodeURIComponent(cityName)},IT&limit=1&appid=${OPENWEATHER_API_KEY}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || data.length === 0) return null;
    return { lat: data[0].lat, lon: data[0].lon, name: data[0].name };
}

// Scarica i dati meteo per le coordinate date
async function fetchWeather(lat, lon) {
    const [currentRes, forecastRes] = await Promise.all([
        fetch(`${OW_BASE}/weather?lat=${lat}&lon=${lon}&units=metric&lang=it&appid=${OPENWEATHER_API_KEY}`),
        fetch(`${OW_BASE}/forecast?lat=${lat}&lon=${lon}&units=metric&lang=it&appid=${OPENWEATHER_API_KEY}`)
    ]);

    if (!currentRes.ok || !forecastRes.ok) return null;

    const current = await currentRes.json();
    const forecast = await forecastRes.json();

    // Formato hourly (ogni 3 ore, prossime 18 ore)
    const hourly = forecast.list.slice(0, 6).map(item => ({
        temp: Math.round(item.main.temp * 10) / 10,
        description: item.weather[0].description,
        pop: item.pop || 0,
        humidity: item.main.humidity,
        wind_speed: item.wind.speed
    }));

    // Formato daily (aggregato per giorno)
    const dailyMap = new Map();
    forecast.list.forEach(item => {
        const date = new Date(item.dt * 1000).toDateString();
        if (!dailyMap.has(date)) {
            dailyMap.set(date, { temps: [], pops: [], descriptions: [] });
        }
        const d = dailyMap.get(date);
        d.temps.push(item.main.temp);
        d.pops.push(item.pop || 0);
        d.descriptions.push(item.weather[0].description);
    });

    const daily = Array.from(dailyMap.values()).slice(0, 5).map(d => ({
        temp_min: Math.round(Math.min(...d.temps) * 10) / 10,
        temp_max: Math.round(Math.max(...d.temps) * 10) / 10,
        description: d.descriptions[Math.floor(d.descriptions.length / 2)],
        pop: Math.max(...d.pops)
    }));

    return {
        current: {
            temp: Math.round(current.main.temp * 10) / 10,
            feels_like: Math.round(current.main.feels_like * 10) / 10,
            humidity: current.main.humidity,
            pressure: current.main.pressure,
            description: current.weather[0].description,
            wind: { speed: current.wind.speed },
            visibility: Math.round((current.visibility || 10000) / 1000)
        },
        hourly,
        daily
    };
}

// Costruisce il contesto meteo da passare all'AI
function buildWeatherContext(city, weatherData) {
    const curr = weatherData.current;
    const hourly = weatherData.hourly || [];
    const daily = weatherData.daily || [];

    return `
Dati meteo REALI aggiornati per ${city}:
- Temperatura attuale: ${curr.temp}°C (percepita ${curr.feels_like}°C)
- Condizione: ${curr.description}
- Umidità: ${curr.humidity}%
- Vento: ${Math.round((curr.wind?.speed || 0) * 3.6)} km/h
- Visibilità: ${curr.visibility} km
- Pressione: ${curr.pressure} hPa

Previsioni prossime ore (ogni 3 ore):
${hourly.map((h, i) => {
    const ore = (i + 1) * 3;
    const pop = h.pop > 0 ? `pioggia ${Math.round(h.pop * 100)}%` : 'niente pioggia';
    return `  Tra ${ore} ore: ${h.temp}°C, ${h.description}, ${pop}`;
}).join('\n')}

Previsioni prossimi giorni:
${daily.map((d, i) => {
    const giorni = ['Oggi', 'Domani', 'Dopodomani', 'Fra 3 giorni', 'Fra 4 giorni'];
    const pop = d.pop > 0 ? `, pioggia ${Math.round(d.pop * 100)}%` : '';
    return `  ${giorni[i] || 'Giorno ' + i}: min ${d.temp_min}°C / max ${d.temp_max}°C, ${d.description}${pop}`;
}).join('\n')}`;
}

exports.handler = async (event) => {
    if (event.httpMethod === 'OPTIONS') return { statusCode: 200, headers, body: '' };
    if (event.httpMethod !== 'POST') return { statusCode: 405, headers, body: JSON.stringify({ error: 'Metodo non consentito' }) };

    if (!GEMINI_API_KEY) {
        return { statusCode: 200, headers, body: JSON.stringify({ text: 'GEMINI_API_KEY non configurata nelle variabili d\'ambiente di Netlify.' }) };
    }

    let question, weatherData, city;
    try {
        ({ question, weatherData, city } = JSON.parse(event.body));
    } catch {
        return { statusCode: 400, headers, body: JSON.stringify({ error: 'Body non valido' }) };
    }

    // Se il frontend non ha trovato la città nella lista hardcodata,
    // la estraiamo dalla domanda con Gemini e geocodifichiamo con OpenWeatherMap
    if (!weatherData && OPENWEATHER_API_KEY) {
        try {
            const extractedCity = await extractCityFromQuestion(question);
            if (extractedCity) {
                const coords = await geocodeCity(extractedCity);
                if (coords) {
                    city = coords.name;
                    weatherData = await fetchWeather(coords.lat, coords.lon);
                }
            }
        } catch (e) {
            console.warn('Geocoding automatico fallito:', e.message);
        }
    }

    // Costruisci il prompt con o senza dati meteo
    const weatherContext = weatherData && city ? buildWeatherContext(city, weatherData) : null;

    const prompt = `Sei un assistente meteo italiano, simpatico e preciso.
Rispondi SEMPRE in italiano, in modo naturale e conversazionale.
Usa emoji meteo quando è appropriato (☀️🌧️🌡️💨❄️⛅🌫️⛈️).
Rispondi in modo completo ma senza sprechi: 3-5 frasi al massimo, vai dritto al punto. Non troncare mai la risposta a metà frase.
${weatherContext
    ? `Basati ESCLUSIVAMENTE sui dati meteo reali qui sotto per rispondere. Non inventare nulla.\n${weatherContext}`
    : `Non hai dati meteo per questa domanda. Chiedi all'utente di specificare una città italiana oppure suggeriscigli di cercarla prima nella barra di ricerca in alto.`
}

Domanda dell'utente: ${question}`;

    try {
        const response = await fetch(`${GEMINI_URL}?key=${GEMINI_API_KEY}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contents: [{ parts: [{ text: prompt }] }],
                generationConfig: { temperature: 0.7, maxOutputTokens: 1024, topP: 0.9 },
                safetySettings: [
                    { category: 'HARM_CATEGORY_HARASSMENT', threshold: 'BLOCK_NONE' },
                    { category: 'HARM_CATEGORY_HATE_SPEECH', threshold: 'BLOCK_NONE' }
                ]
            })
        });

        if (!response.ok) {
            const err = await response.json();
            console.error('Gemini error:', JSON.stringify(err));
            const errMsg = err?.error?.message || 'errore sconosciuto';
            return { statusCode: 200, headers, body: JSON.stringify({ text: `Errore Gemini: ${errMsg}` }) };
        }

        const data = await response.json();
        const text = data.candidates?.[0]?.content?.parts?.[0]?.text || 'Mi dispiace, non ho ricevuto una risposta valida.';

        return { statusCode: 200, headers, body: JSON.stringify({ text: text.trim() }) };

    } catch (error) {
        console.error('Errore chiamata Gemini:', error);
        return { statusCode: 200, headers, body: JSON.stringify({ text: 'Errore di connessione con l\'AI. Controlla la tua connessione e riprova.' }) };
    }
};
