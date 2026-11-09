"""Shared helpers for the Track B audit tests (no tests here).

The suite blocks every socket (tests/conftest.py). On Windows an asyncio event loop needs a loopback socket pair for
its self-pipe, so FastAPI's TestClient cannot start. ``loopback`` lets a test connect to 127.0.0.1 / ::1 only;
every other address is still refused, so nothing reaches the network, NSE or Dhan."""

from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
HEADER = {"X-Pulse-Request": "1"}
SAME_ORIGIN = {"Origin": "http://127.0.0.1:8000"}


def _host(address) -> str | None:
    return address[0] if isinstance(address, tuple) and address else None


@pytest.fixture
def loopback(_no_network, monkeypatch):
    """Allow loopback connections only (the event loop's self-pipe); any other address raises as before."""
    blocked_connect, blocked_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def connect(self, address):
        if _host(address) in _LOOPBACK:
            return _REAL_CONNECT(self, address)
        return blocked_connect(self, address)

    def connect_ex(self, address):
        if _host(address) in _LOOPBACK:
            return _REAL_CONNECT_EX(self, address)
        return blocked_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


@pytest.fixture
def client(loopback):
    """A test client that talks to the app as the page does: Host 127.0.0.1. The lifespan does not run (no
    background threads) because the client is not used as a context manager. Server errors come back as
    responses, not re-raised, so a test can check what a browser would see."""
    from webapp import server

    return TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
