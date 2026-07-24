"""Installation des composants Python Ohana."""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COMMAND_TIMEOUT = 120.0

INSTALLATION_DIRECTORY_MODE = 0o750
INSTALLATION_FILE_MODE = 0o640
INSTALLATION_EXECUTABLE_MODE = 0o750


class PackageInstallationError(RuntimeError):
    """Erreur rencontrée pendant l'installation d'un package Python."""


@dataclass(frozen=True)
class InstalledPythonComponent:
    """Composant Python installé dans son environnement virtuel."""

    name: str
    version: str
    environment_path: Path
    executable_path: Path


def inspect_installed_component(
    *,
    environment_path: Path | str,
    command_name: str,
    component_name: str,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> InstalledPythonComponent | None:
    """Lire la version d'un composant installé, s'il existe."""

    target_environment = Path(environment_path)
    executable_path = get_environment_executable(
        target_environment,
        command_name,
    )

    if not executable_path.is_file():
        return None

    result = _run_command(
        [
            str(executable_path),
            "--version",
        ],
        timeout=timeout,
        error_message=f"Impossible de lire la version de {component_name}",
    )
    output = result.stdout.strip()
    version_matches = re.findall(
        r"(?<!\d)(\d+\.\d+\.\d+(?:[A-Za-z0-9.+-]*))(?!\d)",
        output,
    )

    if len(version_matches) != 1:
        raise PackageInstallationError(
            f"Version illisible pour {component_name} : {output or 'aucune sortie'}."
        )

    return InstalledPythonComponent(
        name=component_name,
        version=version_matches[0],
        environment_path=target_environment,
        executable_path=executable_path,
    )


def create_virtual_environment(
    environment_path: Path | str,
    *,
    python_executable: Path | str = sys.executable,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> Path:
    """Créer un environnement virtuel Python."""

    target_path = Path(environment_path)

    if target_path.exists():
        raise PackageInstallationError(f"L'environnement Python existe déjà : {target_path}.")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(python_executable),
        "-m",
        "venv",
        str(target_path),
    ]

    _run_command(
        command,
        timeout=timeout,
        error_message=(f"Impossible de créer l'environnement Python {target_path}"),
    )

    return target_path


def install_wheel(
    wheel_path: Path | str,
    environment_path: Path | str,
    *,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> None:
    """Installer un wheel dans un environnement virtuel."""

    package_path = Path(wheel_path)
    target_environment = Path(environment_path)

    if not package_path.is_file():
        raise PackageInstallationError(f"Le wheel est introuvable : {package_path}.")

    pip_executable = get_environment_executable(
        target_environment,
        "pip",
    )

    if not pip_executable.is_file():
        raise PackageInstallationError(f"pip est introuvable dans {target_environment}.")

    _run_command(
        [
            str(pip_executable),
            "install",
            "--disable-pip-version-check",
            str(package_path),
        ],
        timeout=timeout,
        error_message=f"Impossible d'installer le wheel {package_path.name}",
    )


def upgrade_wheel(
    wheel_path: Path | str,
    *,
    python_executable: Path | str = sys.executable,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> None:
    """Mettre à niveau un package dans l'environnement Python courant."""

    package_path = Path(wheel_path)

    if not package_path.is_file():
        raise PackageInstallationError(f"Le wheel est introuvable : {package_path}.")

    _run_command(
        [
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            str(package_path),
        ],
        timeout=timeout,
        error_message=f"Impossible de mettre à niveau le wheel {package_path.name}",
    )


def verify_component_command(
    *,
    environment_path: Path | str,
    command_name: str,
    expected_version: str,
    component_name: str,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> InstalledPythonComponent:
    """Vérifier la commande et la version d'un composant installé."""

    installed_component = inspect_installed_component(
        environment_path=environment_path,
        command_name=command_name,
        component_name=component_name,
        timeout=timeout,
    )

    if installed_component is None:
        raise PackageInstallationError(
            f"La commande {command_name} est introuvable après installation."
        )

    if installed_component.version != expected_version:
        raise PackageInstallationError(
            f"Version inattendue pour {component_name} : {installed_component.version}."
        )

    return installed_component


def _secured_file_mode(source_mode: int) -> int:
    """Return a secure mode while preserving executability."""

    executable = bool(source_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    return INSTALLATION_EXECUTABLE_MODE if executable else INSTALLATION_FILE_MODE


def secure_installation_tree(
    installation_path: Path | str,
    *,
    owner: str,
    group: str,
) -> None:
    """Secure a component installation without following symlinks."""

    root_path = Path(installation_path)

    if root_path.is_symlink():
        raise PackageInstallationError(
            f"Le répertoire d'installation {root_path} ne peut pas être un lien symbolique."
        )

    if not root_path.is_dir():
        raise PackageInstallationError(
            f"Le répertoire d'installation est introuvable : {root_path}."
        )

    paths = (root_path, *root_path.rglob("*"))

    for path in paths:
        if path.is_symlink():
            continue

        if path.is_dir():
            mode = INSTALLATION_DIRECTORY_MODE
        elif path.is_file():
            try:
                source_mode = path.stat().st_mode
            except OSError as error:
                raise PackageInstallationError(
                    f"Impossible de lire les permissions de {path} : {error}"
                ) from error

            mode = _secured_file_mode(source_mode)
        else:
            raise PackageInstallationError(
                f"Le chemin d'installation {path} n'est ni un fichier ni un répertoire régulier."
            )

        try:
            shutil.chown(
                path,
                user=owner,
                group=group,
            )
            path.chmod(mode)
        except (LookupError, OSError) as error:
            raise PackageInstallationError(
                f"Impossible de sécuriser {path} ({owner}:{group}, {mode:04o}) : {error}"
            ) from error


def get_environment_executable(
    environment_path: Path,
    command_name: str,
) -> Path:
    """Retourner le chemin d'un exécutable dans un environnement virtuel."""

    if sys.platform == "win32":
        suffix = ".exe"
        return environment_path / "Scripts" / f"{command_name}{suffix}"

    return environment_path / "bin" / command_name


def _run_command(
    command: list[str],
    *,
    timeout: float,
    error_message: str,
) -> subprocess.CompletedProcess[str]:
    """Exécuter une commande système contrôlée."""

    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise PackageInstallationError(f"{error_message} : délai dépassé.") from error
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip() or error.stdout.strip()

        if details:
            raise PackageInstallationError(f"{error_message} : {details}") from error

        raise PackageInstallationError(error_message) from error
    except OSError as error:
        raise PackageInstallationError(f"{error_message} : {error}") from error
