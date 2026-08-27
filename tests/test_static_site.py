import json
import tarfile
from pathlib import Path

import pytest

from ohana_installer.manifest import ComponentManifest, ComponentPackage, StaticInstallation
from ohana_installer.static_site import StaticSiteInstallationError, install_static_component


def _component(directory: Path) -> ComponentManifest:
    return ComponentManifest(
        identifier="shizune",
        name="Ohana-Shizune",
        repository="cedric-HAOS/Ohana-Shizune",
        version="0.1.0",
        release_tag="v0.1.0",
        package=ComponentPackage(type="static", filename="shizune-pwa-0.1.0.tar.gz"),
        static=StaticInstallation(directory=directory),
    )


def _archive(path: Path, *, member_name: str = "version.json") -> None:
    source = path.parent / "source"
    source.mkdir()
    (source / "version.json").write_text(
        json.dumps({"name": "Ohana-Shizune", "version": "0.1.0"}),
        encoding="utf-8",
    )
    (source / "index.html").write_text("<main>Shizune</main>", encoding="utf-8")
    with tarfile.open(path, "w:gz") as archive:
        archive.add(source / "version.json", arcname=member_name)
        archive.add(source / "index.html", arcname="index.html")


def test_install_static_component_validates_version_and_replaces(tmp_path: Path) -> None:
    archive = tmp_path / "shizune.tar.gz"
    destination = tmp_path / "www" / "shizune"
    _archive(archive)

    installed = install_static_component(_component(destination), archive)

    assert installed.version == "0.1.0"
    assert (destination / "index.html").read_text(encoding="utf-8") == "<main>Shizune</main>"


def test_install_static_component_rejects_archive_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _archive(archive, member_name="../version.json")

    with pytest.raises(StaticSiteInstallationError, match="dangereux"):
        install_static_component(_component(tmp_path / "www"), archive)
