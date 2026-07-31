"""Interface en ligne de commande d'Ohana-Installer."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ohana_installer.commands import install, network, uninstall, update, versions
from ohana_installer.interactive import run as run_interactive
from ohana_installer.version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Construire le parseur principal de la CLI."""

    parser = argparse.ArgumentParser(
        prog="ohana",
        description=(
            "Installer, mettre à jour et désinstaller les composants "
            "officiels de l'écosystème Ohana. Sans argument, la commande "
            "ouvre l'interface interactive."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commandes",
        metavar="{install,update,uninstall,versions,network}",
    )

    install.configure_parser(subparsers)
    update.configure_parser(subparsers)
    uninstall.configure_parser(subparsers)
    versions.configure_parser(subparsers)
    network.configure_parser(subparsers)

    return parser


def execute_command(argv: Sequence[str]) -> int:
    """Analyser puis exécuter une commande CLI explicite."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    command_handler = args.command_handler
    return command_handler(args)


def _interactive_terminal_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def main(argv: Sequence[str] | None = None) -> int:
    """Exécuter l'interface interactive ou une commande explicite."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        if not _interactive_terminal_available():
            print(
                "L'interface Ohana nécessite un terminal interactif. "
                "Utilisez une commande explicite, par exemple 'ohana --help'.",
                file=sys.stderr,
            )
            return 2
        return run_interactive(command_runner=execute_command)
    return execute_command(arguments)
