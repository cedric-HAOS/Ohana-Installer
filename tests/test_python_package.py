"""Tests de l'installation des packages Python."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ohana_installer.python_package import (
    PackageInstallationError,
    create_virtual_environment,
    get_environment_executable,
    inspect_installed_component,
    install_wheel,
    upgrade_wheel,
    verify_component_command,
)


def test_create_virtual_environment_runs_python_venv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_path = tmp_path / "venv"
    received_command: list[str] | None = None

    def fake_run_command(
        command: list[str],
        *,
        timeout: float,
        error_message: str,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command

        received_command = command

        assert timeout == 120.0
        assert "Impossible de créer" in error_message

        environment_path.mkdir()

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        fake_run_command,
    )

    result = create_virtual_environment(
        environment_path,
        python_executable="/usr/bin/python3",
    )

    assert result == environment_path
    assert received_command == [
        "/usr/bin/python3",
        "-m",
        "venv",
        str(environment_path),
    ]


def test_create_virtual_environment_rejects_existing_path(
    tmp_path: Path,
) -> None:
    environment_path = tmp_path / "venv"
    environment_path.mkdir()

    with pytest.raises(
        PackageInstallationError,
        match="existe déjà",
    ):
        create_virtual_environment(environment_path)


def test_install_wheel_runs_environment_pip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_path = tmp_path / "venv"
    wheel_path = tmp_path / "ohana_agent.whl"
    wheel_path.write_bytes(b"wheel")

    pip_path = get_environment_executable(
        environment_path,
        "pip",
    )
    pip_path.parent.mkdir(parents=True)
    pip_path.write_text("", encoding="utf-8")

    received_command: list[str] | None = None

    def fake_run_command(
        command: list[str],
        *,
        timeout: float,
        error_message: str,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command

        received_command = command

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        fake_run_command,
    )

    install_wheel(
        wheel_path,
        environment_path,
    )

    assert received_command == [
        str(pip_path),
        "install",
        "--disable-pip-version-check",
        str(wheel_path),
    ]


def test_upgrade_wheel_uses_current_python_and_upgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wheel_path = tmp_path / "ohana_installer.whl"
    wheel_path.write_bytes(b"wheel")
    received_command: list[str] | None = None

    def fake_run_command(
        command: list[str],
        *,
        timeout: float,
        error_message: str,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command
        assert timeout == 120.0
        assert "mettre à niveau" in error_message
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        fake_run_command,
    )

    upgrade_wheel(
        wheel_path,
        python_executable="/opt/ohana-installer/bin/python",
    )

    assert received_command == [
        "/opt/ohana-installer/bin/python",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        str(wheel_path),
    ]


def test_install_wheel_rejects_missing_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        PackageInstallationError,
        match="wheel est introuvable",
    ):
        install_wheel(
            tmp_path / "missing.whl",
            tmp_path / "venv",
        )


def test_verify_component_command_accepts_expected_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_path = tmp_path / "venv"
    executable_path = get_environment_executable(
        environment_path,
        "ohana-agent",
    )
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")

    def fake_run_command(
        command: list[str],
        *,
        timeout: float,
        error_message: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="ohana-agent 1.0.0\n",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        fake_run_command,
    )

    result = verify_component_command(
        environment_path=environment_path,
        command_name="ohana-agent",
        expected_version="1.0.0",
        component_name="Ohana-Agent",
    )

    assert result.name == "Ohana-Agent"
    assert result.version == "1.0.0"
    assert result.executable_path == executable_path


def test_verify_component_command_rejects_unexpected_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_path = tmp_path / "venv"
    executable_path = get_environment_executable(
        environment_path,
        "ohana-agent",
    )
    executable_path.parent.mkdir(parents=True)
    executable_path.write_text("", encoding="utf-8")

    def fake_run_command(
        command: list[str],
        *,
        timeout: float,
        error_message: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="ohana-agent 0.9.0\n",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        fake_run_command,
    )

    with pytest.raises(
        PackageInstallationError,
        match="Version inattendue",
    ):
        verify_component_command(
            environment_path=environment_path,
            command_name="ohana-agent",
            expected_version="1.0.0",
            component_name="Ohana-Agent",
        )


def test_secured_file_mode_preserves_executability() -> None:
    from ohana_installer.python_package import _secured_file_mode

    assert _secured_file_mode(0o100755) == 0o750
    assert _secured_file_mode(0o100644) == 0o640


def test_secure_installation_tree_applies_owner_group_and_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ohana_installer.python_package import secure_installation_tree

    installation_path = tmp_path / "ohana-agent"
    package_directory = installation_path / "venv" / "lib"
    package_directory.mkdir(parents=True)
    module_path = package_directory / "module.py"
    module_path.write_text("value = 1\n", encoding="utf-8")

    owners: list[tuple[Path, str, str]] = []
    modes: dict[Path, int] = {}

    monkeypatch.setattr(
        "ohana_installer.python_package.shutil.chown",
        lambda path, *, user, group: owners.append((Path(path), user, group)),
    )
    monkeypatch.setattr(
        Path,
        "chmod",
        lambda self, mode: modes.__setitem__(self, mode),
    )

    secure_installation_tree(
        installation_path,
        owner="root",
        group="ohana",
    )

    expected_paths = {
        installation_path,
        installation_path / "venv",
        package_directory,
        module_path,
    }

    assert {path for path, _, _ in owners} == expected_paths
    assert all(owner == "root" for _, owner, _ in owners)
    assert all(group == "ohana" for _, _, group in owners)
    assert modes[installation_path] == 0o750
    assert modes[installation_path / "venv"] == 0o750
    assert modes[package_directory] == 0o750
    assert modes[module_path] == 0o640


def test_secure_installation_tree_rejects_missing_directory(
    tmp_path: Path,
) -> None:
    from ohana_installer.python_package import secure_installation_tree

    with pytest.raises(
        PackageInstallationError,
        match="répertoire d'installation est introuvable",
    ):
        secure_installation_tree(
            tmp_path / "missing",
            owner="root",
            group="ohana",
        )


def test_inspect_installed_component_returns_none_when_command_is_missing(
    tmp_path: Path,
) -> None:
    assert (
        inspect_installed_component(
            environment_path=tmp_path / "venv",
            command_name="ohana-agent",
            component_name="Ohana-Agent",
        )
        is None
    )


def test_inspect_installed_component_reads_exact_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_path = tmp_path / "venv"
    executable_path = get_environment_executable(
        environment_path,
        "ohana-agent",
    )
    executable_path.parent.mkdir(parents=True)
    executable_path.touch()

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        lambda command, *, timeout, error_message: subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="ohana-agent 1.2.3\n",
            stderr="",
        ),
    )

    result = inspect_installed_component(
        environment_path=environment_path,
        command_name="ohana-agent",
        component_name="Ohana-Agent",
    )

    assert result is not None
    assert result.version == "1.2.3"
    assert result.executable_path == executable_path


def test_inspect_installed_component_rejects_ambiguous_version_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_path = tmp_path / "venv"
    executable_path = get_environment_executable(
        environment_path,
        "ohana-agent",
    )
    executable_path.parent.mkdir(parents=True)
    executable_path.touch()

    monkeypatch.setattr(
        "ohana_installer.python_package._run_command",
        lambda command, *, timeout, error_message: subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="ohana-agent 1.2.3 (runtime 3.12.0)\n",
            stderr="",
        ),
    )

    with pytest.raises(
        PackageInstallationError,
        match="Version illisible",
    ):
        inspect_installed_component(
            environment_path=environment_path,
            command_name="ohana-agent",
            component_name="Ohana-Agent",
        )
