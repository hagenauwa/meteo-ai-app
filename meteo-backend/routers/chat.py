"""
routers/chat.py — chat AI con rate limiting e contesto meteo opzionale.
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import settings
from rate_limit import InMemoryRateLimiter

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
chat_limiter = InMemoryRateLimiter(
    per_minute=settings.chat_requests_per_minute,
    per_day=settings.chat_requests_per_day,
)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=600)
    city: str | None = None
    weatherData: dict | None = None


@router.post("/chat")
async def chat(request: ChatRequest, http_request: Request):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY non configurata")

    client_ip = http_request.client.host if http_request.client else "anonymous"
    chat_limiter.check(client_ip)

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

    prompt = f"""Sei un assistente meteo esperto per l'Italia.
Rispondi in italiano, in modo chiaro e conciso, massimo 4 frasi.
Se mancano dati certi dichiaralo senza inventare.

{weather_context}

Domanda dell'utente: {request.question}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 512,
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload,
                timeout=15,
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
