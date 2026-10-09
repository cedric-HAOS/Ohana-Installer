"""Restauration vérifiée d'une sauvegarde logique INFRA-01."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from collections.abc import Callable, Sequence
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from ohana_installer.administration import (
    AGENT_PLUGIN_CONFIGURATION_FILENAMES,
    DNSMASQ_MANAGED_FILES,
)
from ohana_installer.restore_authorizations import stage_authorizations
from ohana_installer.restore_manifest import (
    BACKUP_ID_PATTERN,
    RestoreManifest,
    RestoreManifestError,
    parse_restore_manifest,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
OwnerRestorer = Callable[[Path], None]

ALLOWED_ARCHIVE_ROOTS = (
    PurePosixPath("etc/ohana-agent"),
    PurePosixPath("etc/ohana-vision"),
    PurePosixPath("etc/dnsmasq.d"),
    PurePosixPath("etc/chrony/chrony.conf"),
    PurePosixPath("var/lib/ohana-vision/vision.db"),
    PurePosixPath("ohana-backup/descriptor.json"),
)
DESCRIPTOR_PATH = PurePosixPath("ohana-backup/descriptor.json")
REQUIRED_PAYLOAD_ROOTS = ALLOWED_ARCHIVE_ROOTS[:-1]
PAYLOAD_DIRECTORY_ROOTS = frozenset(
    {
        PurePosixPath("etc/ohana-agent"),
        PurePosixPath("etc/ohana-vision"),
        PurePosixPath("etc/dnsmasq.d"),
    }
)
SERVICE_ORDER = (
    "ohana-agent.service",
    "ohana-vision.service",
    "chrony.service",
    "dnsmasq.service",
)


class RestoreError(RuntimeError):
    """Échec sûr d'une étape de restauration."""


@dataclass(frozen=True)
class _RollbackFile:
    destination: Path
    backup: Path | None
    mode: int | None
    uid: int | None
    gid: int | None


def require_tmpfs(path: Path, *, mounts_path: Path = Path("/proc/mounts")) -> None:
    """Refuser tout staging de restauration sur un stockage persistant."""

    if not mounts_path.is_file():
        raise RestoreError("Impossible de vérifier que le répertoire temporaire est en RAM.")
    resolved = path.resolve()
    candidates: list[tuple[Path, str]] = []
    for line in mounts_path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_point = Path(fields[1].replace("\\040", " ")).resolve()
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        candidates.append((mount_point, fields[2]))
    if not candidates:
        raise RestoreError(f"Système de fichiers indéterminé pour {path}.")
    _mount, filesystem = max(candidates, key=lambda candidate: len(candidate[0].parts))
    if filesystem != "tmpfs":
        raise RestoreError(
            f"Le répertoire {path} utilise {filesystem}, pas tmpfs ; restauration refusée."
        )


def latest_local_backup(directory: Path) -> Path:
    """Sélectionner un dossier de sauvegarde explicite ou le plus récent."""

    if (directory / "manifest.json").is_file():
        return directory
    candidates = tuple(
        child
        for child in directory.iterdir()
        if child.is_dir()
        and BACKUP_ID_PATTERN.fullmatch(child.name)
        and _local_backup_is_complete(child)
    )
    if not candidates:
        raise RestoreError(f"Aucune sauvegarde INFRA-01 trouvée dans {directory}.")
    return max(candidates, key=lambda path: path.name)


def _local_backup_is_complete(directory: Path) -> bool:
    try:
        manifest = parse_restore_manifest((directory / "manifest.json").read_bytes())
    except (OSError, RestoreManifestError):
        return False
    return (
        manifest.backup_id == directory.name and (directory / manifest.archive.filename).is_file()
    )


def select_remote_manifest(
    backup_ids: Sequence[str],
    *,
    manifest_reader: Callable[[str], bytes],
    requested_id: str | None = None,
) -> tuple[RestoreManifest, bytes]:
    """Retenir la sauvegarde demandée ou la plus récente entièrement publiée."""

    if requested_id is not None:
        if requested_id not in backup_ids:
            raise RestoreError("La sauvegarde iCloud demandée est introuvable.")
        candidates = (requested_id,)
    else:
        candidates = tuple(reversed(backup_ids))
    for backup_id in candidates:
        try:
            content = manifest_reader(backup_id)
            manifest = parse_restore_manifest(content)
        except (RestoreError, RestoreManifestError):
            if requested_id is not None:
                raise RestoreError(
                    "La sauvegarde iCloud demandée est incomplète ou invalide."
                ) from None
            continue
        if manifest.backup_id == backup_id:
            return manifest, content
        if requested_id is not None:
            raise RestoreError("Le manifeste ne correspond pas à la sauvegarde iCloud demandée.")
    raise RestoreError("Aucune sauvegarde iCloud complète et valide n'est disponible.")


def list_remote_manifests(
    backup_ids: Sequence[str],
    *,
    manifest_reader: Callable[[str], bytes],
) -> tuple[tuple[RestoreManifest, bytes], ...]:
    """Lister les sauvegardes iCloud valides, de la plus récente à la plus ancienne."""

    available: list[tuple[RestoreManifest, bytes]] = []
    for backup_id in reversed(backup_ids):
        try:
            content = manifest_reader(backup_id)
            manifest = parse_restore_manifest(content)
        except (RestoreError, RestoreManifestError):
            continue
        if manifest.backup_id == backup_id:
            available.append((manifest, content))
    if not available:
        raise RestoreError("Aucune sauvegarde INFRA-01 valide n'est disponible dans iCloud.")
    return tuple(available)


def list_remote_backup_ids(
    *,
    rclone_binary: Path,
    rclone_config: Path,
    remote: str,
    command_runner: CommandRunner = subprocess.run,
) -> tuple[str, ...]:
    """Lister les identifiants valides disponibles sur iCloud."""

    result = command_runner(
        (
            str(rclone_binary),
            "lsf",
            remote,
            "--dirs-only",
            "--config",
            str(rclone_config),
            "--log-level",
            "ERROR",
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "erreur inconnue").strip()
        if "directory not found" in detail.lower():
            return ()
        raise RestoreError(f"Impossible de lister les sauvegardes iCloud : {detail}")
    return tuple(
        sorted(
            value
            for line in result.stdout.splitlines()
            if (value := line.strip().rstrip("/")) and BACKUP_ID_PATTERN.fullmatch(value)
        )
    )


def rclone_read_bytes(
    remote_path: str,
    *,
    rclone_binary: Path,
    rclone_config: Path,
    command_runner: CommandRunner = subprocess.run,
) -> bytes:
    """Lire un petit objet distant, tel que le manifeste non secret."""

    result = command_runner(
        (
            str(rclone_binary),
            "cat",
            remote_path,
            "--config",
            str(rclone_config),
            "--log-level",
            "ERROR",
        ),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or b"erreur inconnue").decode(errors="replace").strip()
        raise RestoreError(f"Impossible de lire {remote_path} : {detail}")
    return result.stdout


def decrypt_and_extract(
    encrypted_stream: BinaryIO,
    *,
    manifest: RestoreManifest,
    identity_path: Path,
    staging_directory: Path,
    age_binary: Path = Path("/usr/bin/age"),
    popen_factory: Any = subprocess.Popen,
    chunk_size: int = 1024 * 1024,
) -> tuple[Path, ...]:
    """Vérifier le flux chiffré, le déchiffrer en RAM et extraire les membres sûrs."""

    if not identity_path.is_file():
        raise RestoreError(f"Identité age introuvable : {identity_path}.")
    staging_directory.mkdir(parents=True, exist_ok=True)
    decrypted_tar = staging_directory / "payload.tar"
    extracted = staging_directory / "payload"
    extracted.mkdir()
    process = popen_factory(
        (
            str(age_binary),
            "--decrypt",
            "--identity",
            str(identity_path),
            "--output",
            str(decrypted_tar),
            "-",
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if process.stdin is None:
        process.kill()
        raise RestoreError("age n'a pas ouvert son flux d'entrée.")
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := encrypted_stream.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
            process.stdin.write(chunk)
        process.stdin.close()
        process.stdin = None
        _stdout, stderr = process.communicate()
    except BrokenPipeError as error:
        if process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()
            process.stdin = None
        _stdout, stderr = process.communicate()
        detail = (stderr or b"flux de dechiffrement interrompu").decode(errors="replace").strip()
        raise RestoreError(f"Déchiffrement age impossible : {detail}") from error
    except Exception:
        process.kill()
        if process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()
            process.stdin = None
        process.communicate()
        raise
    if process.returncode != 0:
        detail = (stderr or b"erreur inconnue").decode(errors="replace").strip()
        raise RestoreError(f"Déchiffrement age impossible : {detail}")
    if size != manifest.archive.size_bytes:
        raise RestoreError(
            f"Taille d'archive invalide : {size}, attendu {manifest.archive.size_bytes}."
        )
    if digest.hexdigest() != manifest.archive.sha256:
        raise RestoreError("Le SHA-256 de l'archive chiffrée est invalide.")

    members: list[Path] = []
    try:
        with tarfile.open(decrypted_tar, mode="r:*") as archive:
            for member in archive:
                relative = _safe_member_path(member)
                archive.extract(member, path=extracted, filter="data")
                members.append(extracted.joinpath(*relative.parts))
    except (OSError, tarfile.TarError) as error:
        raise RestoreError(f"Archive de restauration invalide : {error}") from error
    finally:
        decrypted_tar.unlink(missing_ok=True)
    _verify_and_remove_descriptor(extracted, manifest)
    database = extracted / "var/lib/ohana-vision/vision.db"
    if database.is_file():
        _validate_database(database)
    return tuple(members)


def _validate_database(path: Path) -> None:
    try:
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        ) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise RestoreError(f"Base SQLite de sauvegarde invalide : {path.name}.")
    except sqlite3.Error as error:
        raise RestoreError(f"Base SQLite de sauvegarde invalide : {path.name} : {error}") from error


def _verify_and_remove_descriptor(
    extracted: Path,
    manifest: RestoreManifest,
) -> None:
    """Bind the public manifest to metadata protected by the age archive."""

    descriptor_path = extracted.joinpath(*DESCRIPTOR_PATH.parts)
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreError(
            "Le descripteur chiffré de la sauvegarde est absent ou invalide."
        ) from error
    expected = {
        "schema_version": manifest.schema_version,
        "backup_id": manifest.backup_id,
        "created_at": manifest.created_at,
        "profile": manifest.profile,
        "platform_version": manifest.platform_version,
        "agent_version": manifest.agent_version,
        "vision_version": manifest.vision_version,
    }
    if not isinstance(descriptor, dict):
        raise RestoreError("Le descripteur chiffré doit être un objet JSON.")
    if "contents" in descriptor:
        contents = descriptor.pop("contents")
        required = {str(root) for root in REQUIRED_PAYLOAD_ROOTS}
        if (
            not isinstance(contents, list)
            or not all(isinstance(item, str) for item in contents)
            or len(contents) != len(required)
            or set(contents) != required
        ):
            raise RestoreError("L'inventaire du descripteur chiffré est invalide.")
        for root in REQUIRED_PAYLOAD_ROOTS:
            path = extracted.joinpath(*root.parts)
            present = path.is_dir() if root in PAYLOAD_DIRECTORY_ROOTS else path.is_file()
            if not present:
                raise RestoreError(f"Élément déclaré absent de l'archive : {root}.")
    if descriptor != expected:
        raise RestoreError(
            "Le manifeste public ne correspond pas au descripteur chiffré de l'archive."
        )
    descriptor_path.unlink()
    descriptor_path.parent.rmdir()


def _safe_member_path(member: tarfile.TarInfo) -> PurePosixPath:
    if not (member.isfile() or member.isdir()):
        raise RestoreError(f"Type de membre interdit dans l'archive : {member.name}.")
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RestoreError(f"Chemin d'archive interdit : {member.name}.")
    if not any(path == root or path.is_relative_to(root) for root in ALLOWED_ARCHIVE_ROOTS):
        raise RestoreError(f"Chemin hors périmètre de restauration : {member.name}.")
    return path


def install_platform(
    manifest: RestoreManifest,
    *,
    command: Sequence[str] = ("/usr/local/bin/ohana",),
    command_runner: CommandRunner = subprocess.run,
    agent_environment: Path = Path("/opt/ohana-agent/venv"),
    vision_environment: Path = Path("/opt/ohana-vision/venv"),
) -> None:
    """Installer la composition exacte avant de réappliquer ses données."""

    selection = (
        ("--platform-version", manifest.platform_version)
        if manifest.platform_version is not None
        else (
            "--agent-version",
            manifest.agent_version,
            "--vision-version",
            manifest.vision_version,
        )
    )
    action = "update" if agent_environment.exists() or vision_environment.exists() else "install"
    downgrade = ("--allow-downgrade",) if action == "update" else ()
    restore_options = ("--defer-age-identity",) if action == "install" else ()
    result = command_runner(
        (*command, action, "--yes", *selection, *downgrade, *restore_options),
        check=False,
    )
    if result.returncode != 0:
        raise RestoreError("Installation de la composition Agent/Vision sauvegardée impossible.")


def apply_staged_configuration(
    payload_directory: Path,
    *,
    command_runner: CommandRunner = subprocess.run,
    destination_root: Path = Path("/"),
    owner_restorer: OwnerRestorer | None = None,
) -> None:
    """Arrêter les services, appliquer les fichiers puis valider sans activer DHCP."""

    previously_active = tuple(
        service for service in SERVICE_ORDER if _service_is_active(command_runner, service)
    )
    _systemctl(command_runner, "stop", *SERVICE_ORDER)
    rollback_directory = payload_directory.parent / "rollback"
    rollback_files: list[_RollbackFile] = []
    try:
        try:
            generated = stage_authorizations(payload_directory, destination_root)
        except (ValueError, sqlite3.Error) as error:
            raise RestoreError(f"Autorisations de sauvegarde invalides : {error}") from error
        generated_paths = {relative.as_posix() for _source, relative in generated}
        sources = [
            (source, source.relative_to(payload_directory))
            for source in sorted(payload_directory.rglob("*"))
            if source.is_file()
        ]
        sources.extend(generated)
        for source, source_relative in sources:
            relative = PurePosixPath(source_relative.as_posix())
            if (
                not any(
                    relative == root or relative.is_relative_to(root)
                    for root in ALLOWED_ARCHIVE_ROOTS
                )
                and relative.as_posix() not in generated_paths
            ):
                raise RestoreError(f"Fichier restauré hors périmètre : {relative}.")
            destination = destination_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if (
                relative.as_posix() == "var/lib/ohana-vision/vision.db"
                or relative.as_posix() in generated_paths
            ):
                _validate_database(source)
                for suffix in ("-wal", "-shm"):
                    sidecar = destination.with_name(destination.name + suffix)
                    if sidecar.exists():
                        rollback_files.append(
                            _capture_rollback(
                                sidecar, PurePosixPath(str(relative) + suffix), rollback_directory
                            )
                        )
                        sidecar.unlink()
            rollback_files.append(_capture_rollback(destination, relative, rollback_directory))
            _atomic_restore_file(source, destination, owner_restorer=owner_restorer)

        _validate_restored_services(command_runner)
        _systemctl(
            command_runner,
            "enable",
            "--now",
            "chrony.service",
            "ohana-agent.service",
            "ohana-vision.service",
        )
        _systemctl(command_runner, "disable", "--now", "dnsmasq.service", check=False)
    except Exception:
        _systemctl(command_runner, "stop", *SERVICE_ORDER, check=False)
        for rollback in reversed(rollback_files):
            if rollback.destination.suffix == ".db":
                for suffix in ("-wal", "-shm"):
                    rollback.destination.with_name(rollback.destination.name + suffix).unlink(
                        missing_ok=True
                    )
            if rollback.backup is None:
                rollback.destination.unlink(missing_ok=True)
                continue
            _atomic_restore_file(
                rollback.backup,
                rollback.destination,
                owner_restorer=owner_restorer,
            )
            if rollback.mode is not None:
                os.chmod(rollback.destination, rollback.mode)
            chown = getattr(os, "chown", None)
            if chown is not None and rollback.uid is not None and rollback.gid is not None:
                chown(rollback.destination, rollback.uid, rollback.gid)
        if previously_active:
            _systemctl(command_runner, "start", *previously_active, check=False)
        raise


def _capture_rollback(
    destination: Path,
    relative: PurePosixPath,
    rollback_directory: Path,
) -> _RollbackFile:
    if not destination.is_file():
        return _RollbackFile(destination, None, None, None, None)
    stat = destination.stat()
    backup = rollback_directory.joinpath(*relative.parts)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(destination, backup)
    return _RollbackFile(
        destination=destination,
        backup=backup,
        mode=stat.st_mode & 0o777,
        uid=getattr(stat, "st_uid", None),
        gid=getattr(stat, "st_gid", None),
    )


def _atomic_restore_file(
    source: Path,
    destination: Path,
    *,
    owner_restorer: OwnerRestorer | None = None,
) -> None:
    temporary = destination.with_name(f".{destination.name}.ohana-restore")
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, source.stat().st_mode & 0o777)
        os.replace(temporary, destination)
        (owner_restorer or _restore_owner)(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _service_is_active(command_runner: CommandRunner, service: str) -> bool:
    result = command_runner(
        ("/usr/bin/systemctl", "is-active", service),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "active"


def _restore_owner(path: Path) -> None:
    if path == Path("/etc/ohana-agent/rclone.conf"):
        user = group = "ohana-agent"
    elif path.is_relative_to(Path("/etc/ohana-agent")):
        user, group = "root", "ohana-agent"
    elif path.is_relative_to(Path("/etc/ohana-vision")):
        user, group = "root", "ohana-vision"
    elif path.is_relative_to(Path("/var/lib/ohana-vision")):
        user = group = "ohana-vision"
    elif path.is_relative_to(Path("/var/lib/ohana-agent")):
        user = group = "ohana-agent"
    elif path.parent == Path("/etc/dnsmasq.d") and path.name in DNSMASQ_MANAGED_FILES:
        user, group = "root", "ohana-agent"
    else:
        user = group = "root"
    try:
        shutil.chown(path, user=user, group=group)
        if path == Path("/etc/ohana-agent/rclone.conf"):
            path.chmod(0o600)
        if (
            (path.parent == Path("/etc/dnsmasq.d") and path.name in DNSMASQ_MANAGED_FILES)
            or path
            in (
                Path("/etc/ohana-agent/shikamaru.yaml"),
                Path("/etc/ohana-agent/infrastructure.yaml"),
            )
            or (
                path.parent == Path("/etc/ohana-agent/plugins")
                and path.name in AGENT_PLUGIN_CONFIGURATION_FILENAMES
            )
        ):
            path.chmod(0o660)
    except (LookupError, OSError) as error:
        raise RestoreError(f"Propriétaire impossible pour {path} : {error}") from error


def _validate_restored_services(command_runner: CommandRunner) -> None:
    checks = (
        ("/usr/sbin/dnsmasq", "--test"),
        ("/usr/sbin/chronyd", "-p"),
    )
    for command in checks:
        result = command_runner(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "erreur inconnue").strip()
            raise RestoreError(f"Validation {' '.join(command)} impossible : {detail}")


def _systemctl(
    command_runner: CommandRunner,
    *arguments: str,
    check: bool = True,
) -> None:
    result = command_runner(
        ("/usr/bin/systemctl", *arguments),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "erreur inconnue").strip()
        raise RestoreError(f"Commande systemd impossible : {detail}")
