"""Interface interactive en terminal d'Ohana-Installer."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
from typing import TextIO

from ohana_installer.commands.automatic_update import (
    AutomaticUpdateError,
)
from ohana_installer.commands.automatic_update import (
    is_enabled as automatic_update_is_enabled,
)
from ohana_installer.commands.install import (
    AGENT_COMMAND_NAME,
    AGENT_ENVIRONMENT_PATH,
    VISION_COMMAND_NAME,
    VISION_ENVIRONMENT_PATH,
)
from ohana_installer.github import DownloadError
from ohana_installer.manifest import ManifestError, PlatformReleaseEntry
from ohana_installer.network import (
    InitialNetworkConfiguration,
    NetworkProvisioningError,
    begin_network_configuration,
    confirm_network_configuration,
    read_network_state,
    rollback_network_configuration,
)
from ohana_installer.python_package import (
    PackageInstallationError,
    inspect_installed_component,
)
from ohana_installer.release_selection import download_release_catalog
from ohana_installer.version import __version__

CommandRunner = Callable[[Sequence[str]], int]
InputFunction = Callable[[str], str]

STATUS_LABELS = {
    "recommended": "Recommandée",
    "supported": "Supportée",
    "legacy": "Historique",
}


@dataclass(frozen=True)
class InstalledStatus:
    """Versions locales utilisées pour orienter le menu."""

    agent_version: str | None
    vision_version: str | None
    installation_present: bool


def _write(output: TextIO, text: str = "") -> None:
    print(text, file=output)


def _prompt(
    input_function: InputFunction,
    output: TextIO,
    label: str,
    *,
    default: str | None = None,
) -> str:
    suffix = f" [{default}]" if default else ""
    print(f"{label}{suffix} : ", end="", file=output, flush=True)
    value = input_function("").strip()
    return value if value else (default or "")


def _ask_yes_no(
    input_function: InputFunction,
    output: TextIO,
    question: str,
) -> bool:
    answer = _prompt(input_function, output, f"{question} [o/N]")
    return answer.casefold() in {"o", "oui", "y", "yes"}


def _pause(input_function: InputFunction, output: TextIO) -> None:
    _write(output)
    _prompt(input_function, output, "Appuyez sur Entrée pour revenir au menu")


def _clear_terminal(output: TextIO) -> None:
    is_terminal = getattr(output, "isatty", lambda: False)()
    if is_terminal and os.environ.get("TERM", "") != "dumb":
        print("\033[2J\033[H", end="", file=output, flush=True)


def _inspect_version(
    *,
    environment_path: Path,
    command_name: str,
    component_name: str,
) -> str | None:
    try:
        component = inspect_installed_component(
            environment_path=environment_path,
            command_name=command_name,
            component_name=component_name,
        )
    except PackageInstallationError:
        return None
    return component.version if component is not None else None


def _installed_status() -> InstalledStatus:
    return InstalledStatus(
        agent_version=_inspect_version(
            environment_path=AGENT_ENVIRONMENT_PATH,
            command_name=AGENT_COMMAND_NAME,
            component_name="Ohana-Agent",
        ),
        vision_version=_inspect_version(
            environment_path=VISION_ENVIRONMENT_PATH,
            command_name=VISION_COMMAND_NAME,
            component_name="Ohana-Vision",
        ),
        installation_present=(AGENT_ENVIRONMENT_PATH.exists() or VISION_ENVIRONMENT_PATH.exists()),
    )


def _render_main_menu(output: TextIO, status: InstalledStatus) -> None:
    agent = status.agent_version or ("détecté" if AGENT_ENVIRONMENT_PATH.exists() else "absent")
    vision = status.vision_version or (
        "détectée" if VISION_ENVIRONMENT_PATH.exists() else "absente"
    )
    width = 72
    _write(output, "┌" + "─" * (width - 2) + "┐")
    _write(output, f"│{'Ohana Installer ' + __version__:^70}│")
    _write(output, "├" + "─" * (width - 2) + "┤")
    _write(output, f"│{'  Agent installé : ' + agent:<70}│")
    _write(output, f"│{'  Vision installée : ' + vision:<70}│")
    _write(output, "├" + "─" * (width - 2) + "┤")
    try:
        automatic_update = "activée" if automatic_update_is_enabled() else "désactivée"
    except AutomaticUpdateError:
        automatic_update = "indisponible"
    for line in (
        "  1. Installer ou mettre à jour Agent et Vision",
        "  2. Installer une composition antérieure",
        "  3. Configurer le réseau d INFRA-01",
        f"  4. Mise à jour automatique : {automatic_update}",
        "  5. Quitter",
    ):
        _write(output, f"│{line:<70}│")
    _write(output, "└" + "─" * (width - 2) + "┘")


def _run_recommended(
    command_runner: CommandRunner,
    status: InstalledStatus,
) -> int:
    command = "update" if status.installation_present else "install"
    return command_runner([command])


def _numeric_version(version: str) -> tuple[int, int, int] | None:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _is_downgrade(status: InstalledStatus, entry: PlatformReleaseEntry) -> bool:
    comparisons = (
        (status.agent_version, entry.agent_version),
        (status.vision_version, entry.vision_version),
    )
    for installed, target in comparisons:
        if installed is None:
            continue
        installed_key = _numeric_version(installed)
        target_key = _numeric_version(target)
        if installed_key is not None and target_key is not None and installed_key > target_key:
            return True
    return False


def _select_release(
    *,
    input_function: InputFunction,
    output: TextIO,
) -> PlatformReleaseEntry | None:
    with tempfile.TemporaryDirectory(prefix="ohana-installer-menu-") as directory:
        catalog = download_release_catalog(Path(directory))

    releases = tuple(
        release
        for release in catalog.releases
        if release.platform_version != catalog.default_platform_version
    )
    if not releases:
        _write(output, "Aucune composition antérieure n'est publiée dans le catalogue.")
        return None

    _write(output)
    _write(output, "Compositions Agent/Vision antérieures")
    _write(output, "─" * 72)
    for index, release in enumerate(releases, start=1):
        label = STATUS_LABELS[release.status]
        _write(
            output,
            f"{index:>2}. Platform {release.platform_version:<8} "
            f"Agent {release.agent_version:<8} Vision {release.vision_version:<8} "
            f"{label}",
        )
    _write(output, " 0. Retour")

    while True:
        raw_choice = _prompt(input_function, output, "Composition")
        if raw_choice in {"0", "q", "Q"}:
            return None
        try:
            index = int(raw_choice)
        except ValueError:
            _write(output, "Choix invalide.")
            continue
        if 1 <= index <= len(releases):
            return releases[index - 1]
        _write(output, "Choix invalide.")


def _run_selected_release(
    *,
    command_runner: CommandRunner,
    input_function: InputFunction,
    output: TextIO,
    status: InstalledStatus,
) -> int | None:
    try:
        entry = _select_release(input_function=input_function, output=output)
    except DownloadError as error:
        _write(output, f"✗ Téléchargement impossible : {error}")
        return 3
    except ManifestError as error:
        _write(output, f"✗ Le catalogue officiel est invalide : {error}")
        return 3
    if entry is None:
        return None

    downgrade = _is_downgrade(status, entry)
    if entry.status == "legacy":
        _write(output)
        _write(output, "⚠ Cette composition est historique.")
        if not _ask_yes_no(input_function, output, "Poursuivre avec cette composition ?"):
            _write(output, "Installation annulée.")
            return 0
    if downgrade:
        _write(output)
        _write(output, "⚠ Cette sélection rétrogradera au moins un composant installé.")
        if not _ask_yes_no(input_function, output, "Autoriser cette rétrogradation ?"):
            _write(output, "Rétrogradation annulée.")
            return 0

    command = "update" if status.installation_present else "install"
    arguments = [command, "--platform-version", entry.platform_version]
    if command == "update" and downgrade:
        arguments.append("--allow-downgrade")
    return command_runner(arguments)


def _prefix_from_mask(mask: str) -> int:
    normalized = mask.strip()
    if normalized.isdigit():
        prefix = int(normalized)
        if 0 <= prefix <= 32:
            return prefix
        raise NetworkProvisioningError("Le préfixe IPv4 doit être compris entre 0 et 32.")
    try:
        return IPv4Network(f"0.0.0.0/{normalized}").prefixlen
    except ValueError as error:
        raise NetworkProvisioningError(f"Masque IPv4 invalide : {mask}.") from error


def _network_configuration_form(
    *,
    state: dict[str, object],
    input_function: InputFunction,
    output: TextIO,
) -> InitialNetworkConfiguration | None:
    current_interface = str(state.get("interface") or "eth0")
    current_method = "2" if state.get("method") == "auto" else "1"
    current_address = str(state.get("address") or "")
    current_ip = ""
    current_prefix = "24"
    if current_address:
        try:
            parsed_address = IPv4Interface(current_address)
            current_ip = str(parsed_address.ip)
            current_prefix = str(parsed_address.network.prefixlen)
        except ValueError:
            pass
    current_gateway = str(state.get("gateway") or "")
    raw_dns = state.get("dns_servers")
    dns_values = [str(value) for value in raw_dns] if isinstance(raw_dns, list) else []

    _write(output)
    _write(output, "Configuration réseau d INFRA-01")
    _write(output, "─" * 72)
    interface = _prompt(
        input_function,
        output,
        "Interface",
        default=current_interface,
    )
    _write(output, "Mode : 1. Statique   2. DHCP   0. Retour")
    mode = _prompt(input_function, output, "Mode", default=current_method)
    if mode in {"0", "q", "Q"}:
        return None
    if mode == "2":
        return InitialNetworkConfiguration(interface=interface, method="auto")
    if mode != "1":
        raise NetworkProvisioningError("Choisissez le mode 1 (statique) ou 2 (DHCP).")

    address = _prompt(
        input_function,
        output,
        "Adresse IPv4",
        default=current_ip or None,
    )
    mask = _prompt(
        input_function,
        output,
        "Masque ou préfixe",
        default=current_prefix,
    )
    gateway = _prompt(
        input_function,
        output,
        "Passerelle",
        default=current_gateway or None,
    )
    dns_primary = _prompt(
        input_function,
        output,
        "DNS principal",
        default=dns_values[0] if dns_values else None,
    )
    dns_secondary = _prompt(
        input_function,
        output,
        "DNS secondaire",
        default=dns_values[1] if len(dns_values) > 1 else None,
    )

    try:
        prefix = _prefix_from_mask(mask)
        dns_servers = tuple(
            IPv4Address(value) for value in (dns_primary, dns_secondary) if value.strip()
        )
        return InitialNetworkConfiguration(
            interface=interface,
            method="manual",
            address=IPv4Interface(f"{address}/{prefix}"),
            gateway=IPv4Address(gateway),
            dns_servers=dns_servers,
        )
    except ValueError as error:
        raise NetworkProvisioningError(f"Configuration IPv4 invalide : {error}") from error


def _display_network_configuration(
    output: TextIO,
    configuration: InitialNetworkConfiguration,
) -> None:
    _write(output)
    _write(output, "Récapitulatif")
    _write(output, f"  Interface : {configuration.interface}")
    _write(output, f"  Mode      : {'DHCP' if configuration.method == 'auto' else 'Statique'}")
    if configuration.method == "manual":
        _write(output, f"  Adresse   : {configuration.address}")
        _write(output, f"  Passerelle: {configuration.gateway}")
        _write(
            output,
            "  DNS       : " + ", ".join(str(server) for server in configuration.dns_servers),
        )


def _configure_network(
    *,
    input_function: InputFunction,
    output: TextIO,
) -> int | None:
    try:
        state = read_network_state()
        pending = state.get("pending_change")
        if pending is not None:
            raise NetworkProvisioningError(
                "Une modification réseau attend déjà une confirmation ou un retour automatique."
            )
        configuration = _network_configuration_form(
            state=state,
            input_function=input_function,
            output=output,
        )
        if configuration is None:
            return None
        _display_network_configuration(output, configuration)
        if not _ask_yes_no(input_function, output, "Appliquer cette configuration ?"):
            _write(output, "Modification réseau annulée.")
            return 0

        change = begin_network_configuration(
            configuration,
            rollback_seconds=180,
        )
        _write(output)
        _write(output, "✓ Configuration appliquée temporairement.")
        _write(
            output,
            "Sans confirmation, l'ancienne configuration sera restaurée "
            "automatiquement dans 180 secondes.",
        )
        if _ask_yes_no(input_function, output, "La connexion fonctionne-t-elle correctement ?"):
            confirm_network_configuration(change.transaction_id)
            _write(output, "✓ Configuration réseau confirmée.")
        else:
            rollback_network_configuration(change.transaction_id)
            _write(output, "✓ Ancienne configuration réseau restaurée.")
        return 0
    except NetworkProvisioningError as error:
        _write(output, f"✗ Configuration réseau impossible : {error}")
        return 3


def run(
    *,
    command_runner: CommandRunner,
    input_function: InputFunction | None = None,
    output: TextIO | None = None,
) -> int:
    """Afficher le menu principal jusqu'à ce que l'utilisateur le quitte."""
    input_reader = input_function or input
    destination = output or sys.stdout

    while True:
        status = _installed_status()
        _clear_terminal(destination)
        _render_main_menu(destination, status)
        try:
            choice = _prompt(input_reader, destination, "Votre choix")
        except (EOFError, KeyboardInterrupt):
            _write(destination)
            return 0

        if choice == "1":
            result = _run_recommended(command_runner, status)
            _pause(input_reader, destination)
            if result not in {0, 3}:
                return result
        elif choice == "2":
            result = _run_selected_release(
                command_runner=command_runner,
                input_function=input_reader,
                output=destination,
                status=status,
            )
            if result is not None:
                _pause(input_reader, destination)
                if result not in {0, 3}:
                    return result
        elif choice == "3":
            result = _configure_network(
                input_function=input_reader,
                output=destination,
            )
            if result is not None:
                _pause(input_reader, destination)
        elif choice == "4":
            try:
                action = "disable" if automatic_update_is_enabled() else "enable"
            except AutomaticUpdateError:
                action = "enable"
            result = command_runner(["automatic-update", action])
            _pause(input_reader, destination)
            if result not in {0, 3}:
                return result
        elif choice in {"5", "q", "Q"}:
            _write(destination, "Au revoir.")
            return 0
        else:
            _write(destination, "Choix invalide.")
            _pause(input_reader, destination)
