"""Migrations ciblees des configurations locales conservees par Installer."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

BACKUP_CONFIGURATION_PATH = Path("/etc/ohana-agent/plugins/backup.yaml")
BACKUP_CONFIGURATION_MODE = 0o640
# Configurations locales qui recoivent les nouvelles cles du modele livre, sans
# jamais modifier une cle deja presente. Reserve aux fichiers dont toutes les
# cles sont optionnelles cote Agent.
ADDITIVE_CONFIGURATIONS = frozenset({"plugins/zwave.yaml"})
_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:")
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


def _example_blocks(text: str) -> dict[str, str]:
    """Decouper un modele en blocs par cle de premier niveau, commentaires inclus."""

    blocks: dict[str, list[str]] = {}
    pending: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            pending = []
            continue
        if line.startswith("#"):
            pending.append(line)
            current = None
            continue
        match = _TOP_LEVEL_KEY.match(line)
        if match:
            current = [*pending, line]
            blocks[match.group(1)] = current
            pending = []
        elif current is not None and line[0] in " \t-":
            current.append(line)
    return {key: "\n".join(lines) for key, lines in blocks.items()}


def add_missing_configuration_keys(source: Path, destination: Path) -> tuple[str, ...]:
    """Ajouter au fichier local les cles du modele qui y manquent.

    Les cles deja presentes, leurs valeurs et les commentaires locaux ne sont
    jamais modifies : seules les cles absentes sont ajoutees en fin de fichier,
    avec les commentaires du modele. Retourne les cles ajoutees.
    """

    try:
        example_text = source.read_text(encoding="utf-8")
        local_text = destination.read_text(encoding="utf-8")
        example = yaml.safe_load(example_text) or {}
        local = yaml.safe_load(local_text) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigurationMigrationError(
            f"Configuration illisible, cles manquantes non ajoutees : {destination}."
        ) from error
    if not isinstance(example, dict) or not isinstance(local, dict):
        raise ConfigurationMigrationError(
            f"La racine de la configuration doit etre un objet : {destination}."
        )

    blocks = _example_blocks(example_text)
    missing = [key for key in example if key not in local and key in blocks]
    if not missing:
        return ()

    local_text = local_text.replace("\r\n", "\n")
    merged = local_text.rstrip("\n") + "\n" if local_text.strip() else ""
    merged += "".join(f"{blocks[key]}\n" for key in missing)
    try:
        reloaded = yaml.safe_load(merged)
    except yaml.YAMLError as error:
        raise ConfigurationMigrationError(
            f"Ajout des cles manquantes invalide pour {destination}."
        ) from error
    if not isinstance(reloaded, dict) or any(key not in reloaded for key in missing):
        raise ConfigurationMigrationError(f"Ajout des cles manquantes invalide pour {destination}.")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(merged)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        shutil.copymode(destination, temporary_path)
        os.replace(temporary_path, destination)
    except (OSError, shutil.Error) as error:
        raise ConfigurationMigrationError(
            f"Ajout des cles manquantes impossible pour {destination} : {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return tuple(missing)
