"""Gestion des capacités système du profil INFRA-01."""

from __future__ import annotations

import argparse

from ohana_installer.confirmation import confirm_action
from ohana_installer.system_capabilities import (
    CapabilityProvisioningError,
    activate_capability,
    deactivate_capability,
    local_capability_statuses,
)

CAPABILITY_ERROR = 3


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande capability."""

    parser = subparsers.add_parser(
        "capability",
        help="Afficher, activer ou désactiver les capacités d'INFRA-01.",
    )
    actions = parser.add_subparsers(dest="capability_action", required=True)

    status = actions.add_parser("status", help="Afficher l'état des capacités.")
    status.set_defaults(command_handler=run)

    for action in ("activate", "deactivate"):
        action_parser = actions.add_parser(
            action,
            help=f"{action.capitalize()} une capacité.",
        )
        action_parser.add_argument(
            "identifier",
            choices=("dhcp", "time-reference"),
            help="Identifiant de la capacité.",
        )
        action_parser.add_argument(
            "--yes",
            action="store_true",
            help="Accepter automatiquement la confirmation.",
        )
        action_parser.set_defaults(command_handler=run)


def _display_statuses() -> None:
    print("Capacités d'INFRA-01")
    print()
    print(f"{'Capacité':<30} {'Implémentation':<18} État")
    for status in local_capability_statuses():
        print(f"{status.name:<30} {status.implementation:<18} {status.state}")


def _confirm_dhcp_activation(*, assume_yes: bool) -> bool:
    print("⚠ Un seul serveur DHCP doit être actif sur le réseau.")
    print()
    print(
        "Avant de poursuivre, désactivez le serveur DHCP actuellement en service "
        "(box Internet, routeur, autre serveur ou autre machine)."
    )
    print()
    return confirm_action(
        "L'ancien serveur DHCP a-t-il été désactivé ?",
        assume_yes=assume_yes,
    )


def run(args: argparse.Namespace) -> int:
    """Exécuter une action sur les capacités."""

    try:
        if args.capability_action == "status":
            _display_statuses()
            return 0

        identifier = args.identifier
        assume_yes = bool(args.yes)
        if args.capability_action == "activate":
            if identifier == "dhcp" and not _confirm_dhcp_activation(assume_yes=assume_yes):
                print("Activation DHCP annulée.")
                return 0
            if identifier != "dhcp" and not confirm_action(
                f"Activer la capacité {identifier} ?",
                assume_yes=assume_yes,
            ):
                print("Activation annulée.")
                return 0
            activate_capability(identifier)
            print(f"✓ Capacité {identifier} activée.")
            return 0

        if not confirm_action(
            f"Désactiver la capacité {identifier} ?",
            assume_yes=assume_yes,
        ):
            print("Désactivation annulée.")
            return 0
        deactivate_capability(identifier)
        print(f"✓ Capacité {identifier} désactivée.")
        return 0
    except CapabilityProvisioningError as error:
        print(f"✗ Gestion de la capacité impossible : {error}")
        return CAPABILITY_ERROR
