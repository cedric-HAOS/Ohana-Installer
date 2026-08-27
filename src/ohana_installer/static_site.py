"""Installation sûre des composants web statiques Ohana."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ohana_installer.manifest import ComponentManifest


class StaticSiteInstallationError(RuntimeError):
    """Erreur pendant l'installation d'un site statique."""


@dataclass(frozen=True)
class InstalledStaticComponent:
    """Composant web statique installé."""

    name: str
    version: str
    installation_path: Path


def inspect_static_component(component: ComponentManifest) -> InstalledStaticComponent | None:
    """Lire la version d'une PWA déjà installée."""

    if component.static is None:
        raise StaticSiteInstallationError(
            f"Le composant {component.name} ne déclare pas d'installation statique."
        )
    version_path = component.static.directory / "version.json"
    if not version_path.is_file():
        return None
    try:
        metadata = json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StaticSiteInstallationError(
            f"Le version.json installé de {component.name} est invalide."
        ) from error
    version = metadata.get("version")
    if not isinstance(version, str) or not version:
        raise StaticSiteInstallationError(f"La version installée de {component.name} est absente.")
    return InstalledStaticComponent(
        name=component.name,
        version=version,
        installation_path=component.static.directory,
    )


def install_static_component(
    component: ComponentManifest,
    archive_path: Path | str,
    *,
    replace: bool = False,
) -> InstalledStaticComponent:
    """Extraire, valider et installer une archive de site statique."""

    if component.static is None:
        raise StaticSiteInstallationError(
            f"Le composant {component.name} ne déclare pas d'installation statique."
        )

    source = Path(archive_path)
    destination = component.static.directory
    if not source.is_file():
        raise StaticSiteInstallationError(f"L'archive est introuvable : {source}.")
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise StaticSiteInstallationError(
            f"Le répertoire statique {destination} n'est pas un répertoire sûr."
        )
    if destination.exists() and not replace:
        raise StaticSiteInstallationError(f"Le répertoire statique {destination} existe déjà.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ohana-static-") as temporary:
        staging = Path(temporary) / "site"
        staging.mkdir()
        _extract_archive(source, staging)
        version_path = staging / "version.json"
        if not version_path.is_file():
            raise StaticSiteInstallationError("L'archive PWA ne contient pas version.json.")
        try:
            metadata = json.loads(version_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StaticSiteInstallationError("Le version.json de la PWA est invalide.") from error
        if metadata.get("name") != component.name or metadata.get("version") != component.version:
            raise StaticSiteInstallationError(
                f"Version PWA inattendue pour {component.name} : "
                f"{metadata.get('version', 'absente')}."
            )

        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(staging), str(destination))

    return InstalledStaticComponent(
        name=component.name,
        version=component.version,
        installation_path=destination,
    )


def _extract_archive(source: Path, destination: Path) -> None:
    """Extraire une archive sans accepter de chemin ou lien dangereux."""

    if source.name.endswith((".tar.gz", ".tgz")):
        try:
            with tarfile.open(source, "r:gz") as archive:
                members = archive.getmembers()
                _validate_members((member.name for member in members), destination)
                if any(member.issym() or member.islnk() for member in members):
                    raise StaticSiteInstallationError("L'archive PWA ne doit contenir aucun lien.")
                archive.extractall(destination, filter="data")
            return
        except (OSError, tarfile.TarError) as error:
            raise StaticSiteInstallationError(f"Archive PWA illisible : {source}.") from error

    if source.name.endswith(".zip"):
        try:
            with zipfile.ZipFile(source) as archive:
                members = archive.infolist()
                _validate_members((member.filename for member in members), destination)
                if any((member.external_attr >> 16) & 0o170000 == 0o120000 for member in members):
                    raise StaticSiteInstallationError("Archive ZIP PWA invalide.")
                archive.extractall(destination)
            return
        except (OSError, zipfile.BadZipFile) as error:
            raise StaticSiteInstallationError(f"Archive PWA illisible : {source}.") from error

    raise StaticSiteInstallationError(
        "Le package statique doit être une archive .tar.gz, .tgz ou .zip."
    )


def _validate_members(names: Iterable[str], destination: Path) -> None:
    """Refuser les chemins absolus, traversals et extractions hors staging."""

    destination_root = destination.resolve()
    for raw_name in names:
        relative = PurePosixPath(str(raw_name))
        target = (destination / Path(*relative.parts)).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not target.is_relative_to(destination_root)
        ):
            raise StaticSiteInstallationError(f"Chemin dangereux dans l'archive PWA : {raw_name}.")
