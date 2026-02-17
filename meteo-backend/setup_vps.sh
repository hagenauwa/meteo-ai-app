#!/bin/bash
# ============================================================
# setup_vps.sh — Setup completo del backend su VPS Ubuntu/Debian
# Eseguire come root o con sudo
# ============================================================

set -e

echo "🚀 Setup Meteo AI Backend"

# 1. Aggiorna sistema e installa dipendenze
apt-get update -y
apt-get install -y python3.11 python3.11-pip python3.11-venv postgresql postgresql-contrib git

# 2. Crea cartella e copia file
mkdir -p /opt/meteo-backend
cp -r . /opt/meteo-backend/
cd /opt/meteo-backend

# 3. Crea virtual environment Python
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configura PostgreSQL
sudo -u postgres psql -c "CREATE DATABASE meteo_ai;" 2>/dev/null || echo "DB già esistente"
sudo -u postgres psql -c "CREATE USER meteo_user WITH PASSWORD 'meteo_password_cambia_questa';" 2>/dev/null || echo "Utente già esistente"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE meteo_ai TO meteo_user;"
sudo -u postgres psql -d meteo_ai -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 5. Crea file .env se non esiste
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Crea .env con le tue credenziali (vedi .env.example)"
fi

# 6. Crea tabelle DB
source venv/bin/activate
python -c "from database import init_db; init_db()"

# 7. Scarica e carica tutti i comuni italiani
python cities_loader.py --download

# 8. Crea servizio systemd
cat > /etc/systemd/system/meteo-backend.service << 'EOF'
[Unit]
Description=Meteo AI Backend (FastAPI + APScheduler)
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/meteo-backend
Environment="PATH=/opt/meteo-backend/venv/bin"
ExecStart=/opt/meteo-backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 9. Abilita e avvia servizio
chown -R www-data:www-data /opt/meteo-backend
systemctl daemon-reload
systemctl enable meteo-backend
systemctl start meteo-backend

echo ""
echo "✅ Backend avviato!"
echo "   Swagger UI: http://$(hostname -I | awk '{print $1}'):8000/docs"
echo "   Stato:      systemctl status meteo-backend"
echo ""
echo "⚠️  Ricordati di:"
echo "   1. Modificare .env con GEMINI_API_KEY e DATABASE_URL corretti"
echo "   2. Cambiare la password PostgreSQL"
echo "   3. Configurare nginx per HTTPS (opzionale ma consigliato)"
echo "   4. Aggiornare BACKEND_URL in public/index.html con l'IP/dominio del VPS"
