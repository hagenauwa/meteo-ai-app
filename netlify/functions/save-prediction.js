/**
 * Netlify Function: save-prediction.js
 * Endpoint opzionale per persistenza server-side delle previsioni ML
 * 
 * Endpoint: /.netlify/functions/save-prediction
 * 
 * NOTA: Questa funzione è opzionale perché il sistema ML funziona
 * interamente sul client usando localStorage. Utile se in futuro
 * si vuole condividere dati ML tra dispositivi.
 */

// In produzione, usare un database (FaunaDB, Supabase, ecc.)
// Per semplicità, questa versione usa un mock in memoria
const predictionsDB = new Map();

exports.handler = async (event, context) => {
    const headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Content-Type': 'application/json'
    };

    // Gestione preflight OPTIONS
    if (event.httpMethod === 'OPTIONS') {
        return { statusCode: 200, headers, body: '' };
    }

    try {
        // === SALVA PREVISIONE ===
        if (event.httpMethod === 'POST') {
            const body = JSON.parse(event.body);
            const { city, temp, humidity, timestamp } = body;
            
            if (!city || temp === undefined) {
                return {
                    statusCode: 400,
                    headers,
                    body: JSON.stringify({ error: 'Dati mancanti' })
                };
            }

            const predictionId = `${city}_${Date.now()}`;
            const record = {
                id: predictionId,
                city,
                predictedTemp: temp,
                humidity: humidity || 50,
                timestamp: timestamp || new Date().toISOString(),
                verified: false,
                createdAt: new Date().toISOString()
            };

            // Salva nel mock DB
            if (!predictionsDB.has(city)) {
                predictionsDB.set(city, []);
            }
            predictionsDB.get(city).push(record);

            // Limita a 50 previsioni per città
            const cityPredictions = predictionsDB.get(city);
            if (cityPredictions.length > 50) {
                predictionsDB.set(city, cityPredictions.slice(-50));
            }

            return {
                statusCode: 200,
                headers,
                body: JSON.stringify({
                    success: true,
                    id: predictionId,
                    message: 'Previsione salvata'
                })
            };
        }

        // === RECUPERA PREVISIONI ===
        if (event.httpMethod === 'GET') {
            const params = event.queryStringParameters || {};
            const { city, verify, actualTemp } = params;

            if (!city) {
                return {
                    statusCode: 400,
                    headers,
                    body: JSON.stringify({ error: 'Parametro city richiesto' })
                };
            }

            // Verifica previsioni passate
            if (verify === 'true' && actualTemp !== undefined) {
                const cityPredictions = predictionsDB.get(city) || [];
                const now = new Date();
                const verified = [];

                cityPredictions.forEach(pred => {
                    if (pred.verified) return;
                    
                    const predTime = new Date(pred.timestamp);
                    const hoursDiff = (now - predTime) / (1000 * 60 * 60);
                    
                    // Verifica previsioni tra 1 e 12 ore
                    if (hoursDiff >= 1 && hoursDiff <= 12) {
                        pred.actualTemp = parseFloat(actualTemp);
                        pred.error = pred.actualTemp - pred.predictedTemp;
                        pred.verified = true;
                        pred.verifiedAt = now.toISOString();
                        verified.push(pred);
                    }
                });

                return {
                    statusCode: 200,
                    headers,
                    body: JSON.stringify({
                        verified: verified.length,
                        predictions: verified
                    })
                };
            }

            // Recupera tutte le previsioni della città
            const cityPredictions = predictionsDB.get(city) || [];
            
            return {
                statusCode: 200,
                headers,
                body: JSON.stringify({
                    city,
                    count: cityPredictions.length,
                    predictions: cityPredictions
                })
            };
        }

        return {
            statusCode: 405,
            headers,
            body: JSON.stringify({ error: 'Metodo non supportato' })
        };

    } catch (error) {
        console.error('Save prediction error:', error);
        
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
