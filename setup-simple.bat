@echo off
echo ============================================
echo    METEO AI APP - Setup Automatico
echo ============================================
echo.

REM Verifica Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Node.js NON trovato!
    echo.
    echo Devi installare Node.js manualmente:
    echo    1. Vai su: https://nodejs.org/
    echo    2. Scarica la versione "LTS"
    echo    3. Installa con tutte le opzioni di default
    echo    4. Chiudi e riapri il terminale
    echo.
    pause
    exit /b 1
)

echo [OK] Node.js trovato: 
node --version
echo.

REM Installa Netlify CLI
echo [..] Installazione Netlify CLI (attendi un momento)...
npm install -g netlify-cli
if %errorlevel% neq 0 (
    echo [X] Errore installazione
    pause
    exit /b 1
)
echo [OK] Netlify CLI installato!
echo.

REM Login
echo [..] Apro il browser per il login a Netlify...
echo    (Clicca "Authorize" nella pagina che si apre)
netlify login
if %errorlevel% neq 0 (
    echo [X] Login fallito
    pause
    exit /b 1
)
echo [OK] Login effettuato!
echo.

REM Collega progetto
echo [..] Collego il progetto a Netlify...
netlify link
if %errorlevel% neq 0 (
    echo [!] Progetto non collegato. Per il primo deploy esegui:
    echo       netlify deploy --prod
)

REM API Key
echo.
echo ============================================
echo    CONFIGURAZIONE API KEY
echo ============================================
echo.

if not exist .env (
    echo [!] Crea account gratuito su:
    echo     https://home.openweathermap.org/users/sign_up
    echo.
    echo     Poi copia la API Key da "My API Keys"
    echo.
    set /p API_KEY="Incolla qui la API key: "
    echo OPENWEATHER_API_KEY=%API_KEY% > .env
    echo [OK] File .env creato!
) else (
    echo [OK] File .env gia presente
)

echo.
echo ============================================
echo    PROSSI PASSAGGI
echo ============================================
echo.
echo 1. Test locale:  netlify dev
echo 2. Deploy:      netlify deploy --prod
echo.
pause
