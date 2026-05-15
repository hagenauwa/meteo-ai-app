# 🚀 Avvio Rapido Meteo AI App

> Stack dual: frontend JS + backend Python. Prepara due terminali!

## Prerequisiti
- [Node.js LTS](https://nodejs.org/)
- Python 3.11+ + `pip`

## 1. Clona il repo

```bash
git clone <repo-url>
cd meteo-ai-app
```

## 2. Avvia il backend 🐍

```bash
cd meteo-backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Modifica .env: DATABASE_URL=sqlite:///./meteo_ai.db
uvicorn main:app --reload
```

👉 Il backend gira su [http://localhost:8000](http://localhost:8000)

## 3. Avvia il frontend ⚡ (altro terminale)

```bash
npm install
npm run dev   # usa Netlify Dev -> http://localhost:8888
```

Oppure apri direttamente `public/index.html` — il frontend rileva `localhost` e punta a `:8000` automaticamente.

## 🚀 Deploy

| Parte | Piattaforma | Config |
|-------|-------------|--------|
| Frontend | Netlify | `netlify.toml` incluso |
| Backend | Render | `render.yaml` incluso |

## 🩹 Troubleshooting

- `uvicorn` non trovato → attiva il virtualenv (`source venv/bin/activate`)
- Frontend non trova il backend → controlla che il backend sia su `:8000`
- Porta occupata → modifica la porta in `uvicorn main:app --reload --port <porta>`
