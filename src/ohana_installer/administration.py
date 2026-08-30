"""Préparation sécurisée du flux d'administration Agent/Vision."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

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
AGENT_WORKER_TOKEN_PATH = AGENT_CONFIGURATION_DIRECTORY / "katsuyu.token"
AGENT_WORKER_TLS_DIRECTORY = AGENT_CONFIGURATION_DIRECTORY / "tls"
AGENT_WORKER_CA_CERTIFICATE_PATH = AGENT_WORKER_TLS_DIRECTORY / "ca.crt"
AGENT_WORKER_CA_PRIVATE_KEY_PATH = AGENT_WORKER_TLS_DIRECTORY / "ca.key"
AGENT_WORKER_CERTIFICATE_PATH = AGENT_WORKER_TLS_DIRECTORY / "worker.crt"
AGENT_WORKER_PRIVATE_KEY_PATH = AGENT_WORKER_TLS_DIRECTORY / "worker.key"
OPENSSL_PATH = Path("/usr/bin/openssl")
AGENT_PLUGIN_CONFIGURATION_FILENAMES = (
    "dns.yaml",
    "ntp.yaml",
    "mqtt.yaml",
    "home-assistant-telemetry.yaml",
)

VISION_CONFIGURATION_DIRECTORY = Path("/etc/ohana-vision")
VISION_CONFIGURATION_PATH = VISION_CONFIGURATION_DIRECTORY / "vision.yaml"
VISION_TOKEN_PATH = VISION_CONFIGURATION_DIRECTORY / "management.token"
VISION_COMPANION_CA_PATH = VISION_CONFIGURATION_DIRECTORY / "companion-ca.crt"

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
DISTRIBUTED_JOBS_TLS_MINIMUM_AGENT_VERSION = (1, 17, 0)
WAKE_ON_LAN_MINIMUM_AGENT_VERSION = (1, 18, 0)
WAKE_ON_LAN_BATCHING_MINIMUM_AGENT_VERSION = (1, 26, 4)
INFRA_LOG_SOURCE_MINIMUM_AGENT_VERSION = (1, 26, 12)
SHIZUNE_COMPANION_MINIMUM_AGENT_VERSION = (1, 24, 0)


class AdministrationPreparationError(RuntimeError):
    """Erreur pendant la préparation de l'administration."""


@dataclass(frozen=True)
class AdministrationPreparation:
    """Résultat de la préparation du flux d'administration."""

    configured: bool
    dhcp_enabled: bool
    token_created: bool
    network_enabled: bool = False
    jobs_enabled: bool = False
    worker_tls_enabled: bool = False
    companion_enabled: bool = False
    units_installed: tuple[Path, ...] = ()


def prepare_administration(
    *,
    agent_configuration_path: Path = AGENT_CONFIGURATION_PATH,
    agent_infrastructure_path: Path = AGENT_INFRASTRUCTURE_PATH,
    agent_token_path: Path = AGENT_TOKEN_PATH,
    vision_configuration_path: Path = VISION_CONFIGURATION_PATH,
    vision_token_path: Path = VISION_TOKEN_PATH,
    vision_companion_ca_path: Path = VISION_COMPANION_CA_PATH,
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
    worker_token_path: Path = AGENT_WORKER_TOKEN_PATH,
    worker_tls_directory: Path = AGENT_WORKER_TLS_DIRECTORY,
    openssl_path: Path = OPENSSL_PATH,
    worker_dns_name: str = "infra-01.ohana.lan",
    worker_ip_address: str = "192.168.1.10",
) -> AdministrationPreparation:
    """Configurer automatiquement les échanges d'administration locaux."""
    if require_linux and os.name != "posix":
        return AdministrationPreparation(
            configured=False,
            dhcp_enabled=False,
            token_created=False,
            network_enabled=False,
            jobs_enabled=False,
            worker_tls_enabled=False,
            companion_enabled=False,
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
    jobs_tls_supported = supports_distributed_jobs_tls(agent_version)
    wake_on_lan_supported = supports_wake_on_lan(agent_version)
    wake_on_lan_batching_supported = supports_wake_on_lan_batching(agent_version)
    infra_log_source_supported = supports_infra_log_source(agent_version)
    companion_supported = supports_shizune_companion(agent_version)

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

    if jobs_tls_supported:
        worker_token = _resolve_private_token(worker_token_path)
        _write_token(
            worker_token_path,
            worker_token,
            group_name="ohana-agent",
            secure_ownership=secure_ownership,
        )
        worker_tls_paths = _prepare_worker_tls(
            directory=worker_tls_directory,
            openssl_path=openssl_path,
            dns_name=worker_dns_name,
            ip_address=worker_ip_address,
            secure_ownership=secure_ownership,
        )
        _ensure_agent_jobs_section(
            agent_configuration_path,
            worker_token_path=worker_token_path,
            ca_certificate_path=worker_tls_paths["ca_certificate"],
            certificate_path=worker_tls_paths["certificate"],
            private_key_path=worker_tls_paths["private_key"],
        )
        if wake_on_lan_supported:
            _ensure_agent_wake_on_lan_section(
                agent_configuration_path,
                include_batching=wake_on_lan_batching_supported,
            )
        if infra_log_source_supported:
            _ensure_agent_infra_log_source(agent_configuration_path)
        if companion_supported:
            _ensure_agent_companion_section(
                agent_configuration_path,
                ca_certificate_path=worker_tls_paths["ca_certificate"],
                certificate_path=worker_tls_paths["certificate"],
                private_key_path=worker_tls_paths["private_key"],
            )
            _install_vision_companion_ca(
                worker_tls_paths["ca_certificate"],
                vision_companion_ca_path,
                secure_ownership=secure_ownership,
            )
            _ensure_vision_companion_section(
                vision_configuration_path,
                companion_url=f"https://{worker_dns_name}:8767",
                ca_certificate_path=vision_companion_ca_path,
            )

    if secure_ownership:
        _secure_mutable_path(
            agent_infrastructure_path.parent,
            group_name="ohana-agent",
            mode=0o770,
        )
        _secure_mutable_path(
            agent_configuration_path,
            group_name="ohana-agent",
            mode=0o660,
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
        jobs_enabled=jobs_tls_supported,
        worker_tls_enabled=jobs_tls_supported,
        companion_enabled=companion_supported,
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


def _resolve_private_token(path: Path) -> str:
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    return secrets.token_urlsafe(48)


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


def _ensure_agent_jobs_section(
    path: Path,
    *,
    worker_token_path: Path,
    ca_certificate_path: Path,
    certificate_path: Path,
    private_key_path: Path,
) -> None:
    """Enable the existing jobs contract and own only its worker TLS subsection."""
    lines = path.read_text(encoding="utf-8").splitlines()
    administration_start = next(
        (index for index, line in enumerate(lines) if line == "administration:"),
        None,
    )
    if administration_start is None:
        raise AdministrationPreparationError("La section administration Agent est absente.")
    administration_end = _nested_section_end(
        lines,
        administration_start,
        indentation=0,
    )
    jobs_start = next(
        (
            index
            for index in range(administration_start + 1, administration_end)
            if lines[index] == "  jobs:"
        ),
        None,
    )
    tls_block = [
        "    worker_tls:",
        "      enabled: true",
        "      host: 0.0.0.0",
        "      port: 8766",
        f"      certificate_file: {certificate_path.as_posix()}",
        f"      private_key_file: {private_key_path.as_posix()}",
        f"      ca_certificate_file: {ca_certificate_path.as_posix()}",
    ]
    if jobs_start is None:
        insertion_index = next(
            (
                index
                for index in range(administration_start + 1, administration_end)
                if lines[index] in {"  network:", "  dhcp:"}
            ),
            administration_end,
        )
        block = [
            "  jobs:",
            "    enabled: true",
            "    database_path: /var/lib/ohana-agent/distributed-jobs.db",
            f"    worker_token_file: {worker_token_path.as_posix()}",
            "    lease_seconds: 60",
            "    waiting_worker_after_seconds: 30",
            "    retention_days: 30",
            "    max_active_jobs: 1000",
            *tls_block,
        ]
        lines[insertion_index:insertion_index] = block
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return

    jobs_end = _nested_section_end(lines, jobs_start, indentation=2)
    enabled_index = next(
        (
            index
            for index in range(jobs_start + 1, jobs_end)
            if lines[index].lstrip().startswith("enabled:")
            and lines[index].startswith("    ")
            and not lines[index].startswith("      ")
        ),
        None,
    )
    if enabled_index is None:
        lines.insert(jobs_start + 1, "    enabled: true")
        jobs_end += 1
    else:
        lines[enabled_index] = "    enabled: true"

    token_index = next(
        (
            index
            for index in range(jobs_start + 1, jobs_end)
            if lines[index].strip().startswith("worker_token_file:")
        ),
        None,
    )
    if token_index is None:
        lines.insert(jobs_end, f"    worker_token_file: {worker_token_path.as_posix()}")
        jobs_end += 1
    else:
        lines[token_index] = f"    worker_token_file: {worker_token_path.as_posix()}"

    tls_start = next(
        (index for index in range(jobs_start + 1, jobs_end) if lines[index] == "    worker_tls:"),
        None,
    )
    if tls_start is None:
        lines[jobs_end:jobs_end] = tls_block
    else:
        tls_end = _nested_section_end(lines, tls_start, indentation=4)
        lines[tls_start:tls_end] = tls_block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _ensure_agent_wake_on_lan_section(
    path: Path,
    *,
    include_batching: bool = True,
) -> None:
    """Add the bounded Wake-on-LAN policy without overwriting local settings."""
    lines = path.read_text(encoding="utf-8").splitlines()
    administration_start = next(
        (index for index, line in enumerate(lines) if line == "administration:"),
        None,
    )
    if administration_start is None:
        raise AdministrationPreparationError("La section administration Agent est absente.")
    administration_end = _nested_section_end(
        lines,
        administration_start,
        indentation=0,
    )
    jobs_start = next(
        (
            index
            for index in range(administration_start + 1, administration_end)
            if lines[index] == "  jobs:"
        ),
        None,
    )
    if jobs_start is None:
        raise AdministrationPreparationError("La section jobs Agent est absente.")

    jobs_end = _nested_section_end(lines, jobs_start, indentation=2)
    wake_start = next(
        (index for index in range(jobs_start + 1, jobs_end) if lines[index] == "    wake_on_lan:"),
        None,
    )
    if wake_start is not None:
        if include_batching:
            wake_end = _nested_section_end(lines, wake_start, indentation=4)
            _add_missing_wake_on_lan_options(lines, wake_start, wake_end)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return

    worker_tls_start = next(
        (index for index in range(jobs_start + 1, jobs_end) if lines[index] == "    worker_tls:"),
        None,
    )
    insertion_index = worker_tls_start if worker_tls_start is not None else jobs_end
    block = [
        "    wake_on_lan:",
        "      enabled: false",
        "      worker_id: katsuyu-bubule",
        "      mac_address: null",
        "      broadcast_address: 192.168.1.255",
        "      port: 9",
        "      wait_timeout_seconds: 180",
        "      available_for_seconds: 30",
    ]
    if include_batching:
        block.extend(
            [
                "      packet_burst_count: 3",
                "      burst_interval_seconds: 0.1",
                "      retry_count: 2",
                "      retry_delay_seconds: 1.0",
                "      batch_window_seconds: 600",
                "      planned_window_start_hour: 0",
                "      planned_window_end_hour: 5",
                "      schedule_timezone: Europe/Paris",
                "      minimum_interval_seconds: 7200",
                "      shutdown_after_completion: true",
            ]
        )
    lines[insertion_index:insertion_index] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _add_missing_wake_on_lan_options(
    lines: list[str],
    wake_start: int,
    wake_end: int,
) -> None:
    defaults = (
        ("packet_burst_count", "3"),
        ("burst_interval_seconds", "0.1"),
        ("retry_count", "2"),
        ("retry_delay_seconds", "1.0"),
        ("batch_window_seconds", "600"),
        ("planned_window_start_hour", "0"),
        ("planned_window_end_hour", "5"),
        ("schedule_timezone", "Europe/Paris"),
        ("minimum_interval_seconds", "7200"),
        ("shutdown_after_completion", "true"),
    )
    existing = {
        line.strip().split(":", 1)[0]
        for line in lines[wake_start + 1 : wake_end]
        if line.startswith("      ") and ":" in line
    }
    additions = [f"      {name}: {value}" for name, value in defaults if name not in existing]
    if additions:
        lines[wake_end:wake_end] = additions


def _ensure_agent_infra_log_source(path: Path) -> None:
    """Add INFRA-01 to the bounded log policy without replacing local values."""
    lines = path.read_text(encoding="utf-8").splitlines()
    jobs_start = next(
        (index for index, line in enumerate(lines) if line == "  jobs:"),
        None,
    )
    if jobs_start is None:
        raise AdministrationPreparationError("La section jobs Agent est absente.")
    jobs_end = _nested_section_end(lines, jobs_start, indentation=2)
    logs_start = next(
        (index for index in range(jobs_start + 1, jobs_end) if lines[index] == "    logs:"),
        None,
    )
    if logs_start is None:
        insertion_index = next(
            (
                index
                for index in range(jobs_start + 1, jobs_end)
                if lines[index] in {"    wake_on_lan:", "    worker_tls:"}
            ),
            jobs_end,
        )
        lines[insertion_index:insertion_index] = [
            "    logs:",
            "      enabled: false",
            '      schedule: "0 5 * * *"',
            "      sources:",
            "        - infra-01",
            "        - ha-01",
            "        - linky-01",
            "        - zwave-01",
            "      window_hours: 24",
            "      max_bytes_per_source: 2097152",
            "      timeout_seconds: 900",
        ]
    else:
        logs_end = _nested_section_end(lines, logs_start, indentation=4)
        sources_start = next(
            (
                index
                for index in range(logs_start + 1, logs_end)
                if lines[index] == "      sources:"
            ),
            None,
        )
        if sources_start is None:
            lines[logs_end:logs_end] = [
                "      sources:",
                "        - infra-01",
            ]
        else:
            # Installer releases predating this migration could leave list items
            # aligned with ``sources:``. Repair only those direct list items so
            # local source names are preserved before adding INFRA-01.
            source_index = sources_start + 1
            while source_index < len(lines):
                line = lines[source_index]
                if line.startswith("      - "):
                    lines[source_index] = f"  {line}"
                    source_index += 1
                    continue
                if not line.strip() or line.lstrip().startswith("#"):
                    source_index += 1
                    continue
                if len(line) - len(line.lstrip()) > 6:
                    source_index += 1
                    continue
                break
            sources_end = _nested_section_end(lines, sources_start, indentation=6)
            configured = {
                line.removeprefix("        - ").strip()
                for line in lines[sources_start + 1 : sources_end]
                if line.startswith("        - ")
            }
            if "infra-01" not in configured:
                lines.insert(sources_start + 1, "        - infra-01")

    rendered = "\n".join(lines) + "\n"
    try:
        yaml.safe_load(rendered)
    except yaml.YAMLError as error:
        raise AdministrationPreparationError(
            "La migration de la configuration Agent produirait un YAML invalide."
        ) from error
    path.write_text(rendered, encoding="utf-8", newline="\n")


def _ensure_agent_companion_section(
    path: Path,
    *,
    ca_certificate_path: Path,
    certificate_path: Path,
    private_key_path: Path,
) -> None:
    """Add the bounded Shizune listener without overwriting local settings."""
    lines = path.read_text(encoding="utf-8").splitlines()
    administration_start = next(
        (index for index, line in enumerate(lines) if line == "administration:"),
        None,
    )
    if administration_start is None:
        raise AdministrationPreparationError("La section administration Agent est absente.")
    administration_end = _nested_section_end(
        lines,
        administration_start,
        indentation=0,
    )
    companion_start = next(
        (
            index
            for index in range(administration_start + 1, administration_end)
            if lines[index] == "  companion:"
        ),
        None,
    )
    if companion_start is not None:
        return
    block = [
        "  companion:",
        "    enabled: true",
        "    host: 0.0.0.0",
        "    port: 8767",
        f"    certificate_file: {certificate_path.as_posix()}",
        f"    private_key_file: {private_key_path.as_posix()}",
        f"    ca_certificate_file: {ca_certificate_path.as_posix()}",
        "    credential_ttl_days: 90",
        "    push:",
        "      enabled: false",
        "      environment: production",
        "      team_id: null",
        "      key_id: null",
        "      bundle_id: fr.ohana.Shizune",
        "      private_key_file: /etc/ohana-agent/shizune-apns.p8",
        "      timeout_seconds: 5.0",
    ]
    insertion_index = next(
        (
            index
            for index in range(administration_start + 1, administration_end)
            if lines[index] in {"  network:", "  dhcp:"}
        ),
        administration_end,
    )
    lines[insertion_index:insertion_index] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _install_vision_companion_ca(
    source: Path,
    destination: Path,
    *,
    secure_ownership: bool,
) -> None:
    """Give Vision a public CA copy without exposing Agent's TLS directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, destination)
    except OSError as error:
        raise AdministrationPreparationError(
            f"Impossible de fournir la CA compagnon à Vision : {error}"
        ) from error
    if secure_ownership:
        _secure_mutable_path(destination, group_name="ohana-vision", mode=0o644)


def _ensure_vision_companion_section(
    path: Path,
    *,
    companion_url: str,
    ca_certificate_path: Path,
) -> None:
    """Complete Vision's existing Agent section for the Shizune bridge."""
    lines = path.read_text(encoding="utf-8").splitlines()
    agent_start = next(
        (index for index, line in enumerate(lines) if line == "agent:"),
        None,
    )
    if agent_start is None:
        raise AdministrationPreparationError("La section agent de Vision est absente.")
    agent_end = _nested_section_end(lines, agent_start, indentation=0)
    existing = {
        line.strip().split(":", 1)[0]
        for line in lines[agent_start + 1 : agent_end]
        if line.startswith("  ") and not line.startswith("    ") and ":" in line
    }
    values = (
        ("companion_enabled", "true"),
        ("companion_url", companion_url),
        ("companion_ca_file", ca_certificate_path.as_posix()),
    )
    additions = [f"  {name}: {value}" for name, value in values if name not in existing]
    if additions:
        lines[agent_end:agent_end] = additions
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _nested_section_end(lines: list[str], start: int, *, indentation: int) -> int:
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        current_indentation = len(line) - len(line.lstrip())
        if current_indentation <= indentation:
            return index
    return len(lines)


def _prepare_worker_tls(
    *,
    directory: Path,
    openssl_path: Path,
    dns_name: str,
    ip_address: str,
    secure_ownership: bool,
) -> dict[str, Path]:
    """Create the private Ohana CA and renewable Agent worker certificate once."""
    paths = {
        "ca_certificate": directory / "ca.crt",
        "ca_private_key": directory / "ca.key",
        "certificate": directory / "worker.crt",
        "private_key": directory / "worker.key",
        "request": directory / "worker.csr",
        "serial": directory / "ca.srl",
    }
    durable = tuple(
        paths[name]
        for name in (
            "ca_certificate",
            "ca_private_key",
            "certificate",
            "private_key",
        )
    )
    existing = [path for path in durable if path.exists()]
    if existing and len(existing) != len(durable):
        raise AdministrationPreparationError(
            "La configuration TLS Katsuyu est incomplète ; aucune clé ne sera remplacée."
        )
    if not existing:
        if not openssl_path.is_file():
            raise AdministrationPreparationError(
                f"OpenSSL est requis pour préparer Katsuyu : {openssl_path}."
            )
        directory.mkdir(parents=True, exist_ok=True)
        commands = (
            [
                str(openssl_path),
                "req",
                "-x509",
                "-newkey",
                "rsa:3072",
                "-sha256",
                "-days",
                "3650",
                "-nodes",
                "-subj",
                "/CN=Ohana Local Worker CA",
                "-addext",
                "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext",
                "keyUsage=critical,keyCertSign,cRLSign",
                "-keyout",
                str(paths["ca_private_key"]),
                "-out",
                str(paths["ca_certificate"]),
            ],
            [
                str(openssl_path),
                "req",
                "-new",
                "-newkey",
                "rsa:3072",
                "-sha256",
                "-nodes",
                "-subj",
                f"/CN={dns_name}",
                "-addext",
                f"subjectAltName=DNS:{dns_name},IP:{ip_address}",
                "-addext",
                "basicConstraints=critical,CA:FALSE",
                "-addext",
                "keyUsage=critical,digitalSignature,keyEncipherment",
                "-addext",
                "extendedKeyUsage=serverAuth",
                "-keyout",
                str(paths["private_key"]),
                "-out",
                str(paths["request"]),
            ],
            [
                str(openssl_path),
                "x509",
                "-req",
                "-in",
                str(paths["request"]),
                "-CA",
                str(paths["ca_certificate"]),
                "-CAkey",
                str(paths["ca_private_key"]),
                "-CAcreateserial",
                "-days",
                "825",
                "-sha256",
                "-copy_extensions",
                "copy",
                "-out",
                str(paths["certificate"]),
            ],
        )
        try:
            for command in commands:
                _run_openssl(command)
        except Exception:
            for candidate in paths.values():
                candidate.unlink(missing_ok=True)
            raise
        paths["request"].unlink(missing_ok=True)

    if secure_ownership:
        _secure_mutable_path(directory, group_name="ohana-agent", mode=0o750)
        _secure_mutable_path(paths["certificate"], group_name="ohana-agent", mode=0o644)
        _secure_mutable_path(paths["private_key"], group_name="ohana-agent", mode=0o640)
        _secure_mutable_path(paths["ca_certificate"], group_name="ohana-agent", mode=0o644)
        _secure_root_secret(paths["ca_private_key"])
        if paths["serial"].exists():
            _secure_root_secret(paths["serial"])
    return paths


def _run_openssl(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AdministrationPreparationError(
            f"OpenSSL n'a pas pu préparer le certificat Katsuyu : {detail}"
        )


def _secure_root_secret(path: Path) -> None:
    try:
        shutil.chown(path, user="root", group="root")
        path.chmod(0o600)
    except (LookupError, OSError) as error:
        raise AdministrationPreparationError(
            f"Impossible de sécuriser la clé privée {path} : {error}"
        ) from error


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


def supports_distributed_jobs_tls(agent_version: str | None) -> bool:
    """Provision jobs only for an Agent version that owns the HTTPS contract."""
    if agent_version is None:
        return False
    return _supports_agent_version(
        agent_version,
        minimum=DISTRIBUTED_JOBS_TLS_MINIMUM_AGENT_VERSION,
    )


def supports_wake_on_lan(agent_version: str | None) -> bool:
    """Provision Wake-on-LAN only when Agent owns the Phase 5 contract."""
    if agent_version is None:
        return False
    return _supports_agent_version(
        agent_version,
        minimum=WAKE_ON_LAN_MINIMUM_AGENT_VERSION,
    )


def supports_wake_on_lan_batching(agent_version: str | None) -> bool:
    """Indiquer si Agent comprend les rafales et le regroupement WOL."""
    if agent_version is None:
        return False
    return _supports_agent_version(
        agent_version,
        minimum=WAKE_ON_LAN_BATCHING_MINIMUM_AGENT_VERSION,
    )


def supports_infra_log_source(agent_version: str | None) -> bool:
    """Provision INFRA-01 journal analysis only for compatible Agents."""
    if agent_version is None:
        return False
    return _supports_agent_version(
        agent_version,
        minimum=INFRA_LOG_SOURCE_MINIMUM_AGENT_VERSION,
    )


def supports_shizune_companion(agent_version: str | None) -> bool:
    """Provision the companion listener only when Agent owns its scoped contract."""
    if agent_version is None:
        return False
    return _supports_agent_version(
        agent_version,
        minimum=SHIZUNE_COMPANION_MINIMUM_AGENT_VERSION,
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
