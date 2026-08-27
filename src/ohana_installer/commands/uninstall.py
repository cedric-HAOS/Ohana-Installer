"""Commande de désinstallation."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ohana_installer.commands.automatic_update import (
    SERVICE_NAME as AUTOMATIC_UPDATE_SERVICE_NAME,
)
from ohana_installer.commands.automatic_update import (
    TIMER_NAME as AUTOMATIC_UPDATE_TIMER_NAME,
)
from ohana_installer.commands.automatic_update import (
    AutomaticUpdateError,
)
from ohana_installer.commands.automatic_update import (
    disable as disable_automatic_update,
)
from ohana_installer.commands.automatic_update import (
    is_enabled as automatic_update_is_enabled,
)
from ohana_installer.commands.automatic_update import (
    remove_units as remove_automatic_update_units,
)
from ohana_installer.commands.install import (
    AGENT_INSTALLATION_PATH,
    SHIZUNE_INSTALLATION_PATH,
    VISION_INSTALLATION_PATH,
)
from ohana_installer.confirmation import confirm_action
from ohana_installer.network import (
    NETWORK_HELPER_PATH,
    NETWORK_STATE_DIRECTORY,
    NETWORK_SUDOERS_PATH,
    NetworkProvisioningError,
    remove_network_administration,
)
from ohana_installer.systemd import (
    SYSTEMD_SYSTEM_DIRECTORY,
    SystemdCommandError,
    SystemdInstallationError,
    disable_systemd_service,
    reload_systemd_daemon,
    remove_systemd_service,
    stop_systemd_service,
)

UNINSTALLATION_ERROR = 3

SERVICE_NAMES = (
    "ohana-agent.service",
    "ohana-vision.service",
)

INSTALLATION_PATHS = (
    AGENT_INSTALLATION_PATH,
    VISION_INSTALLATION_PATH,
    SHIZUNE_INSTALLATION_PATH,
)


class UninstallationError(RuntimeError):
    """Erreur pendant la suppression d'un composant."""


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande uninstall."""

    parser = subparsers.add_parser(
        "uninstall",
        help="Désinstaller les composants officiels Ohana.",
        description="Désinstaller les composants officiels Ohana.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accepter automatiquement les confirmations.",
    )
    parser.set_defaults(command_handler=run)


def _service_is_installed(
    service_name: str,
    *,
    system_directory: Path | str = SYSTEMD_SYSTEM_DIRECTORY,
) -> bool:
    """Indiquer si une unité systemd est installée."""

    return (Path(system_directory) / service_name).is_file()


def _remove_installation_path(path: Path) -> bool:
    """Supprimer un répertoire d'installation.

    Retourner True si le répertoire a été supprimé.
    """

    if not path.exists():
        return False

    if not path.is_dir():
        raise UninstallationError(f"Le chemin d'installation {path} n'est pas un répertoire.")

    try:
        shutil.rmtree(path)
    except OSError as error:
        raise UninstallationError(f"Impossible de supprimer {path} : {error}") from error

    return True


def run(args: argparse.Namespace) -> int:
    """Exécuter la commande uninstall."""

    assume_yes = bool(args.yes)

    print("Désinstallation des composants Ohana...")
    print()

    try:
        installed_services = tuple(
            service_name for service_name in SERVICE_NAMES if _service_is_installed(service_name)
        )
        existing_paths = tuple(path for path in INSTALLATION_PATHS if path.exists())
        network_administration_exists = any(
            path.exists()
            for path in (
                NETWORK_HELPER_PATH,
                NETWORK_SUDOERS_PATH,
                NETWORK_STATE_DIRECTORY,
            )
        )
        automatic_update_exists = any(
            (SYSTEMD_SYSTEM_DIRECTORY / name).exists()
            for name in (AUTOMATIC_UPDATE_SERVICE_NAME, AUTOMATIC_UPDATE_TIMER_NAME)
        )

        if (
            not installed_services
            and not existing_paths
            and not network_administration_exists
            and not automatic_update_exists
        ):
            print("✓ Aucune installation Ohana détectée.")
            return 0

        if installed_services:
            print("Services à supprimer : " + ", ".join(installed_services))

        if existing_paths:
            print("Répertoires à supprimer : " + ", ".join(str(path) for path in existing_paths))

        print()

        if not confirm_action(
            "Confirmer la désinstallation d'Ohana ?",
            assume_yes=assume_yes,
        ):
            print("Désinstallation annulée.")
            return 0

        print()

        if automatic_update_exists:
            print("Suppression de la mise à jour automatique...")
            if automatic_update_is_enabled():
                disable_automatic_update()
            remove_automatic_update_units()
            reload_systemd_daemon()
            print("✓ Mise à jour automatique supprimée.")
            print()

        if installed_services:
            print("Arrêt des services systemd...")

            for service_name in installed_services:
                stop_systemd_service(service_name)
                print(f"✓ {service_name} arrêté.")

            print()
            print("Désactivation des services systemd...")

            for service_name in installed_services:
                disable_systemd_service(service_name)
                print(f"✓ {service_name} désactivé.")

            print()
            print("Suppression des services systemd...")

            for service_name in installed_services:
                removed = remove_systemd_service(service_name)

                if removed:
                    print(f"✓ {service_name} supprimé.")

            print()
            print("Rechargement de systemd...")

            reload_systemd_daemon()

            print("✓ Configuration systemd rechargée.")
        else:
            print("✓ Aucun service systemd Ohana installé.")

        print()
        print("Suppression de l administration réseau privilégiée...")

        if remove_network_administration():
            print("✓ Helper NetworkManager et règle sudoers supprimés.")
        else:
            print("✓ Administration réseau déjà absente.")

        print()
        print("Suppression des composants...")

        for installation_path in INSTALLATION_PATHS:
            removed = _remove_installation_path(installation_path)

            if removed:
                print(f"✓ {installation_path} supprimé.")
            else:
                print(f"✓ {installation_path} déjà absent.")

    except SystemdCommandError as error:
        print(f"✗ Commande systemd impossible : {error}")
        return UNINSTALLATION_ERROR
    except SystemdInstallationError as error:
        print(f"✗ Suppression systemd impossible : {error}")
        return UNINSTALLATION_ERROR
    except (UninstallationError, NetworkProvisioningError, AutomaticUpdateError) as error:
        print(f"✗ Désinstallation impossible : {error}")
        return UNINSTALLATION_ERROR

    print()
    print("Ohana-Agent, Ohana-Vision et Shizune sont désinstallés.")
    print("Les fichiers de configuration ont été conservés.")

    return 0
