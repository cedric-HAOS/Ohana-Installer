"""Sélection d'une composition Agent/Vision déclarée par Ohana-Platform."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ohana_installer.github import (
    download_platform_catalog,
    download_platform_manifest,
)
from ohana_installer.manifest import (
    ManifestError,
    PlatformManifest,
    PlatformReleaseCatalog,
    PlatformReleaseEntry,
    select_catalog_release,
    validate_manifest_catalog_entry,
)

CATALOG_FILENAME = "release-catalog.yaml"
MANIFEST_FILENAME_PREFIX = "release-manifest"


@dataclass(frozen=True)
class ReleaseSelection:
    """Sélection explicite d'une composition officielle."""

    platform_version: str | None = None
    agent_version: str | None = None
    vision_version: str | None = None

    @property
    def explicit(self) -> bool:
        return any(
            value is not None
            for value in (
                self.platform_version,
                self.agent_version,
                self.vision_version,
            )
        )


def add_release_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """Ajouter les sélecteurs de composition à une commande."""

    parser.add_argument(
        "--platform-version",
        help=(
            "Version Ohana-Platform à installer, par exemple 1.0.20. "
            "Elle sélectionne le couple Agent/Vision déclaré par cette release."
        ),
    )
    parser.add_argument(
        "--agent-version",
        help="Version Ohana-Agent du couple officiel à installer.",
    )
    parser.add_argument(
        "--vision-version",
        help="Version Ohana-Vision du couple officiel à installer.",
    )


def selection_from_args(args: argparse.Namespace) -> ReleaseSelection | None:
    """Valider et extraire la sélection demandée sur la ligne de commande."""

    platform_version = _normalized_optional(args.platform_version)
    agent_version = _normalized_optional(args.agent_version)
    vision_version = _normalized_optional(args.vision_version)

    if platform_version is not None and (agent_version is not None or vision_version is not None):
        raise ManifestError(
            "--platform-version ne peut pas être combiné avec --agent-version ou --vision-version."
        )

    if (agent_version is None) != (vision_version is None):
        raise ManifestError("--agent-version et --vision-version doivent être fournis ensemble.")

    selection = ReleaseSelection(
        platform_version=platform_version,
        agent_version=agent_version,
        vision_version=vision_version,
    )
    return selection if selection.explicit else None


def release_selection_arguments(selection: ReleaseSelection | None) -> tuple[str, ...]:
    """Reconstruire les arguments CLI d'une sélection pour une reprise de commande."""

    if selection is None:
        return ()

    if selection.platform_version is not None:
        return ("--platform-version", selection.platform_version)

    if selection.agent_version is None or selection.vision_version is None:
        raise ManifestError("Sélection Agent/Vision incomplète.")

    return (
        "--agent-version",
        selection.agent_version,
        "--vision-version",
        selection.vision_version,
    )


def download_release_catalog(directory: Path) -> PlatformReleaseCatalog:
    """Télécharger le catalogue officiel dans un répertoire temporaire."""

    return download_platform_catalog(directory / CATALOG_FILENAME)


def download_selected_manifest(
    directory: Path,
    selection: ReleaseSelection,
) -> tuple[PlatformManifest, PlatformReleaseEntry]:
    """Résoudre puis télécharger la composition sélectionnée."""

    catalog = download_release_catalog(directory)
    entry = select_catalog_release(
        catalog,
        platform_version=selection.platform_version,
        agent_version=selection.agent_version,
        vision_version=selection.vision_version,
    )
    manifest_path = directory / (f"{MANIFEST_FILENAME_PREFIX}-{entry.platform_version}.yaml")
    manifest = download_platform_manifest(
        manifest_path,
        release_tag=entry.release_tag,
    )
    validate_manifest_catalog_entry(manifest, entry)
    return manifest, entry


def _normalized_optional(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError("Une version sélectionnée doit être une chaîne de caractères.")
    normalized = value.strip()
    return normalized or None
