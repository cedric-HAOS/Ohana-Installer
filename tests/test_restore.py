"""Tests du contrat et des garde-fous de restauration INFRA-01."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ohana_installer.commands.restore import (
    _choose_remote_manifest,
    _icloud_config,
    _select_icloud_manifest,
)
from ohana_installer.icloud import TemporaryICloudSession
from ohana_installer.restore import (
    RestoreError,
    _safe_member_path,
    _verify_and_remove_descriptor,
    apply_staged_configuration,
    decrypt_and_extract,
    install_platform,
    latest_local_backup,
    list_remote_backup_ids,
    list_remote_manifests,
    select_remote_manifest,
)
from ohana_installer.restore_manifest import (
    RestoreManifestError,
    parse_restore_manifest,
)


class NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:
        pass


class PassthroughAgeProcess:
    def __init__(self, command) -> None:
        self.command = tuple(command)
        self.stdin = NonClosingBytesIO()
        self.input = self.stdin
        self.returncode = 0

    def communicate(self):
        destination = Path(self.command[self.command.index("--output") + 1])
        destination.write_bytes(self.input.getvalue())
        return b"", b""

    def kill(self) -> None:
        self.returncode = -9


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


def test_decrypt_and_extract_accepts_gzip_compressed_tar(tmp_path: Path) -> None:
    descriptor = {
        "schema_version": 1,
        "backup_id": "20260813T120000Z",
        "created_at": "2026-08-13T12:00:00Z",
        "profile": "infra-01",
        "platform_version": "1.0.50",
        "agent_version": "1.12.7",
        "vision_version": "1.11.8",
    }
    encrypted = io.BytesIO()
    with tarfile.open(fileobj=encrypted, mode="w:gz") as archive:
        config = b"enabled: true\n"
        config_member = tarfile.TarInfo("etc/ohana-agent/shikamaru.yaml")
        config_member.size = len(config)
        archive.addfile(config_member, io.BytesIO(config))
        descriptor_body = (json.dumps(descriptor) + "\n").encode()
        descriptor_member = tarfile.TarInfo("ohana-backup/descriptor.json")
        descriptor_member.size = len(descriptor_body)
        archive.addfile(descriptor_member, io.BytesIO(descriptor_body))
    encrypted_body = encrypted.getvalue()
    payload = json.loads(_manifest())
    payload["archive"]["size_bytes"] = len(encrypted_body)
    payload["archive"]["sha256"] = hashlib.sha256(encrypted_body).hexdigest()
    manifest = parse_restore_manifest(json.dumps(payload))
    identity = tmp_path / "identity.agekey"
    identity.write_text("AGE-SECRET-KEY-1TEST\n", encoding="utf-8")

    members = decrypt_and_extract(
        io.BytesIO(encrypted_body),
        manifest=manifest,
        identity_path=identity,
        staging_directory=tmp_path / "restore",
        popen_factory=lambda command, **_kwargs: PassthroughAgeProcess(command),
    )

    restored = tmp_path / "restore/payload/etc/ohana-agent/shikamaru.yaml"
    assert restored.read_bytes() == b"enabled: true\n"
    assert restored in members


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


@pytest.mark.parametrize("choose_backup", (False, True))
def test_icloud_selection_reports_when_no_backup_exists(choose_backup: bool) -> None:
    with pytest.raises(
        RestoreError,
        match="Aucune sauvegarde INFRA-01 n'est disponible dans iCloud",
    ):
        _select_icloud_manifest(
            (),
            choose_backup=choose_backup,
            requested_id=None,
            manifest_reader=lambda _backup_id: pytest.fail("Aucun manifeste à lire."),
        )


def test_restore_reuses_persistent_icloud_connection_without_credentials(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    persistent = tmp_path / "agent-rclone.conf"
    persistent.write_text("[icloud]\n", encoding="utf-8")

    selected = _icloud_config(
        SimpleNamespace(rclone_config=None, apple_id=None),
        tmp_path,
        persistent_config=persistent,
        input_function=lambda _prompt: pytest.fail("Apple ID ne doit pas être demandé."),
        password_function=lambda _prompt: pytest.fail(
            "Le mot de passe Apple ne doit pas être demandé."
        ),
    )

    assert selected == persistent
    assert "Connexion iCloud existante réutilisée" in capsys.readouterr().out


def test_restore_honors_explicit_rclone_configuration(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.conf"
    explicit.write_text("[icloud]\n", encoding="utf-8")
    persistent = tmp_path / "persistent.conf"
    persistent.write_text("[icloud]\n", encoding="utf-8")

    selected = _icloud_config(
        SimpleNamespace(rclone_config=explicit, apple_id=None),
        tmp_path,
        persistent_config=persistent,
        input_function=lambda _prompt: pytest.fail("Apple ID ne doit pas être demandé."),
        password_function=lambda _prompt: pytest.fail(
            "Le mot de passe Apple ne doit pas être demandé."
        ),
    )

    assert selected == explicit


def test_icloud_choice_lists_valid_backups_and_selects_by_number(
    capsys: pytest.CaptureFixture[str],
) -> None:
    newer = json.loads(_manifest())
    newer["backup_id"] = "20260814T120000Z"
    newer["created_at"] = "2026-08-14T12:00:00Z"
    newer["platform_version"] = "1.0.53"
    newer["archive"]["filename"] = "20260814T120000Z.tar.age"
    older = json.loads(_manifest())
    older["backup_id"] = "20260813T120000Z"

    manifests = {
        "20260813T120000Z": json.dumps(older).encode(),
        "20260814T120000Z": json.dumps(newer).encode(),
    }
    selected = _choose_remote_manifest(
        tuple(manifests),
        manifest_reader=manifests.__getitem__,
        input_function=lambda _prompt: "2",
    )

    assert selected is not None
    assert selected[0].backup_id == "20260813T120000Z"
    output = capsys.readouterr().out
    assert "14/08/2026 12:00 UTC" in output
    assert "Platform 1.0.53" in output
    assert "Agent 1.12.7 / Vision 1.11.8" in output


def test_remote_manifest_listing_ignores_invalid_entries() -> None:
    available = list_remote_manifests(
        ("20260812T120000Z", "20260813T120000Z"),
        manifest_reader=lambda backup_id: (
            _manifest() if backup_id == "20260813T120000Z" else b"invalid"
        ),
    )

    assert [manifest.backup_id for manifest, _content in available] == ["20260813T120000Z"]


def test_missing_remote_backup_directory_means_no_backup(tmp_path: Path) -> None:
    result = list_remote_backup_ids(
        rclone_binary=Path("/usr/bin/rclone"),
        rclone_config=tmp_path / "rclone.conf",
        remote="icloud:Ohana/Backups/infra-01",
        command_runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            3,
            "",
            "ERROR : error listing: directory not found",
        ),
    )

    assert result == ()


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
            "--defer-age-identity",
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
