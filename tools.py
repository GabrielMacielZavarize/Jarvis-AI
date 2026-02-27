import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
from langchain_community.tools import DuckDuckGoSearchRun
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("jarvis-tools")


@function_tool()
async def get_weather(
    context: RunContext,
    city: str,
) -> str:
    """Get the current weather for a given city.

    Args:
        city: The name of the city to get weather for.
    """
    try:
        # Primeiro, geocodificar a cidade para obter lat/lon
        geo_response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "pt"},
            timeout=15,
        )
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return f"Cidade '{city}' não encontrada."

        location = geo_data["results"][0]
        lat = location["latitude"]
        lon = location["longitude"]
        city_name = location.get("name", city)

        # Buscar clima atual
        weather_response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=15,
        )
        weather_data = weather_response.json()
        current = weather_data["current"]

        # Mapear código do tempo para descrição
        weather_codes = {
            0: "Céu limpo", 1: "Predominantemente limpo",
            2: "Parcialmente nublado", 3: "Nublado",
            45: "Névoa", 48: "Névoa com geada",
            51: "Garoa leve", 53: "Garoa moderada", 55: "Garoa forte",
            61: "Chuva leve", 63: "Chuva moderada", 65: "Chuva forte",
            71: "Neve leve", 73: "Neve moderada", 75: "Neve forte",
            80: "Pancadas leves", 81: "Pancadas moderadas", 82: "Pancadas fortes",
            95: "Trovoada", 96: "Trovoada com granizo leve", 99: "Trovoada com granizo forte",
        }
        code = current.get("weather_code", -1)
        description = weather_codes.get(code, "Condição desconhecida")

        result = (
            f"{city_name}: {description}, "
            f"{current['temperature_2m']}°C, "
            f"Umidade {current['relative_humidity_2m']}%, "
            f"Vento {current['wind_speed_10m']} km/h"
        )
        logger.info(f"Weather for {city}: {result}")
        return result

    except Exception as e:
        logger.error(f"Error retrieving weather for {city}: {e}")
        return f"Ocorreu um erro ao buscar o clima para {city}."


@function_tool()
async def search_web(
    context: RunContext,
    query: str,
) -> str:
    """Search the web using DuckDuckGo.

    Args:
        query: The search query to look up on the web.
    """
    try:
        results = DuckDuckGoSearchRun().run(tool_input=query)
        logger.info(f"Search results for '{query}': {results}")
        return results
    except Exception as e:
        logger.error(f"Error searching the web for '{query}': {e}")
        return f"Ocorreu um erro ao pesquisar na web por '{query}'."


@function_tool()
async def send_email(
    context: RunContext,
    to_email: str,
    subject: str,
    message: str,
    cc_email: Optional[str] = None,
) -> str:
    """Send an email through Gmail.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        message: Email body content.
        cc_email: Optional CC email address.
    """
    try:
        smtp_server = "smtp.gmail.com"
        smtp_port = 587

        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")

        if not gmail_user or not gmail_password:
            logger.error("Gmail credentials not found in environment variables")
            return (
                "Falha ao enviar email: credenciais do Gmail não configuradas. "
                "Configure GMAIL_USER e GMAIL_APP_PASSWORD no arquivo .env."
            )

        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = subject

        recipients = [to_email]
        if cc_email:
            msg["Cc"] = cc_email
            recipients.append(cc_email)

        msg.attach(MIMEText(message, "plain"))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(gmail_user, gmail_password)

        server.sendmail(gmail_user, recipients, msg.as_string())
        server.quit()

        logger.info(f"Email sent successfully to {to_email}")
        return f"Email enviado com sucesso para {to_email}"

    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail authentication failed")
        return (
            "Falha ao enviar email: erro de autenticação. "
            "Verifique suas credenciais do Gmail."
        )
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error occurred: {e}")
        return f"Falha ao enviar email: erro SMTP - {e}"
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return f"Ocorreu um erro ao enviar email: {e}"
