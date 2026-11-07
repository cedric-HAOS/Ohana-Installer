"""Tests des migrations ciblees de configuration locale."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ohana_installer.configuration_migrations import (
    MANAGED_INFRA_01_VALUES,
    ConfigurationMigrationError,
    add_missing_configuration_keys,
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


EXAMPLE = """enabled: true
timeout: 3.0
# Minutes sans contact avant alerte.
last_seen_alert_minutes: 60
# Delai plus long pour les noeuds sur batterie.
sleeping_last_seen_alert_minutes: 1440
"""


def test_missing_keys_are_appended_with_their_comments(tmp_path: Path) -> None:
    source = tmp_path / "example.yaml"
    source.write_text(EXAMPLE, encoding="utf-8")
    destination = tmp_path / "zwave.yaml"
    destination.write_text("# reglages locaux\nenabled: false\ntimeout: 9.5", encoding="utf-8")

    added = add_missing_configuration_keys(source, destination)

    assert added == ("last_seen_alert_minutes", "sleeping_last_seen_alert_minutes")
    content = destination.read_text(encoding="utf-8")
    assert content.startswith("# reglages locaux\nenabled: false\ntimeout: 9.5\n")
    assert "# Minutes sans contact avant alerte.\nlast_seen_alert_minutes: 60\n" in content
    assert yaml.safe_load(content) == {
        "enabled": False,
        "timeout": 9.5,
        "last_seen_alert_minutes": 60,
        "sleeping_last_seen_alert_minutes": 1440,
    }


def test_existing_keys_are_never_modified_and_rerun_is_a_noop(tmp_path: Path) -> None:
    source = tmp_path / "example.yaml"
    source.write_text(EXAMPLE, encoding="utf-8")
    destination = tmp_path / "zwave.yaml"
    destination.write_text("enabled: true\nlast_seen_alert_minutes: 15\n", encoding="utf-8")

    first = add_missing_configuration_keys(source, destination)
    after_first = destination.read_text(encoding="utf-8")
    second = add_missing_configuration_keys(source, destination)

    assert first == ("timeout", "sleeping_last_seen_alert_minutes")
    assert yaml.safe_load(after_first)["last_seen_alert_minutes"] == 15
    assert second == ()
    assert destination.read_text(encoding="utf-8") == after_first


def test_missing_keys_rejects_unreadable_local_file(tmp_path: Path) -> None:
    source = tmp_path / "example.yaml"
    source.write_text(EXAMPLE, encoding="utf-8")
    destination = tmp_path / "zwave.yaml"
    destination.write_text("enabled: [unclosed\n", encoding="utf-8")

    with pytest.raises(ConfigurationMigrationError):
        add_missing_configuration_keys(source, destination)

    assert destination.read_text(encoding="utf-8") == "enabled: [unclosed\n"
