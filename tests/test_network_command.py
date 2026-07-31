"""Tests de la commande réseau autonome."""

from __future__ import annotations

import argparse
from ipaddress import IPv4Address, IPv4Interface

import pytest

from ohana_installer.commands import network as network_command
from ohana_installer.network import InitialNetworkConfiguration, PendingNetworkChange


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "yes": False,
        "interface": None,
        "dhcp": False,
        "address": None,
        "gateway": None,
        "dns": [],
        "rollback_seconds": 180,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_network_command_displays_current_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        network_command,
        "read_network_state",
        lambda: {
            "interface": "eth0",
            "method": "manual",
            "address": "192.168.1.10/24",
            "gateway": "192.168.1.1",
            "dns_servers": ["192.168.1.11", "192.168.1.12"],
            "state": "100 (connected)",
        },
    )

    assert network_command.run(_args()) == 0
    output = capsys.readouterr().out
    assert "192.168.1.10/24" in output
    assert "192.168.1.11, 192.168.1.12" in output


def test_network_command_applies_and_confirms_static_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = InitialNetworkConfiguration(
        interface="eth0",
        method="manual",
        address=IPv4Interface("192.168.1.10/24"),
        gateway=IPv4Address("192.168.1.1"),
        dns_servers=(IPv4Address("192.168.1.11"),),
    )
    received: list[InitialNetworkConfiguration] = []
    monkeypatch.setattr(
        network_command,
        "begin_network_configuration",
        lambda configuration, **_kwargs: (
            received.append(configuration) or PendingNetworkChange("b" * 32, None, {})
        ),
    )
    confirmations: list[str] = []
    monkeypatch.setattr(
        network_command,
        "confirm_network_configuration",
        lambda transaction_id: (
            confirmations.append(transaction_id)
            or {
                "interface": "eth0",
                "method": "manual",
                "address": "192.168.1.10/24",
                "gateway": "192.168.1.1",
                "dns_servers": ["192.168.1.11"],
                "state": "connected",
            }
        ),
    )

    result = network_command.run(
        _args(
            yes=True,
            interface="eth0",
            address="192.168.1.10/24",
            gateway="192.168.1.1",
            dns=["192.168.1.11"],
        )
    )

    assert result == 0
    assert received == [expected]
    assert confirmations == ["b" * 32]
