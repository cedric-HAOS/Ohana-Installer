"""Commande de restauration complète d'INFRA-01."""

from __future__ import annotations

import argparse
import getpass
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ohana_installer.age_identity import (
    IDENTITY_PATH,
    AgeIdentityError,
    download_recovery_identity,
    ensure_age_installed,
    install_identity,
)
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
    list_remote_manifests,
    rclone_read_bytes,
    require_tmpfs,
    select_remote_manifest,
)
from ohana_installer.restore_manifest import (
    RestoreManifest,
    RestoreManifestError,
    parse_restore_manifest,
)

RESTORE_ERROR = 3
DEFAULT_REMOTE = "icloud:Ohana/Backups/infra-01"
RUNTIME_DIRECTORY = Path("/run/ohana-installer/restore")
RCLONE_BINARY = Path("/usr/bin/rclone")


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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--backup-id",
        help="Sauvegarde précise ; dernière valide par défaut.",
    )
    selection.add_argument(
        "--choose-backup",
        action="store_true",
        help="Afficher les sauvegardes iCloud valides et en choisir une.",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        help="Identité age locale ; récupérée automatiquement depuis iCloud si absente.",
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


def _display_backup_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%d/%m/%Y %H:%M UTC")


def _choose_remote_manifest(
    backup_ids: tuple[str, ...],
    *,
    manifest_reader: Callable[[str], bytes],
    input_function: Callable[[str], str] = input,
) -> tuple[RestoreManifest, bytes] | None:
    available = list_remote_manifests(
        backup_ids,
        manifest_reader=manifest_reader,
    )
    print("Sauvegardes INFRA-01 valides disponibles dans iCloud :")
    for index, (manifest, _content) in enumerate(available, start=1):
        platform = manifest.platform_version or "composition historique"
        print(
            f"  {index}. {_display_backup_date(manifest.created_at)} — "
            f"Platform {platform} — Agent {manifest.agent_version} / "
            f"Vision {manifest.vision_version} — {manifest.backup_id}"
        )
    print("  0. Annuler")
    while True:
        choice = input_function("Votre choix : ").strip()
        if choice in {"0", "q", "Q"}:
            return None
        try:
            selected = int(choice)
        except ValueError:
            print("Choix invalide.")
            continue
        if 1 <= selected <= len(available):
            return available[selected - 1]
        print("Choix invalide.")


def _select_icloud_manifest(
    backup_ids: tuple[str, ...],
    *,
    choose_backup: bool,
    requested_id: str | None,
    manifest_reader: Callable[[str], bytes],
    input_function: Callable[[str], str] = input,
) -> tuple[RestoreManifest, bytes] | None:
    if not backup_ids:
        raise RestoreError("Aucune sauvegarde INFRA-01 n'est disponible dans iCloud.")
    if choose_backup:
        return _choose_remote_manifest(
            backup_ids,
            manifest_reader=manifest_reader,
            input_function=input_function,
        )
    return select_remote_manifest(
        backup_ids,
        requested_id=requested_id,
        manifest_reader=manifest_reader,
    )


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
                def manifest_reader(backup_id: str) -> bytes:
                    return rclone_read_bytes(
                        f"{args.remote.rstrip('/')}/{backup_id}/manifest.json",
                        rclone_binary=RCLONE_BINARY,
                        rclone_config=rclone_config,
                    )

                selected = _select_icloud_manifest(
                    backup_ids,
                    choose_backup=bool(args.choose_backup),
                    requested_id=args.backup_id,
                    manifest_reader=manifest_reader,
                )
                if selected is None:
                    print("Restauration annulée.")
                    return 0
                manifest, manifest_bytes = selected
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

            ensure_age_installed()
            identity_path = args.identity
            recovered_identity = False
            if identity_path is None and IDENTITY_PATH.is_file():
                identity_path = IDENTITY_PATH
            if identity_path is None and args.local is None:
                assert rclone_config is not None
                identity_path = download_recovery_identity(
                    runtime / "infra-01.agekey",
                    rclone_config=rclone_config,
                )
                recovered_identity = True
                print("✓ Identité age récupérée depuis iCloud.")
            if identity_path is None:
                raise RestoreError(
                    "Une restauration locale nécessite --identity ; "
                    "la récupération automatique est disponible avec --icloud."
                )
            staging = runtime / "staging"
            if args.local is not None:
                archive_path = backup_directory / manifest.archive.filename
                with archive_path.open("rb") as stream:
                    decrypt_and_extract(
                        stream,
                        manifest=manifest,
                        identity_path=identity_path,
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
                    identity_path=identity_path,
                    staging_directory=staging,
                )
                _stdout, stderr = process.communicate()
                if process.returncode != 0:
                    detail = (stderr or b"erreur inconnue").decode(errors="replace")
                    raise RestoreError(f"Téléchargement iCloud interrompu : {detail[:500]}")

            print("✓ Archive déchiffrée, SHA-256 vérifié et contenu contrôlé.")
            install_platform(manifest)
            apply_staged_configuration(staging / "payload")
            install_identity(identity_path)
            if recovered_identity:
                print("✓ Identité age installée sur la nouvelle machine.")
            else:
                print("✓ Identité age locale installée et validée.")
            print("✓ Configurations restaurées et services validés.")
            print("La capacité DHCP reste inactive par sécurité.")
            print("Activez-la avec : ohana capability activate dhcp")
            return 0
    except (
        ICloudAuthenticationError,
        AgeIdentityError,
        OSError,
        RcloneInstallationError,
        RestoreError,
        RestoreManifestError,
        shutil.Error,
    ) as error:
        print(f"✗ Restauration impossible : {error}")
        return RESTORE_ERROR
