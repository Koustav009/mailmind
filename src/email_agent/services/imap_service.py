import asyncio
import re

import aioimaplib

LITERAL_END_RE = re.compile(rb"\{\d+\}$")
UID_RE = re.compile(rb"UID (\d+)")
FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
LABELS_RE = re.compile(rb"X-GM-LABELS \(([^)]*)\)")

FETCH_QUERY = "(UID FLAGS X-GM-LABELS BODY.PEEK[])"
FETCH_QUERY_NO_LABELS = "(UID FLAGS BODY.PEEK[])"

CATEGORY_LABELS = {
    "CATEGORY_PRIMARY": "Primary",
    "CATEGORY_PROMOTIONS": "Promotions",
    "CATEGORY_SOCIAL": "Social",
    "CATEGORY_UPDATES": "Updates",
    "CATEGORY_FORUMS": "Forums",
}


def mail_folder_from_labels(labels: list[str], flags: list[str] | None = None) -> str:
    """Map Gmail IMAP labels/flags to the visible tab (Primary/Promotions/...)."""
    for label in labels:
        if label in CATEGORY_LABELS:
            return CATEGORY_LABELS[label]
    lowered = {label.lower() for label in labels}
    if (flags and "\\Junk" in flags) or lowered & {"\\junk", "spam", "[gmail]/spam"}:
        return "Spam"
    return "Primary"


class ImapError(Exception):
    pass


def parse_uid_search(lines: list[bytes]) -> list[int]:
    """Extract UID list from a UID SEARCH response."""
    ids: list[int] = []
    for line in lines:
        for token in line.split():
            if token.isdigit():
                ids.append(int(token))
    return ids


def parse_fetch_response(lines: list) -> tuple[int, list[str], list[str], bytes]:
    """Parse a single-message FETCH response into (uid, flags, labels, raw bytes)."""
    uid = 0
    flags: list[str] = []
    labels: list[str] = []
    raw = b""
    for i, line in enumerate(lines):
        if not isinstance(line, bytes):
            continue
        if not LITERAL_END_RE.search(line.rstrip()):
            continue
        uid_match = UID_RE.search(line)
        if uid_match:
            uid = int(uid_match.group(1))
        flags_match = FLAGS_RE.search(line)
        if flags_match:
            flags = flags_match.group(1).decode(errors="replace").split()
        labels_match = LABELS_RE.search(line)
        if labels_match:
            labels = labels_match.group(1).decode(errors="replace").split()
        if i + 1 < len(lines) and isinstance(lines[i + 1], (bytes, bytearray)):
            raw = bytes(lines[i + 1])
        break
    return uid, flags, labels, raw


class ImapService:
    """Async IMAP client wrapper: fetch unseen, mark seen, move to Trash/Archive.

    All move operations are idempotent: a message that is already gone is
    treated as a successful no-op.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        folder: str = "INBOX",
        archive_folder: str = "Archive",
        trash_folder: str = "Trash",
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._folder = folder
        self._archive_folder = archive_folder
        self._trash_folder = trash_folder
        self._client: aioimaplib.IMAP4_SSL | None = None
        self._gm_labels = True

    async def connect(self) -> None:
        await self.disconnect()
        client = aioimaplib.IMAP4_SSL(host=self._host, port=self._port, timeout=60)
        await client.wait_hello_from_server()
        self._client = client
        self._check_sync(await client.login(self._user, self._password), "login")
        self._check_sync(await client.select(self._folder), "select")

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.logout()
            except Exception:
                pass
            self._client = None

    async def fetch_unseen(self, since: str | None = None) -> list[tuple[int, list[str], list[str], bytes]]:
        """Fetch UNSEEN messages with BODY.PEEK (read status untouched).

        Returns (uid, flags, labels, raw) tuples. `since` limits the search to
        recent mail (IMAP SINCE date, e.g. '05-Oct-2026') — important for
        mailboxes with long unread history. Labels are Gmail X-GM-LABELS
        (empty on non-Gmail servers).
        """

        async def op() -> list[tuple[int, list[str], list[str], bytes]]:
            client = self._require()
            criteria = ["UNSEEN"]
            if since:
                criteria += ["SINCE", since]
            resp = await client.uid_search(*criteria)
            self._check_sync(resp, "uid search")
            results: list[tuple[int, list[str], list[str], bytes]] = []
            for uid in parse_uid_search(resp.lines):
                fetch = await self._fetch_one(client, uid)
                results.append(parse_fetch_response(fetch.lines))
            return results

        return await self._with_reconnect(op)

    async def _fetch_one(self, client: aioimaplib.IMAP4_SSL, uid: int):
        query = FETCH_QUERY if self._gm_labels else FETCH_QUERY_NO_LABELS
        try:
            resp = await client.uid("fetch", str(uid), query)
            self._check_sync(resp, "uid fetch")
            return resp
        except ImapError:
            if not self._gm_labels:
                raise
            self._gm_labels = False  # server lacks X-GM-LABELS (non-Gmail)
            resp = await client.uid("fetch", str(uid), FETCH_QUERY_NO_LABELS)
            self._check_sync(resp, "uid fetch")
            return resp

    async def fetch_message(self, uid: int) -> bytes:
        """Re-fetch the full raw message for a UID (used by Show Full)."""

        async def op() -> bytes:
            client = self._require()
            resp = await client.uid("fetch", str(uid), "(UID BODY.PEEK[])")
            self._check_sync(resp, "uid fetch")
            return parse_fetch_response(resp.lines)[3]

        return await self._with_reconnect(op)

    async def mark_seen(self, uid: int) -> None:
        """Mark a message as \\Seen. Called only after a successful DB write."""

        async def op() -> None:
            client = self._require()
            resp = await client.uid("store", str(uid), "+FLAGS.SILENT", "(\\Seen)")
            self._check_sync(resp, "uid store")

        await self._with_reconnect(op)

    async def move_to_trash(self, uid: int) -> bool:
        return await self.move(uid, self._trash_folder)

    async def move_to_archive(self, uid: int) -> bool:
        return await self.move(uid, self._archive_folder)

    async def move(self, uid: int, destination: str) -> bool:
        """Move a message to `destination`. Returns False if it is already gone."""

        async def op() -> bool | None:
            client = self._require()
            exists = await client.uid("fetch", str(uid), "(UID)")
            if exists.result != "OK":
                return False
            if client.has_capability("MOVE"):
                resp = await client.protocol.move(str(uid), f'"{destination}"', by_uid=True)
                if resp.result == "OK":
                    return True
            self._check_sync(await client.uid("copy", str(uid), f'"{destination}"'), "uid copy")
            await client.uid("store", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
            await client.expunge()
            return True

        result = await self._with_reconnect(op)
        return bool(result)

    def _require(self) -> aioimaplib.IMAP4_SSL:
        if self._client is None:
            raise ImapError("IMAP client is not connected")
        return self._client

    def _check_sync(self, resp: object, action: str) -> None:
        if getattr(resp, "result", None) != "OK":
            raise ImapError(f"IMAP {action} failed: {getattr(resp, 'lines', b'')}")

    async def _with_reconnect(self, op):
        try:
            return await op()
        except (ImapError, aioimaplib.AioImapException, OSError, asyncio.TimeoutError):
            await self.disconnect()
            await self.connect()
            return await op()
