"""`python doctor.py --fontes` (fontes.py): cada fonte com resposta no formato certo, no formato mudado e
sem rede. Nenhum teste vai à internet: o `requests` e o socket são de mentira."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

import pytest
import requests

import fontes
import osint
import quotes
from doctor import main as doctor_main

GOOD: dict[str, Any] = {
    "ip": {
        "ip": "8.8.8.8",
        "success": True,
        "type": "IPv4",
        "country": "Estados Unidos",
        "region": "Califórnia",
        "city": "Mountain View",
        "latitude": 37.386,
        "longitude": -122.0838,
        "connection": {"asn": 15169, "org": "Google LLC", "isp": "Google LLC", "domain": "google.com"},
        "timezone": {"id": "America/Los_Angeles", "utc": "-07:00"},
    },
    "internetdb": {"cpes": ["cpe:/a:isc:bind"], "hostnames": ["dns.google"], "ip": "8.8.8.8", "ports": [53, 443], "tags": ["cloud"], "vulns": []},
    "urlhaus": {"query_status": "no_results"},
    "dns": {"Status": 0, "Answer": [{"name": "google.com.", "type": 1, "TTL": 300, "data": "142.250.78.14"}]},
    "rdap": {
        "events": [
            {"eventAction": "registration", "eventDate": "1997-09-15T04:00:00Z"},
            {"eventAction": "expiration", "eventDate": "2028-09-14T04:00:00Z"},
            {"eventAction": "last changed", "eventDate": "2019-09-09T15:39:04Z"},
        ],
        "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "MarkMonitor Inc."]]]}],
        "nameservers": [{"ldhName": "NS1.GOOGLE.COM"}, {"ldhName": "NS2.GOOGLE.COM"}],
        "status": ["client delete prohibited"],
    },
    "crtsh": [{"name_value": "www.iana.org\niana.org"}, {"name_value": "data.iana.org"}],
    "cnpj": {
        "razao_social": "BANCO DO BRASIL SA",
        "nome_fantasia": "DIRECAO GERAL",
        "descricao_situacao_cadastral": "ATIVA",
        "data_inicio_atividade": "1966-08-01",
        "natureza_juridica": "Sociedade de Economia Mista",
        "porte": "DEMAIS",
        "capital_social": 120000000000,
        "cnae_fiscal_descricao": "Bancos múltiplos, com carteira comercial",
        "descricao_tipo_de_logradouro": "SETOR",
        "logradouro": "SAUN QUADRA 5 LOTE B",
        "numero": "S/N",
        "bairro": "ASA NORTE",
        "municipio": "BRASILIA",
        "uf": "DF",
        "cep": "70040912",
        "qsa": [{"nome_socio": "FULANO DE TAL", "qualificacao_socio": "Diretor"}],
    },
    "cep": {"cep": "01310100", "state": "SP", "city": "São Paulo", "neighborhood": "Bela Vista", "street": "Avenida Paulista", "location": {"type": "Point", "coordinates": {"longitude": "-46.65", "latitude": "-23.56"}}},
    "ddd": {"state": "SP", "cities": ["SAO PAULO", "OSASCO", "BARUERI", "CARAPICUIBA", "COTIA", "DIADEMA", "GUARULHOS", "ITAQUAQUECETUBA", "MAUA", "SANTO ANDRE", "SAO BERNARDO DO CAMPO", "TABOAO DA SERRA"]},
    "breaches": {"breaches": [["Adobe", "LinkedIn"]]},
    "pwned": "\n".join(["0018A45C4D1DEF81644B54AB7F969B88D65:1", "1E4C9B93F3F0682250B6CF8331B7EE68FD8:10434004", "00D4F6E8FA6EECAD2A3AA415EEC418D38EC:0"]),
    "quotes": {
        "USDBRL": {"code": "USD", "codein": "BRL", "bid": "5.1234", "pctChange": "0.31", "high": "5.15", "low": "5.08", "create_date": "2026-11-13 10:00:01"},
        "BTCBRL": {"code": "BTC", "codein": "BRL", "bid": "350000", "pctChange": "-1.2", "high": "355000", "low": "345000", "create_date": "2026-11-13 10:00:02"},
    },
    "geocode": {"results": [{"name": "São Paulo", "latitude": -23.5475, "longitude": -46.63611, "country": "Brasil", "timezone": "America/Sao_Paulo"}]},
    "forecast": {
        "timezone": "America/Sao_Paulo",
        "current": {"temperature_2m": 24.1, "relative_humidity_2m": 60, "weather_code": 3, "wind_speed_10m": 9.4, "apparent_temperature": 25.0, "is_day": 1},
        "daily": {
            "time": [f"2026-11-{13 + i}" for i in range(7)],
            "weather_code": [3] * 7,
            "temperature_2m_max": [28.0] * 7,
            "temperature_2m_min": [18.0] * 7,
            "precipitation_probability_max": [20] * 7,
        },
        "hourly": {"time": [f"2026-11-13T{h:02d}:00" for h in range(24)], "temperature_2m": [22.0] * 24, "precipitation_probability": [10] * 24},
    },
}

# Como cada regra de osint.SITES responde para quem existe e para quem não existe.
PRESENT = {"status": {"id": 1}, "npmsearch": {"objects": [{"package": {}}], "total": 1}, "list": [{"id": 1}], "notnull": {"id": "x"}, "users": {"users": [{"id": 1}]}, "keybase": {"them": [{"id": 1}]}}
ABSENT = {"status": None, "npmsearch": {"objects": [], "total": 0}, "list": [], "notnull": None, "users": {"users": []}, "keybase": {"them": [None]}}


class FakeResponse:
    def __init__(self, payload: Any = None, status: int = 200, text: str = "", body: bytes = b"") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text
        self._body = body

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error", response=self)

    def iter_content(self, chunk_size: int = 0):
        yield self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeInternet:
    """Os serviços de verdade, de mentira. `payloads` e `statuses` deixam cada teste mudar uma fonte."""

    def __init__(self) -> None:
        self.payloads = copy.deepcopy(GOOD)
        self.statuses: dict[str, int] = {}
        self.errors: dict[str, Exception] = {}
        self.down = False
        self.body = b"x" * 1000
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sent_bytes = 0
        self.known_user_present: dict[str, bool] = {}
        self.challenge: set[str] = set()

    # ----- rotas -----
    def _key(self, url: str, params: dict[str, Any]) -> str | None:
        table = (
            ("ipwho.is/8.8.8.8", "ip"),
            ("internetdb.shodan.io/8.8.8.8", "internetdb"),
            ("urlhaus-api.abuse.ch/v1/url/", "urlhaus"),
            ("dns.google/resolve", "dns"),
            ("rdap.org/domain/google.com", "rdap"),
            ("crt.sh/", "crtsh"),
            ("brasilapi.com.br/api/cnpj/v1/00000000000191", "cnpj"),
            ("brasilapi.com.br/api/cep/v2/01310100", "cep"),
            ("brasilapi.com.br/api/ddd/v1/11", "ddd"),
            ("xposedornot.com/v1/check-email/test%40example.com", "breaches"),
            ("pwnedpasswords.com/range/5BAA6", "pwned"),
            ("economia.awesomeapi.com.br/json/last/USD-BRL,BTC-BRL", "quotes"),
            ("geocoding-api.open-meteo.com/v1/search", "geocode"),
            ("api.open-meteo.com/v1/forecast", "forecast"),
            ("speed.cloudflare.com/__down", "down"),
            ("speed.cloudflare.com/__up", "up"),
        )
        for fragment, key in table:
            if fragment in url:
                return key
        for site in osint.SITES:
            name, api = site[0], site[1]
            for user in (fontes.KNOWN_USERS[name], fontes.ABSENT_USER):
                slug = quote(user.lower() if name == "Chess.com" else user, safe="")
                if url == api.format(u=slug):
                    return f"site:{name}:{'present' if user != fontes.ABSENT_USER else 'absent'}"
        return None

    def _answer(self, key: str, method: str) -> FakeResponse:
        if key in self.errors:
            raise self.errors[key]
        status = self.statuses.get(key)
        if key in self.challenge:
            return FakeResponse(text="<html><title>Client Challenge</title></html>")
        if key.startswith("site:"):
            _, name, which = key.split(":")
            rule = next(site[3] for site in osint.SITES if site[0] == name)
            present = which == "present" and self.known_user_present.get(name, True)
            if present:
                return FakeResponse(PRESENT[rule], status or 200)
            return FakeResponse(ABSENT[rule], status or (404 if rule == "status" else 200))
        if key == "down":
            return FakeResponse(status=status or 200, body=self.body)
        if key == "up":
            return FakeResponse(status=status or 200)
        if key == "pwned":
            return FakeResponse(text=self.payloads["pwned"], status=status or 200)
        if key == "breaches":
            if status is None and self.payloads["breaches"] is None:
                return FakeResponse({"Error": "Not found"}, 404)
            return FakeResponse(self.payloads["breaches"], status or 200)
        return FakeResponse(self.payloads[key], status or 200)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        params = kwargs.get("params") or {}
        self.calls.append((url, params))
        if self.down:
            raise requests.ConnectionError("Name or service not known")
        key = self._key(url, params)
        if key is None:
            return FakeResponse({}, 404)
        return self._answer(key, "get")

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, {}))
        self.sent_bytes += len(kwargs.get("data") or b"")
        if self.down:
            raise requests.ConnectionError("Name or service not known")
        return self._answer(self._key(url, {}) or "up", "post")

    def connect(self, address: tuple[str, int], timeout: float = 2.0) -> Any:
        if self.down:
            raise OSError("Network is unreachable")

        class Socket:
            def close(self) -> None:
                return None

        return Socket()


@pytest.fixture(autouse=True)
def clean_quotes_cache(monkeypatch):
    quotes._cache.clear()
    monkeypatch.setattr(fontes, "urlhaus_key", lambda: None)  # a chave do URLhaus só entra nos testes que a pedem
    yield
    quotes._cache.clear()


def run_all(net: FakeInternet, **kwargs: Any) -> dict[str, fontes.SourceResult]:
    sleeps: list[float] = []
    results = fontes.check_all(http=net, connect=net.connect, sleep=sleeps.append, **kwargs)
    by_name = {result.name: result for result in results}
    assert len(by_name) == len(results), "dois nomes iguais escondem uma fonte"
    return by_name


def only(results: dict[str, fontes.SourceResult], status: str) -> list[str]:
    return [name for name, result in results.items() if result.status == status]


# ───────────────────────── formato certo ─────────────────────────


def test_every_source_is_ok_with_the_expected_format() -> None:
    net = FakeInternet()
    results = run_all(net)
    assert [(name, r.detail) for name, r in results.items() if r.status != fontes.OK] == []
    assert len(results) == len(fontes.all_checks())
    assert fontes.exit_code(results.values()) == fontes.EXIT_OK


def test_every_site_of_osint_has_its_own_line_and_a_known_user() -> None:
    assert set(fontes.KNOWN_USERS) == {site[0] for site in osint.SITES}
    assert fontes.ABSENT_USER not in fontes.KNOWN_USERS.values()
    names = [name for group, name, _ in fontes.all_checks() if group.startswith("Perfis")]
    assert names == [site[0] for site in osint.SITES]


def test_every_source_named_in_the_task_is_checked() -> None:
    net = FakeInternet()
    run_all(net)
    hosts = {url.split("/")[2] for url, _ in net.calls}
    for host in (
        "ipwho.is", "internetdb.shodan.io", "dns.google", "rdap.org", "crt.sh", "brasilapi.com.br", "api.xposedornot.com", "api.pwnedpasswords.com",
        "economia.awesomeapi.com.br", "geocoding-api.open-meteo.com", "api.open-meteo.com", "speed.cloudflare.com",
    ):  # fmt: skip
        assert host in hosts, host
    # Um host de cada API de perfil de osint.SITES.
    for site in osint.SITES:
        assert site[1].split("/")[2] in hosts, site[0]


def test_pypi_is_not_a_profile_source_anymore() -> None:
    # O PyPI responde 200 com uma página de verificação para qualquer nome: não há como saber, então saiu da lista.
    assert "PyPI" not in {site[0] for site in osint.SITES}
    assert "PyPI" not in fontes.KNOWN_USERS
    assert "PyPI" not in run_all(FakeInternet())


def test_internetdb_without_scan_data_or_with_a_changed_format_is_a_failure() -> None:
    net = FakeInternet()
    net.statuses["internetdb"] = 404
    result = run_all(net)["internetdb.shodan.io · portas, hosts e CVEs de um IP"]
    assert result.status == fontes.FAILED and "404" in result.detail
    net = FakeInternet()
    net.payloads["internetdb"]["ports"] = "53,443"  # o campo mudou de tipo
    result = run_all(net)["internetdb.shodan.io · portas, hosts e CVEs de um IP"]
    assert result.status == fontes.FAILED and "ports" in result.detail


URLHAUS_CHECK = "urlhaus-api.abuse.ch · link na lista de malware"


def test_urlhaus_is_only_checked_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    net = FakeInternet()
    assert URLHAUS_CHECK not in run_all(net)
    assert not any("urlhaus" in url for url, _ in net.calls)
    monkeypatch.setattr(fontes, "urlhaus_key", lambda: "chave-de-teste")
    net = FakeInternet()
    results = run_all(net)
    assert results[URLHAUS_CHECK].status == fontes.OK
    assert any("urlhaus-api.abuse.ch" in url for url, _ in net.calls)


def test_urlhaus_with_a_refused_key_or_a_new_status_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fontes, "urlhaus_key", lambda: "chave-de-teste")
    net = FakeInternet()
    net.statuses["urlhaus"] = 401
    result = run_all(net)[URLHAUS_CHECK]
    assert result.status == fontes.FAILED and "recusou a chave" in result.detail
    net = FakeInternet()
    net.payloads["urlhaus"] = {"query_status": "coisa_nova"}
    result = run_all(net)[URLHAUS_CHECK]
    assert result.status == fontes.FAILED and "coisa_nova" in result.detail


def test_urlhaus_key_comes_from_the_environment_or_the_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.undo()  # o autouse trocou a função; aqui vale a de verdade
    monkeypatch.delenv("JARVIS_URLHAUS_KEY", raising=False)
    monkeypatch.setattr(fontes, "__file__", str(tmp_path / "fontes.py"))
    assert fontes.urlhaus_key() is None
    (tmp_path / ".env").write_text("JARVIS_URLHAUS_KEY=abc123\n", encoding="utf-8")
    assert fontes.urlhaus_key() == "abc123"
    monkeypatch.setenv("JARVIS_URLHAUS_KEY", "")  # o segredo vazio do workflow não vira chave
    assert fontes.urlhaus_key() is None
    monkeypatch.setenv("JARVIS_URLHAUS_KEY", "sua-chave-aqui")
    assert fontes.urlhaus_key() is None
    monkeypatch.setenv("JARVIS_URLHAUS_KEY", "xyz")
    assert fontes.urlhaus_key() == "xyz"


def test_the_speed_test_uses_a_minimum_volume() -> None:
    net = FakeInternet()
    run_all(net)
    down = [params for url, params in net.calls if "__down" in url]
    assert down and all(int(params["bytes"]) <= 200_000 for params in down)
    assert 0 < net.sent_bytes <= 50_000


def test_nothing_personal_is_sent() -> None:
    net = FakeInternet()
    run_all(net)
    email_calls = [url for url, _ in net.calls if "xposedornot" in url]
    assert email_calls and all(url.endswith("test%40example.com") for url in email_calls)
    # A senha vai só como prefixo de 5 caracteres do SHA-1.
    assert [url for url, _ in net.calls if "pwnedpasswords" in url] == ["https://api.pwnedpasswords.com/range/5BAA6"]


# ───────────────────────── formato mudado ─────────────────────────


def _drop(path: tuple[Any, ...]):
    def mutate(payload: Any) -> None:
        for step in path[:-1]:
            payload = payload[step]
        del payload[path[-1]]

    return mutate


def _set(path: tuple[Any, ...], value: Any):
    def mutate(payload: Any) -> None:
        for step in path[:-1]:
            payload = payload[step]
        payload[path[-1]] = value

    return mutate


CHANGED = [
    # (chave, mudança, fonte que tem que falhar, pedaço do motivo)
    ("ip", _drop(("connection",)), "ipwho.is · localização de IP", "Provedor"),
    ("ip", _set(("connection", "asn"), 64500), "ipwho.is · localização de IP", "AS15169"),
    ("ip", _drop(("latitude",)), "ipwho.is · localização de IP", "latitude"),
    ("dns", _set(("Answer", 0, "data"), "não sou um IP"), "dns.google · registros DNS", "não é um IP"),
    ("dns", _drop(("Answer",)), "dns.google · registros DNS", "nenhum registro"),
    ("rdap", _set(("events",), []), "rdap.org · registro do domínio", "criação"),
    ("rdap", _set(("entities",), []), "rdap.org · registro do domínio", "registrador"),
    ("rdap", _set(("events", 0, "eventDate"), "setembro de 1997"), "rdap.org · registro do domínio", "formato que não leio"),
    ("crtsh", [{"common_name": "www.iana.org"}], "crt.sh · subdomínios por certificado", "nenhum subdomínio"),
    ("cnpj", _drop(("razao_social",)), "BrasilAPI · CNPJ", "Razão social"),
    ("cnpj", _set(("razao_social",), "OUTRA EMPRESA"), "BrasilAPI · CNPJ", "OUTRA EMPRESA"),
    ("cnpj", _set(("descricao_situacao_cadastral",), "BAIXADA"), "BrasilAPI · CNPJ", "ativa"),
    ("cep", _drop(("street",)), "BrasilAPI · CEP", "Rua"),
    ("cep", _set(("city",), "Santos"), "BrasilAPI · CEP", "Santos"),
    ("ddd", _drop(("cities",)), "BrasilAPI · DDD", "vazia"),
    ("ddd", _set(("state",), "RJ"), "BrasilAPI · DDD", "RJ"),
    ("breaches", {"Breaches": "mudou"}, "XposedOrNot · vazamentos de email", "formato pode ter mudado"),
    ("pwned", "1E4C9B93F3F0682250B6CF8331B7EE68FD8,10434004", "Pwned Passwords · senha por prefixo", "nenhum sufixo"),
    ("pwned", "0018A45C4D1DEF81644B54AB7F969B88D65:1", "Pwned Passwords · senha por prefixo", "password"),
    ("quotes", _drop(("USDBRL", "bid")), "AwesomeAPI · cotações", "vieram 1"),
    ("quotes", _drop(("BTCBRL", "pctChange")), "AwesomeAPI · cotações", "variação"),
    ("quotes", _drop(("USDBRL", "create_date")), "AwesomeAPI · cotações", "hora"),
    ("geocode", _set(("results",), []), "geocodificação de cidade", "results"),
    ("forecast", _drop(("current", "relative_humidity_2m")), "previsão de 7 dias", "KeyError"),
    ("forecast", _drop(("daily",)), "previsão de 7 dias", "0 dias"),
    ("forecast", _drop(("hourly",)), "previsão de 7 dias", "0 pontos"),
    ("forecast", _drop(("daily",)), "clima de agora (modo ambiente)", "máxima e mínima"),
    ("forecast", _set(("current", "temperature_2m"), "24 graus"), "clima de agora (modo ambiente)", "número"),
]


@pytest.mark.parametrize("key, mutation, source, reason", CHANGED, ids=[f"{c[0]}-{i}" for i, c in enumerate(CHANGED)])
def test_a_changed_format_shows_up_as_a_failure(key: str, mutation: Any, source: str, reason: str) -> None:
    net = FakeInternet()
    if callable(mutation):
        mutation(net.payloads[key])
    else:
        net.payloads[key] = mutation
    results = run_all(net)
    assert results[source].status == fontes.FAILED, results[source]
    assert reason.lower() in results[source].detail.lower(), results[source].detail
    # Só a fonte mexida falha; a mudança do clima pode atingir as duas leituras da mesma API.
    assert set(only(results, fontes.FAILED)) <= {source, "previsão de 7 dias", "clima de agora (modo ambiente)"}
    assert fontes.exit_code(results.values()) == fontes.EXIT_FAILED


def test_a_server_error_is_a_failure_with_the_status() -> None:
    net = FakeInternet()
    net.statuses["crtsh"] = 502
    net.statuses["up"] = 403
    results = run_all(net)
    assert results["crt.sh · subdomínios por certificado"].status == fontes.FAILED
    assert "502" in results["crt.sh · subdomínios por certificado"].detail
    assert results["Cloudflare · upload"].status == fontes.FAILED
    assert "403" in results["Cloudflare · upload"].detail


def test_an_http_error_raised_by_the_module_is_a_failure_with_the_status() -> None:
    net = FakeInternet()
    net.statuses["geocode"] = 503
    result = run_all(net)["geocodificação de cidade"]
    assert result.status == fontes.FAILED
    assert "503" in result.detail


def test_a_download_without_data_is_a_failure() -> None:
    net = FakeInternet()
    net.body = b""
    results = run_all(net)
    assert results["Cloudflare · download"].status == fontes.FAILED
    assert "200" in results["Cloudflare · download"].detail


def test_a_profile_that_disappeared_or_a_site_answering_yes_to_everything() -> None:
    net = FakeInternet()
    net.known_user_present["GitHub"] = False
    net.statuses["site:Reddit:absent"] = 200  # passou a responder 200 para qualquer nome
    results = run_all(net)
    assert results["GitHub"].status == fontes.FAILED
    assert "torvalds" in results["GitHub"].detail
    assert results["Reddit"].status == fontes.FAILED
    assert "nome que ninguém tem" in results["Reddit"].detail
    assert set(only(results, fontes.FAILED)) == {"GitHub", "Reddit"}


def test_a_site_answering_with_a_challenge_page_is_not_trusted() -> None:
    net = FakeInternet()
    net.challenge.add("site:Docker Hub:absent")
    result = run_all(net)["Docker Hub"]
    assert result.status == fontes.FAILED
    assert "verificação" in result.detail


def test_a_site_that_blocks_the_query_is_a_failure_with_the_status() -> None:
    net = FakeInternet()
    net.statuses["site:Docker Hub:present"] = 403
    results = run_all(net)
    assert results["Docker Hub"].status == fontes.FAILED
    assert "403" in results["Docker Hub"].detail


def test_the_breach_service_answering_404_is_ok_and_says_what_was_not_seen() -> None:
    net = FakeInternet()
    net.payloads["breaches"] = None
    result = run_all(net)["XposedOrNot · vazamentos de email"]
    assert result.status == fontes.OK
    assert "404" in result.detail and "não foi visto" in result.detail


def test_quotes_are_fetched_even_with_a_fresh_cache() -> None:
    net = FakeInternet()
    quotes.fetch_pairs([("USD", "BRL"), ("BTC", "BRL")], net)  # enche o cache de um minuto
    net.calls.clear()
    assert run_all(net)["AwesomeAPI · cotações"].status == fontes.OK
    assert any("awesomeapi" in url for url, _ in net.calls)


# ───────────────────────── sem rede ─────────────────────────


def test_without_a_network_every_source_is_unreachable_not_failed() -> None:
    net = FakeInternet()
    net.down = True
    sleeps: list[float] = []
    results = fontes.check_all(http=net, connect=net.connect, sleep=sleeps.append)
    assert {result.status for result in results} == {fontes.NO_NETWORK}
    assert all("Name or service not known" in r.detail or "Network is unreachable" in r.detail for r in results)
    assert fontes.exit_code(results) == fontes.EXIT_NO_NETWORK
    assert len(sleeps) == len(results)  # uma segunda tentativa para cada


def test_a_timeout_on_one_source_does_not_hide_the_others() -> None:
    net = FakeInternet()
    net.errors["rdap"] = requests.Timeout("Read timed out")
    results = run_all(net)
    assert only(results, fontes.NO_NETWORK) == ["rdap.org · registro do domínio"]
    assert "Timeout" in results["rdap.org · registro do domínio"].detail
    assert len(only(results, fontes.OK)) == len(results) - 1
    assert fontes.exit_code(results.values()) == fontes.EXIT_NO_NETWORK


def test_a_failure_wins_over_unreachable_in_the_exit_code() -> None:
    net = FakeInternet()
    net.errors["rdap"] = requests.ConnectionError("recusou")
    net.payloads["cep"].pop("street")
    results = run_all(net)
    assert fontes.exit_code(results.values()) == fontes.EXIT_FAILED


def test_the_network_dropping_in_the_middle_of_a_check_is_not_blamed_on_the_format() -> None:
    net = FakeInternet()
    net.errors["site:GitHub:absent"] = requests.ConnectionError("caiu")
    result = run_all(net)["GitHub"]
    assert result.status == fontes.NO_NETWORK


def test_a_second_attempt_rescues_a_flaky_network() -> None:
    net = FakeInternet()
    attempts = {"count": 0}
    real_get = net.get

    def flaky(url: str, **kwargs: Any) -> Any:
        if "dns.google" in url:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise requests.Timeout("lento")
        return real_get(url, **kwargs)

    net.get = flaky  # type: ignore[method-assign]
    result = run_all(net)["dns.google · registros DNS"]
    assert result.status == fontes.OK
    assert attempts["count"] == 2


def test_a_format_failure_is_not_retried() -> None:
    net = FakeInternet()
    net.payloads["dns"] = {"Answer": []}
    sleeps: list[float] = []
    fontes.check_all(http=net, connect=net.connect, sleep=sleeps.append)
    assert sleeps == []


# ───────────────────────── ignorar, relatório e doctor.py ─────────────────────────


def test_ignored_sources_are_shown_but_do_not_count() -> None:
    net = FakeInternet()
    net.statuses["site:Reddit:present"] = 403
    results = run_all(net, ignore=["reddit", " "])
    assert results["Reddit"].status == fontes.IGNORED
    assert results["Reddit"].real_status == fontes.FAILED
    assert fontes.exit_code(results.values()) == fontes.EXIT_OK


def test_the_report_has_one_line_per_source_and_the_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    net = FakeInternet()
    net.payloads["cep"].pop("street")
    net.errors["rdap"] = requests.Timeout("lento")
    code = fontes.run(http=net, connect=net.connect, sleep=lambda _: None)
    out = capsys.readouterr().out
    assert code == fontes.EXIT_FAILED
    assert "Olho de Deus (ODD-42)" in out and "Perfis de usuário (osint.SITES)" in out and "Internet (RED-45)" in out
    assert "[ok] ipwho.is · localização de IP:" in out
    assert "[FALHA] BrasilAPI · CEP:" in out
    assert "[sem rede] rdap.org · registro do domínio:" in out
    assert out.count("\n[") == len(fontes.all_checks())
    assert "1 com falha" in out and "1 sem rede" in out


def test_the_report_when_everything_is_fine(capsys: pytest.CaptureFixture[str]) -> None:
    net = FakeInternet()
    assert fontes.run(http=net, connect=net.connect, sleep=lambda _: None) == 0
    out = capsys.readouterr().out
    assert f"{len(fontes.all_checks())} ok." in out and "FALHA" not in out


def test_doctor_fontes_flag_runs_the_sources_and_returns_their_code() -> None:
    with patch("fontes.run", return_value=2) as run:
        assert doctor_main(["--fontes", "--ignorar", "reddit, crt.sh"]) == 2
    run.assert_called_once_with(ignore=["reddit", " crt.sh"])


def test_doctor_without_flag_does_not_touch_the_sources() -> None:
    with patch("fontes.run") as run, patch("doctor.load_settings", side_effect=doctor_settings_error()):
        assert doctor_main([]) == 1
    run.assert_not_called()


def doctor_settings_error() -> Exception:
    from settings import SettingsError

    return SettingsError("de mentira")


def test_netcheck_measures_with_the_size_it_is_given() -> None:
    import netcheck

    net = FakeInternet()
    net.body = b"x" * 5000
    assert netcheck.measure_download(net, size=5000) > 0
    assert netcheck.measure_upload(net, size=1234) > 0
    assert net.calls[0][1] == {"bytes": 5000}
    assert net.sent_bytes == 1234
    # Sem pedir tamanho, continua no volume de sempre.
    assert netcheck.DOWN_BYTES == 25_000_000 and netcheck.UP_BYTES == 4_000_000


def test_the_weekly_workflow_runs_on_schedule_and_by_hand_but_never_on_pull_requests() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "fontes.yml").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    code = "\n".join(lines)
    assert "schedule:" in code and "workflow_dispatch:" in code
    for trigger in ("pull_request", "push:", "pull_request_target"):
        assert trigger not in code, trigger
    assert "python doctor.py --fontes" in code
    assert "continue-on-error" not in code  # falhar tem que deixar o job vermelho
