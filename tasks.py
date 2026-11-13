"""Tarefas e notas (protocolo TAR-43).

"Anota aí: comprar café", "me lembra de fechar o relatório até sexta" (sem hora: vira tarefa com
prazo), "o que falta hoje?", "já fiz o relatório". Tudo fica em ``tarefas.json`` nesta pasta,
fora do git, e aparece no painel Tarefas do HUD, onde também dá para marcar e apagar com um clique.

Uma tarefa tem texto, prazo opcional (um dia, sem hora) e fica aberta ou feita. Uma nota é só um
texto guardado. Aviso com hora marcada é outra coisa: são os lembretes do PRO-28.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from livekit.agents import RunContext, function_tool
from pydantic import BaseModel, Field

from hud import show_card, tool_status

logger = logging.getLogger("jarvis-tasks")

PROTOCOL = "TAR-43"
TASKS_FILE = Path(__file__).resolve().parent / "tarefas.json"
MAX_TEXT = 200
MAX_ITEMS = 300
# Feitas há mais tempo que isto saem do arquivo na próxima gravação.
DONE_KEEP_DAYS = 14
KINDS = ("task", "note")
WEEKDAYS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
# Parecido com o filtro da memória: senha e token não vão para um arquivo de texto.
SECRET_PATTERN = re.compile(r"\b(senha|password|passwd|token|api[ _-]?key|chave (?:de api|secreta)|cvv|codigo de seguranca)\b\s*(?:e|eh|é|:|=)?\s*\S+", re.IGNORECASE)

_lock = threading.Lock()


class TaskError(ValueError):
    """Pedido que não dá para atender; a mensagem vai para o usuário."""


def _plain(text: str) -> str:
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9/ -]+", " ", stripped.lower()).split())


def clean_text(text: Any) -> str:
    cleaned = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text or "")).split())
    if not cleaned:
        raise TaskError("Faltou dizer o que anotar.")
    if SECRET_PATTERN.search(_plain(cleaned)) or SECRET_PATTERN.search(cleaned):
        raise TaskError("Isso parece uma senha ou um token. Não guardo esse tipo de coisa num arquivo de texto.")
    return cleaned[:MAX_TEXT]


def parse_due(text: str | None, today: dt.date | None = None) -> dt.date | None:
    """ "hoje", "amanhã", "sexta", "dia 20", "20/11" ou "2026-11-20" → a data. Vazio → sem prazo."""
    plain = _plain(text or "")
    if not plain or plain in ("sem prazo", "nenhum", "nao"):
        return None
    today = today or dt.date.today()
    if plain in ("hoje", "ainda hoje", "pra hoje", "para hoje"):
        return today
    if plain in ("amanha", "pra amanha", "para amanha"):
        return today + dt.timedelta(days=1)
    if plain == "depois de amanha":
        return today + dt.timedelta(days=2)
    words = plain.replace("-feira", "").replace(" feira", "").split()
    for word in words:
        if word in WEEKDAYS:
            ahead = (WEEKDAYS.index(word) - today.weekday()) % 7
            # "sexta" dito numa sexta é a da semana que vem; para hoje existe "hoje".
            return today + dt.timedelta(days=ahead or 7)
    try:
        return dt.date.fromisoformat(plain)
    except ValueError:
        pass
    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", plain)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        year += 2000 if year < 100 else 0
        try:
            due = dt.date(year, month, day)
        except ValueError:
            raise TaskError(f"Não entendi a data “{text}”.") from None
        if not match.group(3) and due < today:
            due = due.replace(year=year + 1)
        return due
    match = re.search(r"\bdia (\d{1,2})\b", plain)
    if match:
        day = int(match.group(1))
        for offset in range(0, 3):
            month = (today.month - 1 + offset) % 12 + 1
            year = today.year + (today.month - 1 + offset) // 12
            try:
                due = dt.date(year, month, day)
            except ValueError:
                continue
            if due >= today:
                return due
    raise TaskError(f"Não entendi o prazo “{text}”. Diga hoje, amanhã, um dia da semana ou uma data.")


def describe_due(due: str | None, today: dt.date | None = None) -> str:
    if not due:
        return ""
    try:
        date = dt.date.fromisoformat(due)
    except ValueError:
        return ""
    today = today or dt.date.today()
    days = (date - today).days
    if days < 0:
        return f"atrasada desde {date.strftime('%d/%m')}"
    if days == 0:
        return "hoje"
    if days == 1:
        return "amanhã"
    if days < 7:
        return ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")[date.weekday()]
    return date.strftime("%d/%m")


# ───────────────────────── arquivo ─────────────────────────


def _valid(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    text = " ".join(str(item.get("text") or "").split())[:MAX_TEXT]
    kind = item.get("kind") if item.get("kind") in KINDS else "task"
    if not text:
        return None
    due = str(item.get("due") or "") or None
    if due:
        try:
            dt.date.fromisoformat(due)
        except ValueError:
            due = None
    return {
        "id": str(item.get("id") or secrets.token_hex(3))[:32],
        "kind": kind,
        "text": text,
        "done": bool(item.get("done")) and kind == "task",
        "due": due if kind == "task" else None,
        "created_at": str(item.get("created_at") or ""),
        "done_at": str(item.get("done_at") or "") or None,
    }


def load_items(path: Path | None = None) -> list[dict[str, Any]]:
    """Todos os itens, do mais antigo para o mais novo. Arquivo ausente ou ilegível: lista vazia."""
    target = path or TASKS_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [valid for valid in (_valid(item) for item in items) if valid]


def _save(items: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or TASKS_FILE
    if target.exists():
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Arquivo estragado: guarda uma cópia antes de escrever por cima.
            backup = target.with_name(f"{target.stem}.corrompido-{int(time.time())}{target.suffix}")
            os.replace(target, backup)
            logger.warning("%s estava ilegível e foi guardado em %s.", target.name, backup.name)
    temp = target.with_name(f"{target.name}.tmp")
    temp.write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)


def _prune(items: list[dict[str, Any]], now: dt.datetime) -> list[dict[str, Any]]:
    limit = (now - dt.timedelta(days=DONE_KEEP_DAYS)).isoformat(timespec="seconds")
    return [item for item in items if not (item["done"] and (item.get("done_at") or "") < limit)]


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def add_item(text: str, kind: str = "task", due: dt.date | None = None, *, path: Path | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise TaskError("Só existem tarefas e notas.")
    cleaned = clean_text(text)
    moment = now or _now()
    with _lock:
        items = [item for item in _prune(load_items(path), moment) if item]
        if sum(1 for item in items if not item["done"]) >= MAX_ITEMS:
            raise TaskError(f"Já são {MAX_ITEMS} itens abertos. Conclua ou apague alguns antes de anotar mais.")
        same = next((item for item in items if item["kind"] == kind and not item["done"] and _plain(item["text"]) == _plain(cleaned)), None)
        if same is not None:
            if kind == "task" and due is not None:
                same["due"] = due.isoformat()
                _save(items, path)
            return same
        item = {
            "id": secrets.token_hex(3),
            "kind": kind,
            "text": cleaned,
            "done": False,
            "due": due.isoformat() if due and kind == "task" else None,
            "created_at": moment.isoformat(timespec="seconds"),
            "done_at": None,
        }
        items.append(item)
        _save(items, path)
    return item


def set_done(item_id: str, done: bool = True, *, path: Path | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    with _lock:
        items = [item for item in load_items(path) if item]
        item = next((item for item in items if item["id"] == item_id and item["kind"] == "task"), None)
        if item is None:
            raise TaskError("Não achei essa tarefa.")
        item["done"] = done
        item["done_at"] = (now or _now()).isoformat(timespec="seconds") if done else None
        _save(items, path)
    return item


def remove_item(item_id: str, *, path: Path | None = None) -> dict[str, Any]:
    with _lock:
        items = [item for item in load_items(path) if item]
        item = next((item for item in items if item["id"] == item_id), None)
        if item is None:
            raise TaskError("Não achei esse item.")
        _save([other for other in items if other["id"] != item_id], path)
    return item


def open_tasks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tarefas abertas na ordem em que são lidas: com prazo primeiro (o mais perto antes), depois as sem prazo."""
    tasks = [item for item in items if item and item["kind"] == "task" and not item["done"]]
    return sorted(tasks, key=lambda item: (item["due"] is None, item["due"] or "", item["created_at"]))


def notes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((item for item in items if item and item["kind"] == "note"), key=lambda item: item["created_at"], reverse=True)


def find(which: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """O item que "a segunda", "2" ou "a do relatório" aponta, na ordem em que a lista foi lida."""
    plain = _plain(which)
    if not candidates:
        raise TaskError("A lista está vazia.")
    ordinals = {"primeira": 1, "primeiro": 1, "segunda": 2, "segundo": 2, "terceira": 3, "terceiro": 3, "quarta": 4, "quarto": 4, "quinta": 5, "quinto": 5, "ultima": len(candidates), "ultimo": len(candidates)}
    number = next((int(word) for word in plain.split() if word.isdigit()), None) or next((ordinals[word] for word in plain.split() if word in ordinals), None)
    words = [word for word in plain.split() if len(word) > 2 and word not in ordinals and word not in ("tarefa", "nota", "aquela", "essa", "esse", "item", "numero")]
    if words:
        scored = [(sum(1 for word in words if word in _plain(item["text"])), item) for item in candidates]
        best = max(score for score, _ in scored)
        winners = [item for score, item in scored if score == best]
        if best > 0 and len(winners) == 1:
            return winners[0]
        if best > 0 and number is None:
            options = "; ".join(f"{index}. {item['text']}" for index, item in enumerate(winners[:4], start=1))
            raise TaskError(f"Achei mais de uma: {options}. Qual delas?")
    if number is not None and 1 <= number <= len(candidates):
        return candidates[number - 1]
    raise TaskError(f"Não achei “{which}” na lista.")


def card(items: list[dict[str, Any]], today: dt.date | None = None) -> dict[str, Any]:
    """O painel Tarefas: abertas na ordem de leitura, as feitas de hoje e as notas."""
    today = today or dt.date.today()
    day = today.isoformat()

    def view(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item["id"],
            "text": item["text"],
            "done": item["done"],
            "due": item["due"],
            "due_label": describe_due(item["due"], today),
            "overdue": bool(item["due"] and item["due"] < day and not item["done"]),
        }

    pending = open_tasks(items)
    done_today = [item for item in items if item and item["kind"] == "task" and item["done"] and (item.get("done_at") or "")[:10] == day]
    return {
        "tasks": [view(item) for item in pending] + [view(item) for item in done_today],
        "notes": [{"id": item["id"], "text": item["text"], "created_at": item["created_at"]} for item in notes(items)[:40]],
        "open": len(pending),
        "overdue": sum(1 for item in pending if item["due"] and item["due"] < day),
        "due_today": sum(1 for item in pending if item["due"] == day),
        "done_today": len(done_today),
    }


def spoken_list(items: list[dict[str, Any]], show: str = "tarefas", today: dt.date | None = None) -> str:
    pending = open_tasks(items)
    saved = notes(items)
    parts: list[str] = []
    if show in ("tarefas", "tudo"):
        if pending:
            lines = [f"{index}. {item['text']}" + (f" ({describe_due(item['due'], today)})" if item["due"] else "") for index, item in enumerate(pending[:12], start=1)]
            more = f" E mais {len(pending) - 12}." if len(pending) > 12 else ""
            parts.append(f"{len(pending)} {'tarefa aberta' if len(pending) == 1 else 'tarefas abertas'}: " + "; ".join(lines) + "." + more)
        else:
            parts.append("Nenhuma tarefa aberta.")
    if show in ("notas", "tudo"):
        if saved:
            parts.append(f"{len(saved)} {'nota' if len(saved) == 1 else 'notas'}: " + "; ".join(f"{index}. {item['text']}" for index, item in enumerate(saved[:8], start=1)) + ".")
        else:
            parts.append("Nenhuma nota guardada.")
    return " ".join(parts)


# ───────────────────────── ferramentas de voz ─────────────────────────


def build_task_tools() -> list[Any]:
    async def refresh() -> None:
        await show_card("tasks", card(await asyncio.to_thread(load_items)))

    @function_tool()
    async def add_task(context: RunContext, text: str, due: str = "") -> str:
        """Anota uma tarefa a fazer, com prazo opcional (um dia, sem hora). Use para "tenho que...",
        "preciso...", "põe na lista...". Para avisar numa hora marcada use set_reminder, não esta.

        Args:
            text: A tarefa, curta, do jeito que o usuário disse.
            due: Prazo: "hoje", "amanhã", um dia da semana, "dia 20" ou "20/11". Vazio: sem prazo.
        """
        await tool_status("add_task", "running", text[:60])
        try:
            item = await asyncio.to_thread(add_item, text, "task", parse_due(due))
        except TaskError as exc:
            await tool_status("add_task", "error", text[:60])
            return str(exc)
        await refresh()
        await tool_status("add_task", "done", item["text"][:60])
        when = describe_due(item["due"])
        return f"Tarefa anotada: {item['text']}" + (f", para {when}." if when else ".")

    @function_tool()
    async def add_note(context: RunContext, text: str) -> str:
        """Guarda uma nota rápida ("anota aí...", "guarda essa ideia..."). Não é um fato sobre o
        usuário (isso é remember) nem algo a fazer (isso é add_task).

        Args:
            text: O texto da nota.
        """
        await tool_status("add_note", "running", text[:60])
        try:
            item = await asyncio.to_thread(add_item, text, "note")
        except TaskError as exc:
            await tool_status("add_note", "error", text[:60])
            return str(exc)
        await refresh()
        await tool_status("add_note", "done", item["text"][:60])
        return f"Nota guardada: {item['text']}."

    @function_tool()
    async def list_tasks(context: RunContext, show: str = "tarefas") -> str:
        """Lê as tarefas abertas e as notas e abre o painel Tarefas ("o que falta hoje?", "minhas notas").

        Args:
            show: "tarefas", "notas" ou "tudo".
        """
        wanted = show if show in ("tarefas", "notas", "tudo") else "tarefas"
        await tool_status("list_tasks", "running", wanted)
        items = await asyncio.to_thread(load_items)
        await show_card("tasks", card(items))
        await tool_status("list_tasks", "done", wanted)
        return spoken_list(items, wanted)

    @function_tool()
    async def complete_task(context: RunContext, which: str) -> str:
        """Marca uma tarefa como feita ("já fiz o relatório", "risca a segunda").

        Args:
            which: Palavras da tarefa ou a posição dela na lista lida ("2", "a segunda", "a última").
        """
        await tool_status("complete_task", "running", which[:60])
        try:
            target = find(which, open_tasks(await asyncio.to_thread(load_items)))
            item = await asyncio.to_thread(set_done, target["id"], True)
        except TaskError as exc:
            await tool_status("complete_task", "error", which[:60])
            return str(exc)
        await refresh()
        await tool_status("complete_task", "done", item["text"][:60])
        left = len(open_tasks(await asyncio.to_thread(load_items)))
        return f"Feita: {item['text']}. " + (f"Faltam {left}." if left else "Lista zerada.")

    @function_tool()
    async def remove_task(context: RunContext, which: str, kind: str = "tarefa") -> str:
        """Apaga uma tarefa ou uma nota da lista sem marcar como feita ("tira o dentista da lista", "apaga a nota do wifi").

        Args:
            which: Palavras do item ou a posição dele na lista lida.
            kind: "tarefa" ou "nota".
        """
        await tool_status("remove_task", "running", which[:60])
        try:
            items = await asyncio.to_thread(load_items)
            target = find(which, notes(items) if _plain(kind).startswith("nota") else open_tasks(items))
            item = await asyncio.to_thread(remove_item, target["id"])
        except TaskError as exc:
            await tool_status("remove_task", "error", which[:60])
            return str(exc)
        await refresh()
        await tool_status("remove_task", "done", item["text"][:60])
        return f"Apaguei: {item['text']}."

    return [add_task, add_note, list_tasks, complete_task, remove_task]


# ───────────────────────── rotas do HUD ─────────────────────────


class NewItem(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    kind: str = Field(default="task", max_length=8)
    due: str | None = Field(default=None, max_length=40)


class DoneBody(BaseModel):
    done: bool


def build_tasks_router(enabled: Callable[[], bool], require_local: Callable[..., None], path: Callable[[], Path | None] = lambda: None) -> APIRouter:
    router = APIRouter(prefix="/api/tasks")

    def guard(request: Request) -> None:
        require_local(request, "A lista de tarefas")
        if not enabled():
            raise HTTPException(status_code=403, detail="As tarefas estão desligadas (JARVIS_ENABLE_DAY=false no .env).")

    def snapshot() -> dict[str, Any]:
        return card(load_items(path()))

    @router.get("")
    def read(request: Request) -> dict[str, Any]:
        require_local(request, "A lista de tarefas")
        return {"enabled": enabled(), **(snapshot() if enabled() else card([]))}

    @router.post("")
    def create(body: NewItem, request: Request) -> dict[str, Any]:
        guard(request)
        try:
            add_item(body.text, body.kind if body.kind in KINDS else "task", parse_due(body.due), path=path())
        except TaskError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"enabled": True, **snapshot()}

    @router.patch("/{item_id}")
    def toggle(item_id: str, body: DoneBody, request: Request) -> dict[str, Any]:
        guard(request)
        try:
            set_done(item_id[:32], body.done, path=path())
        except TaskError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"enabled": True, **snapshot()}

    @router.delete("/{item_id}")
    def delete(item_id: str, request: Request) -> dict[str, Any]:
        guard(request)
        try:
            remove_item(item_id[:32], path=path())
        except TaskError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"enabled": True, **snapshot()}

    return router
