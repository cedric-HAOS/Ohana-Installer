"""A restoration leaves a small report the Agent can read."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ohana_installer.commands import restore as command
from ohana_installer.restore import RestoreError
from ohana_installer.restore_manifest import parse_restore_manifest
from ohana_installer.restore_report import (
    RestoreProgress,
    outcome_for_failure,
    write_report,
)

MANIFEST = json.dumps(
    {
        "schema_version": 1,
        "backup_id": "20260813T120000Z",
        "created_at": "2026-08-13T12:00:00Z",
        "profile": "infra-01",
        "platform_version": "1.0.50",
        "agent_version": "1.12.7",
        "vision_version": "1.11.8",
        "archive": {
            "filename": "20260813T120000Z.tar.age",
            "size_bytes": 42,
            "sha256": "a" * 64,
            "encryption": "age",
        },
    }
).encode()


def _reports(directory: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def test_report_records_outcome_stage_and_backup(tmp_path: Path) -> None:
    progress = RestoreProgress(mode="icloud", stage="done", backup_id="20260813T120000Z")

    path = write_report(
        progress,
        "ok",
        "Restauration terminée.",
        directory=tmp_path / "reports",
        now=datetime(2026, 10, 25, 11, 0, tzinfo=UTC),
    )

    assert path is not None and path.parent == tmp_path / "reports"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["target"] == "infra-01"
    assert (report["outcome"], report["mode"], report["stage"]) == ("ok", "icloud", "done")
    assert report["backup_id"] == "20260813T120000Z"
    assert report["finished_at"].startswith("2026-10-25T")
    assert report["report_id"] and report["installer_version"]
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o644


def test_report_never_carries_a_secret_and_stays_short(tmp_path: Path) -> None:
    progress = RestoreProgress(mode="icloud", stage="download")

    path = write_report(
        progress,
        "failed",
        "rclone: session_id=abc123 password: hunter2 " + "x" * 1000,
        directory=tmp_path,
    )

    detail = json.loads(path.read_text(encoding="utf-8"))["detail"]
    assert "abc123" not in detail and "hunter2" not in detail
    assert len(detail) <= 300


def test_an_unwritable_directory_never_breaks_the_restoration(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")

    assert write_report(RestoreProgress(mode="local"), "ok", directory=blocker / "r") is None


def test_unknown_outcomes_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inconnu"):
        write_report(RestoreProgress(mode="local"), "fine", directory=tmp_path)


@pytest.mark.parametrize(
    "stage, outcome",
    [
        ("selection", "failed"),
        ("download", "failed"),
        ("install", "partial"),
        ("configuration", "partial"),
        ("identity", "partial"),
    ],
)
def test_a_failure_after_the_machine_was_modified_is_partial(stage, outcome) -> None:
    assert outcome_for_failure(stage) == outcome


def _arguments(backup: Path) -> SimpleNamespace:
    return SimpleNamespace(
        local=backup,
        backup_id=None,
        identity=backup / "identity",
        yes=True,
        choose_backup=False,
        icloud=False,
    )


@pytest.fixture
def local_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "manifest.json").write_bytes(MANIFEST)
    (backup / "20260813T120000Z.tar.age").write_bytes(b"x")
    reports = tmp_path / "reports"
    monkeypatch.setattr(command, "RUNTIME_DIRECTORY", tmp_path / "run")
    monkeypatch.setattr(command, "require_tmpfs", lambda _path: None)
    monkeypatch.setattr(command, "latest_local_backup", lambda _path: backup)
    monkeypatch.setattr(command, "ensure_age_installed", lambda: None)
    monkeypatch.setattr(command, "confirm_action", lambda *_a, **_k: True)
    monkeypatch.setattr(command, "parse_restore_manifest", parse_restore_manifest)
    monkeypatch.setattr("ohana_installer.restore_report.REPORT_DIRECTORY", reports)
    return backup, reports, monkeypatch


def test_a_restoration_that_fails_while_decrypting_reports_a_failure(local_run, capsys) -> None:
    backup, reports, monkeypatch = local_run

    def broken(*_args, **_kwargs):
        raise RestoreError("age: no identity matched any of the recipients")

    monkeypatch.setattr(command, "decrypt_and_extract", broken)

    assert command.run(_arguments(backup)) == command.RESTORE_ERROR

    (report,) = _reports(reports)
    assert (report["outcome"], report["stage"]) == ("failed", "download")
    assert report["backup_id"] == "20260813T120000Z"
    assert "no identity matched" in report["detail"]
    assert "Restauration impossible" in capsys.readouterr().out


def test_a_restoration_that_fails_after_installing_is_partial(local_run) -> None:
    backup, reports, monkeypatch = local_run
    monkeypatch.setattr(command, "decrypt_and_extract", lambda *_a, **_k: None)
    monkeypatch.setattr(command, "install_platform", lambda _manifest: None)

    def broken(_payload):
        raise RestoreError("Le service ohana-agent ne démarre pas.")

    monkeypatch.setattr(command, "apply_staged_configuration", broken)

    assert command.run(_arguments(backup)) == command.RESTORE_ERROR

    (report,) = _reports(reports)
    assert (report["outcome"], report["stage"]) == ("partial", "configuration")


def test_a_complete_restoration_reports_success(local_run) -> None:
    backup, reports, monkeypatch = local_run
    monkeypatch.setattr(command, "decrypt_and_extract", lambda *_a, **_k: None)
    monkeypatch.setattr(command, "install_platform", lambda _manifest: None)
    monkeypatch.setattr(command, "apply_staged_configuration", lambda _payload: None)
    monkeypatch.setattr(command, "install_identity", lambda _path: None)

    assert command.run(_arguments(backup)) == 0

    (report,) = _reports(reports)
    assert (report["outcome"], report["stage"]) == ("ok", "done")


def test_a_cancelled_restoration_leaves_no_report(local_run) -> None:
    backup, reports, monkeypatch = local_run
    monkeypatch.setattr(command, "confirm_action", lambda *_a, **_k: False)

    assert command.run(_arguments(backup)) == 0
    assert not reports.exists() or _reports(reports) == []
