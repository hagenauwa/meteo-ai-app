"""
routers/chat.py — Chat AI con Google Gemini

POST /api/chat
Body: { "question": "...", "city": "Roma" (opzionale) }

Migrato da netlify/functions/ai-chat.js
"""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


class ChatRequest(BaseModel):
    question: str
    city:     str | None = None
    weatherData: dict | None = None  # Dati meteo pre-fetchati (opzionale)


@router.post("/chat")
async def chat(request: ChatRequest):
    """Risponde a domande meteo in linguaggio naturale tramite Gemini."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY non configurata")

    # Costruisci contesto meteo se disponibile
    weather_context = ""
    if request.weatherData:
        wd = request.weatherData
        current = wd.get("current", {})
        city_name = request.city or wd.get("name", "la città richiesta")
        weather_context = f"""
Dati meteo attuali per {city_name}:
- Temperatura: {current.get('temp', 'N/D')}°C (percepita: {current.get('feels_like', 'N/D')}°C)
- Umidità: {current.get('humidity', 'N/D')}%
- Pressione: {current.get('pressure', 'N/D')} hPa
- Vento: {current.get('windSpeed', current.get('wind_speed', 'N/D'))} km/h
- Condizioni: {current.get('weather', [{}])[0].get('description', 'N/D')}
"""

    prompt = f"""Sei un assistente meteo esperto per l'Italia. Rispondi in italiano, in modo chiaro e conciso.
Usa emoji meteo dove appropriato. Massimo 3-4 frasi.

{weather_context}

Domanda dell'utente: {request.question}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            text = (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "Non ho potuto elaborare la risposta.")
            )
            return {"text": text}

        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Errore Gemini API: {str(e)}")
