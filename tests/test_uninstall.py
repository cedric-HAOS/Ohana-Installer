"""Tests de la commande de désinstallation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ohana_installer.cli import main
from ohana_installer.commands.install import (
    AGENT_INSTALLATION_PATH,
    SHIZUNE_INSTALLATION_PATH,
    VISION_INSTALLATION_PATH,
)
from ohana_installer.systemd import (
    SystemdCommandError,
)


def test_uninstall_removes_services_and_components(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operations: list[str] = []

    monkeypatch.setattr(
        "ohana_installer.commands.uninstall._service_is_installed",
        lambda service_name: True,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.stop_systemd_service",
        lambda service_name: operations.append(f"stop:{service_name}"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.disable_systemd_service",
        lambda service_name: operations.append(f"disable:{service_name}"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.remove_systemd_service",
        lambda service_name: operations.append(f"remove:{service_name}") or True,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.reload_systemd_daemon",
        lambda: operations.append("reload"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.remove_network_administration",
        lambda: operations.append("network-admin") or True,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall._remove_installation_path",
        lambda path: operations.append(f"path:{path}") or True,
    )

    assert main(["uninstall", "--yes"]) == 0

    assert operations == [
        "stop:ohana-agent.service",
        "stop:ohana-vision.service",
        "disable:ohana-agent.service",
        "disable:ohana-vision.service",
        "remove:ohana-agent.service",
        "remove:ohana-vision.service",
        "reload",
        "network-admin",
        f"path:{AGENT_INSTALLATION_PATH}",
        f"path:{VISION_INSTALLATION_PATH}",
        f"path:{SHIZUNE_INSTALLATION_PATH}",
    ]

    output = capsys.readouterr().out

    assert "ohana-agent.service arrêté" in output
    assert "ohana-vision.service désactivé" in output
    assert f"{AGENT_INSTALLATION_PATH} supprimé" in output
    assert f"{VISION_INSTALLATION_PATH} supprimé" in output
    assert f"{SHIZUNE_INSTALLATION_PATH} supprimé" in output
    assert ("Ohana-Agent, Ohana-Vision et Shizune sont désinstallés.") in output
    assert ("Les fichiers de configuration ont été conservés.") in output


def test_uninstall_accepts_already_absent_installation(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall._service_is_installed",
        lambda service_name: False,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall._remove_installation_path",
        lambda path: False,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.NETWORK_HELPER_PATH",
        Path("/definitely/missing/helper"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.NETWORK_SUDOERS_PATH",
        Path("/definitely/missing/sudoers"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.NETWORK_STATE_DIRECTORY",
        Path("/definitely/missing/state"),
    )

    assert main(["uninstall", "--yes"]) == 0

    output = capsys.readouterr().out

    assert "Aucune installation Ohana détectée" in output


def test_uninstall_fails_when_service_stop_fails(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall._service_is_installed",
        lambda service_name: True,
    )

    def raise_stop_error(service_name: str) -> None:
        raise SystemdCommandError(f"arrêt refusé pour {service_name}")

    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.stop_systemd_service",
        raise_stop_error,
    )

    assert main(["uninstall", "--yes"]) == 3

    output = capsys.readouterr().out

    assert "Commande systemd impossible" in output
    assert "arrêt refusé" in output


def test_remove_installation_path_removes_directory(
    tmp_path: Path,
) -> None:
    installation_path = tmp_path / "ohana-agent"
    installation_path.mkdir()
    (installation_path / "file.txt").write_text(
        "content",
        encoding="utf-8",
    )

    from ohana_installer.commands.uninstall import (
        _remove_installation_path,
    )

    removed = _remove_installation_path(
        installation_path,
    )

    assert removed is True
    assert installation_path.exists() is False


def test_remove_installation_path_accepts_missing_directory(
    tmp_path: Path,
) -> None:
    from ohana_installer.commands.uninstall import (
        _remove_installation_path,
    )

    removed = _remove_installation_path(
        tmp_path / "missing",
    )

    assert removed is False


def test_uninstall_cancellation_prevents_service_changes(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "ohana_installer.commands.uninstall._service_is_installed",
        lambda service_name: True,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    def fail_if_called(service_name: str) -> None:
        raise AssertionError("Le service ne doit pas être arrêté.")

    monkeypatch.setattr(
        "ohana_installer.commands.uninstall.stop_systemd_service",
        fail_if_called,
    )

    assert main(["uninstall"]) == 0
    assert "Désinstallation annulée" in capsys.readouterr().out
