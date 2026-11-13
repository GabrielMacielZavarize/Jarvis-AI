"""Checagem das fontes externas (`python doctor.py --fontes`).

As consultas do Jarvis (Olho de Deus, cotações, clima, teste de internet) foram escritas lendo a
documentação de cada serviço. Aqui cada fonte é consultada de verdade, com um valor conhecido, pelas
MESMAS funções de leitura dos módulos: se um serviço mudar o formato da resposta, a função deixa de
achar o campo e a fonte aparece como falha.

Cada fonte termina em um de três estados:

- ``ok``: respondeu e o formato é o esperado;
- ``falha``: respondeu, mas o formato mudou, o servidor devolveu erro ou o valor conhecido sumiu;
- ``sem rede``: não deu para falar com o servidor (sem internet, tempo esgotado, conexão recusada).

Sai com 0 quando tudo está ok, 1 se alguma fonte falhou e 2 se nenhuma falhou mas alguma ficou sem
rede. Os volumes são mínimos: o teste de velocidade baixa 200 KB e sobe 50 KB.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

OK = "ok"
FAILED = "falha"
NO_NETWORK = "sem rede"
IGNORED = "ignorada"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_NETWORK = 2

# Volume mínimo do teste de velocidade: o suficiente para provar que o servidor responde no formato certo.
SPEED_DOWN_BYTES = 200_000
SPEED_UP_BYTES = 50_000
WORKERS = 6
RETRY_DELAY_S = 2.0

# Um perfil que existe em cada site de osint.SITES. Se um deles sumir, troque aqui (e confira no
# navegador): a fonte aparece como falha dizendo que o perfil de teste não foi achado.
KNOWN_USERS: dict[str, str] = {
    "GitHub": "torvalds",
    "GitLab": "sytses",
    "Codeberg": "Gusted",
    "Hugging Face": "julien-c",
    "Docker Hub": "jpetazzo",
    "npm": "sindresorhus",
    "DEV": "ben",
    "Hacker News": "pg",
    "Codewars": "jhoffner",
    "Keybase": "chris",
    "Reddit": "spez",
    "Bluesky": "jay",
    "Mastodon": "Gargron",
    "Lichess": "thibault",
    "Chess.com": "hikaru",
    "Duolingo": "duolingo",
    "Scratch": "griffpatch",
}
# Nome que ninguém tem: o site tem que dizer que o perfil não existe.
ABSENT_USER = "jarvisdoctorsemperfil9x7q2k"

PWNED_PREFIX = "5BAA6"  # SHA-1 de "password" começa com 5BAA6
PWNED_SUFFIX = "1E4C9B93F3F0682250B6CF8331B7EE68FD8"
# Um endereço de teste (domínio reservado example.com): nunca o email de uma pessoa de verdade.
BREACH_TEST_EMAIL = "test@example.com"


class SourceFailure(Exception):
    """A fonte respondeu, mas não do jeito que o código lê."""


@dataclass(frozen=True)
class SourceResult:
    group: str
    name: str
    status: str
    detail: str
    # Quando ``ignorada``, o estado de verdade (para mostrar ao lado).
    real_status: str = ""


class Probe:
    """Embrulha o ``requests`` (ou um substituto) e anota o que aconteceu, para dar o motivo da falha.

    As funções dos módulos engolem erros de rede e devolvem ``None``; o Probe é quem sabe que foi a
    rede, e que status o servidor respondeu.
    """

    def __init__(self, http: Any = requests, connect: Callable[..., Any] = socket.create_connection) -> None:
        self._http = http
        self._connect = connect
        self.statuses: list[int] = []
        self.network_errors: list[str] = []

    def _note_error(self, exc: BaseException) -> None:
        reason = str(exc) or type(exc).__name__
        host = re.search(r"host='([^']+)'", reason)
        # O texto do requests repete a URL inteira; o que ajuda é o tipo do erro e o servidor.
        self.network_errors.append(f"{type(exc).__name__} ao falar com {host.group(1)}" if host else _short(f"{type(exc).__name__}: {reason}", 140))

    def get(self, url: str, **kwargs: Any) -> Any:
        try:
            response = self._http.get(url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            self._note_error(exc)
            raise
        self.statuses.append(response.status_code)
        return response

    def post(self, url: str, **kwargs: Any) -> Any:
        try:
            response = self._http.post(url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            self._note_error(exc)
            raise
        self.statuses.append(response.status_code)
        return response

    def connect(self, address: tuple[str, int], timeout: float = 2.0) -> Any:
        try:
            return self._connect(address, timeout=timeout)
        except OSError as exc:
            self._note_error(exc)
            raise

    @property
    def last_status(self) -> int | None:
        return self.statuses[-1] if self.statuses else None

    def why_empty(self) -> str:
        """Motivo de uma função ter devolvido ``None``: o status que o servidor deu, ou nada."""
        if self.statuses and self.statuses[-1] != 200:
            return f"o servidor respondeu {self.statuses[-1]}"
        if self.statuses:
            return "o servidor respondeu 200, mas sem os dados esperados"
        return "o servidor não respondeu"


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _need(condition: Any, message: str) -> None:
    if not condition:
        raise SourceFailure(message)


def _rows(result: dict[str, Any]) -> dict[str, str]:
    """Todas as linhas “rótulo: valor” de um resultado do Olho de Deus."""
    rows: dict[str, str] = {}
    for section in result.get("sections") or []:
        for label, value in section.get("rows") or []:
            rows.setdefault(label, value)
    return rows


def _need_rows(rows: dict[str, str], *labels: str) -> None:
    missing = [label for label in labels if not rows.get(label)]
    _need(not missing, "campo(s) que a leitura não achou mais na resposta: " + ", ".join(missing))


def _list(result: dict[str, Any], title: str) -> dict[str, Any] | None:
    return next((item for item in result.get("lists") or [] if item.get("title") == title), None)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ───────────────────────── Olho de Deus ─────────────────────────


def check_ip(probe: Probe) -> str:
    import osint

    result = osint.lookup_ip("8.8.8.8", probe)
    rows = _rows(result)
    _need_rows(rows, "País", "Provedor", "ASN")
    _need(rows["ASN"] == "AS15169", f"o ASN do 8.8.8.8 devia ser AS15169, veio {rows['ASN']}")
    _need(result.get("point"), "a resposta não trouxe latitude e longitude")
    return f"{rows['Provedor']}, {rows['ASN']}, {rows['País']}"


def check_internetdb(probe: Probe) -> str:
    import osint

    info = osint.internetdb(probe, "8.8.8.8")
    _need(info["known"], "o InternetDB respondeu 404 para o 8.8.8.8, que sempre teve varredura: o endereço da API pode ter mudado")
    _need(info["ports"], "nenhuma porta lida na resposta do InternetDB: o formato do campo “ports” pode ter mudado")
    return f"{len(info['ports'])} porta(s), {len(info['hostnames'])} nome(s) de host, {len(info['vulns'])} CVE(s) para o 8.8.8.8"


def urlhaus_key() -> str | None:
    """A chave do URLhaus: JARVIS_URLHAUS_KEY no ambiente (o job semanal) ou no .env deste PC."""
    key = os.environ.get("JARVIS_URLHAUS_KEY")
    if key is None:
        try:
            from dotenv import dotenv_values

            key = dotenv_values(Path(__file__).resolve().parent / ".env").get("JARVIS_URLHAUS_KEY")
        except Exception:
            key = None
    key = (key or "").strip()
    return None if not key or key.lower().startswith(("your-", "sua-", "seu-")) else key


def check_urlhaus(probe: Probe, key: str) -> str:
    import osint

    # example.com não é malware: a resposta certa é "no_results". Prova que a chave vale e que o
    # formato do status ainda é o que a leitura espera; o formato de um endereço listado não dá para provar aqui.
    found = osint.urlhaus_check(probe, "https://example.com/", key)
    if found["listed"]:
        return "chave aceita; o endereço de teste veio listado (inesperado), mas o formato foi lido"
    return "chave aceita; o endereço de teste (example.com) veio “não listado”; o formato de um endereço listado não foi visto"


def check_dns(probe: Probe) -> str:
    import osint

    records = osint.dns_records(probe, "google.com", "A")
    _need(records, "nenhum registro A para google.com")
    for record in records:
        try:
            ipaddress.ip_address(record)
        except ValueError:
            raise SourceFailure(f"registro A que não é um IP: “{record}”") from None
    return f"{len(records)} registro(s) A para google.com"


def check_rdap(probe: Probe) -> str:
    import osint

    info = osint.rdap_domain(probe, "google.com")
    _need(info is not None, f"não veio o registro do domínio ({probe.why_empty()})")
    missing = [label for key, label in (("created", "criação"), ("expires", "vencimento"), ("registrar", "registrador"), ("nameservers", "servidores de nome")) if not info.get(key)]
    _need(not missing, "campo(s) que a leitura não achou mais: " + ", ".join(missing))
    _need(osint._age_days(info["created"]) is not None, f"a data de criação veio num formato que não leio: {info['created']}")
    return f"criado em {osint._date(info['created'])}, registrador {info['registrar']}"


def check_crtsh(probe: Probe) -> str:
    import osint

    names = osint.certificate_subdomains(probe, "iana.org")
    _need(names, "nenhum subdomínio de iana.org nos certificados públicos")
    return f"{len(names)} subdomínio(s) de iana.org"


def check_cnpj(probe: Probe) -> str:
    import osint

    result = osint.lookup_cnpj("00.000.000/0001-91", probe)
    rows = _rows(result)
    _need_rows(rows, "Razão social", "Aberta em", "Natureza jurídica", "Atividade principal", "Logradouro", "Cidade")
    _need("BANCO DO BRASIL" in rows["Razão social"].upper(), f"a razão social do CNPJ de teste veio “{rows['Razão social']}”")
    verdict = result.get("verdict")
    _need(verdict and verdict["level"] == "ok", "a situação cadastral não veio como ativa")
    return f"{rows['Razão social']}, {rows['Cidade']}"


def check_cep(probe: Probe) -> str:
    import osint

    result = osint.lookup_cep("01310-100", probe)
    rows = _rows(result)
    _need_rows(rows, "Rua", "Bairro", "Cidade")
    _need("paulista" in rows["Rua"].lower(), f"a rua do CEP de teste veio “{rows['Rua']}”")
    _need("sao paulo" in osint.strip_accents(rows["Cidade"]).lower(), f"a cidade do CEP de teste veio “{rows['Cidade']}”")
    return f"{rows['Rua']}, {rows['Cidade']}"


def check_ddd(probe: Probe) -> str:
    import osint

    result = osint.lookup_ddd("11", probe)
    _need(result["summary"].startswith("SP"), f"o estado do DDD 11 veio “{result['summary']}”")
    cities = _list(result, "Cidades")
    _need(cities and cities["total"] >= 10, "a lista de cidades do DDD 11 veio vazia ou curta")
    # A BrasilAPI escreve as cidades em maiúsculas e sem acento (“SAO PAULO”).
    _need(any(osint.strip_accents(city).lower() == "sao paulo" for city in cities["items"]), "São Paulo não está nas cidades do DDD 11")
    return f"SP, {cities['total']} cidades"


def check_breaches(probe: Probe) -> str:
    import osint

    result = osint.lookup_email(BREACH_TEST_EMAIL, probe)
    verdict = result.get("verdict")
    _need(verdict, "a consulta não terminou em um veredito")
    if probe.last_status == 200:
        breaches = _list(result, "Vazamentos")
        _need(breaches and breaches["items"], "o serviço respondeu 200, mas nenhum vazamento foi lido: o formato pode ter mudado")
        return f"{breaches['total']} vazamento(s) para o endereço de teste"
    # 404 é a resposta de “nenhum vazamento”: prova que o endereço responde, não o formato do 200.
    return "endereço de teste sem vazamentos (404); o formato da resposta 200 não foi visto"


def check_pwned(probe: Probe) -> str:
    import osint

    pairs = osint.pwned_range(PWNED_PREFIX, probe)
    _need(pairs, "nenhum sufixo lido na resposta")
    found = {suffix: count for suffix, count in pairs}
    _need(PWNED_SUFFIX in found, f"o sufixo da senha “password” não está no prefixo {PWNED_PREFIX}")
    _need(found[PWNED_SUFFIX] > 1000, "a contagem da senha “password” veio baixa demais")
    return f"{len(pairs)} sufixos no prefixo {PWNED_PREFIX}"


def check_profile(site: tuple[str, str, str, str]) -> Callable[[Probe], str]:
    name = site[0]

    def check(probe: Probe) -> str:
        import osint

        known = KNOWN_USERS.get(name)
        _need(known, f"falta um usuário de teste para {name} em fontes.KNOWN_USERS")
        _, _, exists = osint.check_site(site, known, probe)
        if exists is not True:
            if exists is None:
                raise SourceFailure(f"não deu para saber se “{known}” existe ({probe.why_empty()})")
            raise SourceFailure(f"o perfil de teste “{known}” não foi achado (a conta pode ter sumido ou o formato mudou)")
        _, _, exists = osint.check_site(site, ABSENT_USER, probe)
        if exists is True:
            raise SourceFailure("um nome que ninguém tem apareceu como perfil existente: a resposta do site mudou e daria falso positivo")
        _need(exists is False, f"o site não disse que um nome que ninguém tem não existe ({probe.why_empty()}; pode ser bloqueio ou página de verificação)")
        return f"“{known}” existe e um nome inventado não"

    return check


# ───────────────────────── cotações ─────────────────────────


def check_quotes(probe: Probe) -> str:
    import quotes

    quotes._cache.clear()  # a cotação guardada há menos de um minuto esconderia a consulta de verdade
    items = quotes.quotes(["USD", "BTC"], probe)
    _need(len(items) == 2, f"vieram {len(items)} cotações em vez de 2")
    for item in items:
        _need(item["value"] > 0, f"{item['code']}: cotação zero ou negativa")
        for key, label in (("change_pct", "variação do dia"), ("high", "máxima"), ("low", "mínima")):
            _need(_number(item[key]), f"{item['code']}: a leitura não achou mais a {label}")
        _need(item["at"], f"{item['code']}: a leitura não achou mais a hora da cotação")
    usd = next(item for item in items if item["code"] == "USD")
    return f"dólar R$ {usd['value']:.2f}, {', '.join(item['code'] for item in items)} com variação, máxima e mínima"


# ───────────────────────── clima ─────────────────────────


def check_geocoding(probe: Probe) -> str:
    import tools

    try:
        place = tools._geocode("São Paulo", probe)
    except tools.CityNotFoundError:
        raise SourceFailure("a geocodificação não achou São Paulo: a lista “results” veio vazia ou mudou de nome") from None
    _need(_number(place["latitude"]) and _number(place["longitude"]), "latitude e longitude não vieram como número")
    _need(place.get("name"), "a geocodificação não trouxe o nome do lugar")
    _need(-35 < place["latitude"] < -10 and -75 < place["longitude"] < -30, f"São Paulo veio em {place['latitude']}, {place['longitude']}")
    return f"{place['name']} em {place['latitude']:.2f}, {place['longitude']:.2f}"


def check_forecast(probe: Probe) -> str:
    import tools

    try:
        summary, card = tools._fetch_weather("São Paulo", probe)
    except tools.CityNotFoundError:
        raise SourceFailure("a geocodificação não achou São Paulo: a lista “results” veio vazia ou mudou de nome") from None
    current = card["current"]
    for key in ("temperature", "humidity", "wind", "code"):
        _need(_number(current[key]), f"clima de agora: “{key}” não veio como número")
    _need(len(card["daily"]) == 7, f"a previsão veio com {len(card['daily'])} dias em vez de 7")
    today = card["daily"][0]
    _need(_number(today["max"]) and _number(today["min"]), "a previsão de hoje veio sem máxima e mínima")
    _need(len(card["hourly"]) == tools.HOURLY_POINTS, f"a previsão por hora veio com {len(card['hourly'])} pontos em vez de {tools.HOURLY_POINTS}")
    return summary


def check_ambient(probe: Probe) -> str:
    import weather

    now = weather.current_conditions(-23.55, -46.63, probe)
    _need(_number(now["temperature"]), "a temperatura de agora não veio como número")
    _need(_number(now["max"]) and _number(now["min"]), "o modo ambiente ficou sem máxima e mínima")
    _need(_number(now["code"]), "o código de tempo não veio como número")
    return f"{now['temperature']}°C, {now['label']}"


# ───────────────────────── internet ─────────────────────────


def check_latency(probe: Probe) -> str:
    import netcheck

    ping = netcheck.measure_latency(connect=probe.connect)
    _need(ping is not None, "nenhum servidor respondeu")
    return f"{ping:g} ms até 1.1.1.1 e 8.8.8.8"


def check_download(probe: Probe) -> str:
    import netcheck

    mbps = netcheck.measure_download(probe, size=SPEED_DOWN_BYTES)
    _need(mbps is not None and mbps > 0, f"o download de teste não devolveu dados ({probe.why_empty()})")
    return f"{SPEED_DOWN_BYTES // 1000} KB baixados ({mbps:g} Mbps)"


def check_upload(probe: Probe) -> str:
    import netcheck

    mbps = netcheck.measure_upload(probe, size=SPEED_UP_BYTES)
    _need(mbps is not None and mbps > 0, f"o upload de teste foi recusado ({probe.why_empty()})")
    return f"{SPEED_UP_BYTES // 1000} KB enviados ({mbps:g} Mbps)"


# ───────────────────────── execução ─────────────────────────

Check = tuple[str, str, Callable[[Probe], str]]  # (grupo, nome, checagem)


def all_checks() -> list[Check]:
    import osint

    ODD = "Olho de Deus (ODD-42)"
    checks: list[Check] = [
        (ODD, "ipwho.is · localização de IP", check_ip),
        (ODD, "internetdb.shodan.io · portas, hosts e CVEs de um IP", check_internetdb),
        (ODD, "dns.google · registros DNS", check_dns),
        (ODD, "rdap.org · registro do domínio", check_rdap),
        (ODD, "crt.sh · subdomínios por certificado", check_crtsh),
        (ODD, "BrasilAPI · CNPJ", check_cnpj),
        (ODD, "BrasilAPI · CEP", check_cep),
        (ODD, "BrasilAPI · DDD", check_ddd),
        (ODD, "XposedOrNot · vazamentos de email", check_breaches),
        (ODD, "Pwned Passwords · senha por prefixo", check_pwned),
    ]
    # O URLhaus só entra com a chave (como no Jarvis: sem a chave a checagem de link não existe).
    key = urlhaus_key()
    if key:
        checks.append((ODD, "urlhaus-api.abuse.ch · link na lista de malware", lambda probe, key=key: check_urlhaus(probe, key)))
    checks += [("Perfis de usuário (osint.SITES)", f"{site[0]}", check_profile(site)) for site in osint.SITES]
    checks += [
        ("Cotações (COT-44)", "AwesomeAPI · cotações", check_quotes),
        ("Clima (Open-Meteo)", "geocodificação de cidade", check_geocoding),
        ("Clima (Open-Meteo)", "previsão de 7 dias", check_forecast),
        ("Clima (Open-Meteo)", "clima de agora (modo ambiente)", check_ambient),
        ("Internet (RED-45)", "Cloudflare · latência (TCP)", check_latency),
        ("Internet (RED-45)", "Cloudflare · download", check_download),
        ("Internet (RED-45)", "Cloudflare · upload", check_upload),
    ]
    return checks


def run_check(
    group: str,
    name: str,
    check: Callable[[Probe], str],
    *,
    http: Any = requests,
    connect: Callable[..., Any] = socket.create_connection,
    sleep: Callable[[float], None] = time.sleep,
) -> SourceResult:
    """Roda uma checagem. Sem rede, tenta mais uma vez antes de desistir (rede de verdade oscila)."""
    attempt = 0
    while True:
        attempt += 1
        probe = Probe(http, connect)
        try:
            return SourceResult(group, name, OK, _short(check(probe), 160))
        except SourceFailure as exc:
            failure = str(exc)
        except (requests.ConnectionError, requests.Timeout) as exc:
            probe._note_error(exc)
            failure = ""
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            failure = f"o servidor respondeu {status}" if status else f"o servidor respondeu com erro: {exc}"
        except ImportError as exc:
            failure = f"não deu para carregar o módulo: {exc}"
        except Exception as exc:
            # OsintError e QuoteError já são frases para o usuário; o resto é a leitura quebrando
            # com o formato novo (campo que não existe mais, tipo diferente...).
            failure = str(exc) if type(exc).__name__ in {"OsintError", "QuoteError"} else f"a leitura quebrou: {type(exc).__name__}: {exc}"
        # Uma função que engole o erro de rede e devolve vazio também termina aqui: se a rede falhou
        # durante a checagem, não dá para concluir nada sobre o formato.
        if probe.network_errors:
            if attempt < 2:
                sleep(RETRY_DELAY_S)
                continue
            return SourceResult(group, name, NO_NETWORK, probe.network_errors[-1])
        return SourceResult(group, name, FAILED, _short(failure or "falhou sem motivo", 200))


def check_all(
    *,
    http: Any = requests,
    connect: Callable[..., Any] = socket.create_connection,
    sleep: Callable[[float], None] = time.sleep,
    ignore: Iterable[str] = (),
    on_result: Callable[[SourceResult], None] | None = None,
    checks: list[Check] | None = None,
) -> list[SourceResult]:
    """Roda todas as checagens (em paralelo, na ordem de sempre) e devolve os resultados."""
    ignored = [item.strip().lower() for item in ignore if item.strip()]
    wanted = checks if checks is not None else all_checks()

    def work(item: Check) -> SourceResult:
        group, name, check = item
        result = run_check(group, name, check, http=http, connect=connect, sleep=sleep)
        if any(part in f"{group} {name}".lower() for part in ignored):
            return SourceResult(group, name, IGNORED, result.detail, real_status=result.status)
        return result

    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for result in pool.map(work, wanted):
            results.append(result)
            if on_result:
                on_result(result)
    return results


def exit_code(results: Iterable[SourceResult]) -> int:
    statuses = [result.status for result in results]
    if FAILED in statuses:
        return EXIT_FAILED
    if NO_NETWORK in statuses:
        return EXIT_NO_NETWORK
    return EXIT_OK


def summary(results: list[SourceResult]) -> str:
    counts = [(len([r for r in results if r.status == status]), label) for status, label in ((OK, "ok"), (FAILED, "com falha"), (NO_NETWORK, "sem rede"), (IGNORED, "ignorada(s)"))]
    return ", ".join(f"{count} {label}" for count, label in counts if count)


def run(ignore: Iterable[str] = (), **kwargs: Any) -> int:
    """`python doctor.py --fontes`: consulta tudo, mostra uma linha por fonte e devolve o código de saída."""
    print("Jarvis Doctor · fontes externas")
    print("Consulta cada serviço de verdade, com um valor conhecido, pelas mesmas funções de leitura do Jarvis.")
    print("O teste de velocidade usa um volume mínimo (200 KB para baixar, 50 KB para enviar).")

    printed: list[str] = []

    def show(result: SourceResult) -> None:
        if result.group not in printed:
            printed.append(result.group)
            title = result.group
            print(f"\n{title}")
            print("-" * len(title))
        tag = {OK: "ok", FAILED: "FALHA", NO_NETWORK: "sem rede", IGNORED: "ignorada"}[result.status]
        extra = f" [{result.real_status}]" if result.real_status else ""
        print(f"[{tag}]{extra} {result.name}: {result.detail}")

    results = check_all(ignore=ignore, on_result=show, **kwargs)
    code = exit_code(results)
    print("\nResumo")
    print("------")
    print(summary(results) + ".")
    if code == EXIT_FAILED:
        print("Alguma fonte falhou: o formato da resposta mudou ou o serviço está com problema. Veja docs/problemas.md.")
    elif code == EXIT_NO_NETWORK:
        print("Nenhuma fonte falhou, mas algumas não puderam ser alcançadas: confira a sua internet e rode de novo.")
    return code
