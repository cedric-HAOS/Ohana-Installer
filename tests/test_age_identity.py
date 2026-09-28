"""Tests de la gestion automatique de l'identite age d'INFRA-01."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ohana_installer import age_identity


def _result(command, *, stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(command, code, stdout, stderr)


def _redirect_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    keys = root / "keys"
    age_binary = root / "bin" / "age"
    age_keygen = root / "bin" / "age-keygen"
    age_binary.parent.mkdir(parents=True)
    age_binary.touch()
    age_keygen.touch()
    monkeypatch.setattr(age_identity, "AGE_BINARY", age_binary)
    monkeypatch.setattr(age_identity, "AGE_KEYGEN_BINARY", age_keygen)
    monkeypatch.setattr(age_identity, "IDENTITY_DIRECTORY", keys)
    monkeypatch.setattr(age_identity, "IDENTITY_PATH", keys / "infra-01.agekey")
    monkeypatch.setattr(age_identity, "RECIPIENT_PATH", keys / "infra-01.agepub")
    monkeypatch.setattr(age_identity.shutil, "chown", lambda *_args, **_kwargs: None)


def test_ensure_local_identity_creates_public_files_and_uploads_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    rclone_config = tmp_path / "rclone.conf"
    rclone_config.write_text("[icloud]\n", encoding="utf-8")
    monkeypatch.setattr(age_identity, "RCLONE_CONFIG_PATH", rclone_config)
    commands: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        normalized = tuple(command)
        commands.append(normalized)
        if "-o" in normalized:
            Path(normalized[-1]).write_text("AGE-SECRET-KEY-1TEST\n", encoding="utf-8")
            return _result(command)
        if "-y" in normalized:
            return _result(command, stdout="age1managedrecipient\n")
        if "size" in normalized:
            return _result(
                command,
                stdout=json.dumps({"bytes": age_identity.IDENTITY_PATH.stat().st_size}),
            )
        return _result(command)

    recipient = age_identity.ensure_local_identity(command_runner=runner)

    assert recipient == "age1managedrecipient"
    assert age_identity.IDENTITY_PATH.read_text(encoding="utf-8") == ("AGE-SECRET-KEY-1TEST\n")
    assert age_identity.RECIPIENT_PATH.read_text(encoding="utf-8") == ("age1managedrecipient\n")
    assert any("copyto" in command for command in commands)
    assert any(age_identity.RECOVERY_REMOTE_PATH in command for command in commands)


def _expired_icloud_runner(command, **_kwargs):
    normalized = tuple(command)
    if "-o" in normalized:
        Path(normalized[-1]).write_text("AGE-SECRET-KEY-1TEST\n", encoding="utf-8")
        return _result(command)
    if "-y" in normalized:
        return _result(command, stdout="age1managedrecipient\n")
    if "copyto" in normalized:
        # INFRA-01, 28 September: the iCloud session had expired.
        return _result(
            command,
            code=1,
            stderr='HTTP error 421 (421 Misdirected Request) "Invalid global session"',
        )
    return _result(command)


@pytest.mark.parametrize("existed", [True, False])
def test_refresh_local_identity_tolerates_icloud_only_for_an_existing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existed: bool,
) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    rclone_config = tmp_path / "rclone.conf"
    rclone_config.write_text("[icloud]\n", encoding="utf-8")
    monkeypatch.setattr(age_identity, "RCLONE_CONFIG_PATH", rclone_config)
    if existed:
        age_identity.IDENTITY_DIRECTORY.mkdir(parents=True)
        age_identity.IDENTITY_PATH.write_text("AGE-SECRET-KEY-1TEST\n", encoding="utf-8")

    if not existed:
        # A key created now has no recovery copy anywhere: stay blocking.
        with pytest.raises(age_identity.AgeIdentityError, match="Invalid global session"):
            age_identity.refresh_local_identity(command_runner=_expired_icloud_runner)
        return

    recipient, warning = age_identity.refresh_local_identity(command_runner=_expired_icloud_runner)
    assert recipient == "age1managedrecipient"
    assert warning is not None and "Invalid global session" in warning


def test_refresh_local_identity_reports_no_warning_after_a_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(age_identity, "RCLONE_CONFIG_PATH", tmp_path / "absent.conf")

    def runner(command, **_kwargs):
        normalized = tuple(command)
        if "-o" in normalized:
            Path(normalized[-1]).write_text("AGE-SECRET-KEY-1TEST\n", encoding="utf-8")
        if "-y" in normalized:
            return _result(command, stdout="age1managedrecipient\n")
        return _result(command)

    assert age_identity.refresh_local_identity(command_runner=runner) == (
        "age1managedrecipient",
        None,
    )


def test_download_recovery_identity_validates_recipient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "recovered.agekey"
    config = tmp_path / "rclone.conf"

    def runner(command, **_kwargs):
        normalized = tuple(command)
        if "copyto" in normalized:
            destination.write_text("AGE-SECRET-KEY-1TEST\n", encoding="utf-8")
            return _result(command)
        return _result(command, stdout="age1recoveredrecipient\n")

    recovered = age_identity.download_recovery_identity(
        destination,
        rclone_config=config,
        command_runner=runner,
    )

    assert recovered == destination
    assert destination.is_file()


def test_download_recovery_identity_reports_missing_remote(tmp_path: Path) -> None:
    destination = tmp_path / "missing.agekey"

    with pytest.raises(age_identity.AgeIdentityError, match="introuvable dans iCloud"):
        age_identity.download_recovery_identity(
            destination,
            rclone_config=tmp_path / "rclone.conf",
            command_runner=lambda command, **_kwargs: _result(
                command,
                code=1,
                stderr="object not found",
            ),
        )
