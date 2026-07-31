"""Préparation sécurisée du flux d'administration Agent/Vision."""

from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from ohana_installer.network import (
    AGENT_NETWORK_HELPER_ENTRYPOINT,
    NETWORK_HELPER_PATH,
    NETWORK_SUDOERS_PATH,
    NMCLI_PATH,
    VISUDO_PATH,
    NetworkAdministrationPreparation,
    NetworkProvisioningError,
    prepare_network_administration,
)
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
    "home-assistant-telemetry.yaml",
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
DHCP_RELOAD_HELPER_PATH = Path("/opt/ohana-agent/venv/bin/ohana-agent-dhcp-reload-helper")
NETWORK_ADMINISTRATION_MINIMUM_AGENT_VERSION = (1, 11, 0)
DHCP_LEASE_PURGE_MINIMUM_AGENT_VERSION = (1, 11, 1)


class AdministrationPreparationError(RuntimeError):
    """Erreur pendant la préparation de l'administration."""


@dataclass(frozen=True)
class AdministrationPreparation:
    """Résultat de la préparation du flux d'administration."""

    configured: bool
    dhcp_enabled: bool
    token_created: bool
    network_enabled: bool = False
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
    network_helper_path: Path = NETWORK_HELPER_PATH,
    network_sudoers_path: Path = NETWORK_SUDOERS_PATH,
    network_entrypoint_path: Path = AGENT_NETWORK_HELPER_ENTRYPOINT,
    nmcli_path: Path = NMCLI_PATH,
    visudo_path: Path = VISUDO_PATH,
    agent_version: str | None = None,
) -> AdministrationPreparation:
    """Configurer automatiquement les échanges d'administration locaux."""
    if require_linux and os.name != "posix":
        return AdministrationPreparation(
            configured=False,
            dhcp_enabled=False,
            token_created=False,
            network_enabled=False,
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

    network_supported = supports_network_administration(agent_version)
    dhcp_lease_purge_supported = supports_dhcp_lease_purge(agent_version)

    _append_section_if_missing(
        agent_configuration_path,
        section_name="administration",
        content=_agent_administration_section(
            dhcp_enabled=dhcp_enabled,
            token_path=agent_token_path,
            network_supported=network_supported,
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

    if network_supported:
        try:
            network_preparation = prepare_network_administration(
                helper_path=network_helper_path,
                sudoers_path=network_sudoers_path,
                entrypoint_path=network_entrypoint_path,
                nmcli_path=nmcli_path,
                visudo_path=visudo_path,
                secure_ownership=secure_ownership,
            )
        except NetworkProvisioningError as error:
            raise AdministrationPreparationError(str(error)) from error

        _ensure_agent_network_section(
            agent_configuration_path,
            enabled=network_preparation.enabled,
            helper_path=network_helper_path,
        )
    else:
        _remove_agent_network_section(agent_configuration_path)
        network_preparation = NetworkAdministrationPreparation(
            enabled=False,
            helper_installed=False,
            sudoers_installed=False,
        )

    installed_units: tuple[Path, ...] = ()

    if dhcp_enabled:
        _prepare_dnsmasq_files(
            dnsmasq_configuration_directory,
            secure_ownership=secure_ownership,
        )
        installed_units = _install_reload_units(
            systemd_directory,
            purge_stale_leases=dhcp_lease_purge_supported,
        )

    return AdministrationPreparation(
        configured=True,
        dhcp_enabled=dhcp_enabled,
        token_created=token_created,
        network_enabled=network_preparation.enabled,
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
    network_supported: bool,
) -> str:
    enabled = "true" if dhcp_enabled else "false"

    lines = [
        "administration:",
        "  enabled: true",
        "  host: 127.0.0.1",
        "  port: 8765",
        f"  token_file: {token_path.as_posix()}",
    ]
    if network_supported:
        lines.extend(
            [
                "  network:",
                "    enabled: false",
                "    helper_path: /usr/local/sbin/ohana-network-helper",
                "    sudo_path: /usr/bin/sudo",
                "    rollback_seconds: 90",
            ]
        )
    lines.extend(
        [
            "  dhcp:",
            f"    enabled: {enabled}",
            "",
        ]
    )
    return "\n".join(lines)


def _ensure_agent_network_section(
    path: Path,
    *,
    enabled: bool,
    helper_path: Path,
) -> None:
    """Ajouter ou mettre à jour la section réseau sans dupliquer administration."""
    content = path.read_text(encoding="utf-8")
    enabled_text = "true" if enabled else "false"
    if "  network:\n" in content:
        lines = content.splitlines()
        in_network = False
        for index, line in enumerate(lines):
            if line == "  network:":
                in_network = True
                continue
            if in_network and line.startswith("  ") and not line.startswith("    "):
                in_network = False
            if in_network and line.strip().startswith("enabled:"):
                lines[index] = f"    enabled: {enabled_text}"
            if in_network and line.strip().startswith("helper_path:"):
                lines[index] = f"    helper_path: {helper_path.as_posix()}"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return

    lines = content.splitlines()
    insertion_index = None
    for index, line in enumerate(lines):
        if line.startswith("  dhcp:"):
            insertion_index = index
            break
    block = [
        "  network:",
        f"    enabled: {enabled_text}",
        f"    helper_path: {helper_path.as_posix()}",
        "    sudo_path: /usr/bin/sudo",
        "    rollback_seconds: 90",
    ]
    if insertion_index is None:
        lines.extend(block)
    else:
        lines[insertion_index:insertion_index] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def supports_network_administration(agent_version: str | None) -> bool:
    """Indiquer si la version Agent comprend le contrat NetworkManager du Lot C."""
    return _supports_agent_version(
        agent_version,
        minimum=NETWORK_ADMINISTRATION_MINIMUM_AGENT_VERSION,
    )


def supports_dhcp_lease_purge(agent_version: str | None) -> bool:
    """Indiquer si Agent fournit le helper de purge ciblée des baux DHCP."""
    return _supports_agent_version(
        agent_version,
        minimum=DHCP_LEASE_PURGE_MINIMUM_AGENT_VERSION,
    )


def _supports_agent_version(
    agent_version: str | None,
    *,
    minimum: tuple[int, int, int],
) -> bool:
    if agent_version is None:
        return True
    try:
        parts = tuple(int(part) for part in agent_version.split("."))
    except ValueError as error:
        raise AdministrationPreparationError(
            f"Version Ohana-Agent invalide : {agent_version}."
        ) from error
    if len(parts) != 3:
        raise AdministrationPreparationError(f"Version Ohana-Agent invalide : {agent_version}.")
    return parts >= minimum


def _remove_agent_network_section(path: Path) -> None:
    """Retirer la section inconnue des Agents antérieurs à la version 1.11.0."""
    lines = path.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index] != "  network:":
            result.append(lines[index])
            index += 1
            continue
        index += 1
        while index < len(lines) and (lines[index].startswith("    ") or not lines[index].strip()):
            index += 1
    path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8", newline="\n")


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
    *,
    purge_stale_leases: bool,
) -> tuple[Path, ...]:
    systemd_directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    service_path = systemd_directory / DHCP_RELOAD_SERVICE_NAME
    path_unit_path = systemd_directory / DHCP_RELOAD_PATH_NAME
    service_path.write_text(
        _reload_service_content(purge_stale_leases=purge_stale_leases),
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


def _reload_service_content(*, purge_stale_leases: bool) -> str:
    lines = [
        "[Unit]",
        "Description=Apply an Ohana DHCP update",
        "After=dnsmasq.service",
        "",
        "[Service]",
        "Type=oneshot",
    ]

    if purge_stale_leases:
        lines.extend(
            [
                f"ExecStart={DHCP_RELOAD_HELPER_PATH}",
                "NoNewPrivileges=true",
                "ProtectSystem=strict",
                "ProtectHome=true",
                "PrivateTmp=true",
                "ReadWritePaths=/var/lib/misc",
            ]
        )
    else:
        lines.append("ExecStart=/usr/bin/systemctl reload-or-restart dnsmasq.service")

    return "\n".join([*lines, ""])


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
