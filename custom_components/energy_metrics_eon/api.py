"""Client for the Google Apps Script bridge (see apps_script/Code.gs)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=120)


class BridgeError(Exception):
    """The bridge could not be reached or returned something unexpected."""


class BridgeAuthError(BridgeError):
    """The bridge rejected the token."""


@dataclass
class Attachment:
    name: str
    data: bytes


@dataclass
class Message:
    id: str
    date_ms: int
    subject: str
    attachments: list[Attachment]


class BridgeClient:
    """Fetches export e-mails from the user's Apps Script web app."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self._url = url
        self._token = token

    async def _post(self, payload: dict) -> dict:
        payload = {"token": self._token, **payload}
        try:
            # Apps Script answers the POST with a 302 that must be followed by a GET;
            # aiohttp does exactly that by default.
            async with self._session.post(
                self._url, json=payload, timeout=TIMEOUT
            ) as resp:
                text = await resp.text()
                status = resp.status
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BridgeError(f"Cannot reach the Apps Script: {err}") from err

        try:
            body = json.loads(text)
        except ValueError as err:
            raise BridgeError(
                f"Apps Script returned HTTP {status} without JSON; check that the "
                "web app is deployed with access set to 'Anyone'"
            ) from err

        if not isinstance(body, dict) or not body.get("ok"):
            error = body.get("error") if isinstance(body, dict) else None
            if error == "unauthorized":
                raise BridgeAuthError("The Apps Script rejected the token")
            detail = body.get("detail", "") if isinstance(body, dict) else ""
            raise BridgeError(f"Apps Script error: {error} {detail}".strip())
        return body

    async def mark_processed(self, ids: list[str], after_ms: int) -> int | None:
        """Label, mark as read and archive the given export e-mails.

        Returns how many were marked, or None if the deployed script is an
        older version without this feature. Such a script treats the request
        as a fetch; after_ms and the limit keep its answer small.
        """
        body = await self._post(
            {"action": "mark_processed", "ids": ids, "after": after_ms, "limit": 1}
        )
        marked = body.get("marked")
        return marked if isinstance(marked, int) else None

    async def fetch(self, after_ms: int, limit: int) -> list[Message]:
        """Return messages newer than after_ms, oldest first."""
        body = await self._post({"after": after_ms, "limit": limit})

        messages: list[Message] = []
        for raw in body.get("messages", []):
            attachments = []
            for att in raw.get("attachments", []):
                try:
                    data = base64.b64decode(att.get("data", ""))
                except (binascii.Error, ValueError):
                    continue
                attachments.append(Attachment(str(att.get("name", "")), data))
            messages.append(
                Message(
                    id=str(raw.get("id", "")),
                    date_ms=int(raw.get("date", 0)),
                    subject=str(raw.get("subject", "")),
                    attachments=attachments,
                )
            )
        return messages
