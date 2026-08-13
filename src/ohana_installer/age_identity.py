"""Gestion locale et récupération iCloud de l'identité age d'INFRA-01."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

AGE_BINARY = Path("/usr/bin/age")
AGE_KEYGEN_BINARY = Path("/usr/bin/age-keygen")
APT_GET = "/usr/bin/apt-get"
IDENTITY_DIRECTORY = Path("/etc/ohana-agent/keys")
IDENTITY_PATH = IDENTITY_DIRECTORY / "infra-01.agekey"
RECIPIENT_PATH = IDENTITY_DIRECTORY / "infra-01.agepub"
RCLONE_BINARY = Path("/usr/bin/rclone")
RCLONE_CONFIG_PATH = Path("/etc/ohana-agent/rclone.conf")
RECOVERY_REMOTE_PATH = "icloud:Ohana/Recovery/infra-01.agekey"


class AgeIdentityError(RuntimeError):
    """Échec de préparation ou de récupération de l'identité age."""


def _run(
    command: Sequence[str],
    *,
    command_runner: CommandRunner = subprocess.run,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = command_runner(
            tuple(command),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise AgeIdentityError(f"Impossible d'exécuter {command[0]} : {error}") from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "erreur inconnue").strip()
        raise AgeIdentityError(f"La commande {' '.join(command)} a échoué : {detail[:500]}")
    return result


def ensure_age_installed(
    *,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Installer age uniquement lorsque ses deux binaires sont absents."""

    if AGE_BINARY.is_file() and AGE_KEYGEN_BINARY.is_file():
        return
    for command in (
        (APT_GET, "update"),
        (APT_GET, "install", "--yes", "--no-install-recommends", "age"),
    ):
        _run(command, command_runner=command_runner)
    if not AGE_BINARY.is_file() or not AGE_KEYGEN_BINARY.is_file():
        raise AgeIdentityError("L'installation de age n'a pas fourni age et age-keygen.")


def derive_recipient(
    identity_path: Path,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> str:
    """Dériver et valider le destinataire public d'une identité."""

    result = _run(
        (str(AGE_KEYGEN_BINARY), "-y", str(identity_path)),
        command_runner=command_runner,
    )
    recipient = result.stdout.strip()
    if not recipient.startswith("age1"):
        raise AgeIdentityError("age-keygen n'a pas produit de destinataire public valide.")
    return recipient


def install_identity(
    source: Path,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> str:
    """Installer atomiquement une identité et son destinataire public."""

    if not source.is_file():
        raise AgeIdentityError(f"Identité age introuvable : {source}.")
    recipient = derive_recipient(source, command_runner=command_runner)
    IDENTITY_DIRECTORY.mkdir(parents=True, exist_ok=True)
    os.chmod(IDENTITY_DIRECTORY, 0o750)
    shutil.chown(IDENTITY_DIRECTORY, user="root", group="ohana-agent")
    temporary_identity = IDENTITY_PATH.with_suffix(".agekey.tmp")
    temporary_recipient = RECIPIENT_PATH.with_suffix(".agepub.tmp")
    try:
        shutil.copyfile(source, temporary_identity)
        os.chmod(temporary_identity, 0o640)
        shutil.chown(temporary_identity, user="root", group="ohana-agent")
        temporary_recipient.write_text(recipient + "\n", encoding="utf-8")
        os.chmod(temporary_recipient, 0o640)
        shutil.chown(temporary_recipient, user="root", group="ohana-agent")
        os.replace(temporary_identity, IDENTITY_PATH)
        os.replace(temporary_recipient, RECIPIENT_PATH)
    finally:
        temporary_identity.unlink(missing_ok=True)
        temporary_recipient.unlink(missing_ok=True)
    return recipient


def create_identity(
    *,
    command_runner: CommandRunner = subprocess.run,
) -> str:
    """Créer l'identité locale lorsqu'aucune identité n'existe."""

    ensure_age_installed(command_runner=command_runner)
    if IDENTITY_PATH.is_file():
        return install_identity(IDENTITY_PATH, command_runner=command_runner)
    IDENTITY_DIRECTORY.mkdir(parents=True, exist_ok=True)
    os.chmod(IDENTITY_DIRECTORY, 0o750)
    shutil.chown(IDENTITY_DIRECTORY, user="root", group="ohana-agent")
    temporary = IDENTITY_DIRECTORY / ".infra-01.agekey.new"
    try:
        _run(
            (str(AGE_KEYGEN_BINARY), "-o", str(temporary)),
            command_runner=command_runner,
        )
        os.chmod(temporary, 0o640)
        return install_identity(temporary, command_runner=command_runner)
    finally:
        temporary.unlink(missing_ok=True)


def upload_recovery_identity(
    *,
    command_runner: CommandRunner = subprocess.run,
) -> bool:
    """Copier et valider l'identité dans iCloud lorsque rclone est configuré."""

    if not IDENTITY_PATH.is_file() or not RCLONE_CONFIG_PATH.is_file():
        return False
    _run(
        (
            str(RCLONE_BINARY),
            "copyto",
            str(IDENTITY_PATH),
            RECOVERY_REMOTE_PATH,
            "--config",
            str(RCLONE_CONFIG_PATH),
            "--log-level",
            "ERROR",
        ),
        command_runner=command_runner,
    )
    result = _run(
        (
            str(RCLONE_BINARY),
            "size",
            RECOVERY_REMOTE_PATH,
            "--json",
            "--config",
            str(RCLONE_CONFIG_PATH),
        ),
        command_runner=command_runner,
    )
    try:
        remote_size = int(json.loads(result.stdout)["bytes"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AgeIdentityError(
            "rclone n'a pas renvoye une taille exploitable pour la copie iCloud."
        ) from error
    if remote_size != IDENTITY_PATH.stat().st_size:
        raise AgeIdentityError("La copie de récupération iCloud n'a pas la taille attendue.")
    return True


def ensure_local_identity(
    *,
    command_runner: CommandRunner = subprocess.run,
) -> str:
    """Créer ou réparer l'identité locale, puis la synchroniser si possible."""

    recipient = create_identity(command_runner=command_runner)
    upload_recovery_identity(command_runner=command_runner)
    return recipient


def download_recovery_identity(
    destination: Path,
    *,
    rclone_config: Path,
    command_runner: CommandRunner = subprocess.run,
) -> Path:
    """Télécharger l'identité de récupération dans le tmpfs de restauration."""

    result = _run(
        (
            str(RCLONE_BINARY),
            "copyto",
            RECOVERY_REMOTE_PATH,
            str(destination),
            "--config",
            str(rclone_config),
            "--log-level",
            "ERROR",
        ),
        command_runner=command_runner,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        detail = (result.stderr or result.stdout or "identité absente").strip()
        raise AgeIdentityError(
            f"Identité de récupération age introuvable dans iCloud : {detail[:300]}"
        )
    os.chmod(destination, 0o600)
    derive_recipient(destination, command_runner=command_runner)
    return destination
