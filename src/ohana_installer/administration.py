"""Préparation sécurisée du flux d'administration Agent/Vision."""

from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from ohana_installer.systemd import (
    enable_systemd_service,
    start_systemd_service,
)

AGENT_CONFIGURATION_DIRECTORY = Path("/etc/ohana-agent")
AGENT_CONFIGURATION_PATH = AGENT_CONFIGURATION_DIRECTORY / "shikamaru.yaml"
AGENT_INFRASTRUCTURE_PATH = AGENT_CONFIGURATION_DIRECTORY / "infrastructure.yaml"
AGENT_TOKEN_PATH = AGENT_CONFIGURATION_DIRECTORY / "management.token"
AGENT_PLUGIN_CONFIGURATION_FILENAMES = (
    "dns.yaml",
    "ntp.yaml",
    "mqtt.yaml",
)

VISION_CONFIGURATION_DIRECTORY = Path("/etc/ohana-vision")
VISION_CONFIGURATION_PATH = VISION_CONFIGURATION_DIRECTORY / "vision.yaml"
VISION_TOKEN_PATH = VISION_CONFIGURATION_DIRECTORY / "management.token"

DNSMASQ_EXECUTABLE = Path("/usr/sbin/dnsmasq")
DNSMASQ_CONFIGURATION_DIRECTORY = Path("/etc/dnsmasq.d")
DNSMASQ_MANAGED_FILES = (
    "00-ohana.conf",
    "10-infrastructure.conf",
    "20-serveurs.conf",
    "30-infrastructure-reseau.conf",
    "40-passerelles-domotiques.conf",
    "50-equipements-critiques.conf",
)

SYSTEMD_SYSTEM_DIRECTORY = Path("/etc/systemd/system")
DHCP_RELOAD_SERVICE_NAME = "ohana-dhcp-reload.service"
DHCP_RELOAD_PATH_NAME = "ohana-dhcp-reload.path"


class AdministrationPreparationError(RuntimeError):
    """Erreur pendant la préparation de l'administration."""


@dataclass(frozen=True)
class AdministrationPreparation:
    """Résultat de la préparation du flux d'administration."""

    configured: bool
    dhcp_enabled: bool
    token_created: bool
    units_installed: tuple[Path, ...] = ()


def prepare_administration(
    *,
    agent_configuration_path: Path = AGENT_CONFIGURATION_PATH,
    agent_infrastructure_path: Path = AGENT_INFRASTRUCTURE_PATH,
    agent_token_path: Path = AGENT_TOKEN_PATH,
    vision_configuration_path: Path = VISION_CONFIGURATION_PATH,
    vision_token_path: Path = VISION_TOKEN_PATH,
    dnsmasq_executable: Path = DNSMASQ_EXECUTABLE,
    dnsmasq_configuration_directory: Path = (DNSMASQ_CONFIGURATION_DIRECTORY),
    systemd_directory: Path = SYSTEMD_SYSTEM_DIRECTORY,
    require_linux: bool = True,
    secure_ownership: bool = True,
) -> AdministrationPreparation:
    """Configurer automatiquement les échanges d'administration locaux."""
    if require_linux and os.name != "posix":
        return AdministrationPreparation(
            configured=False,
            dhcp_enabled=False,
            token_created=False,
        )

    required_paths = (
        agent_configuration_path,
        agent_infrastructure_path,
        vision_configuration_path,
    )
    missing_paths = [path for path in required_paths if not path.is_file()]

    if missing_paths:
        missing = ", ".join(str(path) for path in missing_paths)
        raise AdministrationPreparationError(f"Configurations Ohana introuvables : {missing}.")

    dhcp_enabled = dnsmasq_executable.is_file() and dnsmasq_configuration_directory.is_dir()
    token, token_created = _resolve_token(
        agent_token_path,
        vision_token_path,
    )

    _write_token(
        agent_token_path,
        token,
        group_name="ohana-agent",
        secure_ownership=secure_ownership,
    )
    _write_token(
        vision_token_path,
        token,
        group_name="ohana-vision",
        secure_ownership=secure_ownership,
    )

    _append_section_if_missing(
        agent_configuration_path,
        section_name="administration",
        content=_agent_administration_section(
            dhcp_enabled=dhcp_enabled,
            token_path=agent_token_path,
        ),
    )
    _append_section_if_missing(
        vision_configuration_path,
        section_name="agent",
        content=_vision_agent_section(
            token_path=vision_token_path,
        ),
    )

    if secure_ownership:
        _secure_mutable_path(
            agent_infrastructure_path.parent,
            group_name="ohana-agent",
            mode=0o770,
        )
        _secure_mutable_path(
            agent_infrastructure_path,
            group_name="ohana-agent",
            mode=0o660,
        )

    _prepare_plugin_configuration_files(
        agent_configuration_path.parent / "plugins",
        secure_ownership=secure_ownership,
    )

    installed_units: tuple[Path, ...] = ()

    if dhcp_enabled:
        _prepare_dnsmasq_files(
            dnsmasq_configuration_directory,
            secure_ownership=secure_ownership,
        )
        installed_units = _install_reload_units(
            systemd_directory,
        )

    return AdministrationPreparation(
        configured=True,
        dhcp_enabled=dhcp_enabled,
        token_created=token_created,
        units_installed=installed_units,
    )


def activate_administration(
    preparation: AdministrationPreparation,
) -> None:
    """Activer l'unité de surveillance du rechargement DHCP."""
    if not preparation.configured or not preparation.dhcp_enabled:
        return

    enable_systemd_service(
        DHCP_RELOAD_PATH_NAME,
    )
    start_systemd_service(
        DHCP_RELOAD_PATH_NAME,
    )


def _resolve_token(
    agent_token_path: Path,
    vision_token_path: Path,
) -> tuple[str, bool]:
    for path in (
        agent_token_path,
        vision_token_path,
    ):
        if not path.is_file():
            continue

        token = path.read_text(encoding="utf-8").strip()

        if token:
            return token, False

    return secrets.token_urlsafe(48), True


def _write_token(
    path: Path,
    token: str,
    *,
    group_name: str,
    secure_ownership: bool,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        f"{token}\n",
        encoding="utf-8",
        newline="\n",
    )

    if secure_ownership:
        _secure_mutable_path(
            path,
            group_name=group_name,
            mode=0o640,
        )


def _append_section_if_missing(
    path: Path,
    *,
    section_name: str,
    content: str,
) -> None:
    current = path.read_text(encoding="utf-8")

    if any(
        line.rstrip() == f"{section_name}:"
        for line in current.splitlines()
        if line and not line[0].isspace()
    ):
        return

    separator = "" if current.endswith("\n\n") else "\n"
    path.write_text(
        f"{current.rstrip()}\n{separator}{content}",
        encoding="utf-8",
        newline="\n",
    )


def _agent_administration_section(
    *,
    dhcp_enabled: bool,
    token_path: Path,
) -> str:
    enabled = "true" if dhcp_enabled else "false"

    return "\n".join(
        [
            "administration:",
            "  enabled: true",
            "  host: 127.0.0.1",
            "  port: 8765",
            f"  token_file: {token_path.as_posix()}",
            "  dhcp:",
            f"    enabled: {enabled}",
            "",
        ]
    )


def _vision_agent_section(
    *,
    token_path: Path,
) -> str:
    return "\n".join(
        [
            "agent:",
            "  administration_enabled: true",
            "  administration_url: http://127.0.0.1:8765",
            f"  token_file: {token_path.as_posix()}",
            "  timeout_seconds: 5.0",
            "",
        ]
    )


def _prepare_plugin_configuration_files(
    directory: Path,
    *,
    secure_ownership: bool,
) -> None:
    """Préparer les configurations de plugins modifiables par Agent."""
    try:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        raise AdministrationPreparationError(
            f"Impossible de préparer le répertoire des plugins {directory} : {error}"
        ) from error

    if directory.is_symlink() or not directory.is_dir():
        raise AdministrationPreparationError(
            f"Le répertoire des plugins {directory} n'est pas un répertoire régulier."
        )

    if secure_ownership:
        _secure_mutable_path(
            directory,
            group_name="ohana-agent",
            mode=0o770,
        )

    for filename in AGENT_PLUGIN_CONFIGURATION_FILENAMES:
        path = directory / filename

        if not path.exists():
            continue

        if not path.is_file() or path.is_symlink():
            raise AdministrationPreparationError(f"Configuration de plugin non régulière : {path}.")

        if secure_ownership:
            _secure_mutable_path(
                path,
                group_name="ohana-agent",
                mode=0o660,
            )


def _prepare_dnsmasq_files(
    directory: Path,
    *,
    secure_ownership: bool,
) -> None:
    legacy_main_path = directory / "00-ohanna.conf"
    corrected_main_path = directory / "00-ohana.conf"

    if legacy_main_path.is_file() and not corrected_main_path.exists():
        legacy_main_path.replace(corrected_main_path)

    if secure_ownership:
        _secure_mutable_path(
            directory,
            group_name="ohana-agent",
            mode=0o770,
        )

    for filename in DNSMASQ_MANAGED_FILES:
        path = directory / filename

        if not path.exists():
            path.touch()

        if not path.is_file() or path.is_symlink():
            raise AdministrationPreparationError(f"Fichier dnsmasq non régulier : {path}.")

        if secure_ownership:
            _secure_mutable_path(
                path,
                group_name="ohana-agent",
                mode=0o660,
            )


def _secure_mutable_path(
    path: Path,
    *,
    group_name: str,
    mode: int,
) -> None:
    try:
        shutil.chown(
            path,
            user="root",
            group=group_name,
        )
        path.chmod(mode)
    except (LookupError, OSError) as error:
        raise AdministrationPreparationError(
            f"Impossible de sécuriser {path} (root:{group_name}, {mode:04o}) : {error}"
        ) from error


def _install_reload_units(
    systemd_directory: Path,
) -> tuple[Path, ...]:
    systemd_directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    service_path = systemd_directory / DHCP_RELOAD_SERVICE_NAME
    path_unit_path = systemd_directory / DHCP_RELOAD_PATH_NAME
    service_path.write_text(
        _reload_service_content(),
        encoding="utf-8",
        newline="\n",
    )
    path_unit_path.write_text(
        _reload_path_content(),
        encoding="utf-8",
        newline="\n",
    )
    service_path.chmod(0o644)
    path_unit_path.chmod(0o644)

    return (
        service_path,
        path_unit_path,
    )


def _reload_service_content() -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Reload dnsmasq after an Ohana DHCP update",
            "After=dnsmasq.service",
            "",
            "[Service]",
            "Type=oneshot",
            ("ExecStart=/usr/bin/systemctl reload-or-restart dnsmasq.service"),
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "",
        ]
    )


def _reload_path_content() -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Watch Ohana DHCP reload requests",
            "",
            "[Path]",
            ("PathChanged=/run/ohana-agent/dhcp-reload.request"),
            f"Unit={DHCP_RELOAD_SERVICE_NAME}",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )
