"""Tests du provisionnement NetworkManager."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path

import pytest

from ohana_installer.network import (
    InitialNetworkConfiguration,
    NetworkProvisioningError,
    apply_initial_network_configuration,
    prepare_network_administration,
    remove_network_administration,
)


def test_static_network_configuration_requires_same_subnet() -> None:
    with pytest.raises(NetworkProvisioningError):
        InitialNetworkConfiguration(
            interface="eth0",
            method="manual",
            address=IPv4Interface("192.168.1.10/24"),
            gateway=IPv4Address("192.168.2.1"),
            dns_servers=(IPv4Address("192.168.1.11"),),
        )


def test_prepare_network_administration_installs_wrapper_and_sudoers(
    tmp_path: Path,
) -> None:
    entrypoint = tmp_path / "ohana-agent-network-helper"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o755)
    nmcli = tmp_path / "nmcli"
    nmcli.write_text("#!/bin/sh\n", encoding="utf-8")
    nmcli.chmod(0o755)
    helper = tmp_path / "sbin" / "ohana-network-helper"
    sudoers = tmp_path / "sudoers.d" / "ohana-agent-network"

    preparation = prepare_network_administration(
        helper_path=helper,
        sudoers_path=sudoers,
        entrypoint_path=entrypoint,
        nmcli_path=nmcli,
        visudo_path=tmp_path / "missing-visudo",
        secure_ownership=False,
    )

    assert preparation.enabled is True
    assert helper.read_text(encoding="utf-8") == (f'#!/bin/sh\nexec "{entrypoint}" "$@"\n')
    assert sudoers.read_text(encoding="utf-8") == (f"ohana-agent ALL=(root) NOPASSWD: {helper} *\n")
    if os.name == "posix":
        assert stat.S_IMODE(helper.stat().st_mode) == 0o755
    if os.name == "posix":
        assert stat.S_IMODE(sudoers.stat().st_mode) == 0o440


def test_initial_network_configuration_rejects_network_address() -> None:
    with pytest.raises(NetworkProvisioningError, match="réseau ou broadcast"):
        InitialNetworkConfiguration(
            interface="eth0",
            method="manual",
            address=IPv4Interface("192.168.1.0/24"),
            gateway=IPv4Address("192.168.1.1"),
            dns_servers=(IPv4Address("192.168.1.11"),),
        )


def test_apply_initial_network_configuration_applies_then_confirms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "ohana-network-helper"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        input_data = kwargs.get("input")
        calls.append((command, input_data if isinstance(input_data, str) else None))
        if command[1] == "apply":
            payload = {
                "transaction_id": "a" * 32,
                "state": {"interface": "eth0", "method": "manual"},
            }
        else:
            payload = {
                "interface": "eth0",
                "method": "manual",
                "address": "192.168.1.10/24",
            }
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr("ohana_installer.network.subprocess.run", fake_run)
    configuration = InitialNetworkConfiguration(
        interface="eth0",
        method="manual",
        address=IPv4Interface("192.168.1.10/24"),
        gateway=IPv4Address("192.168.1.1"),
        dns_servers=(
            IPv4Address("192.168.1.11"),
            IPv4Address("192.168.1.12"),
        ),
    )

    state = apply_initial_network_configuration(
        configuration,
        helper_path=helper,
    )

    assert state["address"] == "192.168.1.10/24"
    assert calls[0][0] == [
        str(helper),
        "apply",
        "--rollback-seconds",
        "90",
    ]
    assert json.loads(calls[0][1] or "{}") == configuration.payload()
    assert calls[1][0] == [str(helper), "confirm", "a" * 32]


def test_remove_network_administration_confirms_pending_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "ohana-network-helper"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)
    sudoers = tmp_path / "ohana-network-sudoers"
    sudoers.write_text("rule\n", encoding="utf-8")
    state = tmp_path / "network-state"
    state.mkdir()
    (state / ("b" * 32 + ".json")).write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("ohana_installer.network.subprocess.run", fake_run)

    assert (
        remove_network_administration(
            helper_path=helper,
            sudoers_path=sudoers,
            state_directory=state,
        )
        is True
    )
    assert calls == [[str(helper), "confirm", "b" * 32]]
    assert not helper.exists()
    assert not sudoers.exists()
    assert not state.exists()
