"""Cotações e conversões (protocolo COT-44).

"Quanto está o dólar?", "e o bitcoin?", "quanto dá 150 dólares em reais?", "10 milhas em
quilômetros". As cotações vêm da AwesomeAPI (pública, sem chave) e ficam guardadas por um minuto;
as conversões de unidade são conta feita aqui mesmo, sem rede.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from typing import Any

import requests
from livekit.agents import RunContext, function_tool

from hud import net_activity, show_card, tool_status

logger = logging.getLogger("jarvis-quotes")

PROTOCOL = "COT-44"
API = "https://economia.awesomeapi.com.br/json/last/"
API_HOST = "economia.awesomeapi.com.br"
TIMEOUT_S = 8.0
CACHE_S = 60.0
DEFAULT_CURRENCIES = ("USD", "EUR", "BTC")

# Como cada moeda é chamada na conversa.
CURRENCIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "BRL": ("Real", ("real", "reais", "brl", "r$")),
    "USD": ("Dólar", ("dolar", "dolares", "usd", "dolar americano", "us$", "$")),
    "EUR": ("Euro", ("euro", "euros", "eur", "€")),
    "GBP": ("Libra", ("libra", "libras", "gbp", "libra esterlina", "£")),
    "ARS": ("Peso argentino", ("peso argentino", "pesos argentinos", "ars", "peso")),
    "JPY": ("Iene", ("iene", "ienes", "jpy", "yen")),
    "CAD": ("Dólar canadense", ("dolar canadense", "dolares canadenses", "cad")),
    "AUD": ("Dólar australiano", ("dolar australiano", "dolares australianos", "aud")),
    "CHF": ("Franco suíço", ("franco suico", "francos suicos", "chf", "franco")),
    "CNY": ("Yuan", ("yuan", "yuans", "cny", "renminbi")),
    "BTC": ("Bitcoin", ("bitcoin", "bitcoins", "btc")),
    "ETH": ("Ethereum", ("ethereum", "eth", "ether")),
}

# Unidades: (grandeza, fator para a unidade-base). Temperatura é tratada à parte.
UNITS: dict[str, tuple[str, float]] = {
    "mm": ("comprimento", 0.001), "cm": ("comprimento", 0.01), "m": ("comprimento", 1.0), "km": ("comprimento", 1000.0),
    "in": ("comprimento", 0.0254), "ft": ("comprimento", 0.3048), "yd": ("comprimento", 0.9144), "mi": ("comprimento", 1609.344),
    "mg": ("massa", 1e-6), "g": ("massa", 0.001), "kg": ("massa", 1.0), "t": ("massa", 1000.0),
    "oz": ("massa", 0.028349523125), "lb": ("massa", 0.45359237),
    "ml": ("volume", 0.001), "l": ("volume", 1.0), "gal": ("volume", 3.785411784), "xic": ("volume", 0.24),
    "m/s": ("velocidade", 1.0), "km/h": ("velocidade", 1 / 3.6), "mph": ("velocidade", 0.44704), "kn": ("velocidade", 0.514444),
    "s": ("tempo", 1.0), "min": ("tempo", 60.0), "h": ("tempo", 3600.0), "dia": ("tempo", 86400.0), "sem": ("tempo", 604800.0),
    "b": ("dados", 1.0), "kb": ("dados", 1024.0), "mb": ("dados", 1024.0**2), "gb": ("dados", 1024.0**3), "tb": ("dados", 1024.0**4),
    "m2": ("area", 1.0), "km2": ("area", 1e6), "ha": ("area", 1e4), "ft2": ("area", 0.09290304),
    "c": ("temperatura", 1.0), "f": ("temperatura", 1.0), "k": ("temperatura", 1.0),
}  # fmt: skip
UNIT_ALIASES: dict[str, str] = {
    "milimetro": "mm", "milimetros": "mm", "centimetro": "cm", "centimetros": "cm", "metro": "m", "metros": "m",
    "quilometro": "km", "quilometros": "km", "kilometro": "km", "kilometros": "km",
    "polegada": "in", "polegadas": "in", "inch": "in", "inches": "in", "pe": "ft", "pes": "ft", "feet": "ft", "foot": "ft",
    "jarda": "yd", "jardas": "yd", "milha": "mi", "milhas": "mi", "mile": "mi", "miles": "mi",
    "miligrama": "mg", "miligramas": "mg", "grama": "g", "gramas": "g", "quilo": "kg", "quilos": "kg", "kilo": "kg", "kilos": "kg",
    "quilograma": "kg", "quilogramas": "kg", "tonelada": "t", "toneladas": "t", "onca": "oz", "oncas": "oz",
    "libra peso": "lb", "libras peso": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "mililitro": "ml", "mililitros": "ml", "litro": "l", "litros": "l", "galao": "gal", "galoes": "gal", "xicara": "xic", "xicaras": "xic",
    "metros por segundo": "m/s", "quilometros por hora": "km/h", "km por hora": "km/h", "kmh": "km/h", "milhas por hora": "mph", "no": "kn", "nos": "kn",
    "segundo": "s", "segundos": "s", "minuto": "min", "minutos": "min", "hora": "h", "horas": "h", "dias": "dia", "semana": "sem", "semanas": "sem",
    "byte": "b", "bytes": "b", "kilobyte": "kb", "kilobytes": "kb", "megabyte": "mb", "megabytes": "mb", "mega": "mb", "megas": "mb",
    "gigabyte": "gb", "gigabytes": "gb", "giga": "gb", "gigas": "gb", "terabyte": "tb", "terabytes": "tb", "tera": "tb", "teras": "tb",
    "metro quadrado": "m2", "metros quadrados": "m2", "m²": "m2", "quilometro quadrado": "km2", "quilometros quadrados": "km2", "km²": "km2",
    "hectare": "ha", "hectares": "ha", "pe quadrado": "ft2", "pes quadrados": "ft2",
    "celsius": "c", "grau celsius": "c", "graus celsius": "c", "°c": "c", "graus": "c",
    "fahrenheit": "f", "grau fahrenheit": "f", "graus fahrenheit": "f", "°f": "f", "kelvin": "k",
}  # fmt: skip
UNIT_NAMES = {
    "mm": "mm", "cm": "cm", "m": "m", "km": "km", "in": "pol", "ft": "pés", "yd": "jardas", "mi": "milhas", "mg": "mg", "g": "g", "kg": "kg",
    "t": "t", "oz": "oz", "lb": "lb", "ml": "ml", "l": "L", "gal": "galões", "xic": "xícaras", "m/s": "m/s", "km/h": "km/h", "mph": "mph",
    "kn": "nós", "s": "s", "min": "min", "h": "h", "dia": "dias", "sem": "semanas", "b": "B", "kb": "KB", "mb": "MB", "gb": "GB", "tb": "TB",
    "m2": "m²", "km2": "km²", "ha": "ha", "ft2": "pés²", "c": "°C", "f": "°F", "k": "K",
}  # fmt: skip


class QuoteError(ValueError):
    """Pedido que não dá para atender; a mensagem vai para o usuário."""


def _plain(text: str) -> str:
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", str(text)) if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.lower().replace(".", " ").split())


def currency_code(name: str) -> str | None:
    plain = _plain(name)
    if plain.upper() in CURRENCIES:
        return plain.upper()
    for code, (_, aliases) in CURRENCIES.items():
        if plain in aliases:
            return code
    return None


def unit_code(name: str) -> str | None:
    raw = str(name).strip().lower()
    plain = _plain(name).replace("²", "2")
    for candidate in (raw, plain):
        if candidate in UNITS:
            return candidate
        if candidate in UNIT_ALIASES:
            return UNIT_ALIASES[candidate]
    return None


def format_number(value: float, decimals: int | None = None) -> str:
    """Número à brasileira: 1.234,56. Sem `decimals`, guarda o que importa do valor."""
    if decimals is None:
        magnitude = abs(value)
        decimals = 0 if float(value).is_integer() else 2 if magnitude >= 1 else 4 if magnitude >= 0.01 else 6
    text = f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text.rstrip("0").rstrip(",") if "," in text and decimals > 2 else text


def convert_units(amount: float, source: str, target: str) -> float:
    kind_a, factor_a = UNITS[source]
    kind_b, factor_b = UNITS[target]
    if kind_a != kind_b:
        raise QuoteError(f"Não dá para converter {kind_a} em {kind_b}.")
    if kind_a == "temperatura":
        celsius = amount if source == "c" else (amount - 32) * 5 / 9 if source == "f" else amount - 273.15
        return celsius if target == "c" else celsius * 9 / 5 + 32 if target == "f" else celsius + 273.15
    return amount * factor_a / factor_b


# ───────────────────────── cotações ─────────────────────────

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_pairs(pairs: list[tuple[str, str]], http: Any = requests, *, now: float | None = None) -> dict[str, dict[str, Any]]:
    """Cotação de cada par (moeda, em qual moeda), com um minuto de memória."""
    moment = time.monotonic() if now is None else now
    wanted = list(dict.fromkeys(f"{a}-{b}" for a, b in pairs))
    missing = [pair for pair in wanted if pair not in _cache or moment - _cache[pair][0] > CACHE_S]
    if missing:
        response = http.get(API + ",".join(missing), timeout=TIMEOUT_S, headers={"Accept": "application/json"})
        if response.status_code == 404:
            raise QuoteError("Não achei cotação para essa moeda.")
        if response.status_code != 200:
            raise QuoteError(f"O serviço de cotações respondeu {response.status_code}.")
        try:
            data = response.json()
        except ValueError:
            raise QuoteError("O serviço de cotações respondeu algo que não entendi.") from None
        for pair in missing:
            entry = data.get(pair.replace("-", "")) if isinstance(data, dict) else None
            bid = _number((entry or {}).get("bid"))
            if bid is None:
                continue
            code, base = pair.split("-")
            _cache[pair] = (
                moment,
                {
                    "code": code,
                    "base": base,
                    "name": CURRENCIES.get(code, (code,))[0],
                    "value": bid,
                    "change_pct": _number(entry.get("pctChange")),
                    "high": _number(entry.get("high")),
                    "low": _number(entry.get("low")),
                    "at": str(entry.get("create_date") or "")[:19],
                },
            )
    return {pair: _cache[pair][1] for pair in wanted if pair in _cache}


def quotes(codes: list[str] | None = None, http: Any = requests) -> list[dict[str, Any]]:
    """Cada moeda em reais, na ordem pedida."""
    wanted = [code for code in dict.fromkeys(codes or DEFAULT_CURRENCIES) if code != "BRL"]
    if not wanted:
        raise QuoteError("O real é a base: diga outra moeda para eu cotar.")
    found = fetch_pairs([(code, "BRL") for code in wanted], http)
    items = [found[f"{code}-BRL"] for code in wanted if f"{code}-BRL" in found]
    if not items:
        raise QuoteError("O serviço de cotações não devolveu nenhum valor.")
    return items


def convert_currency(amount: float, source: str, target: str, http: Any = requests) -> tuple[float, float]:
    """(resultado, taxa). Passa pelo real quando o par direto não existe."""
    if source == target:
        return amount, 1.0
    legs = [(code, "BRL") for code in (source, target) if code != "BRL"]
    found = fetch_pairs(legs, http)
    to_brl = 1.0 if source == "BRL" else (found.get(f"{source}-BRL") or {}).get("value")
    from_brl = 1.0 if target == "BRL" else (found.get(f"{target}-BRL") or {}).get("value")
    if not to_brl or not from_brl:
        raise QuoteError("Não achei cotação para uma das moedas.")
    rate = to_brl / from_brl
    return amount * rate, rate


def parse_currencies(text: str) -> list[str]:
    """ "dólar, euro e bitcoin" → ["USD", "EUR", "BTC"]. Nada reconhecido → as três de sempre."""
    plain = _plain(text or "")
    if not plain:
        return list(DEFAULT_CURRENCIES)
    found: list[str] = []
    for part in re.split(r"\s*(?:,|;| e |/)\s*", plain):
        code = currency_code(part.strip())
        if code:
            found.append(code)
    return list(dict.fromkeys(found)) or list(DEFAULT_CURRENCIES)


def spoken_quote(item: dict[str, Any]) -> str:
    decimals = 0 if item["value"] >= 1000 else 2 if item["value"] >= 0.1 else 4
    change = item.get("change_pct")
    trend = "" if change is None else f", {'alta' if change >= 0 else 'queda'} de {format_number(abs(change), 2)}% no dia"
    return f"{item['name']}: R$ {format_number(item['value'], decimals)}{trend}"


def convert(amount: float, source: str, target: str, http: Any = requests) -> dict[str, Any]:
    """Converte moedas (pela cotação de agora) ou unidades (conta local)."""
    if not isinstance(amount, (int, float)) or amount != amount or abs(amount) > 1e15:
        raise QuoteError("Esse valor não dá para converter.")
    money = (currency_code(source), currency_code(target))
    units = [unit_code(source), unit_code(target)]
    # "libra" sozinha é a moeda; ao lado de um peso ("libras em quilos") é a unidade.
    for index, name in enumerate((source, target)):
        other = units[1 - index]
        if units[index] is None and _plain(name) in ("libra", "libras") and other and UNITS[other][0] == "massa":
            units[index] = "lb"
    # "libra" é moeda e peso: o outro lado da conversão decide.
    if all(units) and not all(money):
        result = convert_units(float(amount), units[0], units[1])
        return {"amount": amount, "from": UNIT_NAMES[units[0]], "to": UNIT_NAMES[units[1]], "result": result, "kind": "unit", "rate": None}
    if all(money):
        result, rate = convert_currency(float(amount), money[0], money[1], http)
        return {"amount": amount, "from": money[0], "to": money[1], "result": result, "kind": "currency", "rate": rate}
    if all(units):
        result = convert_units(float(amount), units[0], units[1])
        return {"amount": amount, "from": UNIT_NAMES[units[0]], "to": UNIT_NAMES[units[1]], "result": result, "kind": "unit", "rate": None}
    unknown = source if not (money[0] or units[0]) else target
    raise QuoteError(f"Não conheço “{unknown}” como moeda nem como unidade.")


def spoken_conversion(data: dict[str, Any]) -> str:
    if data["kind"] == "currency":
        decimals = 2 if abs(data["result"]) >= 0.1 else 6
        return f"{format_number(data['amount'])} {data['from']} dá {format_number(data['result'], decimals)} {data['to']}, na cotação de agora."
    return f"{format_number(data['amount'])} {data['from']} dá {format_number(data['result'])} {data['to']}."


# ───────────────────────── ferramentas de voz ─────────────────────────


def build_quote_tools() -> list[Any]:
    @function_tool()
    async def get_quotes(context: RunContext, currencies: str = "") -> str:
        """Cotação de moedas em reais agora: dólar, euro, libra, iene, peso argentino, bitcoin, ethereum...

        Args:
            currencies: Moedas separadas por vírgula ("dólar, bitcoin"). Vazio: dólar, euro e bitcoin.
        """
        codes = parse_currencies(currencies)
        detail = ", ".join(codes)
        await tool_status("get_quotes", "running", detail)
        await net_activity([API_HOST])
        try:
            items = await asyncio.to_thread(quotes, codes)
        except QuoteError as exc:
            await tool_status("get_quotes", "error", detail)
            return str(exc)
        except requests.RequestException:
            await tool_status("get_quotes", "error", detail)
            return "O serviço de cotações não respondeu (falha de rede)."
        await show_card("quotes", {"items": items, "conversion": None})
        await tool_status("get_quotes", "done", detail)
        return ". ".join(spoken_quote(item) for item in items) + "."

    @function_tool()
    async def convert_value(context: RunContext, amount: float, from_unit: str, to_unit: str) -> str:
        """Converte um valor entre moedas (cotação de agora) ou entre unidades de medida: comprimento,
        peso, volume, temperatura, velocidade, tempo, dados e área.

        Args:
            amount: O valor a converter.
            from_unit: De qual moeda ou unidade ("dólar", "milhas", "fahrenheit", "kg").
            to_unit: Para qual moeda ou unidade ("reais", "km", "celsius", "libras peso").
        """
        detail = f"{amount:g} {from_unit} → {to_unit}"[:60]
        await tool_status("convert_value", "running", detail)
        try:
            data = await asyncio.to_thread(convert, amount, from_unit, to_unit)
        except QuoteError as exc:
            await tool_status("convert_value", "error", detail)
            return str(exc)
        except requests.RequestException:
            await tool_status("convert_value", "error", detail)
            return "O serviço de cotações não respondeu (falha de rede)."
        if data["kind"] == "currency":
            await net_activity([API_HOST])
            await show_card("quotes", {"items": [], "conversion": data})
        await tool_status("convert_value", "done", detail)
        return spoken_conversion(data)

    return [get_quotes, convert_value]
