# 🚀 Avvio Rapido - Solo 3 Passaggi

## Passaggio 1: Installa Node.js (una tantum)
⬇️ Vai su https://nodejs.org/ e clicca il pulsante verde "LTS" per scaricare

## Passaggio 2: Ottieni API Key Meteo (una tantum)
1. 🌐 Vai su https://home.openweathermap.org/users/sign_up
2. 📧 Crea account con email e conferma
3. 🔑 Vai su "My API Keys" e copia la chiave (è gratuita)

## Passaggio 3: Esegui lo Script Automatico
Apri il terminale in questa cartella (`C:\Users\Andrea\meteo-ai-app`) ed esegui:

```bash
setup.bat
```

Lo script farà automaticamente:
- ✅ Verifica Node.js
- ✅ Installa Netlify CLI
- ✅ Login a Netlify (si apre il browser)
- ✅ Collega il progetto
- ✅ Crea il file .env con la tua API key

## Deploy finale
Dopo lo script, esegui:

```bash
netlify deploy --prod
```

Il tuo sito sarà online in pochi secondi! 🎉

---

**Troubleshooting:**
- Se vedi "Node.js NON trovato!" → installa Node.js dal passaggio 1 e riprova
- Se richiede login Netlify → usa GitHub o email, più facile
