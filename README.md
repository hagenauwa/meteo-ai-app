# 🌤️ Meteo AI App

Applicazione web di previsioni meteo con Machine Learning, progettata per essere semplice da usare e mantenere anche per principianti.

## 🎯 Caratteristiche

- ✅ **Previsioni meteo accurate** per tutta l'Italia
- 🤖 **Machine Learning integrato** che impara dagli errori di previsione
- 📱 **Design responsive** (funziona su mobile, tablet e desktop)
- ⚡ **Gratuito e open source**
- 🚀 **Deploy facile** su Netlify

## 🛠️ Stack Tecnologico

| Componente | Tecnologia | Motivo della scelta |
|------------|-----------|---------------------|
| Frontend | Vanilla JS + CSS3 | Nessun framework da imparare, codice immediatamente comprensibile |
| ML | TensorFlow.js | Libreria standard, esegue ML direttamente nel browser |
| API | OpenWeatherMap | API meteo affidabile con piano gratuito |
| Hosting | Netlify | Deploy automatico, hosting gratuito, serverless functions |

## 📁 Struttura del Progetto

```
meteo-ai-app/
├── public/                      # File statici (frontend)
│   ├── index.html              # Pagina principale
│   ├── style.css               # Stili CSS
│   ├── app.js                  # Logica applicazione
│   └── ml-model.js             # Sistema Machine Learning
├── netlify/
│   └── functions/              # Serverless functions
│       ├── weather.js          # Proxy API OpenWeatherMap
│       └── save-prediction.js  # Persistenza previsioni (opzionale)
├── netlify.toml                # Configurazione Netlify
├── package.json                # Dipendenze Node.js
└── README.md                   # Questo file
```

## 🚀 Guida all'Installazione

### Step 1: Prerequisiti

1. **Node.js** installato sul tuo computer
   - Scarica da: https://nodejs.org/ (scarica la versione LTS)
   - Verifica installazione: apri terminale e digita `node --version`

2. **Account Netlify** (gratuito)
   - Registrati su: https://www.netlify.com/
   - Puoi usare GitHub, GitLab, Bitbucket o email

3. **Account OpenWeatherMap** (gratuito)
   - Registrati su: https://home.openweathermap.org/users/sign_up
   - Vai su "My API Keys" e copia la tua chiave

### Step 2: Clona/Copia il Progetto

```bash
# Se hai git installato
git clone <repository-url>
cd meteo-ai-app

# Oppure, se non hai git, copia manualmente i file
# in una cartella chiamata "meteo-ai-app"
```

### Step 3: Installa le Dipendenze

```bash
# Entra nella cartella del progetto
cd meteo-ai-app

# Installa il Netlify CLI (Command Line Interface)
npm install -g netlify-cli

# Oppure se preferisci installarlo localmente:
npm install
```

### Step 4: Configura le Variabili d'Ambiente

Crea un file `.env` nella cartella principale:

```env
OPENWEATHER_API_KEY=la_tua_chiave_api_qui
```

**Attenzione:** Non caricare mai questo file su Git! È già incluso nel `.gitignore`.

### Step 5: Testa in Locale

```bash
# Avvia il server di sviluppo Netlify
netlify dev

# L'app sarà disponibile su http://localhost:8888
```

Se vedi la pagina di Meteo AI, tutto funziona!

## 🌐 Deploy su Netlify

### Metodo A: Deploy con Netlify CLI (Consigliato)

```bash
# 1. Effettua il login a Netlify
netlify login

# 2. Collega la cartella al tuo sito Netlify
netlify link

# 3. Deploy del sito
netlify deploy --prod
```

Al termine, vedrai l'URL del tuo sito (es. `https://meteo-ai-abc123.netlify.app`)

### Metodo B: Deploy tramite Git (Continuous Deployment)

1. Crea un repository su GitHub/GitLab/Bitbucket
2. Carica i file del progetto:
   ```bash
   git init
   git add .
   git commit -m "Primo commit"
   git remote add origin <url-tuo-repository>
   git push -u origin main
   ```
3. Vai su Netlify Dashboard → "Add new site" → "Import an existing project"
4. Seleziona il tuo repository
5. Configura:
   - **Build command:** (lascia vuoto, è un sito statico)
   - **Publish directory:** `public`
6. Aggiungi la variabile ambiente `OPENWEATHER_API_KEY` in:
   Site settings → Environment variables → Add variable
7. Clicca "Deploy"

Ogni volta che farai `git push`, Netlify aggiornerà automaticamente il sito!

## 🔧 Configurazione Post-Deploy

### Aggiungere la Chiave API su Netlify

1. Vai su https://app.netlify.com
2. Seleziona il tuo sito
3. Vai su "Site settings" → "Environment variables"
4. Clicca "Add variable"
   - Key: `OPENWEATHER_API_KEY`
   - Value: (la tua chiave di OpenWeatherMap)
5. Salva e fai il redeploy del sito

## 🎓 Come Usare l'App

### Ricerca Meteo

1. Inserisci il nome di una città italiana
2. Clicca "Cerca" o premi Enter
3. Visualizza il meteo attuale e le previsioni

### Sistema Machine Learning

L'app impara automaticamente a correggere le previsioni:

1. **Salvataggio:** Ogni ricerca salva la previsione API
2. **Verifica:** Quando ricontrolli una città dopo qualche ora, l'app confronta la previsione con la realtà
3. **Apprendimento:** Clicca "Allena modello ora" per far imparare l'AI dagli errori passati
4. **Correzione:** Le prossime previsioni mostreranno la correzione AI (es. "+1.2°C basandosi sui dati storici")

### Controlli ML

- **🎓 Allena modello ora:** Addestra la rete neurale con i dati raccolti
- **🗑️ Reset dati ML:** Cancella tutto lo storico (utile se l'AI impara male)
- **✅ Verifica previsioni passate:** Controlla manualmente le previsioni vecchie

## 🐛 Troubleshooting

### "OPENWEATHER_API_KEY non configurata"

**Problema:** La chiave API non è stata impostata su Netlify

**Soluzione:**
1. Vai su Netlify Dashboard → Site settings → Environment variables
2. Aggiungi `OPENWEATHER_API_KEY` con la tua chiave
3. Redeploy il sito (Deploys → Trigger deploy)

### "Città non trovata"

**Problema:** La città non è riconosciuta

**Soluzioni:**
- Prova con il nome italiano (es. "Roma" invece di "Rome")
- Verifica l'ortografia
- Prova con una città più grande nelle vicinanze

### Il modello ML non si addestra

**Problema:** Bottone "Allena modello ora" non funziona

**Causa:** Servono almeno 5 previsioni verificate

**Soluzione:**
1. Cerca la stessa città più volte durante il giorno
2. Aspetta almeno 1-6 ore tra una ricerca e l'altra
3. Clicca "Verifica previsioni passate"
4. Poi "Allena modello ora"

### Errori CORS

Se vedi errori CORS nella console del browser, verifica che:
1. Le Netlify Functions siano deployate correttamente
2. L'URL della funzione sia corretto in `app.js`

## 📝 Modifiche Personalizzate

### Cambiare il colore del tema

Modifica le variabili CSS in `public/style.css`:

```css
:root {
    --primary-color: #3b82f6;    /* Blu di default */
    /* Cambia con: #ef4444 (rosso), #10b981 (verde), #8b5cf6 (viola), ecc. */
}
```

### Aggiungere nuove città italiane

Aggiungi in `public/app.js` nella sezione `ITALIAN_CITIES`:

```javascript
'perugia': { lat: 43.1107, lon: 12.3908 },
'reggio calabria': { lat: 38.1105, lon: 15.6613 }
```

### Modificare il numero di previsioni salvate

In `public/ml-model.js`, cerca `saveHistory()`:

```javascript
// Limita a ultime 100 previsioni
const toSave = this.predictionsHistory.slice(-100);
// Cambia 100 con il numero desiderato
```

## 🆘 Supporto

Se incontri problemi:

1. Controlla la console del browser (F12 → Console) per errori
2. Verifica che tutti i file siano stati caricati correttamente
3. Assicurati che la chiave API sia valida su OpenWeatherMap
4. Controlla i log delle Netlify Functions su Netlify Dashboard → Functions

## 📚 Documentazione Utile

- [OpenWeatherMap API Docs](https://openweathermap.org/api)
- [TensorFlow.js Guide](https://www.tensorflow.org/js/guide)
- [Netlify Functions Docs](https://docs.netlify.com/functions/overview/)
- [CSS Grid Guide](https://css-tricks.com/snippets/css/complete-guide-grid/)

## 📄 Licenza

MIT License - Libero di usare, modificare e distribuire!

---

**Creato con ❤️ per rendere il meteo più intelligente e accessibile a tutti.**

Se trovi utile questo progetto, considera di lasciare una ⭐ sul repository!
