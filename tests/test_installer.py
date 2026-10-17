from __future__ import annotations

import asyncio
import subprocess
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import confirmation
import installer
from confirmation import spoken_digits
from installer import (
    PENDING_INSTALL_KEY,
    SEARCH_KEY,
    Package,
    cancel_app_install,
    confirm_app_install,
    install_command,
    is_valid_package_id,
    parse_search_output,
    prepare_app_install,
    rank_candidates,
    run_install,
    search_apps,
)

from test_tools import FakeHistory, FakeMessage, FakeRunContext

WINGET = r"C:\Users\gabri\AppData\Local\Microsoft\WindowsApps\winget.EXE"

WINGET_VLC = (
    "Name                Id                         Version Match\r\n"
    "-------------------------------------------------------------------\r\n"
    "VLC media player    VideoLAN.VLC               3.0.24  Moniker: vlc\r\n"
    "pympress            Cimbali.pympress           1.8.6   Tag: vlc\r\n"
    "Jellyfin VLC Bridge CrySer66.JellyfinVlcBridge 1.18.0  Tag: vlc\r\n"
    "Very Long Name Tha… Some.Truncated.Ident…      1.0     Tag: vlc\r\n"
    "<additional entries truncated due to result limit>\r\n"
)
MSSTORE_VLC = (
    "Name    Id           Version\r\n"
    "----------------------------\r\n"
    "VLC     9NBLGGH4VVNH Unknown\r\n"
)
NOT_FOUND = 0x8A150014


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout.encode("utf-8"), stderr=b"")


def fake_winget(outputs: dict[str, subprocess.CompletedProcess]):
    """subprocess.run stand-in: answers `winget search` per source and records every call."""

    def run(args, **kwargs):
        source = args[args.index("--source") + 1]
        return outputs.get(source, completed("No package found matching input criteria.\r\n", NOT_FOUND))

    return MagicMock(side_effect=run)


VLC = Package(name="VLC media player", id="VideoLAN.VLC", version="3.0.24", source="winget", match="Moniker: vlc")


class ParseSearchOutputTests(unittest.TestCase):
    def test_parses_winget_table_and_drops_truncated_ids(self) -> None:
        packages = parse_search_output(WINGET_VLC, "winget")

        self.assertEqual([package.id for package in packages], ["VideoLAN.VLC", "Cimbali.pympress", "CrySer66.JellyfinVlcBridge"])
        self.assertEqual(packages[0], VLC)

    def test_parses_msstore_table_without_match_column(self) -> None:
        packages = parse_search_output(MSSTORE_VLC, "msstore")

        self.assertEqual(packages, [Package(name="VLC", id="9NBLGGH4VVNH", version=None, source="msstore")])

    def test_ignores_progress_noise_and_localized_header(self) -> None:
        output = (
            "\r   - \r   \\ \r  ██████████████  1.00 MB / 1.00 MB\r\n"
            "Nome                   ID           Versão\r\n"
            "-------------------------------------------\r\n"
            "Calculadora científica 9WZDNCRDC3G4 Desconhecido\r\n"
        )
        packages = parse_search_output(output, "msstore")

        self.assertEqual(packages, [Package(name="Calculadora científica", id="9WZDNCRDC3G4", version=None, source="msstore")])

    def test_handles_wide_characters_in_names(self) -> None:
        output = (
            "Name       Id                  Version\r\n"
            "--------------------------------------\r\n"
            "网易云音乐 NetEase.CloudMusic  3.1.0\r\n"
        )
        packages = parse_search_output(output, "winget")

        self.assertEqual(packages[0].id, "NetEase.CloudMusic")
        self.assertEqual(packages[0].name, "网易云音乐")

    def test_no_table_means_no_packages(self) -> None:
        self.assertEqual(parse_search_output("No package found matching input criteria.\r\n", "winget"), [])

    def test_rank_prefers_exact_name_then_winget(self) -> None:
        store = Package(name="VLC", id="9NBLGGH4VVNH", version=None, source="msstore")
        other = Package(name="pympress", id="Cimbali.pympress", version="1.8.6", source="winget", match="Tag: vlc")
        ranked = rank_candidates("vlc", [other, VLC, store])

        self.assertEqual(ranked[0], VLC)
        self.assertEqual(ranked[1], store)
        self.assertEqual(ranked[-1], other)


class CommandSafetyTests(unittest.TestCase):
    def test_package_id_validation(self) -> None:
        for package_id, source in (
            ("VideoLAN.VLC", "winget"),
            ("Notepad++.Notepad++", "winget"),
            ("Python.Python.3.12", "winget"),
            ("Mozilla.Firefox.pt-BR", "winget"),
            ("9NBDXK71NK08", "msstore"),
            ("XP9K09TBWNMDTN", "msstore"),
        ):
            with self.subTest(package_id=package_id):
                self.assertTrue(is_valid_package_id(package_id, source))

        for package_id, source in (
            ("--uninstall", "winget"),
            ("VLC", "winget"),
            ("VideoLAN.VLC && calc", "winget"),
            ("VideoLAN.VLC;rm", "winget"),
            ("Video LAN.VLC", "winget"),
            ('VideoLAN.VLC" --override "x', "winget"),
            ("Some.Truncated.Ident…", "winget"),
            ("VideoLAN.VLC", "msstore"),
            ("9NBDXK71NK08", "winget"),
            ("VideoLAN.VLC", "https://evil.example"),
        ):
            with self.subTest(package_id=package_id, source=source):
                self.assertFalse(is_valid_package_id(package_id, source))

    def test_install_command_is_fixed(self) -> None:
        with patch("installer.shutil.which", return_value=WINGET):
            command = install_command(VLC)

        self.assertEqual(
            command,
            [
                WINGET,
                "install",
                "--id",
                "VideoLAN.VLC",
                "--exact",
                "--source",
                "winget",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
        )

    def test_install_command_rejects_unvalidated_package(self) -> None:
        with patch("installer.shutil.which", return_value=WINGET):
            with self.assertRaises(installer.InstallError):
                install_command(Package(name="x", id="--uninstall", version=None, source="winget"))
            with self.assertRaises(installer.InstallError):
                install_command(Package(name="x", id="VideoLAN.VLC", version=None, source="custom"))

    def test_run_install_maps_winget_exit_codes(self) -> None:
        cases = {
            0: (True, "instalado com sucesso"),
            0x8A150061: (True, "já está instalado"),
            0x8A15010C: (False, "cancelada"),
        }
        for code, (ok, text) in cases.items():
            with self.subTest(code=hex(code)), patch("installer.shutil.which", return_value=WINGET), patch(
                "installer.subprocess.run", return_value=completed("", code)
            ):
                result = run_install(VLC)
                self.assertEqual(result.ok, ok)
                self.assertIn(text, result.message)

    def test_run_install_reports_unknown_failure_with_last_line(self) -> None:
        output = "Found VLC media player [VideoLAN.VLC]\r\nInstaller failed with exit code: 1603\r\n"
        with patch("installer.shutil.which", return_value=WINGET), patch(
            "installer.subprocess.run", return_value=completed(output, 0x8A150006)
        ):
            result = run_install(VLC)

        self.assertFalse(result.ok)
        self.assertIn("0x8a150006", result.message)
        self.assertIn("Installer failed with exit code: 1603", result.message)

    def test_missing_winget_is_reported(self) -> None:
        with patch("installer.shutil.which", return_value=None):
            with self.assertRaises(installer.InstallError) as raised:
                install_command(VLC)
        self.assertIn("winget não está disponível", str(raised.exception))


class InstallToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.show_card = AsyncMock(return_value=True)
        for patcher in (
            patch.object(confirmation, "CONFIRMATION_WAIT_SECONDS", 0.05),
            patch.object(confirmation, "CONFIRMATION_POLL_SECONDS", 0.01),
            patch("installer.shutil.which", return_value=WINGET),
            patch("installer.show_card", self.show_card),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def context(self) -> FakeRunContext:
        context = FakeRunContext(userdata={})
        context.session.generate_reply = MagicMock()
        return context

    async def _search_and_prepare(self, context: FakeRunContext) -> str:
        run = fake_winget({"winget": completed(WINGET_VLC), "msstore": completed(MSSTORE_VLC)})
        with patch("installer.subprocess.run", run):
            await search_apps(context, query="VLC")
        await prepare_app_install(context, package_id="VideoLAN.VLC", source="winget")
        return context.userdata[PENDING_INSTALL_KEY]["code"]

    async def _confirm(self, context: FakeRunContext, heard: str, code: str, run: MagicMock) -> str:
        context.session.history = FakeHistory([FakeMessage(role="user", text_content=heard)])
        with patch("installer.subprocess.run", run):
            result = await confirm_app_install(context, code=code)
            await asyncio.gather(*installer._INSTALL_TASKS)
        return result

    async def test_search_lists_best_candidates_and_shows_card(self) -> None:
        context = self.context()
        run = fake_winget({"winget": completed(WINGET_VLC), "msstore": completed(MSSTORE_VLC)})

        with patch("installer.subprocess.run", run):
            result = await search_apps(context, query="VLC")

        self.assertIn("1. VLC media player — ID VideoLAN.VLC, versão 3.0.24, fonte winget", result)
        self.assertIn("2. VLC — ID 9NBLGGH4VVNH, versão não informada, fonte Microsoft Store", result)
        self.assertIn("Nada foi instalado", result)
        self.assertEqual(context.userdata[SEARCH_KEY][0]["id"], "VideoLAN.VLC")
        kind, card = self.show_card.await_args.args
        self.assertEqual((kind, card["status"], card["query"]), ("install", "results", "VLC"))
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[:4], [WINGET, "search", "--query", "VLC"])
            self.assertIn("--accept-source-agreements", args)
            self.assertNotIn("shell", call.kwargs)

    async def test_search_rejects_odd_queries_without_running_winget(self) -> None:
        run = MagicMock()
        with patch("installer.subprocess.run", run):
            for query in ("--uninstall vlc", "vlc; calc", "vlc | del", ""):
                with self.subTest(query=query):
                    result = await search_apps(self.context(), query=query)
                    self.assertIn("Diga só o nome do aplicativo", result)
        run.assert_not_called()

    async def test_search_with_no_results(self) -> None:
        with patch("installer.subprocess.run", fake_winget({})):
            result = await search_apps(self.context(), query="zzzznotapp")
        self.assertIn("Nenhum aplicativo encontrado", result)

    async def test_prepare_requires_a_package_from_the_last_search(self) -> None:
        context = self.context()
        result = await prepare_app_install(context, package_id="Evil.Package", source="winget")

        self.assertIn("não está na última busca", result)
        self.assertNotIn(PENDING_INSTALL_KEY, context.userdata)

    async def test_prepare_creates_code_and_explains_confirmation(self) -> None:
        context = self.context()
        code = await self._search_and_prepare(context)

        result = self.show_card.await_args.args
        self.assertEqual(result[0], "install")
        self.assertEqual(result[1]["status"], "pending")
        self.assertEqual(result[1]["code"], code)
        self.assertEqual(len(code), 6)

        text = await prepare_app_install(context, package_id="videolan.vlc")
        new_code = context.userdata[PENDING_INSTALL_KEY]["code"]
        self.assertIn("ainda NÃO instalada", text)
        self.assertIn(f"confirmar instalação {new_code}", text)
        self.assertIn(spoken_digits(new_code), text)

    async def test_confirmed_install_runs_fixed_command_and_reports(self) -> None:
        context = self.context()
        code = await self._search_and_prepare(context)
        run = MagicMock(return_value=completed("Successfully installed\r\n", 0))

        result = await self._confirm(context, f"Confirmar instalação {code[:3]} {code[3:]}.", code, run)

        self.assertIn("iniciada", result)
        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            [WINGET, "install", "--id", "VideoLAN.VLC", "--exact", "--source", "winget",
             "--accept-package-agreements", "--accept-source-agreements"],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertIsNone(context.userdata[PENDING_INSTALL_KEY])
        statuses = [call.args[1]["status"] for call in self.show_card.await_args_list]
        self.assertEqual(statuses[-2:], ["installing", "installed"])
        announcement = context.session.generate_reply.call_args.kwargs["instructions"]
        self.assertIn("instalado com sucesso", announcement)

    async def test_failed_install_is_reported_honestly(self) -> None:
        context = self.context()
        code = await self._search_and_prepare(context)
        run = MagicMock(return_value=completed("", 0x8A15010C))

        await self._confirm(context, f"confirma instalação {spoken_digits(code)}", code, run)

        last_card = self.show_card.await_args.args[1]
        self.assertEqual(last_card["status"], "failed")
        self.assertIn("cancelada", last_card["message"])
        self.assertIn("cancelada", context.session.generate_reply.call_args.kwargs["instructions"])

    async def test_install_needs_the_spoken_install_phrase(self) -> None:
        for heard in ("Pode instalar", "sim", "confirmar {code}", "não confirmar instalação {code}"):
            with self.subTest(heard=heard):
                context = self.context()
                code = await self._search_and_prepare(context)
                run = MagicMock()

                result = await self._confirm(context, heard.format(code=code), code, run)

                run.assert_not_called()
                self.assertIn("Instalação bloqueada", result)
                self.assertIn(f"confirmar instalação {code}", result)
                self.assertIsNotNone(context.userdata[PENDING_INSTALL_KEY])

    async def test_wrong_code_is_rejected(self) -> None:
        context = self.context()
        code = await self._search_and_prepare(context)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        run = MagicMock()

        result = await self._confirm(context, f"confirmar instalação {wrong}", wrong, run)

        run.assert_not_called()
        self.assertIn("Código de confirmação inválido", result)

    async def test_confirm_without_pending_install(self) -> None:
        result = await confirm_app_install(self.context(), code="123456")
        self.assertIn("Não há nenhuma instalação pendente", result)

    async def test_cancel_clears_pending_install(self) -> None:
        context = self.context()
        await self._search_and_prepare(context)

        result = await cancel_app_install(context)

        self.assertIn("nada foi instalado", result)
        self.assertIsNone(context.userdata[PENDING_INSTALL_KEY])
        self.assertEqual(self.show_card.await_args.args[1]["status"], "cancelled")

    async def test_only_one_install_at_a_time(self) -> None:
        context = self.context()
        code = await self._search_and_prepare(context)
        running = asyncio.get_running_loop().create_future()
        installer._INSTALL_TASKS.add(running)
        self.addCleanup(installer._INSTALL_TASKS.discard, running)

        context.session.history = FakeHistory([FakeMessage(role="user", text_content=f"confirmar instalação {code}")])
        result = await confirm_app_install(context, code=code)
        running.set_result(None)

        self.assertIn("Já existe uma instalação em andamento", result)
        self.assertIsNotNone(context.userdata[PENDING_INSTALL_KEY])


class InstallerRegistrationTests(unittest.TestCase):
    def test_tools_are_opt_in(self) -> None:
        from settings import load_settings
        from tools import build_tools

        base = [tool.__name__ for tool in build_tools(load_settings({"GOOGLE_API_KEY": "k"}))]
        enabled = [
            tool.__name__
            for tool in build_tools(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_APP_INSTALL": "true"}))
        ]

        self.assertNotIn("search_apps", base)
        self.assertEqual(
            enabled[len(base):],
            ["search_apps", "prepare_app_install", "confirm_app_install", "cancel_app_install"],
        )
