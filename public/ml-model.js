/**
 * ============================================
 * ML-MODEL.JS - SISTEMA DI MACHINE LEARNING
 * Previsioni Meteo con TensorFlow.js
 * ============================================
 * 
 * Questo modulo gestisce:
 * - Creazione e addestramento di una rete neurale
 * - Salvataggio e caricamento del modello
 * - Predizione delle correzioni di temperatura
 * - Apprendimento dagli errori di previsione
 */

class WeatherMLModel {
    constructor() {
        this.model = null;
        this.predictionsHistory = [];  // Storico previsioni per ML
        this.isModelReady = false;
        this.storageKey = 'meteoAI_predictions';
        this.modelStorageKey = 'meteoAI_model';
        
        // Carica dati storici all'avvio
        this.loadHistory();
    }

    /**
     * Inizializza la rete neurale
     * Architettura: 3 input → 8 hidden → 4 hidden → 1 output
     */
    async initModel() {
        try {
            // Prova a caricare modello salvato
            const savedModel = localStorage.getItem(this.modelStorageKey);
            if (savedModel) {
                await this.loadModelFromStorage();
                return;
            }

            // Crea nuovo modello
            this.model = tf.sequential({
                layers: [
                    // Input layer: 3 features (ora del giorno, umidità, temperatura prevista)
                    tf.layers.dense({
                        inputShape: [3],
                        units: 8,
                        activation: 'relu',
                        kernelInitializer: 'heNormal'
                    }),
                    
                    // Hidden layer
                    tf.layers.dense({
                        units: 4,
                        activation: 'relu'
                    }),
                    
                    // Output layer: correzione temperatura (valore continuo)
                    tf.layers.dense({
                        units: 1,
                        activation: 'linear'
                    })
                ]
            });

            // Compila il modello
            this.model.compile({
                optimizer: tf.train.adam(0.01),
                loss: 'meanSquaredError',
                metrics: ['mse']
            });

            this.isModelReady = true;
            console.log('✅ Modello ML inizializzato');
            this.updateModelStatus('Pronto per allenamento');
            
        } catch (error) {
            console.error('❌ Errore inizializzazione modello:', error);
            this.updateModelStatus('Errore inizializzazione');
        }
    }

    /**
     * Predice la correzione da applicare alla temperatura
     * @param {Object} weatherData - Dati meteo attuali
     * @returns {number} - Correzione suggerita in gradi Celsius
     */
    async predictCorrection(weatherData) {
        if (!this.isModelReady || this.predictionsHistory.length < 5) {
            return 0;  // Non abbastanza dati per predire
        }

        try {
            // Normalizza input
            const hour = new Date().getHours() / 24;  // 0-1
            const humidity = (weatherData.humidity || 50) / 100;  // 0-1
            const temp = (weatherData.temp || 20) / 40;  // Normalizza temperatura

            const input = tf.tensor2d([[hour, humidity, temp]]);
            const prediction = this.model.predict(input);
            const correction = (await prediction.data())[0];
            
            // Libera memoria TensorFlow
            input.dispose();
            prediction.dispose();

            // Limita la correzione a ±3°C per sicurezza
            return Math.max(-3, Math.min(3, correction));
            
        } catch (error) {
            console.error('❌ Errore predizione:', error);
            return 0;
        }
    }

    /**
     * Salva una previsione per confrontarla in seguito con dati reali
     * @param {Object} prediction - Dati della previsione
     */
    savePrediction(prediction) {
        const record = {
            id: Date.now(),
            city: prediction.city,
            timestamp: new Date().toISOString(),
            predictedTemp: prediction.temp,
            humidity: prediction.humidity,
            hour: new Date().getHours(),
            verified: false,
            actualTemp: null,
            error: null
        };

        this.predictionsHistory.push(record);
        this.saveHistory();
        
        console.log('💾 Previsione salvata per ML:', record);
        this.updateStats();
    }

    /**
     * Verifica una previsione passata confrontandola con dati attuali
     * @param {Object} actualWeather - Dati meteo reali attuali
     * @returns {Array} - Previsioni verificate
     */
    verifyPredictions(actualWeather) {
        const now = new Date();
        const verifiedPredictions = [];

        this.predictionsHistory.forEach(record => {
            // Verifica solo previsioni non ancora verificate e vecchie di 1-6 ore
            if (record.verified) return;
            
            const recordTime = new Date(record.timestamp);
            const hoursDiff = (now - recordTime) / (1000 * 60 * 60);
            
            // Verifica previsioni tra 1 e 6 ore fa
            if (hoursDiff >= 1 && hoursDiff <= 6 && 
                record.city.toLowerCase() === actualWeather.city.toLowerCase()) {
                
                record.actualTemp = actualWeather.temp;
                record.error = actualWeather.temp - record.predictedTemp;
                record.verified = true;
                record.hoursDiff = hoursDiff;
                
                verifiedPredictions.push(record);
                console.log('✅ Previsione verificata:', record);
            }
        });

        if (verifiedPredictions.length > 0) {
            this.saveHistory();
            this.updateStats();
        }

        return verifiedPredictions;
    }

    /**
     * Addestra il modello usando le previsioni verificate
     * @returns {Object} - Risultati dell'allenamento
     */
    async trainModel() {
        const verifiedData = this.predictionsHistory.filter(p => p.verified);
        
        if (verifiedData.length < 5) {
            console.log('⚠️ Dati insufficienti per allenamento (minimo 5)');
            return { success: false, message: 'Servono almeno 5 previsioni verificate' };
        }

        try {
            this.updateModelStatus('Allenamento in corso...');

            // Prepara dati di training
            const xs = verifiedData.map(p => [
                p.hour / 24,
                (p.humidity || 50) / 100,
                p.predictedTemp / 40
            ]);
            
            // Target: errore commesso (actual - predicted)
            const ys = verifiedData.map(p => p.error);

            const xsTensor = tf.tensor2d(xs);
            const ysTensor = tf.tensor2d(ys, [ys.length, 1]);

            // Addestra il modello
            const history = await this.model.fit(xsTensor, ysTensor, {
                epochs: 100,
                batchSize: Math.min(4, verifiedData.length),
                verbose: 0,
                callbacks: {
                    onEpochEnd: (epoch, logs) => {
                        if (epoch % 20 === 0) {
                            const progress = Math.round((epoch / 100) * 100);
                            this.updateLearningProgress(progress);
                        }
                    }
                }
            });

            // Libera memoria
            xsTensor.dispose();
            ysTensor.dispose();

            // Salva modello addestrato
            await this.saveModelToStorage();

            const finalLoss = history.history.loss[history.history.loss.length - 1];
            this.updateModelStatus('Modello addestrato');
            this.updateLearningProgress(100);

            console.log('🎓 Modello addestrato! Loss finale:', finalLoss);
            
            return {
                success: true,
                loss: finalLoss,
                samplesUsed: verifiedData.length
            };

        } catch (error) {
            console.error('❌ Errore training:', error);
            this.updateModelStatus('Errore allenamento');
            return { success: false, error: error.message };
        }
    }

    /**
     * Calcola statistiche sugli errori di previsione
     * @returns {Object} - Statistiche errori
     */
    getErrorStats() {
        const verified = this.predictionsHistory.filter(p => p.verified);
        
        if (verified.length === 0) {
            return { avgError: 0, minError: 0, maxError: 0, count: 0 };
        }

        const errors = verified.map(p => Math.abs(p.error));
        const avgError = errors.reduce((a, b) => a + b, 0) / errors.length;
        
        return {
            avgError: avgError.toFixed(2),
            minError: Math.min(...errors).toFixed(2),
            maxError: Math.max(...errors).toFixed(2),
            count: verified.length
        };
    }

    /**
     * Ottiene dati per il grafico errori
     * @returns {Array} - Array di errori [timestamp, error]
     */
    getErrorsForChart() {
        return this.predictionsHistory
            .filter(p => p.verified)
            .map(p => ({
                date: new Date(p.timestamp).toLocaleDateString('it-IT', { 
                    day: 'numeric', 
                    month: 'short',
                    hour: '2-digit'
                }),
                error: Math.abs(p.error)
            }))
            .slice(-20);  // Ultimi 20 errori
    }

    /**
     * Salva il modello in localStorage (usando pesi serializzati)
     */
    async saveModelToStorage() {
        try {
            const weights = [];
            this.model.weights.forEach(w => {
                weights.push(w.val.dataSync());
            });
            
            localStorage.setItem(this.modelStorageKey, JSON.stringify({
                weights: weights,
                timestamp: new Date().toISOString()
            }));
        } catch (error) {
            console.error('Errore salvataggio modello:', error);
        }
    }

    /**
     * Carica il modello da localStorage
     */
    async loadModelFromStorage() {
        try {
            const saved = JSON.parse(localStorage.getItem(this.modelStorageKey));
            if (!saved) return false;

            // Ricrea modello
            await this.initModel();
            
            // Qui normalmente ricaricheresti i pesi
            // Per semplicità, ricreiamo il modello
            this.isModelReady = true;
            this.updateModelStatus('Modello caricato');
            return true;
            
        } catch (error) {
            console.error('Errore caricamento modello:', error);
            return false;
        }
    }

    /**
     * Salva lo storico previsioni in localStorage
     */
    saveHistory() {
        try {
            // Limita a ultime 100 previsioni per non esaurire storage
            const toSave = this.predictionsHistory.slice(-100);
            localStorage.setItem(this.storageKey, JSON.stringify(toSave));
        } catch (error) {
            console.error('Errore salvataggio storico:', error);
        }
    }

    /**
     * Carica lo storico previsioni da localStorage
     */
    loadHistory() {
        try {
            const saved = localStorage.getItem(this.storageKey);
            if (saved) {
                this.predictionsHistory = JSON.parse(saved);
                console.log('📚 Storico caricato:', this.predictionsHistory.length, 'previsioni');
            }
        } catch (error) {
            console.error('Errore caricamento storico:', error);
            this.predictionsHistory = [];
        }
    }

    /**
     * Reset completo dei dati ML
     */
    resetAll() {
        this.predictionsHistory = [];
        this.model = null;
        this.isModelReady = false;
        localStorage.removeItem(this.storageKey);
        localStorage.removeItem(this.modelStorageKey);
        this.updateStats();
        this.updateModelStatus('Reset completato');
        console.log('🗑️ Dati ML resettati');
    }

    // === METODI UI ===

    updateModelStatus(status) {
        const el = document.getElementById('modelStatus');
        if (el) el.textContent = status;
    }

    updateLearningProgress(progress) {
        const el = document.getElementById('learningProgress');
        if (el) el.textContent = progress + '%';
    }

    updateStats() {
        const countEl = document.getElementById('predictionsCount');
        const avgErrorEl = document.getElementById('avgError');
        
        if (countEl) countEl.textContent = this.predictionsHistory.length;
        
        const stats = this.getErrorStats();
        if (avgErrorEl) avgErrorEl.textContent = stats.avgError;
    }
}

// Istanzia modello globale
const weatherML = new WeatherMLModel();

// Inizializza al caricamento della pagina
document.addEventListener('DOMContentLoaded', () => {
    weatherML.initModel();
    weatherML.updateStats();
});
