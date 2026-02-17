@echo off
chcp 65001 >nul
echo ============================================
echo   🚀 Deploy Meteo AI App su Netlify
echo ============================================
echo.

REM Verifica .env
if not exist .env (
    echo ❌ File .env mancante!
    echo Esegui prima: setup.bat
    pause
    exit /b 1
)

REM Leggi API key da .env
for /f "tokens=2 delims==" %%a in ('findstr "OPENWEATHER_API_KEY" .env') do set API_KEY=%%a

if "%API_KEY%"=="" (
    echo ❌ API Key non trovata nel file .env
    pause
    exit /b 1
)

echo ✅ API Key trovata: %API_KEY:~0,10%...
echo.

REM Build (per sito statico non serve, ma per sicurezza)
echo 📦 Preparazione deploy...
echo.

REM Deploy
echo 🌐 Avvio deploy su Netlify...
netlify deploy --prod

if %errorlevel% neq 0 (
    echo.
    echo ❌ Deploy fallito!
    echo Problemi comuni:
    echo   - Non sei loggato: esegui 'netlify login'
    echo   - Sito non collegato: esegui 'netlify link'
    pause
    exit /b 1
)

echo.
echo ============================================
echo   ⚠️  IMPORTANTE: Configura su Netlify!
echo ============================================
echo.
echo Dopo il deploy, devi aggiungere la variabile ambiente:
echo.
echo 1. Vai su https://app.netlify.com
echo 2. Clicca il tuo sito appena creato
echo 3. Vai su "Site settings" ^> "Environment variables"
echo 4. Clicca "Add variable"
echo    - Key:   OPENWEATHER_API_KEY
echo    - Value: %API_KEY%
echo 5. Clicca "Save"
echo 6. Vai su "Deploys" ^> "Trigger deploy" ^> "Clear cache and retry"
echo.
echo Fatto! Il tuo sito funzionerà correttamente 🎉
echo.
pause
