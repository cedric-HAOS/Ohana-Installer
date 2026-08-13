"""Commande de restauration complète d'INFRA-01."""

from __future__ import annotations

import argparse
import getpass
import shutil
import subprocess
import tempfile
from pathlib import Path

from ohana_installer.confirmation import confirm_action
from ohana_installer.icloud import ICloudAuthenticationError, TemporaryICloudSession
from ohana_installer.rclone import RcloneInstallationError, ensure_rclone
from ohana_installer.restore import (
    RestoreError,
    apply_staged_configuration,
    decrypt_and_extract,
    install_platform,
    latest_local_backup,
    list_remote_backup_ids,
    rclone_read_bytes,
    require_tmpfs,
    select_remote_manifest,
)
from ohana_installer.restore_manifest import RestoreManifestError, parse_restore_manifest

RESTORE_ERROR = 3
DEFAULT_REMOTE = "icloud:Ohana/Backups/infra-01"
RUNTIME_DIRECTORY = Path("/run/ohana-installer/restore")
RCLONE_BINARY = Path("/usr/bin/rclone")
AGE_BINARY = Path("/usr/bin/age")


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande restore."""

    parser = subparsers.add_parser(
        "restore",
        help="Reconstruire INFRA-01 depuis une sauvegarde vérifiée.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--local", type=Path, help="Dossier local de sauvegarde.")
    source.add_argument(
        "--icloud",
        action="store_true",
        help="Récupérer la sauvegarde depuis iCloud avec rclone.",
    )
    parser.add_argument("--backup-id", help="Sauvegarde précise ; dernière valide par défaut.")
    parser.add_argument(
        "--identity",
        type=Path,
        required=True,
        help="Fichier d'identité privée age conservé hors d'INFRA-01.",
    )
    parser.add_argument(
        "--rclone-config",
        type=Path,
        help="Configuration rclone existante ; sinon une session iCloud temporaire est créée.",
    )
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help=argparse.SUPPRESS)
    parser.add_argument("--apple-id", help="Apple ID ; demandé interactivement si nécessaire.")
    parser.add_argument("--yes", action="store_true", help="Confirmer la restauration.")
    parser.set_defaults(command_handler=run)


def _temporary_icloud_config(args: argparse.Namespace, runtime: Path) -> Path:
    if args.rclone_config is not None:
        if not args.rclone_config.is_file():
            raise RestoreError(f"Configuration rclone introuvable : {args.rclone_config}.")
        return args.rclone_config
    apple_id = (args.apple_id or input("Apple ID : ")).strip()
    password = getpass.getpass("Mot de passe Apple : ")
    config_path = runtime / "rclone.conf"
    session = TemporaryICloudSession(
        binary=RCLONE_BINARY,
        config_path=config_path,
    )
    continuation = session.begin(apple_id, password)
    if continuation is not None:
        code = input("Code de validation Apple à deux facteurs : ").strip()
        session.complete(continuation, code)
    return config_path


def _ensure_age() -> None:
    if AGE_BINARY.is_file():
        return
    commands = (
        ("/usr/bin/apt-get", "update"),
        (
            "/usr/bin/apt-get",
            "install",
            "--yes",
            "--no-install-recommends",
            "age",
        ),
    )
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "erreur inconnue").strip()
            raise RestoreError(f"Installation de age impossible : {detail}")
    if not AGE_BINARY.is_file():
        raise RestoreError(f"Binaire age introuvable après installation : {AGE_BINARY}.")


def run(args: argparse.Namespace) -> int:
    """Exécuter une restauration locale ou iCloud."""

    try:
        RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
        require_tmpfs(RUNTIME_DIRECTORY)
        with tempfile.TemporaryDirectory(
            prefix="ohana-restore-",
            dir=RUNTIME_DIRECTORY,
        ) as temporary:
            runtime = Path(temporary)
            rclone_config: Path | None = None
            remote_directory: str | None = None
            if args.local is not None:
                backup_directory = latest_local_backup(args.local)
                manifest_bytes = (backup_directory / "manifest.json").read_bytes()
            else:
                ensure_rclone(temporary_directory=runtime)
                rclone_config = _temporary_icloud_config(args, runtime)
                backup_ids = list_remote_backup_ids(
                    rclone_binary=RCLONE_BINARY,
                    rclone_config=rclone_config,
                    remote=args.remote,
                )
                manifest, manifest_bytes = select_remote_manifest(
                    backup_ids,
                    requested_id=args.backup_id,
                    manifest_reader=lambda backup_id: rclone_read_bytes(
                        f"{args.remote.rstrip('/')}/{backup_id}/manifest.json",
                        rclone_binary=RCLONE_BINARY,
                        rclone_config=rclone_config,
                    ),
                )
                remote_directory = f"{args.remote.rstrip('/')}/{manifest.backup_id}"

            if args.local is not None:
                manifest = parse_restore_manifest(manifest_bytes)
            if args.backup_id and manifest.backup_id != args.backup_id:
                raise RestoreError("Le manifeste ne correspond pas au backup_id demandé.")
            print(f"Sauvegarde INFRA-01 {manifest.backup_id}")
            print(f"Créée le        : {manifest.created_at}")
            platform = manifest.platform_version or "déduite du couple sauvegardé"
            print(f"Platform        : {platform}")
            print(f"Agent / Vision  : {manifest.agent_version} / {manifest.vision_version}")
            print(f"Archive chiffrée: {manifest.archive.size_bytes} octets")
            print()
            if not confirm_action(
                "Réinstaller INFRA-01 et restaurer cette sauvegarde ?",
                assume_yes=bool(args.yes),
            ):
                print("Restauration annulée.")
                return 0

            _ensure_age()
            staging = runtime / "staging"
            if args.local is not None:
                archive_path = backup_directory / manifest.archive.filename
                with archive_path.open("rb") as stream:
                    decrypt_and_extract(
                        stream,
                        manifest=manifest,
                        identity_path=args.identity,
                        staging_directory=staging,
                    )
            else:
                assert rclone_config is not None and remote_directory is not None
                process = subprocess.Popen(
                    (
                        str(RCLONE_BINARY),
                        "cat",
                        f"{remote_directory}/{manifest.archive.filename}",
                        "--config",
                        str(rclone_config),
                        "--log-level",
                        "ERROR",
                    ),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if process.stdout is None:
                    process.kill()
                    raise RestoreError("rclone n'a pas ouvert le flux de sauvegarde.")
                decrypt_and_extract(
                    process.stdout,
                    manifest=manifest,
                    identity_path=args.identity,
                    staging_directory=staging,
                )
                _stdout, stderr = process.communicate()
                if process.returncode != 0:
                    detail = (stderr or b"erreur inconnue").decode(errors="replace")
                    raise RestoreError(f"Téléchargement iCloud interrompu : {detail[:500]}")

            print("✓ Archive déchiffrée, SHA-256 vérifié et contenu contrôlé.")
            install_platform(manifest)
            apply_staged_configuration(staging / "payload")
            print("✓ Configurations restaurées et services validés.")
            print("La capacité DHCP reste inactive par sécurité.")
            print("Activez-la avec : ohana capability activate dhcp")
            return 0
    except (
        ICloudAuthenticationError,
        OSError,
        RcloneInstallationError,
        RestoreError,
        RestoreManifestError,
        shutil.Error,
    ) as error:
        print(f"✗ Restauration impossible : {error}")
        return RESTORE_ERROR
