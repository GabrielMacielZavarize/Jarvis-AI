"""Velocidade da internet (protocolo RED-45).

"Como está a minha internet?" mede a latência (tempo de abrir uma conexão com servidores
conhecidos), o download e o upload, e guarda as últimas medições em ``rede.json`` (fora do git)
para o painel Rede do HUD mostrar a evolução.

A medição usa os servidores de teste da Cloudflare, com volume pequeno e tempo limitado: serve
para dizer se a rede está boa, não para tirar o último megabit do plano.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import socket
import statistics
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request
from livekit.agents import RunContext, function_tool

from hud import net_activity, show_card, tool_status

logger = logging.getLogger("jarvis-netcheck")

PROTOCOL = "RED-45"
HISTORY_FILE = Path(__file__).resolve().parent / "rede.json"
MAX_HISTORY = 60
PING_TARGETS = (("1.1.1.1", 443), ("8.8.8.8", 443))
PING_ROUNDS = 3
DOWN_URL = "https://speed.cloudflare.com/__down"
UP_URL = "https://speed.cloudflare.com/__up"
HOST = "speed.cloudflare.com"
DOWN_BYTES = 25_000_000
UP_BYTES = 4_000_000
MAX_SECONDS = 7.0
# Um teste por vez e não mais que um a cada tanto: é banda de verdade que se gasta.
MIN_INTERVAL_S = 20.0

_running = threading.Lock()
_last_run = 0.0


class NetError(RuntimeError):
    """Medição que não deu certo; a mensagem vai para o usuário."""


def measure_latency(targets: tuple[tuple[str, int], ...] = PING_TARGETS, *, connect: Callable[..., Any] = socket.create_connection, clock: Callable[[], float] = time.perf_counter) -> float | None:
    """Mediana, em ms, do tempo de abrir uma conexão TCP com cada servidor (None: nenhum respondeu)."""
    samples: list[float] = []
    for host, port in targets:
        for _ in range(PING_ROUNDS):
            start = clock()
            try:
                sock = connect((host, port), timeout=2.0)
            except OSError:
                continue
            samples.append((clock() - start) * 1000)
            try:
                sock.close()
            except OSError:
                pass
    return round(statistics.median(samples), 1) if samples else None


def measure_download(http: Any = requests, *, clock: Callable[[], float] = time.perf_counter) -> float | None:
    """Download em Mbps: lê até DOWN_BYTES ou MAX_SECONDS, o que vier primeiro."""
    start = clock()
    received = 0
    try:
        with http.get(DOWN_URL, params={"bytes": DOWN_BYTES}, stream=True, timeout=(4.0, MAX_SECONDS)) as response:
            if response.status_code != 200:
                return None
            for chunk in response.iter_content(chunk_size=65536):
                received += len(chunk)
                if clock() - start >= MAX_SECONDS:
                    break
    except requests.RequestException:
        if received == 0:
            return None
    elapsed = clock() - start
    return round(received * 8 / elapsed / 1e6, 1) if elapsed > 0 and received > 0 else None


def measure_upload(http: Any = requests, *, clock: Callable[[], float] = time.perf_counter) -> float | None:
    """Upload em Mbps de UP_BYTES de zeros."""
    payload = bytes(UP_BYTES)
    start = clock()
    try:
        response = http.post(UP_URL, data=payload, timeout=(4.0, MAX_SECONDS * 2), headers={"Content-Type": "application/octet-stream"})
    except requests.RequestException:
        return None
    elapsed = clock() - start
    if response.status_code >= 400 or elapsed <= 0:
        return None
    return round(len(payload) * 8 / elapsed / 1e6, 1)


def rate(result: dict[str, Any]) -> tuple[str, str]:
    """(nível, frase) para o veredito do painel."""
    down, ping = result.get("down_mbps"), result.get("ping_ms")
    if down is None and ping is None:
        return "danger", "Sem conexão com a internet"
    if down is None:
        return "warn", "A latência responde, mas o teste de download falhou"
    if down < 5 or (ping is not None and ping > 250):
        return "danger", "Lenta: chamada de vídeo e streaming vão sofrer"
    if down < 25 or (ping is not None and ping > 90):
        return "warn", "Razoável: dá para trabalhar, com alguma espera"
    return "ok", "Boa: sobra para vídeo, chamadas e downloads"


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    try:
        raw = json.loads((path or HISTORY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs = raw.get("runs") if isinstance(raw, dict) else None
    if not isinstance(runs, list):
        return []
    kept = []
    for run in runs:
        if isinstance(run, dict) and isinstance(run.get("at"), str):
            kept.append({key: run.get(key) for key in ("at", "ping_ms", "down_mbps", "up_mbps")})
    return kept[-MAX_HISTORY:]


def _save(runs: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or HISTORY_FILE
    temp = target.with_name(f"{target.name}.tmp")
    temp.write_text(json.dumps({"version": 1, "runs": runs[-MAX_HISTORY:]}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)


def card(history: list[dict[str, Any]]) -> dict[str, Any]:
    last = history[-1] if history else None
    level, label = rate(last) if last else ("ok", "")
    return {"last": last, "verdict": {"level": level, "label": label} if last else None, "history": history[-30:]}


def run_test(
    *,
    path: Path | None = None,
    http: Any = requests,
    latency: Callable[[], float | None] = measure_latency,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now().astimezone(),
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Mede, grava no histórico e devolve o painel. Um teste por vez."""
    global _last_run
    if not _running.acquire(blocking=False):
        raise NetError("Já tem um teste de velocidade rodando.")
    try:
        wait = MIN_INTERVAL_S - (clock() - _last_run)
        if _last_run and wait > 0:
            raise NetError(f"Acabei de medir. Espere {int(wait) + 1} segundos para medir de novo.")
        ping = latency()
        down = measure_download(http) if ping is not None else None
        up = measure_upload(http) if down is not None else None
        result = {"at": now().isoformat(timespec="seconds"), "ping_ms": ping, "down_mbps": down, "up_mbps": up}
        _last_run = clock()
        history = [*load_history(path), result]
        try:
            _save(history, path)
        except OSError:
            logger.warning("Não deu para gravar o histórico da rede.", exc_info=True)
        return card(history)
    finally:
        _running.release()


def spoken(data: dict[str, Any]) -> str:
    last = data.get("last") or {}
    parts = []
    if last.get("down_mbps") is not None:
        parts.append(f"download de {last['down_mbps']:g} megabits por segundo")
    if last.get("up_mbps") is not None:
        parts.append(f"upload de {last['up_mbps']:g}")
    if last.get("ping_ms") is not None:
        parts.append(f"latência de {last['ping_ms']:g} milissegundos")
    verdict = (data.get("verdict") or {}).get("label", "")
    return (", ".join(parts).capitalize() + ". " if parts else "") + verdict + "."


def build_net_tools() -> list[Any]:
    @function_tool()
    async def network_speed(context: RunContext) -> str:
        """Mede a internet agora: latência, download e upload ("como está a minha internet?",
        "testa a velocidade"). Leva uns 15 segundos e gasta alguns megabytes."""
        await tool_status("network_speed", "running", "medindo")
        await net_activity([HOST, "1.1.1.1"])
        try:
            data = await asyncio.to_thread(run_test)
        except NetError as exc:
            await tool_status("network_speed", "error", "medição")
            return str(exc)
        await show_card("speed", data)
        await tool_status("network_speed", "done", (data.get("verdict") or {}).get("label", "")[:60])
        return spoken(data)

    return [network_speed]


def build_net_router(enabled: Callable[[], bool], require_local: Callable[..., None], path: Callable[[], Path | None] = lambda: None) -> APIRouter:
    router = APIRouter(prefix="/api/network")

    @router.get("")
    def history(request: Request) -> dict[str, Any]:
        require_local(request, "O painel de rede")
        return {"enabled": enabled(), **card(load_history(path()) if enabled() else [])}

    @router.post("/test")
    def test(request: Request) -> dict[str, Any]:
        # Só o próprio PC mede: o teste gasta a banda dele.
        require_local(request, "O teste de rede", devices=False)
        if not enabled():
            raise HTTPException(status_code=403, detail="O teste de rede está desligado (JARVIS_ENABLE_DAY=false no .env).")
        try:
            return {"enabled": True, **run_test(path=path())}
        except NetError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    return router
