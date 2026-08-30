"""Tests du catalogue des couples Agent/Vision."""

from __future__ import annotations

from pathlib import Path

import pytest

from ohana_installer.manifest import (
    ManifestError,
    load_manifest,
    load_release_catalog,
    parse_release_catalog,
    select_catalog_release,
    validate_manifest_catalog_entry,
)

VALID_CATALOG = {
    "schema_version": 1,
    "platform": {
        "name": "Ohana",
        "version": "1.0.22",
    },
    "default_platform_version": "1.0.22",
    "releases": [
        {
            "platform_version": "1.0.22",
            "release_tag": "v1.0.22",
            "agent_version": "1.11.0",
            "vision_version": "1.10.0",
            "status": "recommended",
        },
        {
            "platform_version": "1.0.21",
            "release_tag": "v1.0.21",
            "agent_version": "1.11.0",
            "vision_version": "1.10.0",
            "status": "supported",
        },
        {
            "platform_version": "1.0.20",
            "release_tag": "v1.0.20",
            "agent_version": "1.10.0",
            "vision_version": "1.9.0",
            "status": "legacy",
        },
    ],
}


def test_parse_release_catalog_returns_validated_catalog() -> None:
    catalog = parse_release_catalog(VALID_CATALOG)

    assert catalog.platform_name == "Ohana"
    assert catalog.platform_version == "1.0.22"
    assert catalog.default_platform_version == "1.0.22"
    assert len(catalog.releases) == 3


def test_load_release_catalog_reads_repository_catalog() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    catalog = load_release_catalog(repository_root / "config" / "release-catalog.yaml")

    assert catalog.platform_version == "1.0.92"
    assert catalog.default_platform_version == "1.0.92"
    assert catalog.releases[0].agent_version == "1.26.13"
    assert catalog.releases[0].vision_version == "1.22.10"
    assert catalog.releases[0].shizune_version == "0.2.2"
    assert catalog.releases[-1].platform_version == "1.0.13"


def test_repository_catalog_default_matches_repository_manifest() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    catalog = load_release_catalog(repository_root / "config" / "release-catalog.yaml")
    manifest = load_manifest(repository_root / "config" / "release-manifest.yaml")
    entry = select_catalog_release(catalog)

    validate_manifest_catalog_entry(manifest, entry)


def test_parse_release_catalog_rejects_unknown_default() -> None:
    raw = {
        **VALID_CATALOG,
        "default_platform_version": "9.9.9",
    }

    with pytest.raises(ManifestError, match="référencer une release"):
        parse_release_catalog(raw)


def test_parse_release_catalog_rejects_duplicate_platform_version() -> None:
    raw = {
        **VALID_CATALOG,
        "releases": [
            *VALID_CATALOG["releases"],
            dict(VALID_CATALOG["releases"][0]),
        ],
    }

    with pytest.raises(ManifestError, match="plusieurs entrées"):
        parse_release_catalog(raw)


def test_parse_release_catalog_rejects_release_tag_mismatch() -> None:
    release = {
        **VALID_CATALOG["releases"][0],
        "release_tag": "v2.0.0",
    }
    raw = {
        **VALID_CATALOG,
        "releases": [release],
        "default_platform_version": "1.0.22",
    }

    with pytest.raises(ManifestError, match="doit correspondre"):
        parse_release_catalog(raw)


def test_select_catalog_release_by_platform_version() -> None:
    catalog = parse_release_catalog(VALID_CATALOG)

    release = select_catalog_release(catalog, platform_version="1.0.20")

    assert release.agent_version == "1.10.0"
    assert release.vision_version == "1.9.0"
    assert release.status == "legacy"


def test_select_catalog_release_by_pair_prefers_default_when_duplicated() -> None:
    catalog = parse_release_catalog(VALID_CATALOG)

    release = select_catalog_release(
        catalog,
        agent_version="1.11.0",
        vision_version="1.10.0",
    )

    assert release.platform_version == "1.0.22"


def test_select_catalog_release_rejects_unknown_pair() -> None:
    catalog = parse_release_catalog(VALID_CATALOG)

    with pytest.raises(ManifestError, match="n'est pas déclaré"):
        select_catalog_release(
            catalog,
            agent_version="9.0.0",
            vision_version="9.0.0",
        )
