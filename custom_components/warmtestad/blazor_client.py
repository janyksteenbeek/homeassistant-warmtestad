"""Reverse-engineered client for the new Warmtestad customer portal.

The portal at https://mijn.warmtestad.nl was rebuilt on the **ZeroFriction**
platform as an **ASP.NET Core Blazor Server (Web App)** application. The old
REST API (``portalwarmtestad-prd.azurewebsites.net`` with a bearer token) no
longer exists. Everything now runs over a Blazor **SignalR** circuit that uses
the binary **blazorpack** (MessagePack-based) hub protocol.

How login and data retrieval actually work (reverse-engineered against the live
portal — see README):

* There is **no REST/JSON API** and **no HTTP form POST** for login. The login
  form is interactive: typing and submitting dispatch *browser events* over the
  SignalR circuit (``BeginInvokeDotNetFromJS`` -> ``DispatchEventAsync`` with an
  ``eventHandlerId``). On success the server tells the browser to navigate to
  ``/login?key=<guid>`` (a plain HTTP endpoint that sets the auth cookie).
* The rendered UI — including consumption figures like ``"28,777 GJ"`` and the
  login form's field names / event handler ids — arrives inside Blazor **render
  batches** (a binary RenderTree format). This client parses those batches
  (string table + 20-byte frame records) to find the handler ids to drive, and
  to read the consumption value back out.

Boot sequence for a circuit:

1. ``GET <page>`` -> parse the ``<!--Blazor:{...}-->`` server component markers
   and pick up the antiforgery / session cookies.
2. ``POST /_blazor/negotiate`` -> ``connectionToken``.
3. WebSocket ``/_blazor?id=<token>`` + blazorpack handshake.
4. ``StartCircuit(baseUri, uri, descriptors, null)`` -> server streams render
   batches.

NOTE: This is an unofficial, best-effort reimplementation of an undocumented
binary protocol; it is inherently fragile to portal updates. The mechanics can
be validated end-to-end with dummy credentials (a wrong password renders an
inline "incorrect" message over the circuit), which is how this was developed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import struct

import aiohttp

try:
    import msgpack
except ImportError:  # pragma: no cover - declared in manifest.json requirements
    msgpack = None

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://mijn.warmtestad.nl"
LOGIN_PATH = "/account/login"
CONSUMPTION_PATH = "/consumption"

RECORD_SEPARATOR = 0x1E

# SignalR hub message types.
MSG_INVOCATION = 1
MSG_COMPLETION = 3
MSG_PING = 6

# Phrases the portal renders on a failed login (the portal uses English for
# this message even on the Dutch UI; Dutch variants kept as a safety net).
_LOGIN_ERROR_MARKERS = (
    b"email or password was wrong",
    b"was wrong",
    b"incorrect",
    b"onjuist",
)

_GJ_RE = re.compile(rb"([0-9]{1,3}(?:[.,][0-9]{1,3})?)\s*GJ")


class WarmtestadError(Exception):
    """Raised when the portal flow cannot be completed."""


class WarmtestadAuthError(WarmtestadError):
    """Raised when authentication fails (bad credentials / changed flow)."""


# --------------------------------------------------------------------------- #
# SignalR binary framing
# --------------------------------------------------------------------------- #
def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


def _frame(payload: bytes) -> bytes:
    return _write_varint(len(payload)) + payload


def _iter_messages(data: bytes):
    pos = 0
    while pos < len(data):
        length, pos = _read_varint(data, pos)
        yield data[pos : pos + length]
        pos += length


# --------------------------------------------------------------------------- #
# Blazor render-batch parsing
# --------------------------------------------------------------------------- #
# Frame types (RenderTreeFrameType).
_FRAME_ATTRIBUTE = 3
# Each serialized RenderTreeFrame is a fixed 20-byte record:
#   +0 int32 frameType
#   +4 int32 (attribute: name string-index / element: subtreeLength)
#   +8 int32 (attribute: value string-index / element: name string-index)
#   +12 uint64 (attribute: eventHandlerId)
_FRAME_SIZE = 20


class RenderBatch:
    """Parses the parts of a Blazor render batch that we need."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.strings: list[str] = []
        # (frameIndex, name, value, handlerId)
        self.attributes: list[tuple[int, str, str, int]] = []
        # (componentId, referenceFrameIndex) from the render-tree diffs
        self.diff_refs: list[tuple[int, int]] = []
        try:
            self._parse()
        except Exception as err:  # noqa: BLE001 - tolerate format drift
            _LOGGER.debug("Render batch parse failed: %s", err)

    def _i32(self, off: int) -> int:
        return struct.unpack_from("<i", self.data, off)[0]

    def _u64(self, off: int) -> int:
        return struct.unpack_from("<Q", self.data, off)[0]

    def _parse(self) -> None:
        data = self.data
        n = len(data)
        # The last 5 int32s are section start offsets (per Blazor's
        # OutOfProcessRenderBatch): updatedComponents, referenceFrames,
        # disposedComponentIds, disposedEventHandlerIds, strings.
        updated_start = self._i32(n - 20)
        frames_start = self._i32(n - 16)
        strings_start = self._i32(n - 4)

        # String table: int32 pointers into the buffer; each points at a
        # 7-bit-length-prefixed UTF-8 string.
        ptrs = [self._i32(o) for o in range(strings_start, n - 20, 4)]
        for p in ptrs:
            self.strings.append(self._read_string(p))

        # Reference frames: int32 count, then fixed 20-byte records.
        count = self._i32(frames_start)
        base = frames_start + 4
        for k in range(count):
            fo = base + k * _FRAME_SIZE
            if fo + _FRAME_SIZE > n:
                break
            if self._i32(fo) == _FRAME_ATTRIBUTE:
                name = self._string(self._i32(fo + 4))
                value = self._string(self._i32(fo + 8))
                handler_id = self._u64(fo + 12)
                self.attributes.append((k, name, value, handler_id))

        # updatedComponents: int32 count, then count 4-byte pointers to
        # RenderTreeDiff structs stored earlier in the buffer. Each diff is
        # componentId(int32) + edits ArrayRange (count + 16-byte edits, whose
        # referenceFrameIndex is at edit+8). This lets us map a frame back to
        # the component that rendered it -- needed for input value binding.
        diff_count = self._i32(updated_start)
        for i in range(diff_count):
            diff_off = self._i32(updated_start + 4 + i * 4)
            component_id = self._i32(diff_off)
            edit_count = self._i32(diff_off + 4)
            for e in range(edit_count):
                ref_frame = self._i32(diff_off + 8 + e * 16 + 8)
                self.diff_refs.append((component_id, ref_frame))

    def _read_string(self, off: int) -> str:
        length, shift, p = 0, 0, off
        while True:
            byte = self.data[p]
            p += 1
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        return self.data[p : p + length].decode("utf-8", "replace")

    def _string(self, idx: int) -> str:
        return self.strings[idx] if 0 <= idx < len(self.strings) else ""

    def owner_component(self, frame_index: int) -> int | None:
        """The component that rendered ``frame_index`` (largest diff ref <= it).

        This is the ``componentId`` Blazor expects in ``eventFieldInfo`` so that
        an ``@bind`` input commits its value.
        """
        best = None
        for component_id, ref in self.diff_refs:
            if ref <= frame_index and (best is None or ref > best[1]):
                best = (component_id, ref)
        return best[0] if best else None

    # -- login form introspection ------------------------------------------- #
    def find_login_handlers(self) -> dict | None:
        """Return the login form's event handlers + binding info, or None.

        Walks the attribute frames in document order. An input element's
        attributes are emitted consecutively (``type``, ``name``, ``value``,
        then its ``oninput`` event handler), so we associate the most recent
        ``type`` with the following input handler and remember its frame index
        (to resolve the owning component for ``eventFieldInfo``). The form's
        ``onsubmit`` handler is captured separately.
        """
        result: dict = {}
        cur_type = None
        cur_frame = 0
        for frame_index, name, value, handler in self.attributes:
            if name == "type":
                cur_type = value
                cur_frame = frame_index
            elif name in ("oninput", "onchange") and handler:
                if cur_type == "text" and "email" not in result:
                    result["email"] = handler
                    result["email_component"] = self.owner_component(cur_frame)
                elif cur_type == "password" and "password" not in result:
                    result["password"] = handler
                    result["password_component"] = self.owner_component(cur_frame)
            elif name == "onsubmit" and handler and "submit" not in result:
                result["submit"] = handler
        if {"email", "password", "submit"} <= result.keys():
            return result
        return None

    def consumption_gj(self) -> float | None:
        """Find the cumulative "Verbruik" value among the rendered strings."""
        strings = self.strings
        for i, s in enumerate(strings):
            if s == "Verbruik":
                # The value is rendered close to the label.
                for cand in strings[i : i + 12]:
                    m = _GJ_RE.search(cand.encode())
                    if m:
                        return _to_float(m.group(1))
        values = []
        for s in strings:
            m = _GJ_RE.search(s.encode())
            if m:
                v = _to_float(m.group(1))
                if v is not None:
                    values.append(v)
        return max(values) if values else None


# --------------------------------------------------------------------------- #
# Marker parsing
# --------------------------------------------------------------------------- #
def parse_blazor_markers(html: str) -> list[dict]:
    markers = []
    for match in re.finditer(r"<!--Blazor:(\{.*?\})-->", html, re.DOTALL):
        try:
            obj = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "server":
            markers.append(obj)
    markers.sort(key=lambda m: m.get("sequence", 0))
    return markers


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class WarmtestadBlazorClient:
    """Drives the Blazor Server circuit to log in and read consumption data."""

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if msgpack is None:
            raise WarmtestadError("The 'msgpack' package is required.")
        self._email = email
        self._password = password
        self._session = session
        self._owns_session = session is None
        self._authenticated = False
        self._call_id = 0

    async def __aenter__(self) -> "WarmtestadBlazorClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                headers={"User-Agent": "Mozilla/5.0 (Home Assistant) Warmtestad"},
            )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    # ----- low-level circuit ---------------------------------------------- #
    async def _negotiate_ws(self, path: str):
        """GET the page (markers + cookies) and open the circuit WebSocket."""
        assert self._session is not None
        async with self._session.get(BASE_URL + path) as resp:
            html = await resp.text()
        markers = parse_blazor_markers(html)
        async with self._session.post(
            f"{BASE_URL}/_blazor/negotiate?negotiateVersion=1",
            headers={"Content-Length": "0"},
        ) as resp:
            negotiate = await resp.json()
        token = negotiate.get("connectionToken")
        if not token:
            raise WarmtestadError(f"Negotiate failed: {negotiate}")
        self._handshake_done = False
        ws = await self._session.ws_connect(
            BASE_URL.replace("https://", "wss://") + f"/_blazor?id={token}"
        )
        await ws.send_bytes(
            json.dumps({"protocol": "blazorpack", "version": 1}).encode()
            + bytes([RECORD_SEPARATOR])
        )
        descriptors = json.dumps(
            [{"type": m["type"], "descriptor": m["descriptor"]} for m in markers]
        )
        await ws.send_bytes(
            _frame(
                msgpack.packb(
                    [
                        MSG_INVOCATION,
                        {},
                        "0",
                        "StartCircuit",
                        [BASE_URL + "/", BASE_URL + path, descriptors, None],
                        [],
                    ],
                    use_bin_type=True,
                )
            )
        )
        return ws

    async def _dispatch_event(
        self,
        ws,
        handler_id: int,
        event_name: str,
        event_args: dict,
        field_info: dict | None = None,
    ) -> None:
        """Send a browser event to the circuit (BeginInvokeDotNetFromJS).

        ``field_info`` mirrors the browser's ``eventFieldInfo`` and is REQUIRED
        for ``@bind`` inputs: Blazor reads the bound value from
        ``eventFieldInfo.fieldValue`` (with the owning ``componentId``), not from
        ``event_args``. Passing ``None`` works for plain events (clicks, submit)
        but will NOT commit an input's value.
        """
        self._call_id += 1
        descriptor = {
            "eventHandlerId": handler_id,
            "eventName": event_name,
            "eventFieldInfo": field_info,
        }
        args_json = json.dumps([descriptor, event_args])
        await ws.send_bytes(
            _frame(
                msgpack.packb(
                    [
                        MSG_INVOCATION,
                        {},
                        None,
                        "BeginInvokeDotNetFromJS",
                        [str(self._call_id), None, "DispatchEventAsync", 1, args_json],
                        [],
                    ],
                    use_bin_type=True,
                )
            )
        )

    async def _ack(self, ws, batch_id: int) -> None:
        await ws.send_bytes(
            _frame(
                msgpack.packb(
                    [MSG_INVOCATION, {}, None, "OnRenderCompleted", [batch_id, None], []],
                    use_bin_type=True,
                )
            )
        )

    async def _read(self, ws, timeout: float, on_batch=None, on_invoke=None) -> None:
        """Pump incoming frames for up to ``timeout`` seconds.

        ``on_batch(RenderBatch)`` and ``on_invoke(target, args)`` callbacks may
        raise ``_Stop`` to end the loop early.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=deadline - loop.time())
            except asyncio.TimeoutError:
                return
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                return
            data = msg.data if isinstance(msg.data, (bytes, bytearray)) else bytes(msg.data, "utf-8")
            if not self._handshake_done:
                sep = data.find(bytes([RECORD_SEPARATOR]))
                if sep != -1:
                    self._handshake_done = True
                    data = data[sep + 1 :]
                if not data:
                    continue
            try:
                for raw in _iter_messages(data):
                    await self._handle(ws, raw, on_batch, on_invoke)
            except _Stop:
                return

    async def _handle(self, ws, raw: bytes, on_batch, on_invoke) -> None:
        try:
            dec = msgpack.unpackb(raw, raw=False, strict_map_key=False)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(dec, list) or not dec or dec[0] != MSG_INVOCATION:
            return
        target = dec[3] if len(dec) > 3 else None
        args = dec[4] if len(dec) > 4 else []
        if target == "JS.RenderBatch":
            batch_id = None
            batch_bytes = None
            for a in args:
                if isinstance(a, (bytes, bytearray)):
                    batch_bytes = bytes(a)
                elif isinstance(a, int):
                    batch_id = a
            if batch_id is not None:
                await self._ack(ws, batch_id)
            if batch_bytes is not None and on_batch is not None:
                on_batch(RenderBatch(batch_bytes))
        elif on_invoke is not None:
            on_invoke(target, args)

    # ----- public API ------------------------------------------------------ #
    async def login(self) -> None:
        assert self._session is not None
        ws = await self._negotiate_ws(LOGIN_PATH)
        try:
            handlers: dict | None = None

            def capture(batch: RenderBatch):
                nonlocal handlers
                found = batch.find_login_handlers()
                if found:
                    handlers = found
                    raise _Stop

            await self._read(ws, timeout=12.0, on_batch=capture)
            if not handlers:
                raise WarmtestadAuthError(
                    "Could not locate the login form in the render batch "
                    "(portal layout may have changed). Run scripts/probe.py --dump."
                )

            # Drive the form like the browser does. Crucially, @bind inputs
            # commit their value through eventFieldInfo.fieldValue (with the
            # owning componentId), NOT through the event args -- so we must send
            # eventFieldInfo. A short pause lets each input's re-render settle.
            await self._dispatch_event(
                ws,
                handlers["email"],
                "input",
                {"value": self._email},
                field_info={
                    "componentId": handlers.get("email_component"),
                    "fieldValue": self._email,
                },
            )
            await asyncio.sleep(0.5)
            await self._dispatch_event(
                ws,
                handlers["password"],
                "input",
                {"value": self._password},
                field_info={
                    "componentId": handlers.get("password_component"),
                    "fieldValue": self._password,
                },
            )
            await asyncio.sleep(0.5)
            await self._dispatch_event(ws, handlers["submit"], "submit", {})

            # Watch the response. Bad credentials render an inline error message
            # ("...email or password was wrong"); success navigates the browser
            # to /login?key=<guid> (a plain HTTP endpoint that sets the auth
            # cookie) or on to /overview.
            redirect_url: str | None = None
            login_failed = False

            def on_batch(batch: RenderBatch):
                nonlocal login_failed
                if any(m in batch.data.lower() for m in _LOGIN_ERROR_MARKERS):
                    login_failed = True
                    raise _Stop

            def on_invoke(target: str, args: list):
                nonlocal redirect_url
                blob = json.dumps(args)
                m = re.search(r"/login\?key=[0-9a-fA-F-]+", blob)
                if not m:
                    m = re.search(r"https?://[^\"\\]*/login\?key=[0-9a-fA-F-]+", blob)
                if m:
                    redirect_url = m.group(0)
                    raise _Stop

            await self._read(ws, timeout=15.0, on_batch=on_batch, on_invoke=on_invoke)

            if login_failed:
                raise WarmtestadAuthError("Login rejected (check email/password).")
            if redirect_url:
                path = redirect_url[redirect_url.find("/login?key=") :]
                async with self._session.get(BASE_URL + path) as resp:
                    await resp.read()
            self._authenticated = True
        finally:
            await ws.close()

    async def async_get_consumption_gj(self) -> float | None:
        if not self._authenticated:
            await self.login()
        ws = await self._negotiate_ws(CONSUMPTION_PATH)
        try:
            best: list[float] = []

            def on_batch(batch: RenderBatch):
                value = batch.consumption_gj()
                if value is not None:
                    best.append(value)

            await self._read(ws, timeout=15.0, on_batch=on_batch)
            return best[-1] if best else None
        finally:
            await ws.close()


class _Stop(Exception):
    """Internal signal to stop the receive loop early."""


def _to_float(raw: bytes | str) -> float | None:
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None
