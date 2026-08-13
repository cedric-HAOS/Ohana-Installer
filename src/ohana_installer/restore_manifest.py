"""Contrat versionné des sauvegardes logiques d'INFRA-01."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
BACKUP_ID_PATTERN = re.compile(r"[0-9]{8}T[0-9]{6}Z")


class RestoreManifestError(ValueError):
    """Manifeste de sauvegarde invalide ou non pris en charge."""


@dataclass(frozen=True)
class ArchiveManifest:
    """Archive chiffrée associée à une sauvegarde."""

    filename: str
    size_bytes: int
    sha256: str
    encryption: str


@dataclass(frozen=True)
class RestoreManifest:
    """Métadonnées nécessaires à une reconstruction reproductible."""

    schema_version: int
    backup_id: str
    created_at: str
    profile: str
    platform_version: str | None
    agent_version: str
    vision_version: str
    archive: ArchiveManifest


def parse_restore_manifest(content: bytes | str) -> RestoreManifest:
    """Charger et valider un manifeste JSON non secret."""

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreManifestError(
            "Le manifeste de sauvegarde n'est pas un JSON valide."
        ) from error
    if not isinstance(payload, dict):
        raise RestoreManifestError("Le manifeste de sauvegarde doit être un objet JSON.")

    schema_version = _integer(payload, "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise RestoreManifestError(
            f"Format de sauvegarde {schema_version} non pris en charge ; "
            f"version attendue : {SCHEMA_VERSION}."
        )
    backup_id = _text(payload, "backup_id")
    if BACKUP_ID_PATTERN.fullmatch(backup_id) is None:
        raise RestoreManifestError("backup_id doit respecter le format YYYYMMDDTHHMMSSZ.")
    profile = _text(payload, "profile")
    if profile != "infra-01":
        raise RestoreManifestError(f"Profil de sauvegarde non pris en charge : {profile}.")
    archive_payload = payload.get("archive")
    if not isinstance(archive_payload, dict):
        raise RestoreManifestError("archive doit être un objet JSON.")
    filename = _text(archive_payload, "filename")
    if filename != f"{backup_id}.tar.age":
        raise RestoreManifestError("Le nom de l'archive ne correspond pas au backup_id.")
    size_bytes = _integer(archive_payload, "size_bytes")
    if size_bytes <= 0:
        raise RestoreManifestError("archive.size_bytes doit être supérieur à zéro.")
    sha256 = _text(archive_payload, "sha256")
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise RestoreManifestError("archive.sha256 doit être un SHA-256 hexadécimal.")
    encryption = _text(archive_payload, "encryption")
    if encryption != "age":
        raise RestoreManifestError("Seules les archives chiffrées avec age sont acceptées.")

    return RestoreManifest(
        schema_version=schema_version,
        backup_id=backup_id,
        created_at=_text(payload, "created_at"),
        profile=profile,
        platform_version=_optional_version(payload, "platform_version"),
        agent_version=_version(payload, "agent_version"),
        vision_version=_version(payload, "vision_version"),
        archive=ArchiveManifest(
            filename=filename,
            size_bytes=size_bytes,
            sha256=sha256,
            encryption=encryption,
        ),
    )


def serialize_restore_manifest(manifest: RestoreManifest) -> bytes:
    """Produire la représentation JSON canonique du manifeste."""

    payload = {
        "schema_version": manifest.schema_version,
        "backup_id": manifest.backup_id,
        "created_at": manifest.created_at,
        "profile": manifest.profile,
        "platform_version": manifest.platform_version,
        "agent_version": manifest.agent_version,
        "vision_version": manifest.vision_version,
        "archive": {
            "filename": manifest.archive.filename,
            "size_bytes": manifest.archive.size_bytes,
            "sha256": manifest.archive.sha256,
            "encryption": manifest.archive.encryption,
        },
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RestoreManifestError(f"{key} doit être une chaîne non vide.")
    return value.strip()


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RestoreManifestError(f"{key} doit être un entier.")
    return value


def _version(payload: dict[str, Any], key: str) -> str:
    value = _text(payload, key)
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise RestoreManifestError(f"{key} doit être une version majeure.mineure.correctif.")
    return value


def _optional_version(payload: dict[str, Any], key: str) -> str | None:
    if payload.get(key) is None:
        return None
    return _version(payload, key)
