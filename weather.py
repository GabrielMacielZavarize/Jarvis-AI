"""Clima pelo Open-Meteo (sem chave): rótulos dos códigos WMO e o resumo do modo ambiente do HUD.

Fica fora do tools.py para o servidor do HUD não carregar o LiveKit só por causa do clima.
"""

from __future__ import annotations

from typing import Any

import requests

WEATHER_CODES = {
    0: "Céu limpo",
    1: "Predominantemente limpo",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Névoa",
    48: "Névoa com geada",
    51: "Garoa leve",
    53: "Garoa moderada",
    55: "Garoa forte",
    61: "Chuva leve",
    63: "Chuva moderada",
    65: "Chuva forte",
    71: "Neve leve",
    73: "Neve moderada",
    75: "Neve forte",
    80: "Pancadas leves",
    81: "Pancadas moderadas",
    82: "Pancadas fortes",
    95: "Trovoada",
    96: "Trovoada com granizo leve",
    99: "Trovoada com granizo forte",
}


def current_conditions(latitude: float, longitude: float) -> dict[str, Any]:
    """Temperature now, today's range and the sky, for the ambient mode of the HUD."""
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min",
            "forecast_days": 1,
            "timezone": "auto",
        },
        timeout=8,
    )
    response.raise_for_status()
    data = response.json()
    current = data["current"]
    daily = data.get("daily") or {}
    code = current.get("weather_code")
    return {
        "temperature": current["temperature_2m"],
        "code": code,
        "label": WEATHER_CODES.get(code, "Condição desconhecida"),
        "is_day": current.get("is_day", 1),
        "max": (daily.get("temperature_2m_max") or [None])[0],
        "min": (daily.get("temperature_2m_min") or [None])[0],
    }
