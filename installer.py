"""Instalação de aplicativos pelo winget, sempre com confirmação por código.

O Jarvis lê páginas, notícias e emails, e um texto malicioso pode tentar dar ordens a
ele. Por isso a instalação segue um caminho fechado:

- Nada de shell nem texto livre: o winget roda com uma lista fixa de argumentos.
- A busca aceita só um termo curto com caracteres comuns, passado em ``--query``.
- Só é possível instalar um pacote que veio da última busca, com ID validado por regex
  e fonte ``winget`` ou ``msstore``. O comando é sempre::

      winget install --id <ID> --exact --source <fonte>
                     --accept-package-agreements --accept-source-agreements

- A instalação só começa quando a última fala do usuário é
  "confirmar instalação <código>" (veja ``confirmation.py``).
- Não existe desinstalação, atualização em massa nem outro subcomando do winget.
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import re
import shutil
import subprocess
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Literal

from livekit.agents import RunContext, function_tool

from confirmation import (
    confirmation_phrase,
    new_code,
    normalize_code,
    session_state,
    spoken_digits,
    strip_accents,
    wait_for_user_confirmation,
)
from hud import net_activity, show_card, tool_status

logger = logging.getLogger("jarvis-installer")

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SOURCES = ("winget", "msstore")
SOURCE_LABELS = {"winget": "winget", "msstore": "Microsoft Store"}
SOURCE_HOSTS = {"winget": "cdn.winget.microsoft.com", "msstore": "storeedgefd.dsx.mp.microsoft.com"}
PACKAGE_ID_PATTERNS = {
    # Publicador.Programa[.Variante], ex.: VideoLAN.VLC, Notepad++.Notepad++, Python.Python.3.12
    "winget": re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+-]*(?:\.[A-Za-z0-9_+-]+){1,7}$"),
    # IDs da Microsoft Store: 9NBDXK71NK08, XP9K09TBWNMDTN
    "msstore": re.compile(r"^[0-9A-Z]{12,14}$"),
}
MAX_ID_LENGTH = 128
QUERY_PATTERN = re.compile(r"^\w[\w .+#&'-]{0,59}$")
MAX_CANDIDATES = 5
SEARCH_COUNT = 10
SEARCH_TIMEOUT_S = 60
INSTALL_TIMEOUT_S = 30 * 60
SEARCH_KEY = "app_search"
PENDING_INSTALL_KEY = "pending_install"

NO_PACKAGES_FOUND = 0x8A150014
# Códigos de saída do winget (`winget error --input <código>`).
INSTALL_RESULTS: dict[int, tuple[bool, str]] = {
    0: (True, "instalado com sucesso"),
    0x8A15002B: (True, "já estava instalado e não há atualização disponível"),
    0x8A150061: (True, "já está instalado neste computador"),
    0x8A150109: (True, "instalado; reinicie o computador para concluir"),
    0x8A15010D: (False, "outra versão desse aplicativo já está instalada"),
    0x8A15010E: (False, "uma versão mais nova já está instalada"),
    0x8A15010C: (False, "a instalação foi cancelada no instalador ou na janela de permissão do Windows"),
    0x8A150077: (False, "a autenticação foi cancelada"),
    0x8A150101: (False, "o aplicativo está aberto; feche-o e tente de novo"),
    0x8A150103: (False, "há arquivos em uso; feche o aplicativo e tente de novo"),
    0x8A150102: (False, "outra instalação já está em andamento"),
    0x8A150105: (False, "não há espaço em disco suficiente"),
    0x8A150107: (False, "o instalador precisa de internet e a conexão falhou"),
    0x8A15010F: (False, "uma política do sistema bloqueou a instalação"),
    0x8A150011: (False, "o instalador baixado não confere com o manifesto, então foi descartado"),
    NO_PACKAGES_FOUND: (False, "o pacote não foi encontrado"),
}

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
DIVIDER = re.compile(r"^\s*-{8,}\s*$")

# Instalações em andamento (referência forte para o GC não coletar a tarefa).
_INSTALL_TASKS: set[asyncio.Task[None]] = set()


class InstallError(Exception):
    """User-facing failure of a search or install (message is safe to speak)."""


@dataclass(frozen=True, slots=True)
class Package:
    name: str
    id: str
    version: str | None
    source: str
    match: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


@dataclass(frozen=True, slots=True)
class InstallResult:
    ok: bool
    code: int | None
    message: str


# ───────────────────────── validação ─────────────────────────


def clean_query(query: str) -> str:
    term = re.sub(r"\s+", " ", query).strip()
    if not QUERY_PATTERN.match(term):
        raise InstallError(
            "Diga só o nome do aplicativo (letras, números e espaços, até 60 caracteres)."
        )
    return term


def is_valid_package_id(package_id: str, source: str) -> bool:
    pattern = PACKAGE_ID_PATTERNS.get(source)
    return bool(pattern and len(package_id) <= MAX_ID_LENGTH and pattern.match(package_id))


def winget_executable() -> str:
    path = shutil.which("winget")
    if not path:
        raise InstallError(
            "O winget não está disponível neste computador. Instale o 'Instalador de Aplicativo' "
            "(App Installer) pela Microsoft Store."
        )
    return path


def install_command(package: Package) -> list[str]:
    """The only install command Jarvis can run. Never a shell string."""
    if package.source not in SOURCES or not is_valid_package_id(package.id, package.source):
        raise InstallError("Pacote inválido: o ID ou a fonte não passaram na validação.")
    return [
        winget_executable(),
        "install",
        "--id",
        package.id,
        "--exact",
        "--source",
        package.source,
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]


# ───────────────────────── busca ─────────────────────────


def _char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _split_columns(line: str, starts: list[int]) -> list[str]:
    """Cut a table row by display column (winget pads wide CJK characters as 2 columns)."""
    cells = [""] * len(starts)
    column = 0
    for ch in line:
        index = bisect.bisect_right(starts, column) - 1
        if index >= 0:
            cells[index] += ch
        column += _char_width(ch)
    return [cell.strip() for cell in cells]


def parse_search_output(output: str, source: str) -> list[Package]:
    """Parse `winget search --source <fonte>`: colunas Nome, ID, Versão e (às vezes) Correspondência.

    The header is found by the dashed divider, so it works in any display language.
    Rows whose ID does not validate (for example, truncated with "…") are dropped.
    """
    lines = ANSI_ESCAPE.sub("", output).replace("\b", "").splitlines()
    divider = next((index for index, line in enumerate(lines) if DIVIDER.match(line)), None)
    if not divider:
        return []
    header = lines[divider - 1]
    starts = [match.start() for match in re.finditer(r"(?:^|(?<= ))\S", header)]
    if len(starts) < 3:
        return []

    packages: list[Package] = []
    for line in lines[divider + 1 :]:
        if not line.strip() or line.lstrip().startswith("<"):
            continue
        cells = _split_columns(line, starts)
        name, package_id, version = cells[0], cells[1], cells[2]
        if not name or not is_valid_package_id(package_id, source):
            continue
        packages.append(
            Package(
                name=name,
                id=package_id,
                version=None if version.lower() in {"", "unknown", "desconhecido"} else version,
                source=source,
                match=(cells[3] or None) if len(cells) > 3 else None,
            )
        )
    return packages


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


def rank_candidates(query: str, packages: list[Package]) -> list[Package]:
    """Best matches first: exact name/moniker, then prefix, then substring, then the rest.

    Ties keep winget's own order, with winget before the Microsoft Store.
    """
    target = _normalize(query)
    compact = target.replace(" ", "")

    def score(package: Package) -> int:
        name = _normalize(package.name)
        match = _normalize(package.match)
        if name == target or package.id.lower() == compact or match == f"moniker: {target}":
            return 0
        if name.startswith(target):
            return 1
        if target in name or compact in package.id.lower():
            return 2
        return 3

    unique: dict[tuple[str, str], Package] = {}
    for package in packages:
        unique.setdefault((package.source, package.id.lower()), package)
    return sorted(unique.values(), key=score)


def search_source(query: str, source: str) -> list[Package]:
    result = subprocess.run(
        [
            winget_executable(),
            "search",
            "--query",
            query,
            "--source",
            source,
            "--count",
            str(SEARCH_COUNT),
            "--accept-source-agreements",
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=SEARCH_TIMEOUT_S,
        creationflags=NO_WINDOW,
        check=False,
    )
    code = result.returncode & 0xFFFFFFFF
    if code == NO_PACKAGES_FOUND:
        return []
    packages = parse_search_output(result.stdout.decode("utf-8", "replace"), source)
    if code != 0 and not packages:
        raise InstallError(f"A busca na fonte {SOURCE_LABELS[source]} falhou (código {code:#x}).")
    return packages


async def search_all_sources(query: str) -> tuple[list[Package], list[str]]:
    outcomes = await asyncio.gather(
        *(asyncio.to_thread(search_source, query, source) for source in SOURCES),
        return_exceptions=True,
    )
    packages: list[Package] = []
    errors: list[str] = []
    for source, outcome in zip(SOURCES, outcomes):
        if isinstance(outcome, InstallError):
            errors.append(str(outcome))
        elif isinstance(outcome, BaseException):
            logger.warning("Busca no winget (%s) falhou: %r", source, outcome)
            errors.append(f"A busca na fonte {SOURCE_LABELS[source]} falhou.")
        else:
            packages.extend(outcome)
    return packages, errors


# ───────────────────────── instalação ─────────────────────────


def _last_output_line(output: bytes) -> str | None:
    lines = ANSI_ESCAPE.sub("", output.decode("utf-8", "replace")).splitlines()
    for line in reversed(lines):
        text = line.strip(" -\\|/█▒\t")
        if len(text) > 3:
            return text[:160]
    return None


def run_install(package: Package) -> InstallResult:
    command = install_command(package)
    logger.info("Instalando %s (%s) pelo winget.", package.id, package.source)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=INSTALL_TIMEOUT_S,
            creationflags=NO_WINDOW,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return InstallResult(
            False,
            None,
            "o winget não terminou em 30 minutos; confira no computador se a instalação concluiu",
        )

    code = result.returncode & 0xFFFFFFFF
    if code in INSTALL_RESULTS:
        ok, message = INSTALL_RESULTS[code]
        return InstallResult(ok, code, message)
    detail = _last_output_line(result.stdout)
    message = f"o winget falhou (código {code:#x})" + (f": {detail}" if detail else "")
    return InstallResult(False, code, message)


async def _install_and_report(context: RunContext, package: Package) -> None:
    await show_card("install", {"status": "installing", "package": package.to_dict()})
    await tool_status("confirm_app_install", "running", package.name)
    try:
        result = await asyncio.to_thread(run_install, package)
    except Exception:
        logger.exception("Erro inesperado ao instalar %s.", package.id)
        result = InstallResult(False, None, "erro inesperado ao rodar o winget")

    await show_card(
        "install",
        {
            "status": "installed" if result.ok else "failed",
            "package": package.to_dict(),
            "message": result.message,
        },
    )
    await tool_status("confirm_app_install", "done" if result.ok else "error", package.name)
    logger.info("Instalação de %s terminou: %s", package.id, result.message)
    try:
        context.session.generate_reply(
            instructions=(
                f"Avise o usuário, em uma frase curta, o resultado real da instalação de "
                f"{package.name}: {result.message}."
            )
        )
    except Exception:
        logger.warning("Não foi possível anunciar o fim da instalação de %s.", package.id)


def installs_running() -> bool:
    return any(not task.done() for task in _INSTALL_TASKS)


# ───────────────────────── ferramentas ─────────────────────────


def _describe(package: Package) -> str:
    version = package.version or "não informada"
    return f"{package.name} — ID {package.id}, versão {version}, fonte {package.source_label}"


@function_tool()
async def search_apps(context: RunContext, query: str) -> str:
    """Search apps to download/install on this Windows PC (winget and Microsoft Store).

    Use it when the user asks to download or install a program. Then tell the user the
    best match (name and source) and call prepare_app_install with its exact ID and source.

    Args:
        query: Just the app name, e.g. "VLC", "Spotify", "WhatsApp".
    """
    try:
        term = clean_query(query)
    except InstallError as exc:
        return str(exc)

    await tool_status("search_apps", "running", term)
    await net_activity(list(SOURCE_HOSTS.values()))
    packages, errors = await search_all_sources(term)
    if not packages and errors:
        await tool_status("search_apps", "error", term)
        return " ".join(dict.fromkeys(errors))

    candidates = rank_candidates(term, packages)[:MAX_CANDIDATES]
    state = session_state(context)
    state[SEARCH_KEY] = [package.to_dict() for package in candidates]
    await show_card(
        "install",
        {"status": "results", "query": term, "candidates": [package.to_dict() for package in candidates]},
    )
    await tool_status("search_apps", "done", term)
    if not candidates:
        return f"Nenhum aplicativo encontrado para '{term}' no winget nem na Microsoft Store."

    lines = [f"{index}. {_describe(package)}" for index, package in enumerate(candidates, start=1)]
    return (
        "Pacotes encontrados (também no painel do HUD):\n"
        + "\n".join(lines)
        + "\nConfirme com o usuário qual instalar (prefira o do fabricante oficial) e chame "
        "prepare_app_install com o ID e a fonte exatos. Nada foi instalado ainda."
    )


@function_tool()
async def prepare_app_install(
    context: RunContext,
    package_id: str,
    source: Literal["winget", "msstore"] | None = None,
) -> str:
    """Prepare installing one package from the last search_apps result. Does NOT install yet.

    It creates a 6-digit code. Tell the user the code digit by digit, say it is also on the
    HUD install panel, and explain that to install they must say "confirmar instalação" + code.

    Args:
        package_id: The exact ID from search_apps (e.g. "VideoLAN.VLC").
        source: "winget" or "msstore", as listed in search_apps.
    """
    state = session_state(context)
    wanted_id = package_id.strip().lower()
    chosen = next(
        (
            item
            for item in state.get(SEARCH_KEY) or []
            if item["id"].lower() == wanted_id and (source is None or item["source"] == source)
        ),
        None,
    )
    if chosen is None:
        return (
            "Esse pacote não está na última busca. Use search_apps primeiro e escolha um dos "
            "resultados (ID e fonte exatos)."
        )
    package = Package(**chosen)
    if not is_valid_package_id(package.id, package.source):
        return "Pacote inválido: o ID ou a fonte não passaram na validação."

    code = new_code()
    state[PENDING_INSTALL_KEY] = {"code": code, "package": package.to_dict()}
    await show_card("install", {"status": "pending", "package": package.to_dict(), "code": code})
    logger.info("Instalação preparada: %s (%s).", package.id, package.source)
    return (
        f"Instalação preparada (ainda NÃO instalada): {_describe(package)}.\n"
        f"Código de confirmação: {code} (fale dígito por dígito: {spoken_digits(code)}). "
        "O código também aparece no painel de instalação do HUD.\n"
        f"Para instalar, o usuário precisa dizer: {confirmation_phrase('install', code)}. "
        "'Pode instalar' ou 'sim' não bastam: nesse caso repita o código e a frase."
    )


@function_tool()
async def confirm_app_install(context: RunContext, code: str) -> str:
    """Install the prepared app, only after the user said "confirmar instalação <código>".

    The install runs in the background; Jarvis announces the real result when it ends.

    Args:
        code: The 6-digit confirmation code the user said.
    """
    state = session_state(context)
    pending = state.get(PENDING_INSTALL_KEY)
    if not pending:
        return "Não há nenhuma instalação pendente. Use search_apps e prepare_app_install primeiro."
    if installs_running():
        return "Já existe uma instalação em andamento; espere ela terminar."

    expected_code = pending["code"]
    if normalize_code(code) != expected_code:
        logger.warning("Confirmação de instalação rejeitada por código inválido.")
        return "Código de confirmação inválido. Nada foi instalado."

    confirmed, _ = await wait_for_user_confirmation(context, "install", expected_code)
    if not confirmed:
        logger.warning("Confirmação de instalação rejeitada: a última fala não tinha a frase com o código.")
        return (
            "Instalação bloqueada: a última fala do usuário não foi a confirmação com o código. "
            f"Repita o código ({spoken_digits(expected_code)}) e peça para ele dizer: "
            f"{confirmation_phrase('install', expected_code)}."
        )

    package = Package(**pending["package"])
    state[PENDING_INSTALL_KEY] = None
    task = asyncio.create_task(_install_and_report(context, package))
    _INSTALL_TASKS.add(task)
    task.add_done_callback(_INSTALL_TASKS.discard)
    return (
        f"Instalação de {package.name} iniciada pelo winget (ainda não concluída). Pode aparecer "
        "uma janela de permissão do Windows para o usuário aprovar. O resultado aparece no painel "
        "e será anunciado quando terminar."
    )


@function_tool()
async def cancel_app_install(context: RunContext) -> str:
    """Cancel the prepared (not yet confirmed) app install. It cannot stop one already running."""
    state = session_state(context)
    pending = state.get(PENDING_INSTALL_KEY)
    if not pending:
        return "Não há nenhuma instalação pendente para cancelar."

    state[PENDING_INSTALL_KEY] = None
    await show_card("install", {"status": "cancelled", "package": pending["package"]})
    logger.info("Instalação pendente cancelada.")
    return "Instalação cancelada; nada foi instalado."


def build_install_tools() -> list[Any]:
    return [search_apps, prepare_app_install, confirm_app_install, cancel_app_install]
