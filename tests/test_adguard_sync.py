"""Install/upgrade/restore the AdGuard capability without losing operator choices."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from ohana_installer import adguard_sync
from ohana_installer.manifest import InstallationProfile
from ohana_installer.restore import RestoreError, apply_staged_configuration
from ohana_installer.system_capabilities import KNOWN_CAPABILITIES, provision_profile


@pytest.fixture
def layout(tmp_path, monkeypatch):
    for name, relative in {
        "BINARY": "opt/adguardhome-sync",
        "CONFIGURATION": "etc/ohana-agent/adguardhome-sync.yaml",
        "STATE": "etc/ohana-agent/adguard-sync-state.json",
        "SYSTEMD_DIRECTORY": "systemd",
        "HELPER": "helper",
        "SUDOERS": "sudoers",
    }.items():
        monkeypatch.setattr(adguard_sync, name, tmp_path / relative)
    monkeypatch.setattr(adguard_sync, "ensure_binary", lambda: True)
    commands = []

    def runner(command, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    return commands, runner


def test_new_install_prepares_configuration_and_units_without_activation(layout):
    commands, runner = layout
    adguard_sync.provision(command_runner=runner, secure_ownership=False)
    assert 'password: ""' in adguard_sync.CONFIGURATION.read_text()
    assert (adguard_sync.SYSTEMD_DIRECTORY / adguard_sync.SERVICE).is_file()
    assert (adguard_sync.SYSTEMD_DIRECTORY / adguard_sync.TIMER).is_file()
    assert json.loads(adguard_sync.STATE.read_text())["enabled"] is False
    assert not any(command[1] in {"enable", "start", "stop", "disable"} for command in commands)


def test_upgrade_preserves_configuration_custom_units_and_activation(layout):
    commands, runner = layout
    adguard_sync.CONFIGURATION.parent.mkdir(parents=True)
    adguard_sync.CONFIGURATION.write_bytes(b"private-existing-configuration\n")
    adguard_sync.STATE.write_text('{"schema_version":1,"enabled":true}')
    adguard_sync.SYSTEMD_DIRECTORY.mkdir()
    for name in (adguard_sync.SERVICE, adguard_sync.TIMER):
        (adguard_sync.SYSTEMD_DIRECTORY / name).write_text("custom unit")
    adguard_sync.provision(command_runner=runner, secure_ownership=False)
    adguard_sync.provision(command_runner=runner, secure_ownership=False)
    assert adguard_sync.CONFIGURATION.read_bytes() == b"private-existing-configuration\n"
    assert json.loads(adguard_sync.STATE.read_text())["enabled"] is True
    assert (adguard_sync.SYSTEMD_DIRECTORY / adguard_sync.SERVICE).read_text() == "custom unit"
    assert not any(command[1] in {"enable", "disable", "stop", "start"} for command in commands)


def test_profile_never_attempts_to_install_the_engine_with_apt(layout, monkeypatch):
    commands, runner = layout
    monkeypatch.setattr(adguard_sync, "provision", lambda **kwargs: True)
    result = provision_profile(
        InstallationProfile(
            identifier="infra-01",
            name="INFRA-01",
            capabilities=(KNOWN_CAPABILITIES["adguard-sync"],),
        ),
        command_runner=runner,
    )
    assert result.capabilities[0].package_created
    assert commands == []


def archive_bytes(binary=b"candidate", *, symlink=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        entry = tarfile.TarInfo("adguardhome-sync")
        if symlink:
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            archive.addfile(entry)
        else:
            entry.size = len(binary)
            archive.addfile(entry, io.BytesIO(binary))
    return stream.getvalue()


@pytest.mark.parametrize("failure", ["checksum", "version", "symlink"])
def test_failed_binary_validation_preserves_the_existing_binary(tmp_path, monkeypatch, failure):
    binary = tmp_path / "adguardhome-sync"
    binary.write_bytes(b"existing")
    body = archive_bytes(symlink=failure == "symlink")
    monkeypatch.setattr(adguard_sync.platform, "machine", lambda: "aarch64")
    monkeypatch.setitem(
        adguard_sync.ASSETS,
        "aarch64",
        ("arm64", "0" * 64 if failure == "checksum" else hashlib.sha256(body).hexdigest()),
    )
    monkeypatch.setattr(adguard_sync, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    monkeypatch.setattr(adguard_sync, "installed_version", lambda path: "older")
    with pytest.raises(adguard_sync.AdGuardInstallationError):
        adguard_sync.ensure_binary(binary)
    assert binary.read_bytes() == b"existing"
    assert list(tmp_path.glob(".adguard-*")) == []


@pytest.mark.parametrize("enabled", [True, False, None])
def test_restore_reconstructs_engine_and_honors_saved_activation(tmp_path, monkeypatch, enabled):
    payload = tmp_path / "payload"
    configuration = payload / "etc/ohana-agent/adguardhome-sync.yaml"
    configuration.parent.mkdir(parents=True)
    configuration.write_text("restored settings")
    if enabled is not None:
        configuration.with_name("adguard-sync-state.json").write_text(
            json.dumps({"schema_version": 1, "enabled": enabled})
        )
    helper = tmp_path / "helper"
    helper.touch()
    monkeypatch.setattr(adguard_sync, "HELPER", helper)
    provisions = []
    monkeypatch.setattr(adguard_sync, "provision", lambda **kwargs: provisions.append(True))
    commands = []

    def runner(command, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    apply_staged_configuration(
        payload,
        destination_root=tmp_path / "machine",
        owner_restorer=lambda path: None,
        command_runner=runner,
    )
    assert provisions == [True]
    assert (
        (str(helper), "activate") in commands
        if enabled
        else (str(helper), "activate") not in commands
    )
    if not enabled:
        assert ("/usr/bin/systemctl", "disable", "--now", adguard_sync.TIMER) in commands
        restored_state = tmp_path / "machine/etc/ohana-agent/adguard-sync-state.json"
        assert json.loads(restored_state.read_text())["enabled"] is False


def test_invalid_restore_intent_is_rejected_before_provisioning(tmp_path, monkeypatch):
    payload = tmp_path / "payload"
    state = payload / "etc/ohana-agent/adguard-sync-state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"schema_version":1,"enabled":"yes"}')
    provisions = []
    monkeypatch.setattr(adguard_sync, "provision", lambda **kwargs: provisions.append(True))
    with pytest.raises(RestoreError, match="invalide"):
        apply_staged_configuration(payload)
    assert provisions == []


def test_existing_manual_activation_is_adopted_without_restarting(layout):
    commands, base_runner = layout

    def runner(command, **kwargs):
        result = base_runner(command, **kwargs)
        if command[1] == "is-enabled":
            return subprocess.CompletedProcess(command, 0, "enabled", "")
        return result

    adguard_sync.provision(command_runner=runner, secure_ownership=False)
    assert json.loads(adguard_sync.STATE.read_text())["enabled"] is True
    assert not any(command[1] in {"enable", "disable", "start", "stop"} for command in commands)


def test_privileged_rule_grants_only_two_fixed_commands(layout, monkeypatch):
    adguard_sync.HELPER.touch()
    calls = []
    monkeypatch.setattr(
        adguard_sync.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append(command) or subprocess.CompletedProcess(command, 0, "", "")
        ),
    )
    adguard_sync.prepare_administration(secure_ownership=False)
    rule = adguard_sync.SUDOERS.read_text()
    assert "*" not in rule
    assert rule == (
        f"ohana-agent ALL=(root) NOPASSWD: {adguard_sync.HELPER} activate, "
        f"{adguard_sync.HELPER} deactivate\n"
    )
    assert calls[0][0:2] == ("/usr/sbin/visudo", "-cf")


def test_restore_activation_failure_rolls_back_configuration(tmp_path, monkeypatch):
    payload = tmp_path / "payload"
    source = payload / "etc/ohana-agent/adguardhome-sync.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("restored settings")
    source.with_name("adguard-sync-state.json").write_text('{"schema_version":1,"enabled":true}')
    machine = tmp_path / "machine"
    destination = machine / "etc/ohana-agent/adguardhome-sync.yaml"
    destination.parent.mkdir(parents=True)
    destination.write_text("previous settings")
    helper = tmp_path / "helper"
    helper.touch()
    monkeypatch.setattr(adguard_sync, "HELPER", helper)
    monkeypatch.setattr(adguard_sync, "provision", lambda **kwargs: None)
    commands = []

    def runner(command, **kwargs):
        commands.append(tuple(command))
        if command[0] == str(helper):
            return subprocess.CompletedProcess(command, 1, "", "private")
        if command[1:3] == ("is-enabled", adguard_sync.TIMER):
            return subprocess.CompletedProcess(command, 0, "enabled", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(RestoreError, match="activation refusée"):
        apply_staged_configuration(
            payload,
            command_runner=runner,
            destination_root=machine,
            owner_restorer=lambda path: None,
        )
    assert destination.read_text() == "previous settings"
    assert ("/usr/bin/systemctl", "enable", adguard_sync.TIMER) in commands


@pytest.mark.parametrize("filename", ["adguardhome-sync.yaml", "plugins/adguard-sync.yaml"])
def test_restore_keeps_adguard_configuration_readable_and_administrable(monkeypatch, filename):
    from ohana_installer.restore import _restore_owner

    ownership, modes = [], []
    monkeypatch.setattr(
        "ohana_installer.restore.shutil.chown",
        lambda path, **kwargs: ownership.append((path, kwargs)),
    )
    monkeypatch.setattr(Path, "chmod", lambda path, mode: modes.append((path, mode)))
    path = Path("/etc/ohana-agent") / filename
    _restore_owner(path)
    assert ownership == [(path, {"user": "root", "group": "ohana-agent"})]
    assert modes == [(path, 0o660)]
