from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

import jarvis
from jarvis import _build_stale, _dependencies_stale


class WebDependenciesTests(unittest.TestCase):
    def test_installs_when_missing_or_when_the_lock_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            web = Path(folder)
            lock = web / "package-lock.json"
            lock.write_text("{}", encoding="utf-8")
            self.assertTrue(_dependencies_stale(web))  # nunca instalado

            installed = web / "node_modules" / ".package-lock.json"
            installed.parent.mkdir()
            installed.write_text("{}", encoding="utf-8")
            os.utime(lock, (1_000, 1_000))
            os.utime(installed, (2_000, 2_000))
            self.assertFalse(_dependencies_stale(web))  # instalado depois do lock

            os.utime(lock, (3_000, 3_000))  # um pull trouxe dependência nova
            self.assertTrue(_dependencies_stale(web))


class WebBuildTests(unittest.TestCase):
    def web(self, folder: str) -> Path:
        web = Path(folder)
        (web / "src" / "components").mkdir(parents=True)
        (web / "src" / "components" / "Painel.tsx").write_text("x", encoding="utf-8")
        (web / "index.html").write_text("x", encoding="utf-8")
        for path in web.rglob("*"):
            os.utime(path, (1_000, 1_000))
        return web

    def build(self, web: Path, when: int) -> Path:
        built = web / "dist" / "index.html"
        built.parent.mkdir(exist_ok=True)
        built.write_text("x", encoding="utf-8")
        os.utime(built, (when, when))
        return built

    def test_build_is_stale_when_missing_or_older_than_the_sources(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            web = self.web(folder)
            self.assertTrue(_build_stale(web))  # nunca compilado
            self.build(web, 2_000)
            self.assertFalse(_build_stale(web))

            os.utime(web / "src" / "components" / "Painel.tsx", (3_000, 3_000))  # um pull mudou o HUD
            self.assertTrue(_build_stale(web))
            self.build(web, 4_000)
            self.assertFalse(_build_stale(web))
            os.utime(web / "index.html", (5_000, 5_000))
            self.assertTrue(_build_stale(web))

    def test_changed_interface_is_rebuilt_on_start(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            web = self.web(folder)
            self.build(web, 500)  # mais velho que as fontes
            with patch.object(jarvis, "WEB_DIR", web), patch("jarvis.shutil.which", return_value="npm"), patch("jarvis._dependencies_stale", return_value=False), patch("jarvis.subprocess.run") as run:
                self.assertTrue(jarvis._ensure_web_build(False))
            run.assert_called_once_with(["npm", "run", "build"], cwd=web, check=True)

    def test_fresh_build_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            web = self.web(folder)
            self.build(web, 9_000)
            with patch.object(jarvis, "WEB_DIR", web), patch("jarvis.subprocess.run") as run:
                self.assertTrue(jarvis._ensure_web_build(False))
            run.assert_not_called()

    def test_old_build_still_serves_when_node_is_missing_or_the_build_fails(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as folder:
            web = self.web(folder)
            self.build(web, 500)
            with patch.object(jarvis, "WEB_DIR", web), patch("jarvis.shutil.which", return_value=None):
                self.assertTrue(jarvis._ensure_web_build(False))
            failure = subprocess.CalledProcessError(1, "npm")
            with patch.object(jarvis, "WEB_DIR", web), patch("jarvis.shutil.which", return_value="npm"), patch("jarvis._dependencies_stale", return_value=False), patch("jarvis.subprocess.run", side_effect=failure):
                self.assertTrue(jarvis._ensure_web_build(False))

    def test_first_build_needs_node(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            web = self.web(folder)
            with patch.object(jarvis, "WEB_DIR", web), patch("jarvis.shutil.which", return_value=None):
                self.assertFalse(jarvis._ensure_web_build(False))


if __name__ == "__main__":
    unittest.main()
