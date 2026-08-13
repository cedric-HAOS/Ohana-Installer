"""Migrations ciblees des configurations locales conservees par Installer."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import yaml

BACKUP_CONFIGURATION_PATH = Path("/etc/ohana-agent/plugins/backup.yaml")
BACKUP_CONFIGURATION_MODE = 0o640
MANAGED_INFRA_01_VALUES = {
    "age_recipient_file": "/etc/ohana-agent/keys/infra-01.agepub",
    "age_identity_file": "/etc/ohana-agent/keys/infra-01.agekey",
    "recovery_remote_path": "icloud:Ohana/Recovery/infra-01.agekey",
}


class ConfigurationMigrationError(RuntimeError):
    """Echec d'une migration de configuration locale."""


def migrate_backup_configuration(
    path: Path = BACKUP_CONFIGURATION_PATH,
    *,
    owner: str = "root",
    group: str = "ohana-agent",
) -> bool:
    """Migrer atomiquement le contrat age 1.9.0 sans ecraser les reglages locaux."""

    if not path.is_file():
        return False
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigurationMigrationError(
            f"Configuration de sauvegarde illisible : {path}."
        ) from error
    if not isinstance(content, dict):
        raise ConfigurationMigrationError(
            f"La racine de la configuration de sauvegarde doit etre un objet : {path}."
        )
    infra = content.setdefault("infra_01", {})
    if not isinstance(infra, dict):
        raise ConfigurationMigrationError(
            "La section infra_01 de la configuration de sauvegarde doit etre un objet."
        )

    changed = False
    if "age_recipient" in infra:
        del infra["age_recipient"]
        changed = True
    for key, value in MANAGED_INFRA_01_VALUES.items():
        if infra.get(key) != value:
            infra[key] = value
            changed = True
    if not changed:
        return False

    serialized = yaml.safe_dump(
        content,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, BACKUP_CONFIGURATION_MODE)
        shutil.chown(temporary_path, user=owner, group=group)
        os.replace(temporary_path, path)
    except (OSError, shutil.Error) as error:
        raise ConfigurationMigrationError(
            f"Migration de la configuration de sauvegarde impossible : {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return True
