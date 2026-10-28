"""Tests for the FTP transport against a local aioftp server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
import socket
from unittest.mock import patch

import aioftp
import pytest

from bom_weather_api import (
    BomConnectionError,
    BomNotFoundError,
    BomTimeoutError,
    FtpTransport,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def ftp_server(tmp_path: Path) -> AsyncIterator[int]:
    """Run an anonymous FTP server serving tmp_path."""
    (tmp_path / "anon").mkdir()
    (tmp_path / "anon" / "file.txt").write_bytes(b"hello " * 20000)
    port = _free_port()
    server = aioftp.Server([aioftp.User(base_path=tmp_path)])
    await server.start("127.0.0.1", port)
    try:
        yield port
    finally:
        await server.close()


async def test_fetch(ftp_server: int) -> None:
    transport = FtpTransport("127.0.0.1", port=ftp_server, timeout=10)
    assert await transport.fetch("/anon/file.txt") == b"hello " * 20000


async def test_fetch_missing_file(ftp_server: int) -> None:
    transport = FtpTransport("127.0.0.1", port=ftp_server, timeout=10)
    with pytest.raises(BomNotFoundError):
        await transport.fetch("/anon/missing.txt")


async def test_fetch_connection_refused() -> None:
    transport = FtpTransport("127.0.0.1", port=_free_port(), timeout=5)
    with pytest.raises(BomConnectionError):
        await transport.fetch("/anon/file.txt")


async def test_fetch_other_status_error() -> None:
    transport = FtpTransport("127.0.0.1", timeout=5)
    error = aioftp.StatusCodeError(aioftp.Code("230"), aioftp.Code("421"), "busy")
    with (
        patch.object(aioftp.Client, "connect", side_effect=error),
        pytest.raises(BomConnectionError) as exc,
    ):
        await transport.fetch("/anon/file.txt")
    assert not isinstance(exc.value, BomNotFoundError)


async def test_fetch_timeout() -> None:
    transport = FtpTransport("127.0.0.1", timeout=5)
    with (
        patch.object(aioftp.Client, "connect", side_effect=TimeoutError),
        pytest.raises(BomTimeoutError),
    ):
        await transport.fetch("/anon/file.txt")


async def test_fetch_size_reports_missing_file() -> None:
    """A 550 reply to SIZE is a missing file; RETR is never attempted."""
    transport = FtpTransport("127.0.0.1", timeout=5)
    commands: list[str | None] = []

    async def command(
        self: aioftp.Client, cmd: str | None = None, *args: object, **kwargs: object
    ) -> None:
        commands.append(cmd)
        if cmd and cmd.startswith("SIZE"):
            raise aioftp.StatusCodeError(
                aioftp.Code("213"), aioftp.Code("550"), "missing"
            )

    with (
        patch.object(aioftp.Client, "connect"),
        patch.object(aioftp.Client, "login"),
        patch.object(aioftp.Client, "quit"),
        patch.object(aioftp.Client, "command", command),
        pytest.raises(BomNotFoundError),
    ):
        await transport.fetch("/anon/missing.txt")
    assert commands == ["TYPE I", "SIZE /anon/missing.txt"]
