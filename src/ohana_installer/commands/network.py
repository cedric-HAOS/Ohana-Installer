"""Commande autonome de configuration NetworkManager."""

from __future__ import annotations

import argparse
from ipaddress import IPv4Address, IPv4Interface

from ohana_installer.confirmation import confirm_action
from ohana_installer.network import (
    InitialNetworkConfiguration,
    NetworkProvisioningError,
    begin_network_configuration,
    confirm_network_configuration,
    read_network_state,
    rollback_network_configuration,
)

NETWORK_ERROR = 3


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande network."""
    parser = subparsers.add_parser(
        "network",
        help="Lire ou modifier le réseau d'INFRA-01 sans installer de composant.",
        description="Lire ou modifier la configuration NetworkManager d'INFRA-01.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirmer automatiquement la configuration après son application.",
    )
    parser.add_argument(
        "--interface",
        help="Interface NetworkManager, par exemple eth0.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dhcp",
        action="store_true",
        help="Configurer l'interface en DHCP.",
    )
    mode.add_argument(
        "--address",
        help="Adresse IPv4 statique avec préfixe, par exemple 192.168.1.10/24.",
    )
    parser.add_argument(
        "--gateway",
        help="Passerelle IPv4 de la configuration statique.",
    )
    parser.add_argument(
        "--dns",
        action="append",
        default=[],
        help="Serveur DNS IPv4 ; l'option peut être répétée.",
    )
    parser.add_argument(
        "--rollback-seconds",
        type=int,
        default=180,
        help="Délai de retour automatique, entre 30 et 300 secondes.",
    )
    parser.set_defaults(command_handler=run)


def _configuration_from_args(
    args: argparse.Namespace,
) -> InitialNetworkConfiguration | None:
    requested = bool(args.dhcp or args.address)
    if not requested:
        if args.interface or args.gateway or args.dns:
            raise NetworkProvisioningError("Choisissez --dhcp ou fournissez --address.")
        return None
    if not args.interface:
        raise NetworkProvisioningError("--interface est obligatoire pour modifier le réseau.")
    if args.dhcp:
        if args.gateway or args.dns:
            raise NetworkProvisioningError(
                "La passerelle et les DNS manuels ne s'appliquent pas au mode DHCP."
            )
        return InitialNetworkConfiguration(
            interface=args.interface,
            method="auto",
        )
    if not args.gateway or not args.dns:
        raise NetworkProvisioningError(
            "--gateway et au moins un --dns sont requis en mode statique."
        )
    try:
        return InitialNetworkConfiguration(
            interface=args.interface,
            method="manual",
            address=IPv4Interface(args.address),
            gateway=IPv4Address(args.gateway),
            dns_servers=tuple(IPv4Address(value) for value in args.dns),
        )
    except ValueError as error:
        raise NetworkProvisioningError(f"Configuration IPv4 invalide : {error}") from error


def _display_state(state: dict[str, object]) -> None:
    method = "DHCP" if state.get("method") == "auto" else "Statique"
    dns = state.get("dns_servers")
    dns_text = ", ".join(str(value) for value in dns) if isinstance(dns, list) else "—"
    print(f"Interface : {state.get('interface') or '—'}")
    print(f"Mode      : {method}")
    print(f"Adresse   : {state.get('address') or '—'}")
    print(f"Passerelle: {state.get('gateway') or '—'}")
    print(f"DNS       : {dns_text or '—'}")
    print(f"État      : {state.get('state') or 'inconnu'}")


def run(args: argparse.Namespace) -> int:
    """Lire ou modifier la configuration réseau sans installer Agent/Vision."""
    try:
        configuration = _configuration_from_args(args)
        if configuration is None:
            _display_state(read_network_state())
            return 0

        print("Nouvelle configuration réseau :")
        print(f"  Interface : {configuration.interface}")
        print(f"  Mode      : {'DHCP' if configuration.method == 'auto' else 'Statique'}")
        if configuration.method == "manual":
            print(f"  Adresse   : {configuration.address}")
            print(f"  Passerelle: {configuration.gateway}")
            print("  DNS       : " + ", ".join(str(server) for server in configuration.dns_servers))
        print()

        if not confirm_action(
            "Appliquer cette configuration réseau ?",
            assume_yes=bool(args.yes),
        ):
            print("Modification réseau annulée.")
            return 0

        change = begin_network_configuration(
            configuration,
            rollback_seconds=args.rollback_seconds,
        )
        print()
        print("✓ Nouvelle configuration appliquée temporairement.")
        print(
            f"  Sans confirmation, l'ancienne configuration sera restaurée "
            f"dans {args.rollback_seconds} secondes."
        )

        if args.yes or confirm_action(
            "La connexion fonctionne-t-elle correctement ?",
            assume_yes=False,
        ):
            state = confirm_network_configuration(change.transaction_id)
            print("✓ Configuration réseau confirmée.")
            _display_state(state)
            return 0

        state = rollback_network_configuration(change.transaction_id)
        print("✓ Ancienne configuration réseau restaurée.")
        _display_state(state)
        return 0
    except NetworkProvisioningError as error:
        print(f"✗ Configuration réseau impossible : {error}")
        return NETWORK_ERROR
