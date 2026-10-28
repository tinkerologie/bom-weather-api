"""Transport for the BoM anonymous FTP server."""

from __future__ import annotations

import asyncio
from typing import Protocol

import aioftp

from .const import DEFAULT_TIMEOUT, FTP_HOST
from .exceptions import BomConnectionError, BomNotFoundError, BomTimeoutError

# FTP reply code for "file unavailable".
_FILE_UNAVAILABLE = "550"


class FileTransport(Protocol):
    """Something that can fetch a file from the BoM FTP server."""

    async def fetch(self, path: str) -> bytes:
        """Return the contents of the file at ``path``."""


class FtpTransport:
    """Download files from the BoM anonymous FTP server."""

    def __init__(
        self,
        host: str = FTP_HOST,
        *,
        port: int = 21,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the transport."""
        self._host = host
        self._port = port
        self._timeout = timeout

    async def fetch(self, path: str) -> bytes:
        """Download a file using an anonymous FTP session."""
        try:
            async with asyncio.timeout(self._timeout):
                async with aioftp.Client.context(
                    self._host,
                    self._port,
                    socket_timeout=self._timeout,
                ) as client:
                    await _ensure_exists(client, path)
                    async with client.download_stream(path) as stream:
                        chunks = [block async for block in stream.iter_by_block()]
                    return b"".join(chunks)
        except TimeoutError as err:
            raise BomTimeoutError(f"Timeout downloading {path}") from err
        except aioftp.StatusCodeError as err:
            if _FILE_UNAVAILABLE in {str(code) for code in err.received_codes}:
                raise BomNotFoundError(f"Not found: {path}", status=550) from err
            raise BomConnectionError(f"FTP error downloading {path}: {err}") from err
        except (OSError, aioftp.AIOFTPException) as err:
            raise BomConnectionError(f"Error downloading {path}: {err}") from err


async def _ensure_exists(client: aioftp.Client, path: str) -> None:
    """Raise a 550 StatusCodeError if ``path`` does not exist.

    The check runs on the control connection before RETR, because aioftp
    leaks the data connection when RETR is refused.
    """
    await client.command("TYPE I", "200")
    try:
        await client.command(f"SIZE {path}", "213")
    except aioftp.StatusCodeError as err:
        if _FILE_UNAVAILABLE in {str(code) for code in err.received_codes}:
            raise
        # SIZE is not supported by every server; fall back to MLST.
        if not await client.exists(path):
            raise aioftp.StatusCodeError(
                aioftp.Code("213"), aioftp.Code(_FILE_UNAVAILABLE), "not found"
            ) from err
