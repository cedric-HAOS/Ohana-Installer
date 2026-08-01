"""Gestion de la mise à jour automatique d'Ohana."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from ohana_installer.systemd import (
    SYSTEMD_SYSTEM_DIRECTORY,
    SystemdCommandError,
    reload_systemd_daemon,
)

AUTOMATIC_UPDATE_ERROR = 3
SERVICE_NAME = "ohana-update.service"
TIMER_NAME = "ohana-update.timer"
OHANA_COMMAND = "/usr/local/bin/ohana"

SERVICE_CONTENT = f"""[Unit]
Description=Mise à jour automatique d'Ohana
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={OHANA_COMMAND} update --yes --if-needed
"""

TIMER_CONTENT = """[Unit]
Description=Vérification quotidienne des mises à jour Ohana

[Timer]
OnCalendar=*-*-* 04:00:00
RandomizedDelaySec=30m
Persistent=true
Unit=ohana-update.service

[Install]
WantedBy=timers.target
"""


class AutomaticUpdateError(RuntimeError):
    """Erreur de configuration de la mise à jour automatique."""


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande automatic-update."""

    parser = subparsers.add_parser(
        "automatic-update",
        help="Configurer la mise à jour automatique.",
        description="Activer, désactiver ou consulter la mise à jour automatique.",
    )
    actions = parser.add_subparsers(dest="automatic_update_action", required=True)
    for action in ("enable", "disable", "status"):
        action_parser = actions.add_parser(action)
        action_parser.set_defaults(command_handler=run)


def _run_systemctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["systemctl", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise AutomaticUpdateError("La commande systemd a dépassé le délai autorisé.") from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()
        suffix = f" : {details}" if details else ""
        raise AutomaticUpdateError(
            f"La commande systemctl {' '.join(arguments)} a échoué{suffix}."
        ) from error
    except OSError as error:
        raise AutomaticUpdateError(f"Impossible d'exécuter systemctl : {error}") from error


def is_enabled() -> bool:
    """Indiquer si le timer automatique est activé."""

    result = _run_systemctl("is-enabled", TIMER_NAME, check=False)
    return result.returncode == 0 and result.stdout.strip() in {"enabled", "enabled-runtime"}


def _write_unit(name: str, content: str) -> None:
    destination = SYSTEMD_SYSTEM_DIRECTORY / name
    try:
        destination.write_text(content, encoding="utf-8", newline="\n")
        destination.chmod(0o644)
    except OSError as error:
        raise AutomaticUpdateError(f"Impossible d'installer {destination} : {error}") from error


def enable() -> None:
    """Installer et activer le timer quotidien."""

    _write_unit(SERVICE_NAME, SERVICE_CONTENT)
    _write_unit(TIMER_NAME, TIMER_CONTENT)
    reload_systemd_daemon()
    _run_systemctl("enable", "--now", TIMER_NAME)


def disable() -> None:
    """Desactiver le timer quotidien, s'il existe."""

    _run_systemctl("disable", "--now", TIMER_NAME)


def remove_units(*, system_directory: Path | str = SYSTEMD_SYSTEM_DIRECTORY) -> bool:
    """Supprimer les unites de mise a jour automatique presentes."""

    removed = False
    for name in (SERVICE_NAME, TIMER_NAME):
        path = Path(system_directory) / name
        try:
            if path.exists():
                path.unlink()
                removed = True
        except OSError as error:
            raise AutomaticUpdateError(f"Impossible de supprimer {path} : {error}") from error
    return removed


def run(args: argparse.Namespace) -> int:
    """Executer l'action demandee."""

    try:
        if args.automatic_update_action == "enable":
            enable()
            print("✓ Mise à jour automatique activée (chaque jour vers 04:00).")
        elif args.automatic_update_action == "disable":
            if is_enabled():
                disable()
            print("✓ Mise à jour automatique désactivée.")
        else:
            state = "activée" if is_enabled() else "désactivée"
            print(f"Mise à jour automatique : {state}.")
        return 0
    except (AutomaticUpdateError, SystemdCommandError, OSError) as error:
        print(f"✗ Configuration de la mise à jour automatique impossible : {error}")
        return AUTOMATIC_UPDATE_ERROR
