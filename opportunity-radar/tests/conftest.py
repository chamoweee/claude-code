"""Global test guards.

The suite claims to touch no network. This makes that claim enforceable rather
than aspirational: any test that reaches for a socket fails loudly, naming
itself, instead of quietly making a live request and passing anyway.

That is not hypothetical. The job tests originally looked offline — the price
fetchers were patched at module level — but `fetch_macro` bound its default
fetcher in the signature, so the patch had no effect and every run was hitting
Yahoo for real. It passed, it was just slow, and nobody would have noticed.
"""

from __future__ import annotations

import socket

import pytest


class NetworkAccessAttempted(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Block outbound sockets for every test."""
    if request.node.get_closest_marker("allow_network"):
        return

    def blocked(*args, **kwargs):
        raise NetworkAccessAttempted(
            f"{request.node.nodeid} tried to open a network connection. "
            f"Tests must use tests/fixtures/ or an injected fetcher."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
