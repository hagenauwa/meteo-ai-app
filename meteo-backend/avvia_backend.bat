@echo off
title Meteo AI Backend
cd /d "%~dp0"
echo ========================================
echo   Meteo AI Backend
echo   http://localhost:8000
echo   Documentazione: http://localhost:8000/docs
echo ========================================

REM Controlla se la porta 8000 e' gia' in uso
netstat -ano | findstr ":8000" | findstr "LISTENING" > NUL 2>&1
if %ERRORLEVEL% == 0 (
    echo [WARN] Porta 8000 gia' in uso. Backend forse gia' avviato.
    echo        Per fermare: taskkill /F /IM python.exe
    pause
    exit /b 1
)

REM Prima esecuzione: scarica comuni italiani se il DB non esiste
if not exist meteo_ai.db (
    echo [SETUP] Prima esecuzione: scarico ~7.900 comuni italiani...
    echo         Questa operazione richiede circa 3 minuti (solo la prima volta)
    python cities_loader.py --download
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Errore nel download dei comuni. Riprova.
        pause
        exit /b 1
    )
)

echo [OK] Avvio server...
python -m uvicorn main:app --host 0.0.0.0 --port 8000
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Errore nell'avvio del backend.
    pause
)
