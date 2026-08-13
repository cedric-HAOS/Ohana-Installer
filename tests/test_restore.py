"""Tests du contrat et des garde-fous de restauration INFRA-01."""

from __future__ import annotations

import json
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from ohana_installer.icloud import TemporaryICloudSession
from ohana_installer.restore import (
    RestoreError,
    _safe_member_path,
    _verify_and_remove_descriptor,
    apply_staged_configuration,
    install_platform,
    latest_local_backup,
    select_remote_manifest,
)
from ohana_installer.restore_manifest import (
    RestoreManifestError,
    parse_restore_manifest,
)


def _manifest() -> bytes:
    return json.dumps(
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


def test_parse_restore_manifest_accepts_supported_contract() -> None:
    manifest = parse_restore_manifest(_manifest())

    assert manifest.backup_id == "20260813T120000Z"
    assert manifest.profile == "infra-01"
    assert manifest.archive.encryption == "age"


def test_parse_restore_manifest_rejects_unencrypted_archive() -> None:
    payload = json.loads(_manifest())
    payload["archive"]["encryption"] = "none"

    with pytest.raises(RestoreManifestError, match="age"):
        parse_restore_manifest(json.dumps(payload))


@pytest.mark.parametrize(
    "name",
    (
        "../../etc/shadow",
        "/etc/ohana-agent/shikamaru.yaml",
        "etc/ssh/sshd_config",
        "etc/ohana-agent/token-link",
    ),
)
def test_restore_rejects_unsafe_archive_members(name: str) -> None:
    member = tarfile.TarInfo(name)
    member.type = tarfile.SYMTYPE if name.endswith("token-link") else tarfile.REGTYPE

    with pytest.raises(RestoreError):
        _safe_member_path(member)


def test_restore_accepts_only_managed_configuration_member() -> None:
    member = tarfile.TarInfo("etc/ohana-agent/plugins/backup.yaml")
    member.type = tarfile.REGTYPE

    assert str(_safe_member_path(member)) == "etc/ohana-agent/plugins/backup.yaml"


def test_encrypted_descriptor_must_match_public_manifest(tmp_path: Path) -> None:
    manifest = parse_restore_manifest(_manifest())
    descriptor = tmp_path / "ohana-backup/descriptor.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup_id": manifest.backup_id,
                "created_at": manifest.created_at,
                "profile": manifest.profile,
                "platform_version": manifest.platform_version,
                "agent_version": manifest.agent_version,
                "vision_version": manifest.vision_version,
            }
        ),
        encoding="utf-8",
    )

    _verify_and_remove_descriptor(tmp_path, manifest)

    assert not descriptor.exists()


def test_encrypted_descriptor_rejects_manifest_archive_mismatch(tmp_path: Path) -> None:
    manifest = parse_restore_manifest(_manifest())
    descriptor = tmp_path / "ohana-backup/descriptor.json"
    descriptor.parent.mkdir(parents=True)
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup_id": "20260812T120000Z",
                "created_at": manifest.created_at,
                "profile": manifest.profile,
                "platform_version": manifest.platform_version,
                "agent_version": manifest.agent_version,
                "vision_version": manifest.vision_version,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RestoreError, match="ne correspond pas"):
        _verify_and_remove_descriptor(tmp_path, manifest)


def test_latest_local_backup_selects_latest_valid_directory(tmp_path: Path) -> None:
    for backup_id in ("20260812T120000Z", "20260813T120000Z"):
        directory = tmp_path / backup_id
        directory.mkdir()
        manifest = json.loads(_manifest())
        manifest["backup_id"] = backup_id
        manifest["archive"]["filename"] = f"{backup_id}.tar.age"
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / f"{backup_id}.tar.age").write_bytes(b"archive")

    assert latest_local_backup(tmp_path).name == "20260813T120000Z"


def test_remote_selection_skips_newer_incomplete_backup() -> None:
    older_id = "20260812T120000Z"
    newer_id = "20260813T120000Z"
    payload = json.loads(_manifest())
    payload["backup_id"] = older_id
    payload["archive"]["filename"] = f"{older_id}.tar.age"

    def reader(backup_id: str) -> bytes:
        if backup_id == newer_id:
            raise RestoreError("manifest absent")
        return json.dumps(payload).encode()

    manifest, _content = select_remote_manifest(
        (older_id, newer_id),
        manifest_reader=reader,
    )

    assert manifest.backup_id == older_id


def test_temporary_icloud_session_completes_two_factor(tmp_path: Path) -> None:
    config = tmp_path / "rclone.conf"
    responses = iter(
        (
            {"State": "challenge", "Option": {"Name": "config_2fa"}},
            {"State": ""},
        )
    )

    def runner(command, **_kwargs):
        config.write_text("[icloud]\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(next(responses)),
            "",
        )

    session = TemporaryICloudSession(
        binary=Path("/usr/bin/rclone"),
        config_path=config,
        runner=runner,
    )
    continuation = session.begin("cedric@example.test", "secret")

    assert continuation is not None
    session.complete(continuation, "123456")
    assert config.is_file()


def test_install_platform_uses_saved_component_pair_for_fresh_machine(
    tmp_path: Path,
) -> None:
    manifest = parse_restore_manifest(_manifest())
    manifest = replace(manifest, platform_version=None)
    commands: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0)

    install_platform(
        manifest,
        command=("ohana",),
        command_runner=runner,
        agent_environment=tmp_path / "agent",
        vision_environment=tmp_path / "vision",
    )

    assert commands == [
        (
            "ohana",
            "install",
            "--yes",
            "--agent-version",
            "1.12.7",
            "--vision-version",
            "1.11.8",
        )
    ]


def test_configuration_restore_rolls_back_on_validation_failure(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    source = payload / "etc/ohana-agent/shikamaru.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("new\n", encoding="utf-8")
    destination_root = tmp_path / "machine"
    destination = destination_root / "etc/ohana-agent/shikamaru.yaml"
    destination.parent.mkdir(parents=True)
    destination.write_text("old\n", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        normalized = tuple(command)
        commands.append(normalized)
        if normalized[1:3] == ("is-active", "ohana-agent.service"):
            return subprocess.CompletedProcess(normalized, 0, "active\n", "")
        if normalized[:2] == ("/usr/sbin/dnsmasq", "--test"):
            return subprocess.CompletedProcess(normalized, 1, "", "invalid")
        return subprocess.CompletedProcess(normalized, 0, "", "")

    with pytest.raises(RestoreError, match="dnsmasq"):
        apply_staged_configuration(
            payload,
            command_runner=runner,
            destination_root=destination_root,
            owner_restorer=lambda _path: None,
        )

    assert destination.read_text(encoding="utf-8") == "old\n"
    assert (
        "/usr/bin/systemctl",
        "start",
        "ohana-agent.service",
    ) in commands
