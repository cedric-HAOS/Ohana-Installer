"""Génération des unités systemd officielles Ohana."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ohana_installer.manifest import (
    ComponentManifest,
    ComponentService,
)

SYSTEMD_SYSTEM_DIRECTORY = Path("/etc/systemd/system")
DEFAULT_SYSTEMCTL_TIMEOUT = 30.0


class SystemdCommandError(RuntimeError):
    """Erreur pendant l'exécution d'une commande systemctl."""


class SystemdInstallationError(RuntimeError):
    """Erreur pendant l'installation d'une unité systemd."""


@dataclass(frozen=True)
class SystemdServiceStatus:
    """État d'un service systemd."""

    service_name: str
    active: bool
    status: str


@dataclass(frozen=True)
class InstalledSystemdService:
    """Unité systemd installée sur le système."""

    component: ComponentManifest
    source_path: Path
    destination_path: Path
    created: bool
    updated: bool = False


class SystemdGenerationError(RuntimeError):
    """Erreur pendant la génération d'une unité systemd."""


@dataclass(frozen=True)
class GeneratedSystemdService:
    """Unité systemd générée pour un composant."""

    component: ComponentManifest
    path: Path
    content: str


def get_systemd_service_status(
    service_name: str,
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> SystemdServiceStatus:
    """Retourner l'état d'un service systemd."""

    _validate_service_name(service_name)

    command = [
        str(systemctl_executable),
        "is-active",
        service_name,
    ]

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemdCommandError(
            "La vérification du service systemd a dépassé le délai autorisé."
        ) from error
    except OSError as error:
        raise SystemdCommandError(f"Commande systemd impossible : {error}") from error

    status = result.stdout.strip() or "unknown"

    return SystemdServiceStatus(
        service_name=service_name,
        active=status == "active",
        status=status,
    )


def reload_systemd_daemon(
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Recharger la configuration systemd."""

    command = [
        str(systemctl_executable),
        "daemon-reload",
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemdCommandError(
            "La commande systemctl daemon-reload a dépassé le délai autorisé."
        ) from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()

        if details:
            raise SystemdCommandError(
                f"La commande systemctl daemon-reload a échoué : {details}"
            ) from error

        raise SystemdCommandError("La commande systemctl daemon-reload a échoué.") from error
    except OSError as error:
        raise SystemdCommandError(
            f"Impossible d'exécuter systemctl daemon-reload : {error}"
        ) from error


def render_systemd_service(
    service: ComponentService,
) -> str:
    """Générer le contenu d'une unité systemd."""

    executable = service.executable.as_posix()
    working_directory = service.working_directory.as_posix()

    command = shlex.join(
        [
            executable,
            *service.arguments,
        ]
    )

    service_lines = [
        "[Unit]",
        f"Description={service.description}",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={service.user}",
        f"Group={service.group}",
        f"WorkingDirectory={working_directory}",
        f"ExecStart={command}",
    ]

    if service.filename == "ohana-agent.service":
        service_lines.extend(
            [
                "RuntimeDirectory=ohana-agent",
                "RuntimeDirectoryMode=0750",
            ]
        )

    state_directory = {
        "ohana-agent.service": "ohana-agent",
        "ohana-vision.service": "ohana-vision",
    }.get(service.filename)
    if state_directory is not None:
        service_lines.extend(
            [
                f"StateDirectory={state_directory}",
                "StateDirectoryMode=0750",
            ]
        )

    service_lines.extend(
        [
            "Restart=on-failure",
            "RestartSec=5",
            (
                "NoNewPrivileges=false"
                if service.filename == "ohana-agent.service"
                else "NoNewPrivileges=true"
            ),
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )

    return "\n".join(service_lines)


def generate_component_service(
    component: ComponentManifest,
    destination_directory: Path | str,
) -> GeneratedSystemdService:
    """Générer l'unité systemd déclarée par un composant."""

    if component.service is None:
        raise SystemdGenerationError(f"{component.name} ne déclare aucun service systemd.")

    destination = Path(destination_directory) / component.service.filename
    content = render_systemd_service(component.service)

    try:
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.write_text(
            content,
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        raise SystemdGenerationError(f"Impossible de générer {destination} : {error}") from error

    return GeneratedSystemdService(
        component=component,
        path=destination,
        content=content,
    )


def generate_systemd_services(
    components: tuple[ComponentManifest, ...],
    destination_directory: Path | str,
) -> tuple[GeneratedSystemdService, ...]:
    """Générer les unités systemd déclarées dans le manifeste."""

    return tuple(
        generate_component_service(
            component,
            destination_directory,
        )
        for component in components
        if component.service is not None
    )


def install_generated_service(
    generated_service: GeneratedSystemdService,
    *,
    system_directory: Path | str = SYSTEMD_SYSTEM_DIRECTORY,
    replace: bool = False,
) -> InstalledSystemdService:
    """Installer une unité systemd générée."""

    source_path = generated_service.path
    destination_path = Path(system_directory) / source_path.name

    if not source_path.is_file():
        raise SystemdInstallationError(f"L'unité générée est introuvable : {source_path}.")

    if destination_path.exists():
        try:
            existing_content = destination_path.read_text(
                encoding="utf-8",
            )
        except OSError as error:
            raise SystemdInstallationError(
                f"Impossible de lire {destination_path} : {error}"
            ) from error

        if existing_content == generated_service.content:
            return InstalledSystemdService(
                component=generated_service.component,
                source_path=source_path,
                destination_path=destination_path,
                created=False,
                updated=False,
            )

        if not replace:
            raise SystemdInstallationError(
                f"L'unité {destination_path} existe déjà avec un contenu différent."
            )

        try:
            shutil.copy2(
                source_path,
                destination_path,
            )
        except OSError as error:
            raise SystemdInstallationError(
                f"Impossible de remplacer {destination_path} : {error}"
            ) from error

        return InstalledSystemdService(
            component=generated_service.component,
            source_path=source_path,
            destination_path=destination_path,
            created=False,
            updated=True,
        )

    try:
        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            source_path,
            destination_path,
        )
    except OSError as error:
        raise SystemdInstallationError(
            f"Impossible d'installer {destination_path} : {error}"
        ) from error

    return InstalledSystemdService(
        component=generated_service.component,
        source_path=source_path,
        destination_path=destination_path,
        created=True,
        updated=False,
    )


def install_generated_services(
    generated_services: tuple[GeneratedSystemdService, ...],
    *,
    system_directory: Path | str = SYSTEMD_SYSTEM_DIRECTORY,
    replace: bool = False,
) -> tuple[InstalledSystemdService, ...]:
    """Installer plusieurs unités systemd générées."""

    return tuple(
        install_generated_service(
            generated_service,
            system_directory=system_directory,
            replace=replace,
        )
        for generated_service in generated_services
    )


def enable_systemd_service(
    service_name: str,
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Activer un service systemd au démarrage."""

    _validate_service_name(service_name)

    command = [
        str(systemctl_executable),
        "enable",
        service_name,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemdCommandError(
            f"La commande systemctl enable {service_name} a dépassé le délai autorisé."
        ) from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()

        if details:
            raise SystemdCommandError(
                f"La commande systemctl enable {service_name} a échoué : {details}"
            ) from error

        raise SystemdCommandError(
            f"La commande systemctl enable {service_name} a échoué."
        ) from error
    except OSError as error:
        raise SystemdCommandError(
            f"Impossible d'exécuter systemctl enable {service_name} : {error}"
        ) from error


def disable_systemd_service(
    service_name: str,
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Désactiver un service systemd au démarrage."""

    _validate_service_name(service_name)

    command = [
        str(systemctl_executable),
        "disable",
        service_name,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemdCommandError(
            f"La commande systemctl disable {service_name} a dépassé le délai autorisé."
        ) from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()

        if details:
            raise SystemdCommandError(
                f"La commande systemctl disable {service_name} a échoué : {details}"
            ) from error

        raise SystemdCommandError(
            f"La commande systemctl disable {service_name} a échoué."
        ) from error
    except OSError as error:
        raise SystemdCommandError(
            f"Impossible d'exécuter systemctl disable {service_name} : {error}"
        ) from error


def remove_systemd_service(
    service_name: str,
    *,
    system_directory: Path | str = SYSTEMD_SYSTEM_DIRECTORY,
) -> bool:
    """Supprimer une unité systemd.

    Retourner True si le fichier a été supprimé et False s'il était absent.
    """

    _validate_service_name(service_name)

    service_path = Path(system_directory) / service_name

    if not service_path.exists():
        return False

    if not service_path.is_file():
        raise SystemdInstallationError(f"L'unité systemd {service_path} n'est pas un fichier.")

    try:
        service_path.unlink()
    except OSError as error:
        raise SystemdInstallationError(
            f"Impossible de supprimer {service_path} : {error}"
        ) from error

    return True


def enable_systemd_services(
    installed_services: tuple[InstalledSystemdService, ...],
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Activer plusieurs services systemd."""

    for installed_service in installed_services:
        enable_systemd_service(
            installed_service.destination_path.name,
            systemctl_executable=systemctl_executable,
            timeout=timeout,
        )


def stop_systemd_service(
    service_name: str,
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Arrêter un service systemd."""

    _validate_service_name(service_name)

    command = [
        str(systemctl_executable),
        "stop",
        service_name,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemdCommandError(
            f"La commande systemctl stop {service_name} a dépassé le délai autorisé."
        ) from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()

        if details:
            raise SystemdCommandError(
                f"La commande systemctl stop {service_name} a échoué : {details}"
            ) from error

        raise SystemdCommandError(f"La commande systemctl stop {service_name} a échoué.") from error
    except OSError as error:
        raise SystemdCommandError(
            f"Impossible d'exécuter systemctl stop {service_name} : {error}"
        ) from error


def start_systemd_service(
    service_name: str,
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Démarrer un service systemd."""

    _validate_service_name(service_name)

    command = [
        str(systemctl_executable),
        "start",
        service_name,
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemdCommandError(
            f"La commande systemctl start {service_name} a dépassé le délai autorisé."
        ) from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()

        if details:
            raise SystemdCommandError(
                f"La commande systemctl start {service_name} a échoué : {details}"
            ) from error

        raise SystemdCommandError(
            f"La commande systemctl start {service_name} a échoué."
        ) from error
    except OSError as error:
        raise SystemdCommandError(
            f"Impossible d'exécuter systemctl start {service_name} : {error}"
        ) from error


def start_systemd_services(
    installed_services: tuple[InstalledSystemdService, ...],
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> None:
    """Démarrer plusieurs services systemd."""

    for installed_service in installed_services:
        start_systemd_service(
            installed_service.destination_path.name,
            systemctl_executable=systemctl_executable,
            timeout=timeout,
        )


def get_systemd_services_status(
    installed_services: tuple[InstalledSystemdService, ...],
    *,
    systemctl_executable: Path | str = "systemctl",
    timeout: float = DEFAULT_SYSTEMCTL_TIMEOUT,
) -> tuple[SystemdServiceStatus, ...]:
    """Retourner l'état de tous les services systemd installés."""

    return tuple(
        get_systemd_service_status(
            installed_service.destination_path.name,
            systemctl_executable=systemctl_executable,
            timeout=timeout,
        )
        for installed_service in installed_services
    )


def _validate_service_name(service_name: str) -> None:
    """Valider un nom de service systemd."""

    if not service_name or Path(service_name).name != service_name:
        raise SystemdCommandError(f"Nom de service systemd invalide : {service_name!r}.")

    if not service_name.endswith((".service", ".path")):
        raise SystemdCommandError(
            f"Le nom {service_name!r} doit se terminer par '.service' ou '.path'."
        )
