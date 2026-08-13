"""Tests des migrations ciblees de configuration locale."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ohana_installer.configuration_migrations import (
    MANAGED_INFRA_01_VALUES,
    ConfigurationMigrationError,
    migrate_backup_configuration,
)


def test_backup_migration_preserves_local_settings_and_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "backup.yaml"
    path.write_text(
        """enabled: true
rclone_remote: icloud:Ohana/Backups
infra_01:
  enabled: true
  schedule: 0 1 * * *
  age_recipient: age1legacy
  remote_retention_count: 9
targets:
- id: ha-01
  token: secret-token
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ohana_installer.configuration_migrations.shutil.chown",
        lambda *_args, **_kwargs: None,
    )

    assert migrate_backup_configuration(path) is True

    migrated = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert migrated["enabled"] is True
    assert migrated["targets"] == [{"id": "ha-01", "token": "secret-token"}]
    assert migrated["infra_01"]["enabled"] is True
    assert migrated["infra_01"]["schedule"] == "0 1 * * *"
    assert migrated["infra_01"]["remote_retention_count"] == 9
    assert "age_recipient" not in migrated["infra_01"]
    for key, value in MANAGED_INFRA_01_VALUES.items():
        assert migrated["infra_01"][key] == value


def test_backup_migration_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "backup.yaml"
    path.write_text(
        yaml.safe_dump({"infra_01": dict(MANAGED_INFRA_01_VALUES)}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ohana_installer.configuration_migrations.shutil.chown",
        lambda *_args, **_kwargs: None,
    )

    assert migrate_backup_configuration(path) is False


def test_backup_migration_rejects_invalid_infra_section(tmp_path: Path) -> None:
    path = tmp_path / "backup.yaml"
    path.write_text("infra_01: invalid\n", encoding="utf-8")

    with pytest.raises(ConfigurationMigrationError, match="infra_01"):
        migrate_backup_configuration(path)
