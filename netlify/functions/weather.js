/**
 * Netlify Function: weather.js
 * Proxy per OpenWeatherMap API
 * Gestisce sia geocoding che dati meteo
 * 
 * Endpoint: /.netlify/functions/weather
 */

// API Key OpenWeatherMap - letta dalle variabili d'ambiente
const OPENWEATHER_API_KEY = process.env.OPENWEATHER_API_KEY;

// USA API 2.5 GRATUITE (non richiedono abbonamento)
const BASE_URL = 'https://api.openweathermap.org/data/2.5';
const GEO_URL = 'https://api.openweathermap.org/geo/1.0';

exports.handler = async (event, context) => {
    // CORS headers per permettere chiamate dal frontend
    const headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET',
        'Content-Type': 'application/json'
    };

    // Gestione preflight OPTIONS
    if (event.httpMethod === 'OPTIONS') {
        return { statusCode: 200, headers, body: '' };
    }

    // Verifica API key configurata
    if (!OPENWEATHER_API_KEY) {
        console.error('ERRORE: OPENWEATHER_API_KEY non trovata nelle environment variables');
        return {
            statusCode: 500,
            headers,
            body: JSON.stringify({
                error: 'OPENWEATHER_API_KEY non configurata',
                message: 'La variabile ambiente OPENWEATHER_API_KEY non è stata trovata. Verifica di averla impostata su Netlify Dashboard > Site settings > Environment variables'
            })
        };
    }
    
    // Verifica che la key non sia vuota o con solo spazi
    const cleanKey = OPENWEATHER_API_KEY.trim();
    if (cleanKey.length < 10) {
        console.error('ERRORE: API key troppo corta:', cleanKey.length);
        return {
            statusCode: 500,
            headers,
            body: JSON.stringify({
                error: 'API key invalida',
                message: 'La API key sembra troppo corta. Verifica che sia completa.'
            })
        };
    }
    
    console.log('Usando API key di lunghezza:', cleanKey.length);

    try {
        const params = event.queryStringParameters || {};
        const { type, city, lat, lon } = params;

        // === GEOCODING: Trova coordinate da nome città ===
        if (type === 'geocoding' && city) {
            const geoUrl = `${GEO_URL}/direct?q=${encodeURIComponent(city)},IT&limit=1&appid=${cleanKey}`;
            
            console.log('Geocoding URL:', geoUrl.replace(cleanKey, 'XXX'));
            
            const response = await fetch(geoUrl);
            const data = await response.json();
            
            console.log('Geocoding status:', response.status);
            console.log('Geocoding response:', JSON.stringify(data).substring(0, 200));
            
            if (!response.ok) {
                console.error('Geocoding error:', data);
                return {
                    statusCode: response.status,
                    headers,
                    body: JSON.stringify({
                        error: 'Errore geocoding',
                        message: data.message || 'Servizio non disponibile',
                        details: data
                    })
                };
            }
            
            if (!data || data.length === 0) {
                return {
                    statusCode: 404,
                    headers,
                    body: JSON.stringify({ error: 'Città non trovata' })
                };
            }

            return {
                statusCode: 200,
                headers,
                body: JSON.stringify({
                    name: data[0].name,
                    lat: data[0].lat,
                    lon: data[0].lon,
                    country: data[0].country
                })
            };
        }

        // === DATI METEO: Recupera previsioni da coordinate ===
        // Usa API 2.5 GRATUITE (weather + forecast)
        if (lat && lon) {
            // Chiamata 1: Meteo attuale
            const currentUrl = `${BASE_URL}/weather?lat=${lat}&lon=${lon}&units=metric&lang=it&appid=${cleanKey}`;
            
            // Chiamata 2: Previsioni (ogni 3 ore, 5 giorni)
            const forecastUrl = `${BASE_URL}/forecast?lat=${lat}&lon=${lon}&units=metric&lang=it&appid=${cleanKey}`;
            
            console.log('Weather URLs:');
            console.log('Current:', currentUrl.replace(cleanKey, 'XXX'));
            console.log('Forecast:', forecastUrl.replace(cleanKey, 'XXX'));
            
            const [currentRes, forecastRes] = await Promise.all([
                fetch(currentUrl),
                fetch(forecastUrl)
            ]);
            
            console.log('Current status:', currentRes.status);
            console.log('Forecast status:', forecastRes.status);
            
            if (!currentRes.ok) {
                const errorData = await currentRes.json();
                console.error('Current weather error:', errorData);
                return {
                    statusCode: currentRes.status,
                    headers,
                    body: JSON.stringify({
                        error: 'Errore meteo attuale',
                        message: errorData.message || 'API Error',
                        details: errorData
                    })
                };
            }
            
            if (!forecastRes.ok) {
                const errorData = await forecastRes.json();
                console.error('Forecast error:', errorData);
                return {
                    statusCode: forecastRes.status,
                    headers,
                    body: JSON.stringify({
                        error: 'Errore previsioni',
                        message: errorData.message || 'API Error',
                        details: errorData
                    })
                };
            }
            
            const currentData = await currentRes.json();
            const forecastData = await forecastRes.json();

            // Converte previsioni ogni 3 ore in formato "hourly" compatibile
            const hourly = forecastData.list.slice(0, 16).map(item => ({
                dt: item.dt,
                temp: Math.round(item.main.temp * 10) / 10,
                humidity: item.main.humidity,
                wind_speed: item.wind.speed,
                weather: item.weather,
                pop: item.pop || 0
            }));

            // Raggruppa per giorno per le previsioni daily
            const dailyMap = new Map();
            forecastData.list.forEach(item => {
                const date = new Date(item.dt * 1000).toDateString();
                if (!dailyMap.has(date)) {
                    dailyMap.set(date, {
                        dt: item.dt,
                        temps: [],
                        humidity: [],
                        wind: [],
                        weather: item.weather,
                        pop: item.pop || 0
                    });
                }
                const day = dailyMap.get(date);
                day.temps.push(item.main.temp);
                day.humidity.push(item.main.humidity);
                day.wind.push(item.wind.speed);
            });

            const daily = Array.from(dailyMap.values()).map(day => ({
                dt: day.dt,
                temp: {
                    min: Math.round(Math.min(...day.temps) * 10) / 10,
                    max: Math.round(Math.max(...day.temps) * 10) / 10,
                    day: Math.round(day.temps.reduce((a,b) => a+b, 0) / day.temps.length * 10) / 10
                },
                humidity: Math.round(day.humidity.reduce((a,b) => a+b, 0) / day.humidity.length),
                wind_speed: Math.round(day.wind.reduce((a,b) => a+b, 0) / day.wind.length * 10) / 10,
                weather: day.weather,
                pop: day.pop
            })).slice(0, 5); // Max 5 giorni

            // Semplifica la risposta per il frontend (formato compatibile)
            const simplified = {
                current: {
                    temp: Math.round(currentData.main.temp * 10) / 10,
                    feels_like: Math.round(currentData.main.feels_like * 10) / 10,
                    humidity: currentData.main.humidity,
                    pressure: currentData.main.pressure,
                    wind_speed: currentData.wind.speed,
                    wind_deg: currentData.wind.deg,
                    visibility: currentData.visibility || 10000,
                    clouds: currentData.clouds?.all || 0,
                    weather: currentData.weather
                },
                hourly: hourly,
                daily: daily,
                lat: currentData.coord.lat,
                lon: currentData.coord.lon,
                timezone: 'auto'
            };

            return {
                statusCode: 200,
                headers,
                body: JSON.stringify(simplified)
            };
        }

        // Nessun parametro valido
        return {
            statusCode: 400,
            headers,
            body: JSON.stringify({
                error: 'Parametri mancanti',
                message: 'Usa ?type=geocoding&city=NOME o ?lat=X&lon=Y'
            })
        };

    } catch (error) {
        console.error('Weather function error:', error);
        
        return {
            statusCode: 500,
            headers,
            body: JSON.stringify({
                error: 'Errore interno',
                message: error.message
            })
        };
    }
};
