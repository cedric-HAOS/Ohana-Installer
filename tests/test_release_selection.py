"""Tests de sélection des compositions sur la ligne de commande."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ohana_installer.manifest import (
    CompatibilityManifest,
    ComponentManifest,
    ComponentPackage,
    ManifestError,
    PlatformManifest,
    PlatformReleaseCatalog,
    PlatformReleaseEntry,
    RuntimeManifest,
)
from ohana_installer.release_selection import (
    ReleaseSelection,
    download_selected_manifest,
    release_selection_arguments,
    selection_from_args,
)


def _args(**values: object) -> argparse.Namespace:
    defaults = {
        "platform_version": None,
        "agent_version": None,
        "vision_version": None,
    }
    defaults.update(values)
    return argparse.Namespace(**defaults)


def _manifest() -> PlatformManifest:
    return PlatformManifest(
        schema_version=1,
        platform_name="Ohana",
        platform_version="1.0.20",
        runtime=RuntimeManifest(minimum_python_version="3.13"),
        components=(
            ComponentManifest(
                identifier="agent",
                name="Ohana-Agent",
                repository="cedric-HAOS/Ohana-Agent",
                version="1.10.0",
                release_tag="v1.10.0",
                package=ComponentPackage(
                    type="wheel",
                    filename="ohana_agent-1.10.0-py3-none-any.whl",
                ),
            ),
            ComponentManifest(
                identifier="vision",
                name="Ohana-Vision",
                repository="cedric-HAOS/Ohana-Vision",
                version="1.9.0",
                release_tag="v1.9.0",
                package=ComponentPackage(
                    type="wheel",
                    filename="ohana_vision-1.9.0-py3-none-any.whl",
                ),
            ),
        ),
        compatibility=CompatibilityManifest(
            operating_system_family="Linux",
            service_manager="systemd",
        ),
    )


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


def test_selection_from_args_accepts_platform_version() -> None:
    assert selection_from_args(_args(platform_version="1.0.20")) == ReleaseSelection(
        platform_version="1.0.20"
    )


def test_selection_from_args_accepts_agent_vision_pair() -> None:
    assert selection_from_args(
        _args(agent_version="1.10.0", vision_version="1.9.0")
    ) == ReleaseSelection(agent_version="1.10.0", vision_version="1.9.0")


def test_selection_from_args_rejects_partial_pair() -> None:
    with pytest.raises(ManifestError, match="doivent être fournis ensemble"):
        selection_from_args(_args(agent_version="1.10.0"))


def test_selection_from_args_rejects_mixed_selectors() -> None:
    with pytest.raises(ManifestError, match="ne peut pas être combiné"):
        selection_from_args(
            _args(
                platform_version="1.0.20",
                agent_version="1.10.0",
                vision_version="1.9.0",
            )
        )


def test_release_selection_arguments_preserves_pair() -> None:
    assert release_selection_arguments(
        ReleaseSelection(agent_version="1.10.0", vision_version="1.9.0")
    ) == (
        "--agent-version",
        "1.10.0",
        "--vision-version",
        "1.9.0",
    )


def test_download_selected_manifest_uses_catalog_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    received_release_tag: str | None = None

    monkeypatch.setattr(
        "ohana_installer.release_selection.download_release_catalog",
        lambda directory: _catalog(),
    )

    def download_manifest(destination: Path, *, release_tag: str) -> PlatformManifest:
        nonlocal received_release_tag
        received_release_tag = release_tag
        assert destination.name == "release-manifest-1.0.20.yaml"
        return manifest

    monkeypatch.setattr(
        "ohana_installer.release_selection.download_platform_manifest",
        download_manifest,
    )

    result, entry = download_selected_manifest(
        tmp_path,
        ReleaseSelection(platform_version="1.0.20"),
    )

    assert result == manifest
    assert entry.platform_version == "1.0.20"
    assert received_release_tag == "v1.0.20"
