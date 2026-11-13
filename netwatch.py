"""Aparelhos da rede (ODD-42): quem o PC já viu no Wi-Fi, com nome dado por você.

Só lê a tabela ARP que o sistema já tem (``osint.parse_neighbors``): não manda pacote para ninguém.
O registro fica no ``rede_aparelhos.json`` (fora do git), indexado pelo MAC, que é o que identifica
um aparelho (o IP muda de um dia para o outro). O monitor de avisos (``proactive.NetworkMonitor``)
usa ``observe`` e as rotas do HUD usam o resto.

Endereço privado: celulares e notebooks modernos usam um MAC aleatório por rede (o bit "localmente
administrado", o segundo bit menos significativo do primeiro byte). Alguns trocam de endereço de tempos
em tempos, então o mesmo celular pode aparecer como "novo" várias vezes. Esses endereços ficam marcados
como privados e são avisados em grupo, no máximo uma vez a cada ``PRIVATE_NOTICE_COOLDOWN_S``.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger("jarvis-netwatch")

DEVICES_FILE = Path(__file__).resolve().parent / "rede_aparelhos.json"
API_PREFIX = "/api/osint/network"

# Na primeira vez a tabela ARP do PC ainda está incompleta (só tem quem ele falou há pouco), então
# o Jarvis aprende em silêncio por este tempo, em vez de só na primeira leitura.
LEARN_S = 30 * 60
PRIVATE_NOTICE_COOLDOWN_S = 6 * 3600
MAX_DEVICES = 250
MAX_NAME_CHARS = 40
MAC_FORMAT = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
_LOCK = threading.Lock()


def is_private_mac(mac: str) -> bool:
    """MAC aleatório ("endereço privado"): o bit localmente administrado do primeiro byte está ligado."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


def clean_name(text: Any) -> str:
    """Nome dado pelo usuário: uma linha, sem caracteres de controle, curto."""
    return "".join(ch for ch in " ".join(str(text or "").split()) if ch.isprintable())[:MAX_NAME_CHARS].strip()


def read_neighbors(run: Callable[..., Any] = subprocess.run) -> list[dict[str, str]]:
    """A tabela ARP do PC (``arp -a`` no Windows, ``ip neigh show`` no Linux): só leitura."""
    import osint

    try:
        done = run(osint._arp_command(), capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return osint.parse_neighbors(getattr(done, "stdout", "") or "")


# ───────────────────────── arquivo ─────────────────────────


def _empty() -> dict[str, Any]:
    return {"version": 1, "learning_until": None, "private_notice_at": None, "devices": {}}


def _valid_device(mac: str, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not MAC_FORMAT.match(mac):
        return None
    return {
        "mac": mac,
        "ip": str(item.get("ip") or "")[:45],
        "name": clean_name(item.get("name")),
        "known": bool(item.get("known")),
        "private": is_private_mac(mac),
        "notified": bool(item.get("notified", True)),
        "origin": "novo" if item.get("origin") == "novo" else "aprendido",
        "first_seen": str(item.get("first_seen") or "")[:40],
        "last_seen": str(item.get("last_seen") or "")[:40],
    }


def _read(path: Path) -> tuple[dict[str, Any], bool]:
    state = _empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return state, True
    except (OSError, ValueError):
        logger.warning("Não consegui ler %s; ele será guardado como cópia antes de gravar.", path.name)
        return state, False
    if not isinstance(raw, dict):
        return state, False
    for key in ("learning_until", "private_notice_at"):
        value = raw.get(key)
        if isinstance(value, str):
            with contextlib.suppress(ValueError):
                dt.datetime.fromisoformat(value)
                state[key] = value
    devices = raw.get("devices")
    if isinstance(devices, dict):
        for mac, item in devices.items():
            device = _valid_device(str(mac).lower(), item)
            if device:
                state["devices"][device["mac"]] = device
    return state, True


def _write(path: Path, state: dict[str, Any], readable: bool) -> None:
    if not readable and path.exists():
        backup = path.with_name(f"{path.stem}.corrompido-{int(dt.datetime.now().timestamp())}{path.suffix}")
        os.replace(path, backup)
        logger.warning("%s estava ilegível e foi guardado em %s.", path.name, backup.name)
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


@contextlib.contextmanager
def _editing(path: Path | None) -> Iterator[dict[str, Any]]:
    target = path or DEVICES_FILE
    with _LOCK:
        state, readable = _read(target)
        before = json.dumps(state, sort_keys=True)
        yield state
        if json.dumps(state, sort_keys=True) != before:
            _write(target, state, readable)


def load(path: Path | None = None) -> dict[str, Any]:
    with _LOCK:
        return _read(path or DEVICES_FILE)[0]


# ───────────────────────── o que o monitor faz ─────────────────────────


def observe(
    seen: list[dict[str, str]],
    now: dt.datetime,
    path: Path | None = None,
    *,
    learn_s: float = LEARN_S,
) -> dict[str, list[dict[str, Any]]]:
    """Registra o que a tabela ARP mostrou e devolve o que merece aviso.

    ``{"public": [...], "private": [...]}``: aparelhos novos com MAC de fábrica e novos com endereço
    privado, ainda não avisados. O aviso dos privados só sai a cada ``PRIVATE_NOTICE_COOLDOWN_S``.
    Durante o aprendizado (a primeira ``learn_s`` segundos, contados da primeira leitura que trouxe
    algum aparelho) tudo entra como conhecido, sem aviso.
    """
    stamp = now.isoformat(timespec="seconds")
    with _editing(path) as state:
        devices = state["devices"]
        if state["learning_until"] is None and seen:
            state["learning_until"] = (now + dt.timedelta(seconds=learn_s)).isoformat(timespec="seconds")
        learning = state["learning_until"] is not None and now < dt.datetime.fromisoformat(state["learning_until"])
        for item in seen:
            mac = item["mac"]
            known = devices.get(mac)
            if known:
                known["ip"] = item["ip"]
                known["last_seen"] = stamp
                continue
            if len(devices) >= MAX_DEVICES:
                continue
            devices[mac] = {
                "mac": mac,
                "ip": item["ip"],
                "name": "",
                "known": learning,
                "private": is_private_mac(mac),
                "notified": learning,
                "origin": "aprendido" if learning else "novo",
                "first_seen": stamp,
                "last_seen": stamp,
            }
        fresh = [device for device in devices.values() if not device["notified"] and not device["known"]]
        # Quem o usuário já nomeou ou marcou como conhecido não precisa de aviso.
        for device in devices.values():
            if device["known"]:
                device["notified"] = True
        public = [device for device in fresh if not device["private"]]
        private = [device for device in fresh if device["private"]]
        for device in public:
            device["notified"] = True
        last_private = state["private_notice_at"]
        cooled = last_private is None or (now - dt.datetime.fromisoformat(last_private)).total_seconds() >= PRIVATE_NOTICE_COOLDOWN_S
        if private and cooled:
            for device in private:
                device["notified"] = True
            state["private_notice_at"] = stamp
        else:
            private = []
        order = lambda device: tuple(int(part) for part in device["ip"].split(".")) if device["ip"] else (999,)  # noqa: E731
        return {"public": sorted(public, key=order), "private": sorted(private, key=order)}


# ───────────────────────── o que o HUD faz ─────────────────────────


def listing(path: Path | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """O que o HUD mostra: os ainda não revisados primeiro, depois os conhecidos, do mais recente ao mais antigo."""
    state = load(path)
    by_recent = sorted(state["devices"].values(), key=lambda device: device["last_seen"], reverse=True)
    unreviewed = [device for device in by_recent if not device["known"]]
    reviewed = [device for device in by_recent if device["known"]]
    learning_until = state["learning_until"]
    moment = now or dt.datetime.now().astimezone()
    learning = bool(learning_until) and moment < dt.datetime.fromisoformat(learning_until)
    return {
        "devices": [*unreviewed, *reviewed],
        "unreviewed": len(unreviewed),
        "learning": learning,
        "learning_until": learning_until,
    }


class DeviceNotFound(KeyError):
    """O MAC não está no registro."""


def update_device(mac: str, *, name: str | None = None, known: bool | None = None, path: Path | None = None) -> dict[str, Any]:
    """Dá nome a um aparelho e/ou o marca como conhecido. Dar nome conta como conhecer."""
    mac = mac.strip().lower().replace("-", ":")
    with _editing(path) as state:
        device = state["devices"].get(mac)
        if device is None:
            raise DeviceNotFound(mac)
        if name is not None:
            device["name"] = clean_name(name)
            if known is None and device["name"]:
                known = True
        if known is not None:
            device["known"] = known
            device["notified"] = True if known else device["notified"]
        return dict(device)


def forget_device(mac: str, path: Path | None = None) -> None:
    """Tira o aparelho do registro. Se ele aparecer de novo, volta como novo."""
    mac = mac.strip().lower().replace("-", ":")
    with _editing(path) as state:
        if mac not in state["devices"]:
            raise DeviceNotFound(mac)
        del state["devices"][mac]


def names(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """MAC → registro, para enriquecer a consulta "Minha rede"."""
    return load(path)["devices"]
