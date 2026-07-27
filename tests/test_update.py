"""Tests de la commande de mise à jour."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ohana_installer.administration import AdministrationPreparation
from ohana_installer.cli import main
from ohana_installer.commands import update as update_command
from ohana_installer.environment import EnvironmentCheck
from ohana_installer.github import (
    DownloadedComponent,
    DownloadError,
    GitHubRelease,
    GitHubReleaseAsset,
)
from ohana_installer.manifest import (
    CompatibilityManifest,
    ComponentManifest,
    ComponentPackage,
    PlatformManifest,
    RuntimeManifest,
)
from ohana_installer.python_package import InstalledPythonComponent
from ohana_installer.system_account import SystemAccount
from ohana_installer.systemd import (
    GeneratedSystemdService,
    InstalledSystemdService,
    SystemdCommandError,
    SystemdServiceStatus,
)
from ohana_installer.version import __version__

_prepare_installer_update = update_command._prepare_installer_update


@pytest.fixture(autouse=True)
def _skip_installer_self_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_command,
        "_prepare_installer_update",
        lambda temporary_path, *, assume_yes: "current",
    )


@pytest.fixture(autouse=True)
def _prepare_administration_without_system_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = AdministrationPreparation(
        configured=True,
        dhcp_enabled=False,
        token_created=False,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update.prepare_administration",
        lambda: preparation,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update.activate_administration",
        lambda _administration: None,
    )


def _build_manifest() -> PlatformManifest:
    return PlatformManifest(
        schema_version=1,
        platform_name="Ohana",
        platform_version="1.1.0",
        runtime=RuntimeManifest(
            minimum_python_version="3.12",
        ),
        components=(
            ComponentManifest(
                identifier="agent",
                name="Ohana-Agent",
                repository="cedric-HAOS/Ohana-Agent",
                version="1.1.0",
                release_tag="v1.1.0",
                package=ComponentPackage(
                    type="wheel",
                    filename="ohana_agent-1.1.0-py3-none-any.whl",
                ),
            ),
            ComponentManifest(
                identifier="vision",
                name="Ohana-Vision",
                repository="cedric-HAOS/Ohana-Vision",
                version="1.1.0",
                release_tag="v1.1.0",
                package=ComponentPackage(
                    type="wheel",
                    filename="ohana_vision-1.1.0-py3-none-any.whl",
                ),
            ),
        ),
        compatibility=CompatibilityManifest(
            operating_system_family="Linux",
            service_manager="systemd",
        ),
    )


def _build_downloaded_components(
    manifest: PlatformManifest,
    directory: Path,
) -> tuple[DownloadedComponent, ...]:
    return tuple(
        DownloadedComponent(
            component=component,
            path=directory / component.package.filename,
        )
        for component in manifest.components
    )


def _build_generated_services(
    manifest: PlatformManifest,
    directory: Path,
) -> tuple[GeneratedSystemdService, ...]:
    return tuple(
        GeneratedSystemdService(
            component=component,
            path=directory / f"ohana-{component.identifier}.service",
            content="[Unit]\n",
        )
        for component in manifest.components
    )


def _build_installed_services(
    manifest: PlatformManifest,
) -> tuple[InstalledSystemdService, ...]:
    return tuple(
        InstalledSystemdService(
            component=component,
            source_path=Path(f"/tmp/ohana-{component.identifier}.service"),
            destination_path=Path(f"/etc/systemd/system/ohana-{component.identifier}.service"),
            created=False,
            updated=True,
        )
        for component in manifest.components
    )


def _build_installed_component(
    name: str,
    command_name: str,
    version: str = "1.1.0",
) -> InstalledPythonComponent:
    identifier = command_name.removeprefix("ohana-")

    return InstalledPythonComponent(
        name=name,
        version=version,
        environment_path=Path(f"/opt/ohana-{identifier}/venv"),
        executable_path=Path(f"/opt/ohana-{identifier}/venv/bin/{command_name}"),
    )


def _installer_release(
    version: str,
    *,
    include_wheel: bool = True,
) -> GitHubRelease:
    assets: tuple[GitHubReleaseAsset, ...] = ()

    if include_wheel:
        assets = (
            GitHubReleaseAsset(
                name=f"ohana_installer-{version}-py3-none-any.whl",
                download_url="https://example.invalid/installer.whl",
                sha256="a" * 64,
                size=5,
            ),
        )

    return GitHubRelease(
        repository="cedric-HAOS/Ohana-Installer",
        tag_name=f"v{version}",
        assets=assets,
    )


def test_installer_self_update_stops_when_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        update_command,
        "discover_latest_release",
        lambda repository: _installer_release(__version__),
    )

    result = _prepare_installer_update(
        tmp_path,
        assume_yes=False,
    )

    assert result == "current"
    assert "déjà à jour" in capsys.readouterr().out


def test_installer_self_update_downloads_upgrades_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release = _installer_release("1.0.3")
    operations: list[str] = []

    monkeypatch.setattr(
        update_command,
        "discover_latest_release",
        lambda repository: release,
    )
    monkeypatch.setattr(
        update_command,
        "confirm_action",
        lambda message, *, assume_yes: assume_yes,
    )

    def download_asset(asset, destination):
        operations.append(f"download:{asset.name}")
        destination.write_bytes(b"wheel")
        return destination

    monkeypatch.setattr(
        update_command,
        "download_release_asset",
        download_asset,
    )
    monkeypatch.setattr(
        update_command,
        "upgrade_wheel",
        lambda wheel_path, *, python_executable: operations.append(
            f"upgrade:{wheel_path.name}:{python_executable}"
        ),
    )
    monkeypatch.setattr(
        update_command,
        "verify_component_command",
        lambda **kwargs: InstalledPythonComponent(
            name="Ohana-Installer",
            version="1.0.3",
            environment_path=Path(sys.prefix),
            executable_path=Path(sys.prefix) / "bin" / "ohana",
        ),
    )

    result = _prepare_installer_update(
        tmp_path,
        assume_yes=True,
    )

    assert result == "updated"
    assert operations == [
        "download:ohana_installer-1.0.3-py3-none-any.whl",
        (f"upgrade:ohana_installer-1.0.3-py3-none-any.whl:{sys.executable}"),
    ]
    output = capsys.readouterr().out
    assert "1.0.3 téléchargé et vérifié" in output
    assert "1.0.3 mis à jour" in output


def test_installer_self_update_can_be_declined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_command,
        "discover_latest_release",
        lambda repository: _installer_release("1.0.3"),
    )
    monkeypatch.setattr(
        update_command,
        "confirm_action",
        lambda message, *, assume_yes: False,
    )
    monkeypatch.setattr(
        update_command,
        "download_release_asset",
        lambda *args, **kwargs: pytest.fail("Le wheel ne doit pas être téléchargé."),
    )

    assert (
        _prepare_installer_update(
            tmp_path,
            assume_yes=False,
        )
        == "declined"
    )


def test_installer_self_update_requires_one_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_command,
        "discover_latest_release",
        lambda repository: _installer_release(
            "1.0.3",
            include_wheel=False,
        ),
    )
    monkeypatch.setattr(
        update_command,
        "confirm_action",
        lambda message, *, assume_yes: True,
    )

    with pytest.raises(DownloadError, match="exactement un wheel"):
        _prepare_installer_update(
            tmp_path,
            assume_yes=True,
        )


def test_restart_update_reexecutes_current_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: tuple[str, list[str]] | None = None

    class RestartCalled(RuntimeError):
        pass

    def fake_execv(executable: str, arguments: list[str]) -> None:
        nonlocal received
        received = (executable, arguments)
        raise RestartCalled

    monkeypatch.setattr(update_command.os, "execv", fake_execv)

    with pytest.raises(RestartCalled):
        update_command._restart_update(assume_yes=True)

    assert received == (
        sys.executable,
        [
            sys.executable,
            "-m",
            "ohana_installer",
            "update",
            "--yes",
        ],
    )


def test_update_updates_and_restarts_official_components(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _build_manifest()
    generated_services = _build_generated_services(
        manifest,
        Path("/tmp/systemd"),
    )
    installed_services = _build_installed_services(manifest)

    operations: list[str] = []

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_components",
        _build_downloaded_components,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_configurations",
        lambda manifest, directory: operations.append("download-config") or (),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._ensure_service_accounts",
        lambda manifest: (
            operations.append("account")
            or (
                SystemAccount(
                    username="ohana",
                    group_name="ohana",
                    user_created=False,
                    group_created=False,
                ),
            )
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._generate_services",
        lambda manifest, directory: generated_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_configurations",
        lambda downloaded_files: operations.append("config") or (),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._stop_services",
        lambda services: operations.append("stop"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_agent",
        lambda components, *, replace: (
            operations.append(f"agent:{replace}")
            or _build_installed_component(
                "Ohana-Agent",
                "ohana-agent",
            )
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_vision",
        lambda components, *, replace: (
            operations.append(f"vision:{replace}")
            or _build_installed_component(
                "Ohana-Vision",
                "ohana-vision",
            )
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._replace_services",
        lambda services: operations.append("replace") or installed_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._reload_systemd",
        lambda: operations.append("reload"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._enable_services",
        lambda services: operations.append("enable"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._start_services",
        lambda services: operations.append("start"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._check_services",
        lambda services: (
            operations.append("check")
            or (
                SystemdServiceStatus(
                    service_name="ohana-agent.service",
                    active=True,
                    status="active",
                ),
                SystemdServiceStatus(
                    service_name="ohana-vision.service",
                    active=True,
                    status="active",
                ),
            )
        ),
    )

    assert main(["update", "--yes"]) == 0

    assert operations == [
        "download-config",
        "account",
        "config",
        "stop",
        "agent:True",
        "vision:True",
        "replace",
        "reload",
        "enable",
        "start",
        "check",
    ]

    output = capsys.readouterr().out

    assert "Téléchargement des configurations" in output
    assert "Vérification des comptes système" in output
    assert "Compte système ohana prêt" in output
    assert "Vérification des fichiers de configuration" in output
    assert "Arrêt des services systemd" in output
    assert "Ohana-Agent 1.1.0 mis à jour" in output
    assert "Ohana-Vision 1.1.0 mis à jour" in output
    assert "ohana-agent.service est actif" in output
    assert "ohana-vision.service est actif" in output
    assert ("Ohana-Agent et Ohana-Vision sont mis à jour, redémarrés et vérifiés.") in output


def test_update_only_reinstalls_outdated_component(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A current component must stay installed and running."""
    manifest = _build_manifest()
    operations: list[str] = []

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )

    def inspect_component(**kwargs) -> InstalledPythonComponent:
        if kwargs["component_name"] == "Ohana-Agent":
            return _build_installed_component(
                "Ohana-Agent",
                "ohana-agent",
            )

        return _build_installed_component(
            "Ohana-Vision",
            "ohana-vision",
            version="1.0.0",
        )

    monkeypatch.setattr(
        "ohana_installer.commands.update.inspect_installed_component",
        inspect_component,
    )

    def selected_identifiers(selected_manifest: PlatformManifest) -> str:
        return ",".join(component.identifier for component in selected_manifest.components)

    def download_components(
        selected_manifest: PlatformManifest,
        directory: Path,
    ) -> tuple[DownloadedComponent, ...]:
        operations.append(f"download:{selected_identifiers(selected_manifest)}")
        return _build_downloaded_components(
            selected_manifest,
            directory,
        )

    monkeypatch.setattr(
        "ohana_installer.commands.update._download_components",
        download_components,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_configurations",
        lambda selected_manifest, directory: (
            operations.append(f"download-config:{selected_identifiers(selected_manifest)}") or ()
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._ensure_service_accounts",
        lambda selected_manifest: (
            operations.append(f"accounts:{selected_identifiers(selected_manifest)}") or ()
        ),
    )

    def generate_services(
        selected_manifest: PlatformManifest,
        directory: Path,
    ) -> tuple[GeneratedSystemdService, ...]:
        operations.append(f"generate:{selected_identifiers(selected_manifest)}")
        return _build_generated_services(
            selected_manifest,
            directory,
        )

    monkeypatch.setattr(
        "ohana_installer.commands.update._generate_services",
        generate_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_configurations",
        lambda downloaded_files: operations.append("config") or (),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._stop_services",
        lambda services: operations.append(
            "stop:" + ",".join(service.component.identifier for service in services)
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_agent",
        lambda components, *, replace: pytest.fail("Ohana-Agent ne doit pas être réinstallé."),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_vision",
        lambda components, *, replace: (
            operations.append(f"vision:{replace}")
            or _build_installed_component(
                "Ohana-Vision",
                "ohana-vision",
            )
        ),
    )

    def replace_services(
        services: tuple[GeneratedSystemdService, ...],
    ) -> tuple[InstalledSystemdService, ...]:
        operations.append(
            "replace:" + ",".join(service.component.identifier for service in services)
        )
        selected_manifest = replace(
            manifest,
            components=tuple(service.component for service in services),
        )
        return _build_installed_services(selected_manifest)

    monkeypatch.setattr(
        "ohana_installer.commands.update._replace_services",
        replace_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._reload_systemd",
        lambda: operations.append("reload"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._enable_services",
        lambda services: operations.append(
            "enable:" + ",".join(service.component.identifier for service in services)
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._start_services",
        lambda services: operations.append(
            "start:" + ",".join(service.component.identifier for service in services)
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._check_services",
        lambda services: (
            operations.append(
                "check:" + ",".join(service.component.identifier for service in services)
            )
            or (
                SystemdServiceStatus(
                    service_name="ohana-agent.service",
                    active=True,
                    status="active",
                ),
                SystemdServiceStatus(
                    service_name="ohana-vision.service",
                    active=True,
                    status="active",
                ),
            )
        ),
    )

    assert main(["update", "--yes"]) == 0

    assert operations == [
        "download:vision",
        "download-config:agent,vision",
        "accounts:agent,vision",
        "generate:agent,vision",
        "config",
        "stop:agent,vision",
        "vision:True",
        "replace:agent,vision",
        "reload",
        "enable:agent,vision",
        "start:agent,vision",
        "check:agent,vision",
    ]

    output = capsys.readouterr().out
    assert "Ohana-Agent: 1.1.0 → 1.1.0 (déjà à jour, conservé)" in output
    assert "Mise à jour d'Ohana-Agent" not in output
    assert "Mise à jour d'Ohana-Vision" in output
    assert "Ohana-Vision est mis à jour, redémarré et vérifié." in output


def test_update_fails_when_environment_is_incompatible(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_called = False

    def load_manifest(directory: Path) -> PlatformManifest:
        del directory

        nonlocal manifest_called
        manifest_called = True

        return _build_manifest()

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=False,
                message="Non compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        load_manifest,
    )

    assert main(["update", "--yes"]) == 3
    assert manifest_called is False

    output = capsys.readouterr().out
    assert "ne permet pas de poursuivre la mise à jour" in output


def test_update_fails_when_service_stop_fails(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _build_manifest()
    generated_services = _build_generated_services(
        manifest,
        Path("/tmp/systemd"),
    )

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_components",
        _build_downloaded_components,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._generate_services",
        lambda manifest, directory: generated_services,
    )

    def raise_stop_error(
        services: tuple[GeneratedSystemdService, ...],
    ) -> None:
        del services
        raise SystemdCommandError("arrêt refusé")

    monkeypatch.setattr(
        "ohana_installer.commands.update._stop_services",
        raise_stop_error,
    )

    assert main(["update", "--yes"]) == 3

    output = capsys.readouterr().out
    assert "Commande systemd impossible" in output
    assert "arrêt refusé" in output


def test_update_fails_when_service_remains_inactive(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _build_manifest()
    generated_services = _build_generated_services(
        manifest,
        Path("/tmp/systemd"),
    )
    installed_services = _build_installed_services(manifest)

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_components",
        _build_downloaded_components,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._generate_services",
        lambda manifest, directory: generated_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._stop_services",
        lambda services: None,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_agent",
        lambda components, *, replace: _build_installed_component(
            "Ohana-Agent",
            "ohana-agent",
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_vision",
        lambda components, *, replace: _build_installed_component(
            "Ohana-Vision",
            "ohana-vision",
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._replace_services",
        lambda services: installed_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._reload_systemd",
        lambda: None,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._enable_services",
        lambda services: None,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._start_services",
        lambda services: None,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._check_services",
        lambda services: (
            SystemdServiceStatus(
                service_name="ohana-agent.service",
                active=False,
                status="failed",
            ),
            SystemdServiceStatus(
                service_name="ohana-vision.service",
                active=True,
                status="active",
            ),
        ),
    )

    assert main(["update", "--yes"]) == 3

    output = capsys.readouterr().out
    assert "ohana-agent.service est failed" in output
    assert "ohana-vision.service est actif" in output


def test_update_cancellation_prevents_component_downloads(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _build_manifest()

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update.inspect_installed_component",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "non")

    def fail_if_called(manifest: PlatformManifest, directory: Path):
        raise AssertionError("Les composants ne doivent pas être téléchargés.")

    monkeypatch.setattr(
        "ohana_installer.commands.update._download_components",
        fail_if_called,
    )

    assert main(["update"]) == 0
    assert "Mise à jour annulée" in capsys.readouterr().out


def test_update_reconciles_platform_when_installed_versions_are_current(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _build_manifest()
    generated_services = _build_generated_services(
        manifest,
        Path("/tmp/systemd"),
    )
    installed_services = _build_installed_services(manifest)
    operations: list[str] = []

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update.inspect_installed_component",
        lambda **kwargs: InstalledPythonComponent(
            name=kwargs["component_name"],
            version="1.1.0",
            environment_path=Path("/opt/ohana/venv"),
            executable_path=Path("/opt/ohana/venv/bin/ohana"),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_components",
        lambda manifest, directory: pytest.fail(
            "Aucun wheel ne doit être téléchargé lorsque les versions sont à jour."
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._download_configurations",
        lambda selected_manifest, directory: operations.append("download-config") or (),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._ensure_service_accounts",
        lambda selected_manifest: operations.append("accounts") or (),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._generate_services",
        lambda selected_manifest, directory: (
            operations.append("generate") or generated_services
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_configurations",
        lambda downloaded_files: operations.append("config") or (),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._stop_services",
        lambda services: operations.append("stop"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_agent",
        lambda components, *, replace: pytest.fail("Ohana-Agent ne doit pas être réinstallé."),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._install_vision",
        lambda components, *, replace: pytest.fail("Ohana-Vision ne doit pas être réinstallé."),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._replace_services",
        lambda services: operations.append("replace") or installed_services,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._reload_systemd",
        lambda: operations.append("reload"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._enable_services",
        lambda services: operations.append("enable"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._start_services",
        lambda services: operations.append("start"),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._check_services",
        lambda services: (
            operations.append("check")
            or (
                SystemdServiceStatus(
                    service_name="ohana-agent.service",
                    active=True,
                    status="active",
                ),
                SystemdServiceStatus(
                    service_name="ohana-vision.service",
                    active=True,
                    status="active",
                ),
            )
        ),
    )

    assert main(["update", "--yes"]) == 0

    assert operations == [
        "download-config",
        "accounts",
        "generate",
        "config",
        "stop",
        "replace",
        "reload",
        "enable",
        "start",
        "check",
    ]

    output = capsys.readouterr().out
    assert "1.1.0 → 1.1.0" in output
    assert "utilisent déjà" in output
    assert "Aucun package Python à télécharger" in output
    assert "composition Platform va néanmoins être réconciliée" in output
    assert "Composition Ohana Platform réconciliée" in output


def test_update_refuses_automatic_downgrade(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _build_manifest()

    monkeypatch.setattr(
        "ohana_installer.commands.update.run_environment_checks",
        lambda: (
            EnvironmentCheck(
                name="Linux",
                success=True,
                message="Compatible.",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update._load_official_manifest",
        lambda directory: manifest,
    )
    monkeypatch.setattr(
        "ohana_installer.commands.update.inspect_installed_component",
        lambda **kwargs: InstalledPythonComponent(
            name=kwargs["component_name"],
            version="2.0.0",
            environment_path=Path("/opt/ohana/venv"),
            executable_path=Path("/opt/ohana/venv/bin/ohana"),
        ),
    )

    assert main(["update", "--yes"]) == 3
    assert "rétrogradation automatique est refusée" in capsys.readouterr().out
