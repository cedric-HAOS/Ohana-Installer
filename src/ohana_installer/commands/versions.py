"""Commande d'affichage des couples Agent/Vision disponibles."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from ohana_installer.github import DownloadError
from ohana_installer.manifest import ManifestError, PlatformReleaseCatalog
from ohana_installer.release_selection import download_release_catalog

VERSIONS_ERROR = 3


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande versions."""

    parser = subparsers.add_parser(
        "versions",
        help="Lister les couples Agent/Vision déclarés par Ohana-Platform.",
        description="Lister les compositions officielles installables.",
    )
    parser.set_defaults(command_handler=run)


def _display_catalog(catalog: PlatformReleaseCatalog) -> None:
    print(f"Catalogue Ohana-Platform {catalog.platform_version}")
    print()
    print("Platform   Agent     Vision    Statut")
    print("---------- --------- --------- -----------")

    status_labels = {
        "recommended": "recommandé",
        "supported": "supporté",
        "legacy": "historique",
    }

    for release in catalog.releases:
        marker = " *" if release.platform_version == catalog.default_platform_version else ""
        print(
            f"{release.platform_version:<10} "
            f"{release.agent_version:<9} "
            f"{release.vision_version:<9} "
            f"{status_labels[release.status]}{marker}"
        )

    print()
    print("* composition utilisée par défaut")
    print()
    print("Installation par version Platform :")
    print("  ohana install --platform-version <version>")
    print("Installation par couple Agent/Vision :")
    print("  ohana install --agent-version <version> --vision-version <version>")


def run(args: argparse.Namespace) -> int:
    """Télécharger puis afficher le catalogue officiel."""

    del args

    try:
        with tempfile.TemporaryDirectory(prefix="ohana-installer-catalog-") as directory:
            catalog = download_release_catalog(Path(directory))
    except DownloadError as error:
        print(f"✗ Téléchargement impossible : {error}")
        return VERSIONS_ERROR
    except ManifestError as error:
        print(f"✗ Le catalogue officiel est invalide : {error}")
        return VERSIONS_ERROR

    _display_catalog(catalog)
    return 0
