"""Tests de la commande de catalogue public."""

from __future__ import annotations

import pytest

from ohana_installer.cli import main
from ohana_installer.github import DownloadError
from ohana_installer.manifest import PlatformReleaseCatalog, PlatformReleaseEntry


def _catalog() -> PlatformReleaseCatalog:
    return PlatformReleaseCatalog(
        schema_version=1,
        platform_name="Ohana",
        platform_version="1.0.22",
        default_platform_version="1.0.22",
        releases=(
            PlatformReleaseEntry(
                platform_version="1.0.22",
                release_tag="v1.0.22",
                agent_version="1.11.0",
                vision_version="1.10.0",
                status="recommended",
            ),
            PlatformReleaseEntry(
                platform_version="1.0.20",
                release_tag="v1.0.20",
                agent_version="1.10.0",
                vision_version="1.9.0",
                status="supported",
            ),
        ),
    )


def test_versions_displays_catalog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "ohana_installer.commands.versions.download_release_catalog",
        lambda directory: _catalog(),
    )

    assert main(["versions"]) == 0

    output = capsys.readouterr().out
    assert "Catalogue Ohana-Platform 1.0.22" in output
    assert "1.11.0" in output
    assert "1.10.0" in output
    assert "composition utilisée par défaut" in output
    assert "--agent-version" in output


def test_versions_reports_download_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_directory):
        raise DownloadError("catalogue absent")

    monkeypatch.setattr(
        "ohana_installer.commands.versions.download_release_catalog",
        fail,
    )

    assert main(["versions"]) == 3
    assert "catalogue absent" in capsys.readouterr().out
