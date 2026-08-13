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

from ohana_installer.age_identity import AgeIdentityError, ensure_local_identity
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
from ohana_installer.system_capabilities import (
    CapabilityProvisioningError,
    CapabilityStatus,
    local_capability_statuses,
)
from ohana_installer.version import __version__

CommandRunner = Callable[[Sequence[str]], int]
InputFunction = Callable[[str], str]

STATUS_LABELS = {
    "recommended": "Recommandée",
    "supported": "Supportée",
    "legacy": "Historique",
}
SUPPORTED_RELEASE_MENU_LIMIT = 9
MENU_WIDTH = 72
OHANA_WORDMARK = (
    " ___  _   _    _    _   _    _",
    "/ _ \\| | | |  / \\  | \\ | |  / \\",
    "| | | | |_| | / _ \\ |  \\| | / _ \\",
    "| |_| |  _  |/ ___ \\| |\\  |/ ___ \\",
    " \\___/|_| |_/_/   \\_\\_| \\_/_/   \\_\\",
    "",
    "I N S T A L L E R",
)
OHANA_LOGO_LINE_COUNT = 5
STEP_ARTWORKS = {
    "install": (
        "INSTALLATION",
        (
            "+-------------+",
            "|  INFRA-01   |",
            "+------^------+",
        ),
    ),
    "restore": (
        "RESTAURATION",
        (
            "[ iCloud ] ---- archive.age ----> [ INFRA-01 ]",
            "                 verified",
            "                    |",
        ),
    ),
    "update": (
        "MISE A JOUR",
        (
            "[ version actuelle ] ==========> [ derniere version ]",
            "                         ^",
            "                    synchroniser",
        ),
    ),
    "composition": (
        "COMPOSITIONS",
        (
            "[ Agent ] + [ Vision ]",
            "          |",
            "     [ Platform ]",
        ),
    ),
    "capabilities": (
        "CAPACITES",
        (
            "[ DHCP ]     [ NTP ]     [ age ]",
            "     \\          |          /",
            "      +------ INFRA-01 ---+",
        ),
    ),
    "network": (
        "RESEAU",
        (
            "o-----------o-----------o",
            "ROUTEUR   INFRA-01      LAN",
            "      adresse . liaison",
        ),
    ),
    "automatic-update": (
        "MISE A JOUR AUTOMATIQUE",
        (
            ".-----------------------.",
            "| calendrier ----> Ohana |",
            "'-----------o-----------'",
        ),
    ),
    "quit": (
        "FIN DE SESSION",
        (
            "       \\o/",
            "        |",
            "       / \\",
        ),
    ),
}


@dataclass(frozen=True)
class InstalledStatus:
    """Versions locales utilisées pour orienter le menu."""

    agent_version: str | None
    vision_version: str | None
    installation_present: bool


def _write(output: TextIO, text: str = "") -> None:
    print(text, file=output)


def _render_step_artwork(output: TextIO, identifier: str) -> None:
    """Afficher l'identité ASCII compacte d'une action du menu."""

    title, artwork = STEP_ARTWORKS[identifier]
    _write(output)
    for line in artwork:
        _write(output, f"{line:^{MENU_WIDTH}}")
    _write(output, f"{title:^{MENU_WIDTH}}")
    _write(output)


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
    width = MENU_WIDTH
    logo_lines = OHANA_WORDMARK[:OHANA_LOGO_LINE_COUNT]
    logo_width = max(map(len, logo_lines))
    logo_padding = " " * ((width - logo_width) // 2)
    for line in logo_lines:
        _write(output, logo_padding + line)
    _write(output)
    _write(output, f"{OHANA_WORDMARK[-1]:^{width}}")
    _write(output)
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
        "  1. Installer une nouvelle machine INFRA-01",
        "  2. Restaurer INFRA-01 depuis une sauvegarde",
        "  3. Mettre à jour une installation Ohana",
        "  4. Installer une composition antérieure",
        "  5. Gérer les capacités d INFRA-01",
        "  6. Configurer le réseau d INFRA-01",
        f"  7. Mise à jour automatique : {automatic_update}",
        "  8. Quitter",
    ):
        _write(output, f"│{line:<70}│")
    _write(output, "└" + "─" * (width - 2) + "┘")


def _manage_capabilities(
    *,
    command_runner: CommandRunner,
    input_function: InputFunction,
    output: TextIO,
) -> int | None:
    """Afficher les actions explicites sur les capacités d'INFRA-01."""

    _render_step_artwork(output, "capabilities")
    try:
        statuses = {status.identifier: status for status in local_capability_statuses()}
        dhcp = statuses["dhcp"]
        time_reference = statuses["time-reference"]
    except (CapabilityProvisioningError, KeyError) as error:
        _write(output, f"✕ Diagnostic des capacités impossible : {error}")
        return 3

    _write(output, "Capacités d INFRA-01")
    _write(output, "─" * 72)
    _write(output, f"  DHCP ({dhcp.implementation}) : {dhcp.state}")
    _write(
        output,
        f"  Référence temporelle ({time_reference.implementation}) : {time_reference.state}",
    )
    _write(output)
    actions: dict[str, tuple[str, CapabilityStatus]] = {
        "1": (
            "deactivate" if dhcp.active else "activate",
            dhcp,
        ),
        "2": (
            "deactivate" if time_reference.active else "activate",
            time_reference,
        ),
    }
    for menu_choice, (action, status) in actions.items():
        verb = "Désactiver" if action == "deactivate" else "Activer"
        label = "DHCP" if status.identifier == "dhcp" else "la référence temporelle"
        _write(output, f"  {menu_choice}. {verb} {label}")
    _write(output, "  0. Retour")
    choice = _prompt(input_function, output, "Votre choix")
    if choice in {"0", "q", "Q"}:
        return None
    if choice not in actions:
        _write(output, "Choix invalide.")
        return 0

    action, status = actions[choice]
    if status.identifier == "dhcp" and action == "activate":
        _write(output)
        _write(output, "⚠ Un seul serveur DHCP doit être actif sur le réseau.")
        _write(output)
        _write(
            output,
            "Avant de poursuivre, désactivez le serveur DHCP actuellement en "
            "service (box Internet, routeur, autre serveur ou autre machine).",
        )
        if not _ask_yes_no(
            input_function,
            output,
            "L'ancien serveur DHCP a-t-il été désactivé ?",
        ):
            _write(output, "Activation DHCP annulée.")
            return 0
        return command_runner(["capability", "activate", "dhcp", "--yes"])

    identifier = status.identifier
    verb = "Activer" if action == "activate" else "Désactiver"
    if not _ask_yes_no(input_function, output, f"{verb} la capacité {identifier} ?"):
        _write(output, "Action annulée.")
        return 0
    return command_runner(["capability", action, identifier, "--yes"])


def _restore_infra_01(
    *,
    command_runner: CommandRunner,
    input_function: InputFunction,
    output: TextIO,
) -> int | None:
    """Collecter uniquement les paramètres non secrets de restauration."""

    _render_step_artwork(output, "restore")
    _write(output, "Restaurer INFRA-01")
    _write(output, "─" * 72)
    _write(output, "  1. Restaurer la dernière sauvegarde iCloud valide")
    _write(output, "  2. Choisir une sauvegarde iCloud")
    _write(output, "  3. Restaurer depuis un dossier local")
    _write(output, "  0. Retour")
    choice = _prompt(input_function, output, "Votre choix")
    if choice in {"0", "q", "Q"}:
        return None
    if choice not in {"1", "2", "3"}:
        _write(output, "Choix invalide.")
        return 0
    arguments = ["restore"]
    if choice == "3":
        identity = _prompt(
            input_function,
            output,
            "Identité privée age (clé USB ou support sécurisé)",
        )
        if not identity:
            _write(output, "L'identité age est obligatoire.")
            return 0
        arguments.extend(("--identity", identity))
        directory = _prompt(input_function, output, "Dossier de sauvegarde")
        if not directory:
            _write(output, "Le dossier de sauvegarde est obligatoire.")
            return 0
        arguments.extend(("--local", directory))
    else:
        arguments.append("--icloud")
        if choice == "2":
            arguments.append("--choose-backup")
        apple_id = _prompt(input_function, output, "Apple ID")
        if apple_id:
            arguments.extend(("--apple-id", apple_id))
    return command_runner(arguments)


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
    _render_step_artwork(output, "composition")
    with tempfile.TemporaryDirectory(prefix="ohana-installer-menu-") as directory:
        catalog = download_release_catalog(Path(directory))

    supported_releases = tuple(
        release
        for release in catalog.releases
        if release.platform_version != catalog.default_platform_version
        and release.status == "supported"
    )
    releases = supported_releases[:SUPPORTED_RELEASE_MENU_LIMIT]
    if not releases:
        _write(output, "Aucune composition antérieure supportée n'est publiée.")
        _write(
            output,
            "Les compositions historiques restent utilisables pour restaurer "
            "une sauvegarde existante.",
        )
        return None

    _write(output)
    _write(output, f"Compositions Agent/Vision antérieures supportées ({len(releases)})")
    _write(output, "─" * 72)
    for index, release in enumerate(releases, start=1):
        label = STATUS_LABELS[release.status]
        _write(
            output,
            f"{index:>2}. Platform {release.platform_version:<8} "
            f"Agent {release.agent_version:<8} Vision {release.vision_version:<8} "
            f"{label}",
        )
    _write(
        output,
        "Les compositions historiques restent utilisables pour restaurer une sauvegarde existante.",
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
    _render_step_artwork(output, "network")
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
    identity_checked = False

    while True:
        status = _installed_status()
        identity_warning = None
        if status.installation_present and os.name == "posix" and not identity_checked:
            try:
                ensure_local_identity()
            except AgeIdentityError as error:
                identity_warning = str(error)
            identity_checked = True
        _clear_terminal(destination)
        _render_main_menu(destination, status)
        if identity_warning is not None:
            _write(
                destination,
                f"⚠ Préparation de l'identité age incomplète : {identity_warning}",
            )
        try:
            choice = _prompt(input_reader, destination, "Votre choix")
        except (EOFError, KeyboardInterrupt):
            _write(destination)
            return 0

        if choice == "1":
            _render_step_artwork(destination, "install")
            result = command_runner(["install"])
            if result == 0 and os.name == "posix":
                try:
                    ensure_local_identity()
                    identity_checked = True
                except AgeIdentityError as error:
                    _write(destination, f"⚠ Identité age non préparée : {error}")
                    result = 3
            _pause(input_reader, destination)
            if result not in {0, 3}:
                return result
        elif choice == "2":
            result = _restore_infra_01(
                command_runner=command_runner,
                input_function=input_reader,
                output=destination,
            )
            if result is not None:
                _pause(input_reader, destination)
                if result not in {0, 3}:
                    return result
        elif choice == "3":
            _render_step_artwork(destination, "update")
            result = command_runner(["update"])
            _pause(input_reader, destination)
            if result not in {0, 3}:
                return result
        elif choice == "4":
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
        elif choice == "5":
            result = _manage_capabilities(
                command_runner=command_runner,
                input_function=input_reader,
                output=destination,
            )
            if result is not None:
                _pause(input_reader, destination)
                if result not in {0, 3}:
                    return result
        elif choice == "6":
            result = _configure_network(
                input_function=input_reader,
                output=destination,
            )
            if result is not None:
                _pause(input_reader, destination)
        elif choice == "7":
            _render_step_artwork(destination, "automatic-update")
            try:
                action = "disable" if automatic_update_is_enabled() else "enable"
            except AutomaticUpdateError:
                action = "enable"
            result = command_runner(["automatic-update", action])
            _pause(input_reader, destination)
            if result not in {0, 3}:
                return result
        elif choice in {"8", "q", "Q"}:
            _render_step_artwork(destination, "quit")
            _write(destination, "Au revoir.")
            return 0
        else:
            _write(destination, "Choix invalide.")
            _pause(input_reader, destination)
