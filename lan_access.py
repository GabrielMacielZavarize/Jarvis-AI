"""Acesso pelo celular na rede de casa (LAN-26).

Com ``python jarvis.py --lan`` o servidor do HUD continua em http://127.0.0.1:8000 para o PC e
também atende https://<ip-do-pc>:8000 na rede local. Fora do próprio PC nada responde sem um
aparelho pareado:

* o HUD do PC mostra um código de 6 dígitos (e um QR) válido por poucos minutos;
* o celular troca o código por um token próprio, guardado num cookie HttpOnly;
* o PC lista os aparelhos pareados e revoga qualquer um, o que corta na hora até o feed da câmera.

Só o hash SHA-256 dos tokens fica em ``aparelhos.json``. O HTTPS usa uma autoridade certificadora
local (``.jarvis-tls/``) restrita a IPs privados e nomes ``.local``: instalada no celular, tira o
aviso de certificado sem permitir que ela assine qualquer outro site.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import ipaddress
import json
import secrets
import socket
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DEVICES_FILE = ROOT / "aparelhos.json"
TLS_DIR = ROOT / ".jarvis-tls"
COOKIE_NAME = "jarvis_aparelho"
# Chrome limita cookies a 400 dias.
COOKIE_MAX_AGE_S = 400 * 24 * 3600
CODE_DIGITS = 6
CODE_TTL_S = 300.0
# Tentativas erradas que queimam o código atual (o PC precisa gerar outro).
MAX_CODE_ATTEMPTS = 5
MAX_DEVICES = 20
LAST_SEEN_WRITE_S = 60.0
# Peers que contam como "o próprio PC". "testclient" é o peer falso do TestClient do Starlette;
# uma conexão real sempre tem um IP como peer.
TEST_PEER = "testclient"
# Rotas que um aparelho sem token pode chamar: saber se está pareado, parear e baixar o certificado.
PUBLIC_API = {("GET", "/api/lan/me"), ("POST", "/api/lan/pair"), ("GET", "/api/lan/ca.crt")}
UNPAIRED = "Aparelho não pareado. Abra o HUD no PC e use o código de pareamento."

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class PairingError(ValueError):
    pass


class DeviceRevoked(Exception):
    """O aparelho foi revogado no meio de uma resposta longa (câmera, eventos)."""


@dataclass
class Device:
    id: str
    name: str
    token_hash: str
    created_at: float
    last_seen: float

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "created_at": self.created_at, "last_seen": self.last_seen}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(raw: str | None) -> str:
    name = " ".join("".join(ch for ch in (raw or "") if ch.isprintable()).split())[:40]
    return name or "Celular"


class DeviceRegistry:
    """Código de pareamento da vez e aparelhos pareados (persistidos em ``aparelhos.json``)."""

    def __init__(self, path: Path | None = DEVICES_FILE, *, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._code: str | None = None
        self._code_expires = 0.0
        self._attempts = 0
        self._devices: dict[str, Device] = {}
        self._dirty_seen: float = 0.0
        self._load()

    # --- Código ----------------------------------------------------------------------------------

    def start_pairing(self) -> dict[str, Any]:
        """Novo código (o anterior deixa de valer)."""
        with self._lock:
            self._code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
            self._code_expires = self._clock() + CODE_TTL_S
            self._attempts = 0
            return self._pairing_state()

    def stop_pairing(self) -> None:
        with self._lock:
            self._code = None

    def pairing_state(self) -> dict[str, Any]:
        with self._lock:
            return self._pairing_state()

    def pair(self, code: str, name: str | None) -> tuple[Device, str]:
        """Troca o código por um token novo; erra demais e o código é queimado."""
        with self._lock:
            if not self._code_valid():
                raise PairingError("Nenhum código ativo. Gere um no HUD do PC (painel Celular).")
            if not secrets.compare_digest(code.strip().encode(), self._code.encode()):  # type: ignore[union-attr]
                self._attempts += 1
                if self._attempts >= MAX_CODE_ATTEMPTS:
                    self._code = None
                    raise PairingError("Código errado vezes demais. Gere um novo código no PC.")
                raise PairingError("Código incorreto.")
            if len(self._devices) >= MAX_DEVICES:
                raise PairingError("Limite de aparelhos pareados atingido. Revogue algum no PC.")
            self._code = None
            token = secrets.token_urlsafe(32)
            now = self._clock()
            device = Device(id=secrets.token_hex(6), name=clean_name(name), token_hash=_hash(token), created_at=now, last_seen=now)
            self._devices[device.id] = device
            self._save()
            return device, token

    # --- Aparelhos -------------------------------------------------------------------------------

    def authenticate(self, token: str | None) -> Device | None:
        if not token:
            return None
        digest = _hash(token)
        with self._lock:
            for device in self._devices.values():
                if secrets.compare_digest(device.token_hash, digest):
                    now = self._clock()
                    if now - device.last_seen > LAST_SEEN_WRITE_S:
                        device.last_seen = now
                        self._save()
                    return device
        return None

    def is_active(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._devices

    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [device.public() for device in sorted(self._devices.values(), key=lambda d: d.created_at)]

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            removed = self._devices.pop(device_id, None) is not None
            if removed:
                self._save()
            return removed

    # --- Internos --------------------------------------------------------------------------------

    def _code_valid(self) -> bool:
        return self._code is not None and self._clock() < self._code_expires

    def _pairing_state(self) -> dict[str, Any]:
        if not self._code_valid():
            return {"code": None, "expires_in": 0}
        return {"code": self._code, "expires_in": max(0, round(self._code_expires - self._clock()))}

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw.get("devices", []):
                device = Device(**{key: item[key] for key in Device.__dataclass_fields__})
                self._devices[device.id] = device
        except (OSError, ValueError, KeyError, TypeError):
            # Arquivo corrompido: melhor exigir novo pareamento do que aceitar lixo.
            self._devices = {}

    def _save(self) -> None:
        if self._path is None:
            return
        payload = {"devices": [asdict(device) for device in self._devices.values()]}
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)


# --- Quem está pedindo ------------------------------------------------------------------------------


def is_loopback_peer(host: str | None) -> bool:
    if host == TEST_PEER:
        return True
    try:
        return ipaddress.ip_address((host or "").split("%")[0]).is_loopback
    except ValueError:
        return False


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _token_from(scope: Scope) -> str | None:
    auth = _header(scope, b"authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookies = _header(scope, b"cookie") or ""
    for part in cookies.split(";"):
        key, _, value = part.strip().partition("=")
        if key == COOKIE_NAME:
            return value
    return None


def device_of(request: Request) -> Device | None:
    """Aparelho pareado que fez o pedido (None para o próprio PC)."""
    return request.scope.get("state", {}).get("lan_device")


def is_local(request: Request) -> bool:
    return is_loopback_peer(request.client.host if request.client else None)


def _is_static(path: str, web_dist: Path) -> bool:
    """Arquivos do HUD compilado (sem dados): o celular precisa deles para mostrar o pareamento."""
    if path in ("/", "/index.html"):
        return True
    try:
        target = (web_dist / path.lstrip("/")).resolve()
        return target.is_relative_to(web_dist.resolve()) and target.is_file()
    except (OSError, ValueError):
        return False


class LanGuard:
    """Middleware ASGI: o próprio PC passa como antes; qualquer outro peer precisa de um aparelho
    pareado, exceto para os arquivos do HUD e as rotas de pareamento. Revogar um aparelho corta
    também as respostas em andamento (feed da câmera, eventos da palavra de ativação)."""

    def __init__(self, app: ASGIApp, registry: Callable[[], DeviceRegistry], web_dist: Path) -> None:
        self.app = app
        self.registry = registry
        self.web_dist = web_dist

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        if is_loopback_peer(client[0] if client else None):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        method, path = scope["method"], scope["path"]
        site = _header(scope, b"sec-fetch-site")
        if site not in (None, "same-origin", "none"):
            await _deny(send, 403, "Pedido de outro site bloqueado.")
            return
        device = self.registry().authenticate(_token_from(scope))
        if device is None:
            public = (method, path) in PUBLIC_API or (method in ("GET", "HEAD") and _is_static(path, self.web_dist))
            if not public:
                await _deny(send, 401, UNPAIRED)
                return
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", {})["lan_device"] = device
        await self._run_while_active(device, scope, receive, send)

    async def _run_while_active(self, device: Device, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.body" and message.get("more_body") and not self.registry().is_active(device.id):
                raise DeviceRevoked(device.id)
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, guarded_send)
        except BaseException as exc:
            if not _caused_by_revocation(exc):
                raise
            if started:
                await send({"type": "http.response.body", "body": b"", "more_body": False})


def _caused_by_revocation(exc: BaseException) -> bool:
    if isinstance(exc, DeviceRevoked):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return all(_caused_by_revocation(inner) for inner in exc.exceptions)
    return exc.__cause__ is not None and _caused_by_revocation(exc.__cause__)


async def _deny(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")],
        }
    )
    await send({"type": "http.response.body", "body": body})


# --- Rotas ------------------------------------------------------------------------------------------


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str | None = Field(default=None, max_length=80)


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _require_pc(request: Request) -> None:
    # Host também conta: uma página com DNS rebinding chega pelo loopback com outro nome.
    host = (request.url.hostname or "").strip("[]").lower()
    if not is_local(request) or host not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Só o próprio PC gerencia os aparelhos pareados.")
    site = request.headers.get("sec-fetch-site")
    if site not in (None, "same-origin", "none"):
        raise HTTPException(status_code=403, detail="Pedido de outro site bloqueado.")


def build_lan_router(registry: Callable[[], DeviceRegistry], lan_urls: Callable[[], list[str]], ca_file: Callable[[], Path | None]) -> APIRouter:
    router = APIRouter(prefix="/api/lan")

    def info() -> dict[str, Any]:
        urls = lan_urls()
        state = registry().pairing_state()
        link = f"{urls[0]}/#parear={state['code']}" if urls and state["code"] else None
        return {"enabled": bool(urls), "urls": urls, "pair_url": link, **state, "devices": registry().devices()}

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        device = device_of(request)
        return {
            "local": is_local(request),
            "paired": device is not None,
            "device": device.public() if device else None,
        }

    @router.post("/pair")
    def pair(body: PairRequest, request: Request, response: Response) -> dict[str, Any]:
        try:
            device, token = registry().pair(body.code, body.name)
        except PairingError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=COOKIE_MAX_AGE_S,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
        )
        return {"paired": True, "device": device.public()}

    @router.get("/ca.crt")
    def ca_certificate() -> Response:
        path = ca_file()
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="O modo rede local (--lan) não está ligado.")
        return Response(
            path.read_bytes(),
            media_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": 'attachment; filename="jarvis-ca.crt"'},
        )

    @router.get("/info")
    def lan_info(request: Request) -> dict[str, Any]:
        _require_pc(request)
        return info()

    @router.post("/pairing")
    def new_code(request: Request) -> dict[str, Any]:
        _require_pc(request)
        if not lan_urls():
            raise HTTPException(status_code=409, detail="Ligue o modo rede local: python jarvis.py --lan")
        registry().start_pairing()
        return info()

    @router.delete("/pairing")
    def cancel_code(request: Request) -> dict[str, Any]:
        _require_pc(request)
        registry().stop_pairing()
        return info()

    @router.get("/qr.svg")
    def qr(request: Request) -> Response:
        _require_pc(request)
        link = info()["pair_url"]
        if link is None:
            raise HTTPException(status_code=404, detail="Nenhum código de pareamento ativo.")
        import segno

        svg = io.BytesIO()
        segno.make(link, error="m").save(svg, kind="svg", scale=6, dark="#5ff4ff", light="#02060b", border=2)
        return Response(svg.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    @router.delete("/devices/{device_id}")
    def revoke(device_id: str, request: Request) -> dict[str, Any]:
        _require_pc(request)
        if not registry().revoke(device_id):
            raise HTTPException(status_code=404, detail="Aparelho não encontrado.")
        return info()

    return router


# --- Rede e certificados ----------------------------------------------------------------------------


def lan_addresses() -> list[str]:
    """IPv4 privados deste PC; o da rota padrão (o Wi-Fi/cabo de casa) vem primeiro."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # UDP não envia nada: só escolhe a interface de saída
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(str(info[4][0]))
    except OSError:
        pass
    # Só as faixas que a CA local pode assinar (PERMITTED_NETWORKS): é a rede de casa.
    home = [ipaddress.ip_network(net) for net in PERMITTED_NETWORKS if not net.startswith("127.")]
    result: list[str] = []
    for raw in found:
        ip = ipaddress.ip_address(raw)
        if any(ip in net for net in home) and raw not in result:
            result.append(raw)
    return result


def lan_url(ip: str, port: int) -> str:
    return f"https://{ip}:{port}"


# A CA só vale para estes destinos (NameConstraints): mesmo se a chave vazar, não assina outros sites.
PERMITTED_NETWORKS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
PERMITTED_DNS = ("local", "localhost")
CA_DAYS = 3650
# iOS e Chrome recusam certificados de servidor com mais de 825 dias.
SERVER_DAYS = 800


@dataclass
class TlsFiles:
    ca_cert: Path
    cert: Path
    key: Path


def ensure_certificates(ips: list[str], directory: Path = TLS_DIR, hostname: str | None = None) -> TlsFiles:
    """CA local (criada uma vez) e certificado do servidor para os IPs atuais (refeito se mudarem)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    directory.mkdir(parents=True, exist_ok=True)
    files = TlsFiles(ca_cert=directory / "jarvis-ca.crt", cert=directory / "servidor.crt", key=directory / "servidor.key")
    ca_key_file = directory / "jarvis-ca.key"
    now = dt.datetime.now(dt.timezone.utc)
    pem = serialization.Encoding.PEM

    def write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
        path.write_bytes(key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        try:
            path.chmod(0o600)
        except OSError:
            pass

    if files.ca_cert.exists() and ca_key_file.exists():
        ca_cert = x509.load_pem_x509_certificate(files.ca_cert.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_file.read_bytes(), password=None)
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis CA local"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Jarvis")])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(
                x509.NameConstraints(
                    permitted_subtrees=[x509.IPAddress(ipaddress.ip_network(net)) for net in PERMITTED_NETWORKS]
                    + [x509.DNSName(name) for name in PERMITTED_DNS],
                    excluded_subtrees=None,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        write_key(ca_key_file, ca_key)
        files.ca_cert.write_bytes(ca_cert.public_bytes(pem))

    host = (hostname or socket.gethostname()).split(".")[0].lower()
    wanted_ips = sorted({*ips, "127.0.0.1"})
    wanted_dns = sorted({"localhost", f"{host}.local"})
    if files.cert.exists() and files.key.exists():
        current = x509.load_pem_x509_certificate(files.cert.read_bytes())
        try:
            san = current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            same = (
                sorted(str(ip) for ip in san.get_values_for_type(x509.IPAddress)) == wanted_ips
                and sorted(san.get_values_for_type(x509.DNSName)) == wanted_dns
                and current.issuer == ca_cert.subject
                and current.not_valid_after_utc - now > dt.timedelta(days=30)
            )
        except x509.ExtensionNotFound:
            same = False
        if same:
            return files

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Jarvis ({host})")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=SERVER_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(name) for name in wanted_dns] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in wanted_ips]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)  # type: ignore[arg-type]
        .sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]
    )
    write_key(files.key, key)
    files.cert.write_bytes(cert.public_bytes(pem))
    return files
