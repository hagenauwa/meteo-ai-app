@echo off
chcp 65001 >nul
echo ============================================
echo   🌤️  METEO AI APP - Setup Automatico
echo ============================================
echo.

REM Verifica Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Node.js NON trovato!
    echo.
    echo ⚠️  Devi installare Node.js manualmente:
    echo    1. Vai su: https://nodejs.org/
    echo    2. Scarica la versione "LTS" (consigliata)
    echo    3. Installa con tutte le opzioni di default
    echo    4. Riapri questo terminale e ri-esegui setup.bat
    echo.
    pause
    exit /b 1
)

echo ✅ Node.js trovato!
node --version
echo.

REM Installa Netlify CLI globalmente
echo 📦 Installazione Netlify CLI...
npm install -g netlify-cli
if %errorlevel% neq 0 (
    echo ❌ Errore installazione Netlify CLI
    pause
    exit /b 1
)
echo ✅ Netlify CLI installato!
echo.

REM Login a Netlify
echo 🔐 Effettua il login a Netlify...
echo Si aprirà il browser per l'autenticazione...
netlify login
if %errorlevel% neq 0 (
    echo ❌ Login fallito
    pause
    exit /b 1
)
echo ✅ Login effettuato!
echo.

REM Collega il progetto
echo 🔗 Collegamento progetto a Netlify...
netlify link
if %errorlevel% neq 0 (
    echo ⚠️  Se è il primo deploy, esegui:
    echo    netlify deploy --prod
    echo    e segui le istruzioni per creare un nuovo sito
    echo.
)

REM Verifica file .env
echo.
echo ============================================
echo   🔑 Configurazione API Key
echo ============================================
echo.

if not exist .env (
    echo ⚠️  File .env non trovato!
    echo.
    echo Devi ottenere una API key gratuita da OpenWeatherMap:
    echo    1. Vai su: https://home.openweathermap.org/users/sign_up
    echo    2. Crea account e conferma email
    echo    3. Vai su "My API Keys"
    echo    4. Copia la chiave
    echo.
    set /p API_KEY="Incolla qui la tua API key: "
    echo OPENWEATHER_API_KEY=%API_KEY% > .env
    echo ✅ File .env creato!
) else (
    echo ✅ File .env già presente
)

echo.
echo ============================================
echo   🚀 Prossimi passaggi
echo ============================================
echo.
echo 1. Per testare in locale:
echo    netlify dev
echo.
echo 2. Per deployare su internet:
echo    netlify deploy --prod
echo.
echo 3. Dopo il primo deploy, aggiungi la variabile
echo    ambiente su Netlify Dashboard:
echo    Site settings ^> Environment variables ^> Add variable
echo    Key: OPENWEATHER_API_KEY
echo.
pause
