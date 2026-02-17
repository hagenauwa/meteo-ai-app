# installa_servizio_windows.ps1
# Registra il backend come Task Pianificato Windows
# Eseguire come Amministratore: Right-click > Esegui come amministratore
#
# Il task parte automaticamente all'avvio del PC, anche senza login utente.

$TaskName   = "MeteoAI-Backend"
$BackendDir = "C:\Users\Andrea\meteo-ai-app\meteo-backend"
$PythonExe  = (Get-Command python).Source
$UvicornCmd = "-m uvicorn main:app --host 0.0.0.0 --port 8000"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installazione Meteo AI Backend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Rimuovi task precedente se esiste
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Crea l'azione
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $UvicornCmd `
    -WorkingDirectory $BackendDir

# Trigger: avvio del PC
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Impostazioni: esegui sempre, anche senza login, riavvia se fallisce
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# Registra il task (gira come SYSTEM per avviarsi senza login)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -User "SYSTEM" `
    -Force

Write-Host ""
Write-Host "[OK] Task '$TaskName' registrato!" -ForegroundColor Green
Write-Host "     Partirà automaticamente ad ogni avvio del PC" -ForegroundColor Green
Write-Host ""
Write-Host "Comandi utili:" -ForegroundColor Yellow
Write-Host "  Avvia ora:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Ferma:      Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "  Rimuovi:    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""

# Avvia subito il task
$resp = Read-Host "Vuoi avviare il backend adesso? (S/N)"
if ($resp -eq "S" -or $resp -eq "s") {
    # Prima esecuzione: scarica comuni italiani
    Write-Host "Scaricando comuni italiani (solo la prima volta)..." -ForegroundColor Yellow
    Set-Location $BackendDir
    python cities_loader.py --download

    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Backend avviato! http://localhost:8000/docs" -ForegroundColor Green
}
