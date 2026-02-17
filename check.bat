@echo off
chcp 65001 >nul
echo ============================================
echo   🔍 Verifica Pre-Deploy
echo ============================================
echo.

set ALL_OK=1

REM 1. Verifica Node.js
echo [1/5] Node.js... 
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo     ❌ NON INSTALLATO
    echo     → Scarica da https://nodejs.org/
    set ALL_OK=0
) else (
    for /f "tokens=*" %%a in ('node --version') do echo     ✅ %%a
)

REM 2. Verifica Netlify CLI
echo [2/5] Netlify CLI...
netlify --version >nul 2>&1
if %errorlevel% neq 0 (
    echo     ❌ NON INSTALLATO
    echo     → Esegui: npm install -g netlify-cli
    set ALL_OK=0
) else (
    for /f "tokens=*" %%a in ('netlify --version') do echo     ✅ %%a
)

REM 3. Verifica file progetto
echo [3/5] File progetto...
if not exist public\index.html (
    echo     ❌ public\index.html mancante
    set ALL_OK=0
) else (
    echo     ✅ Frontend presente
)

if not exist netlify\functions\weather.js (
    echo     ❌ netlify\functions\weather.js mancante
    set ALL_OK=0
) else (
    echo     ✅ API Functions presenti
)

REM 4. Verifica .env
echo [4/5] Configurazione API...
if not exist .env (
    echo     ❌ File .env mancante
    set ALL_OK=0
) else (
    for /f "tokens=*" %%a in (.env) do (
        if not "%%a"=="" (
            echo     ✅ %%a
            goto :env_found
        )
    )
    :env_found
)

REM 5. Verifica login Netlify
echo [5/5] Login Netlify...
netlify status >nul 2>&1
if %errorlevel% neq 0 (
    echo     ❌ NON COLLEGATO
    echo     → Esegui: netlify login
    set ALL_OK=0
) else (
    echo     ✅ Collegato a Netlify
)

echo.
echo ============================================
if %ALL_OK%==1 (
    echo   ✅ Tutto pronto! Puoi eseguire deploy.bat
) else (
    echo   ⚠️  Alcuni problemi trovati
    echo   Esegui setup.bat per risolverli
)
echo ============================================
pause
