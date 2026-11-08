"""SimpleBrain device sync: keep one vault the same on several devices, with no account and no server.

Devices find each other by public key through iroh (peer-to-peer; its public relays only forward
encrypted traffic). A device is added to a vault by entering its pairing code on the other device.
Both devices must be online at the same time; a device that is off just catches up later.

Rules (see plan()): compare each note's content hash with the hash both sides had at the last
successful sync. One side changed: take it. Both changed: keep both (the other copy is saved as a
"conflict" note). One side deleted: delete only if the other side left it alone. Inbox.md and
Calendar.md are line lists edited everywhere, so those are merged line by line instead.

No UI imports. The pure logic is testable without a network; `python simplebrain_sync.py` runs
that plus a two-device sync over localhost (no internet needed).
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import struct
import tempfile
import threading
import time
from datetime import date

import simplebrain_core as core
import simplebrain_today as today_note
import simplebrain_recommend as reco

ALPN = b"simplebrain/sync/1"
MAX_FRAME = 64 * 1024 * 1024
MAX_NOTE = 5 * 1024 * 1024  # a note bigger than this is skipped, not synced
MAX_NOTES = 20000
LINE_MERGE = (core.INBOX_FILE, core.CALENDAR_FILE)
STATE_NAME = "simplebrain-sync.json"  # per device: its identity key and who it trusts. Never in the vault.
BASE_NAME = ".sync-base.json"  # per vault: what each peer and this device agreed on last time
INTERVAL = 45  # seconds between background syncs; a save also triggers one shortly after
CONNECT_TIMEOUT = 12
STEP_TIMEOUT = 60


# ---------- identity, trust and the pairing code ----------

def state_path():
    return os.path.join(core.user_config_dir(), STATE_NAME)


def _write_private(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, 0o600)  # holds this device's secret key and pairing token
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_state(path=None):
    """{'key': hex secret key, 'token': hex pairing secret, 'peers': [hex endpoint ids]}; created on first use."""
    path = path or state_path()
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        if len(bytes.fromhex(s["key"])) == 32 and len(bytes.fromhex(s["token"])) == 16 and isinstance(s["peers"], list):
            return s
    except (OSError, ValueError, KeyError, TypeError):
        pass
    s = {"key": secrets.token_hex(32), "token": secrets.token_hex(16), "peers": []}
    save_state(s, path)
    return s


def paired_devices(path=None):
    """Ids of the devices paired so far, without creating any state (an app that never uses sync
    must not even write a key file)."""
    try:
        with open(path or state_path(), encoding="utf-8") as f:
            return [p for p in json.load(f).get("peers", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def save_state(state, path=None):
    _write_private(path or state_path(), json.dumps(state, indent=1))


def endpoint_id(state):
    import iroh
    return str(iroh.SecretKey.from_bytes(bytes.fromhex(state["key"])).public())


def make_code(endpoint_id_hex, token_hex):
    """Pairing code: this device's id + a secret, with a 2-byte check so a typo is caught on entry."""
    raw = bytes.fromhex(endpoint_id_hex) + bytes.fromhex(token_hex)
    raw += hashlib.sha256(raw).digest()[:2]
    text = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def parse_code(code):
    """-> (endpoint id hex, token hex); ValueError says what's wrong in words the user can act on."""
    text = re.sub(r"[\s-]", "", code or "").upper()
    try:
        raw = base64.b32decode(text + "=" * (-len(text) % 8))
    except ValueError:
        raise ValueError("That isn't a pairing code. Copy it again from the other device.") from None
    if len(raw) != 50 or hashlib.sha256(raw[:48]).digest()[:2] != raw[48:]:
        raise ValueError("That code looks mistyped or cut short. Copy it again from the other device.")
    return raw[:32].hex(), raw[32:48].hex()


# ---------- what is synced ----------

def h(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_name(name):
    """A note name that came over the wire: a plain top-level .md file, never a path or a dotfile."""
    return (isinstance(name, str) and name.endswith(".md") and not name.startswith(".")
            and core.is_safe_note_title(name[:-3]) and len(name) < 200)


PRISTINE = {"Home.md": [h(g) for g in (core.HOME_GUIDE, *core.OLD_HOME_GUIDES)]}  # the starter note a new vault gets; never an edit worth a conflict


class DiskVault:
    """The vault as sync sees it. The app subclasses this to run the file work on its UI thread."""

    def __init__(self, vault):
        self.vault = vault

    def snapshot(self):
        """{name: text} of every note that is synced. Generated notes are rebuilt on each device
        from its own inputs, so syncing them would only make conflicts."""
        out, self.too_big = {}, []
        for name in core.list_notes(self.vault):
            if name == reco.OUT_NAME or not valid_name(name) or len(out) >= MAX_NOTES:
                continue
            try:
                text = core.read_note(name, self.vault)
            except (OSError, UnicodeDecodeError):
                continue
            if core.ANSWERS_MARK not in text and today_note.MARK not in text:  # Today is rebuilt per device
                if len(text) <= MAX_NOTE:
                    out[name] = text
                else:
                    self.too_big.append(name)  # shown in the status, so a skipped note isn't mistaken for a synced one
        return out

    def apply(self, writes, deletes, expect):
        """Write/delete notes, but only where the file is still what the sync planned from
        (expect: name -> hash or None for 'must not exist'). Returns the names skipped."""
        skipped = []
        for name in list(writes) + list(deletes):
            path = os.path.join(self.vault, name)
            try:
                now = h(core.read_note(name, self.vault)) if os.path.exists(path) else None
            except (OSError, UnicodeDecodeError):
                now = "unreadable"
            if now != expect.get(name):
                skipped.append(name)  # changed since the snapshot: leave it, the next round re-plans
            elif name in writes:
                fd, tmp = tempfile.mkstemp(dir=self.vault, prefix=".sync-tmp-")
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(writes[name])
                os.replace(tmp, path)
            elif now is not None:
                core.delete_note(name, self.vault)  # to .trash, so a wrong delete is recoverable
        return skipped

    def load_base(self, peer):
        try:
            with open(os.path.join(self.vault, BASE_NAME), encoding="utf-8") as f:
                b = json.load(f).get(peer, {})
            return {"hashes": dict(b.get("hashes", {})), "texts": dict(b.get("texts", {}))}
        except (OSError, ValueError, AttributeError):
            return {"hashes": {}, "texts": {}}

    def save_base(self, peer, base):
        path = os.path.join(self.vault, BASE_NAME)
        try:
            with open(path, encoding="utf-8") as f:
                every = json.load(f)
        except (OSError, ValueError):
            every = {}
        every[peer] = base
        _write_private(path, json.dumps(every))


# ---------- the decision rule (pure) ----------

def plan(local, remote, base):
    """{name: action} from {name: hash} for each side and the hashes agreed last time.
    pull: take the remote version (or delete, if it has none); push: send ours (or tell it to
    delete); conflict / merge: both changed it. A delete never beats an edit."""
    out = {}
    for n in set(local) | set(remote):
        L, R, B = local.get(n), remote.get(n), base.get(n)
        if L == R:
            continue
        if L == B:
            out[n] = "pull"
        elif R == B:
            out[n] = "push"
        elif L is None or R is None:
            out[n] = "pull" if L is None else "push"
        else:
            out[n] = "merge" if n in LINE_MERGE else "conflict"
    return out


def merge_lines(base, a, b):
    """Three-way merge of two line lists: lines either side deleted stay deleted, lines either
    side added are kept, order follows `a`. Blank lines are layout, not content."""
    def lines(t):
        ls = t.split("\n")
        return ls[:-1] if ls and ls[-1] == "" else ls
    al, bl, old = lines(a), lines(b), set(lines(base)) - {""}
    gone = (old - set(al)) | (old - set(bl))
    out = [x for x in al if x == "" or x not in gone]
    have = set(out)
    for x in bl:
        if x != "" and x not in have and x not in old:
            out.append(x)
            have.add(x)
    return "\n".join(out) + "\n" if out else ""


def conflict_name(name, peer, taken, today=None):
    stem = name[:-3]
    stamp = (today or date.today()).isoformat()
    cand, i = f"{stem} (conflict {peer[:6]} {stamp}).md", 2
    while cand in taken:
        cand = f"{stem} (conflict {peer[:6]} {stamp} {i}).md"
        i += 1
    return cand


def resolve(local_texts, remote_hashes, fetched, base, peer, today=None):
    """Everything a sync round does, as data. local_texts {name: text}; remote_hashes {name: hash};
    fetched {name: remote text} for the names that plan() asked for; base as load_base().
    Returns dict: want (names to fetch), then once fetched: lw/ld (local writes/deletes), rw/rd (remote
    writes/deletes), agreed {name: hash} for every name both sides now hold the same, and counts."""
    lh = {n: h(t) for n, t in local_texts.items()}
    bh = dict(base["hashes"])
    for n, phs in PRISTINE.items():  # a brand-new vault's starter note (any version of it) is not an edit; the oldest match is the base, so a newer one wins
        if n not in bh and n in lh and n in remote_hashes:
            bh[n] = next((ph for ph in reversed(phs) if ph in (lh[n], remote_hashes[n])), None) or bh.get(n)
            if bh[n] is None:
                del bh[n]
    actions = plan(lh, remote_hashes, bh)
    want = sorted(n for n, a in actions.items() if a in ("pull", "conflict", "merge") and n in remote_hashes)
    out = {"actions": actions, "want": want, "lw": {}, "ld": [], "rw": {}, "rd": [], "agreed": {}, "texts": {},
           "expect_local": {}, "expect_remote": {}, "counts": {"pulled": 0, "pushed": 0, "conflicts": 0, "merged": 0}}
    if fetched is None:
        return out
    taken = set(lh) | set(remote_hashes)
    for n in set(lh) | set(remote_hashes):
        a = actions.get(n)
        if a is None:
            if n in lh:
                out["agreed"][n] = lh[n]
            continue
        if a != "push" and n in remote_hashes and n not in fetched:
            continue  # the other side has it but it didn't arrive: do nothing this round, never delete
        out["expect_local"][n], out["expect_remote"][n] = lh.get(n), remote_hashes.get(n)
        if a == "pull":
            if n in remote_hashes:
                out["lw"][n] = fetched[n]
                out["agreed"][n] = remote_hashes[n]
            else:
                out["ld"].append(n)
                out["agreed"][n] = None
            out["counts"]["pulled"] += 1
        elif a == "push":
            if n in lh:
                out["rw"][n] = local_texts[n]
                out["agreed"][n] = lh[n]
            else:
                out["rd"].append(n)
                out["agreed"][n] = None
            out["counts"]["pushed"] += 1
        elif a == "merge":
            merged = merge_lines(base["texts"].get(n, ""), local_texts[n], fetched[n])
            out["lw"][n] = out["rw"][n] = merged
            out["agreed"][n] = h(merged)
            out["counts"]["merged"] += 1
        else:  # conflict: ours stays, theirs is kept as its own note on both devices
            copy = conflict_name(n, peer, taken, today)
            taken.add(copy)
            out["lw"][copy] = out["rw"][copy] = fetched[n]
            out["expect_local"][copy] = out["expect_remote"][copy] = None
            out["rw"][n] = local_texts[n]
            out["agreed"][n], out["agreed"][copy] = lh[n], h(fetched[n])
            out["counts"]["conflicts"] += 1
    for n in LINE_MERGE:  # the text of the agreed list notes, as the base for the next merge
        for src in (out["lw"], out["rw"], local_texts):
            if n in src and out["agreed"].get(n) == h(src[n]):
                out["texts"][n] = src[n]
                break
    return out


def new_base(old, agreed, texts, skipped):
    """Base after a round. A name either side skipped keeps its old entry, so it is re-planned next time."""
    hashes, kept = dict(old["hashes"]), dict(old["texts"])
    for n, hv in agreed.items():
        if n in skipped:
            continue
        if hv is None:
            hashes.pop(n, None)
            kept.pop(n, None)
        else:
            hashes[n] = hv
    for n, t in texts.items():
        if n not in skipped:
            kept[n] = t
    return {"hashes": hashes, "texts": kept}


# ---------- the wire (iroh streams carrying length-prefixed JSON) ----------

async def _send(stream, obj):
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    await stream.write_all(struct.pack(">I", len(data)) + data)


async def _recv(stream):
    (n,) = struct.unpack(">I", await stream.read_exact(4))
    if n > MAX_FRAME:
        raise ValueError("message too large")
    return json.loads(await stream.read_exact(n))


def _clean_manifest(m):
    if not isinstance(m, dict):
        raise ValueError("bad manifest")
    return {n: v for n, v in m.items() if valid_name(n) and isinstance(v, str) and len(v) == 64}


def _clean_texts(d):
    return {n: t for n, t in d.items() if valid_name(n) and (t is None or (isinstance(t, str) and len(t) <= MAX_NOTE))}


class Context:
    """What one device needs to take part in syncs: its vault, trust list and a lock so only one
    sync runs at a time (two devices that start at once must not interleave)."""

    def __init__(self, vault, state, state_file=None, on_change=None):
        self.vault, self.state, self.state_file = vault, state, state_file
        self.on_change = on_change or (lambda names: None)
        self.lock = asyncio.Lock()

    def trust(self, peer):
        if peer not in self.state["peers"]:
            self.state["peers"].append(peer)
            save_state(self.state, self.state_file)


async def serve_connection(ctx, conn):
    """The device that was dialled: authenticate by key, then answer. Never raises to the caller."""
    peer = str(conn.remote_id())
    bi = await conn.accept_bi()
    rx, tx = bi.recv(), bi.send()
    try:
        first = await asyncio.wait_for(_recv(rx), STEP_TIMEOUT)
        if first.get("t") == "pair":
            ok = isinstance(first.get("token"), str) and hmac.compare_digest(first["token"], ctx.state["token"])
            if ok:
                ctx.trust(peer)
            await _send(tx, {"t": "paired"} if ok else {"t": "error", "why": "wrong code"})
        elif first.get("t") == "sync" and peer in ctx.state["peers"]:
            try:
                await asyncio.wait_for(ctx.lock.acquire(), 8)
            except asyncio.TimeoutError:
                await _send(tx, {"t": "error", "why": "busy"})
                return
            try:
                await _serve_sync(ctx, peer, first, rx, tx)
            finally:
                ctx.lock.release()
        else:
            await _send(tx, {"t": "error", "why": "not paired"})
        await tx.finish()
        await asyncio.wait_for(conn.closed(), 10)
    except Exception:
        pass  # a dropped or malformed session must not take the listener down; the next round retries


async def _serve_sync(ctx, peer, first, rx, tx):
    vault = ctx.vault()
    mine = await asyncio.get_running_loop().run_in_executor(None, vault.snapshot)
    await _send(tx, {"t": "manifest", "manifest": {n: h(t) for n, t in mine.items()}})
    req = await asyncio.wait_for(_recv(rx), STEP_TIMEOUT)
    names = [n for n in req.get("names", []) if n in mine]
    await _send(tx, {"t": "files", "files": {n: mine[n] for n in names}})
    done = await asyncio.wait_for(_recv(rx), STEP_TIMEOUT)
    give = _clean_texts(done.get("give", {}))
    writes = {n: t for n, t in give.items() if t is not None}
    deletes = [n for n, t in give.items() if t is None]
    expect = {n: v for n, v in done.get("expect", {}).items() if n in give}
    skipped = await asyncio.get_running_loop().run_in_executor(None, vault.apply, writes, deletes, expect)
    base = vault.load_base(peer)
    agreed = {n: v for n, v in done.get("agreed", {}).items() if valid_name(n) and (v is None or isinstance(v, str))}
    texts = {n: t for n, t in done.get("texts", {}).items() if n in LINE_MERGE and isinstance(t, str)}
    vault.save_base(peer, new_base(base, agreed, texts, set(skipped)))
    await _send(tx, {"t": "done", "skipped": skipped})
    changed = [n for n in list(writes) + deletes if n not in skipped]
    if changed:
        ctx.on_change(changed)


async def sync_with_peer(ctx, ep, peer, addr):
    """Dial a paired device and bring both sides level. Returns the counts dict, or raises."""
    async with ctx.lock:
        vault = ctx.vault()
        loop = asyncio.get_running_loop()
        local = await loop.run_in_executor(None, vault.snapshot)
        conn = await asyncio.wait_for(ep.connect(addr, ALPN), CONNECT_TIMEOUT)
        try:
            bi = await conn.open_bi()
            rx, tx = bi.recv(), bi.send()
            await _send(tx, {"t": "sync", "v": 1})
            reply = await asyncio.wait_for(_recv(rx), STEP_TIMEOUT)
            if reply.get("t") != "manifest":
                raise ConnectionError({"busy": "the other device is busy", "not paired": "the other device doesn't "
                                       "know this one: pair them again"}.get(reply.get("why"), "sync refused"))
            remote = _clean_manifest(reply["manifest"])
            base = vault.load_base(peer)
            first = resolve(local, remote, None, base, peer)
            await _send(tx, {"t": "fetch", "names": first["want"]})
            files = _clean_texts((await asyncio.wait_for(_recv(rx), STEP_TIMEOUT)).get("files", {}))
            fetched = {n: t for n, t in files.items() if n in first["want"] and t is not None}
            r = resolve(local, remote, fetched, base, peer)
            skipped_local = await loop.run_in_executor(None, vault.apply, r["lw"], r["ld"], r["expect_local"])
            await _send(tx, {"t": "apply", "give": {**r["rw"], **{n: None for n in r["rd"]}},
                             "expect": r["expect_remote"], "agreed": r["agreed"], "texts": r["texts"]})
            done = await asyncio.wait_for(_recv(rx), STEP_TIMEOUT)
            skipped = set(skipped_local) | set(done.get("skipped", []))
            vault.save_base(peer, new_base(base, r["agreed"], r["texts"], skipped))
            await tx.finish()
            changed = [n for n in list(r["lw"]) + r["ld"] if n not in skipped_local]
            if changed:
                ctx.on_change(changed)
            return {**r["counts"], "changed": changed, "skipped": len(skipped)}
        finally:
            conn.close(0, b"done")


async def pair_with(ep, code, addr=None):
    """Enter the code shown on another device: dial it, prove we have the code, and learn its id.
    Returns the other device's id on success. (addr: tests dial a known address.)"""
    peer, token = parse_code(code)
    if addr is None:
        import iroh
        addr = iroh.EndpointAddr(iroh.EndpointId.from_string(peer), None, [])
    conn = await asyncio.wait_for(ep.connect(addr, ALPN), CONNECT_TIMEOUT * 2)
    try:
        bi = await conn.open_bi()
        await _send(bi.send(), {"t": "pair", "token": token})
        await bi.send().finish()
        reply = await asyncio.wait_for(_recv(bi.recv()), STEP_TIMEOUT)
    finally:
        conn.close(0, b"done")
    if reply.get("t") != "paired":
        raise ConnectionError("The other device didn't accept that code. Show a fresh one there and try again.")
    return peer


# ---------- the background service the app runs ----------

class SyncService:
    """Runs the listener and the periodic sync on its own thread. Thread-safe entry points:
    code(), new_code(), pair(code), sync_now(), poke(), stop()."""

    def __init__(self, vault, on_status=None, on_change=None, state_file=None, preset=None, resolver=None):
        self.vault_obj = vault
        self.state_file = state_file
        self.state = load_state(state_file)
        self.on_status = on_status or (lambda s: None)
        self.on_change = on_change or (lambda names: None)
        self.preset, self.resolver = preset, resolver
        self.loop = self.ep = self.ctx = None
        self.ready, self.stopping = threading.Event(), threading.Event()
        self.last = {"state": "starting", "message": "Starting…", "time": None}
        self._poked = None
        self.error = None

    # -- called from any thread --
    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True, name="simplebrain-sync").start()

    def code(self):
        return make_code(endpoint_id(self.state), self.state["token"])

    def new_code(self):
        """Replace the secret: a code shown or copied earlier stops working. Devices already paired stay paired."""
        self.state["token"] = secrets.token_hex(16)
        save_state(self.state, self.state_file)
        return self.code()

    def peers(self):
        return list(self.state["peers"])

    def pair(self, code, timeout=60):
        return self._call(self._pair(code), timeout)

    def sync_now(self):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._sync_all(), self.loop)

    def poke(self):
        """A note was saved: sync soon (debounced), so the other device sees it without waiting for the timer."""
        if self.loop and self._poked is not None:
            self.loop.call_soon_threadsafe(self._poked.set)

    def stop(self):
        self.stopping.set()
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: self._poked and self._poked.set())

    def _call(self, coro, timeout):
        if not self.ready.wait(timeout):
            raise ConnectionError("Sync didn't start. Check your internet connection.")
        if self.error:
            raise ConnectionError(self.error)
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # -- on the service thread --
    def _status(self, state, message):
        self.last = {"state": state, "message": message, "time": time.time()}
        self.on_status(self.last)

    def _addr(self, peer):
        import iroh
        return self.resolver(peer) if self.resolver else iroh.EndpointAddr(iroh.EndpointId.from_string(peer), None, [])

    async def _main(self):
        try:
            import iroh
            self.loop = asyncio.get_running_loop()
            self._poked = asyncio.Event()
            self.ctx = Context(lambda: self.vault_obj, self.state, self.state_file, self.on_change)
            self.ep = await iroh.Endpoint.bind(iroh.EndpointOptions(
                preset=self.preset or iroh.preset_n0(), secret_key=bytes.fromhex(self.state["key"]), alpns=[ALPN]))
        except Exception as e:  # iroh missing or no network stack: the app carries on without sync
            self.error = f"Sync is unavailable ({type(e).__name__}: {e})"
            self._status("error", self.error)
            self.ready.set()
            return
        self.ready.set()
        self._status("starting", "Connecting…")
        accept = asyncio.create_task(self._accept_loop())
        try:
            while not self.stopping.is_set():
                if self.state["peers"]:
                    await self._sync_all()
                else:
                    self._status("idle", "No other device paired yet")
                try:
                    await asyncio.wait_for(self._poked.wait(), INTERVAL + random.uniform(0, 10))
                    await asyncio.sleep(3)  # let a burst of saves settle into one sync
                except asyncio.TimeoutError:
                    pass
                self._poked.clear()
        finally:
            accept.cancel()
            await self.ep.close()

    async def _accept_loop(self):
        while True:
            incoming = await self.ep.accept_next()
            if incoming is None:
                return
            asyncio.create_task(self._accept_one(incoming))

    async def _accept_one(self, incoming):
        try:
            conn = await (await incoming.accept()).connect()
            if bytes(conn.alpn()) == ALPN:
                await serve_connection(self.ctx, conn)
        except Exception:
            pass

    async def _pair(self, code):
        peer = parse_code(code)[0]
        await pair_with(self.ep, code, self._addr(peer))
        self.ctx.trust(peer)
        asyncio.create_task(self._sync_all())
        return peer

    async def _sync_all(self):
        for peer in self.peers():
            try:
                r = await sync_with_peer(self.ctx, self.ep, peer, self._addr(peer))
                bits = [f"{r[k]} {k}" for k in ("pulled", "pushed", "merged", "conflicts") if r[k]]
                big = getattr(self.vault_obj, "too_big", [])
                self._status("ok", "Up to date" + (f" ({', '.join(bits)})" if bits else "")
                             + (f"; not synced, over {MAX_NOTE // (1024 * 1024)} MB: {', '.join(big)}" if big else ""))
            except ConnectionError as e:  # the other device answered and said no (busy, not paired)
                self._status("problem", str(e))
            except Exception:  # timeout, offline, relay unreachable: the normal state of a device that is off
                self._status("offline", "Other device not reachable right now")


# ---------- self-test ----------

def available():
    """iroh has no build for some systems (Intel Macs): there SimpleBrain runs without device sync."""
    try:
        import iroh  # noqa: F401
        return True
    except ImportError:
        return False


def selftest():
    if not available():
        print("sync selftest OK (skipped: no iroh build for this system, so sync is off here)")
        return
    A, B, C = h("a"), h("b"), h("c")
    # the decision rule
    assert plan({"n": A}, {"n": A}, {"n": A}) == {}
    assert plan({"n": A}, {"n": B}, {"n": A}) == {"n": "pull"}
    assert plan({"n": B}, {"n": A}, {"n": A}) == {"n": "push"}
    assert plan({"n": B}, {"n": C}, {"n": A}) == {"n": "conflict"}
    assert plan({"Inbox.md": B}, {"Inbox.md": C}, {"Inbox.md": A}) == {"Inbox.md": "merge"}
    assert plan({}, {"n": A}, {}) == {"n": "pull"} and plan({"n": A}, {}, {}) == {"n": "push"}
    assert plan({}, {"n": A}, {"n": A}) == {"n": "push"}  # deleted here, untouched there: delete there
    assert plan({"n": A}, {}, {"n": A}) == {"n": "pull"}  # deleted there: delete here
    assert plan({}, {"n": B}, {"n": A}) == {"n": "pull"} and plan({"n": B}, {}, {"n": A}) == {"n": "push"}  # edit beats delete
    # line merge: both add, one deletes, nothing is lost or doubled
    assert merge_lines("a\nb\n", "a\nb\nx\n", "a\nb\ny\n") == "a\nb\nx\ny\n"
    assert merge_lines("a\nb\n", "a\n", "a\nb\ny\n") == "a\ny\n"  # a deleted b, b added y
    assert merge_lines("", "x\n", "x\n") == "x\n" and merge_lines("", "", "") == ""
    # pairing code round trip and typo detection
    ident, tok = secrets.token_hex(32), secrets.token_hex(16)
    code = make_code(ident, tok)
    assert parse_code(code) == (ident, tok) and parse_code(code.lower().replace("-", " ")) == (ident, tok)
    bad = code[:-1] + ("A" if code[-1] != "A" else "B")
    for broken in (bad, code[:20], "hello", ""):
        try:
            parse_code(broken)
            raise AssertionError(broken)
        except ValueError:
            pass
    # names from the wire
    assert valid_name("Note.md") and valid_name("My note (conflict ab 2026-10-15).md")
    assert not any(valid_name(x) for x in ("../x.md", "a/b.md", ".config", "x.txt", ".hidden.md", "", None, "a\\b.md"))
    # a full round as data: both edited Note, Inbox merges, new notes cross, pristine Home is not a conflict
    texts = {"Note.md": "mine\n", "Inbox.md": "- one\n- two\n", "OnlyHere.md": "x\n", "Home.md": core.HOME_GUIDE}
    remote = {"Note.md": h("theirs\n"), "Inbox.md": h("- one\n- three\n"), "OnlyThere.md": h("y\n"),
              "Home.md": h("# my home\n")}
    base = {"hashes": {"Note.md": h("old\n"), "Inbox.md": h("- one\n")}, "texts": {"Inbox.md": "- one\n"}}
    first = resolve(texts, remote, None, base, "abcdef123")
    assert first["want"] == ["Home.md", "Inbox.md", "Note.md", "OnlyThere.md"]
    r = resolve(texts, remote, {"Home.md": "# my home\n", "Inbox.md": "- one\n- three\n", "Note.md": "theirs\n",
                                "OnlyThere.md": "y\n"}, base, "abcdef123", today=date(2026, 10, 15))
    assert r["lw"]["Home.md"] == "# my home\n" and r["lw"]["OnlyThere.md"] == "y\n"
    assert r["lw"]["Inbox.md"] == r["rw"]["Inbox.md"] == "- one\n- two\n- three\n"
    assert r["lw"]["Note (conflict abcdef 2026-10-15).md"] == "theirs\n" and r["rw"]["Note.md"] == "mine\n"
    assert r["rw"]["OnlyHere.md"] == "x\n" and r["counts"] == {"pulled": 2, "pushed": 1, "conflicts": 1, "merged": 1}
    nb = new_base(base, r["agreed"], r["texts"], {"OnlyHere.md"})
    assert "OnlyHere.md" not in nb["hashes"] and nb["hashes"]["Note.md"] == h("mine\n")  # a skipped name is re-planned
    assert nb["texts"]["Inbox.md"] == "- one\n- two\n- three\n"
    # a starter Home from an older version is still "unedited": the other device's newer Home replaces it quietly
    old_home = {"Home.md": core.OLD_HOME_GUIDES[0]}
    r = resolve(old_home, {"Home.md": h(core.HOME_GUIDE)}, {"Home.md": core.HOME_GUIDE}, {"hashes": {}, "texts": {}}, "abcdef123")
    assert r["actions"]["Home.md"] == "pull" and r["lw"]["Home.md"] == core.HOME_GUIDE
    _selftest_disk()
    try:
        import iroh  # noqa: F401
    except ImportError:
        print("sync selftest OK (iroh not installed: network round skipped)")
        return
    asyncio.run(_selftest_network())
    _selftest_service()
    print("sync selftest OK")


def _selftest_disk():
    with tempfile.TemporaryDirectory() as d:
        v = DiskVault(d)
        core.write_note("A.md", "one\n", d)
        core.write_note("Recommendations.md", "generated\n", d)
        core.write_note("X - Answers.md", core.ANSWERS_MARK + "\n", d)
        open(os.path.join(d, ".config"), "w").write("ICS_URL=secret\n")
        assert set(v.snapshot()) == {"A.md"}  # generated notes and the calendar link never leave
        assert v.too_big == []
        core.write_note("Huge.md", "x" * (MAX_NOTE + 1), d)
        assert set(v.snapshot()) == {"A.md"} and v.too_big == ["Huge.md"]  # skipped, and reported
        os.remove(os.path.join(d, "Huge.md"))
        assert v.apply({"A.md": "two\n"}, [], {"A.md": h("stale\n")}) == ["A.md"]  # changed since the plan: skipped
        assert core.read_note("A.md", d) == "one\n"
        assert v.apply({"A.md": "two\n", "B.md": "new\n"}, [], {"A.md": h("one\n"), "B.md": None}) == []
        assert core.read_note("A.md", d) == "two\n" and core.read_note("B.md", d) == "new\n"
        assert v.apply({}, ["A.md"], {"A.md": h("two\n")}) == [] and not os.path.exists(os.path.join(d, "A.md"))
        assert os.path.exists(os.path.join(d, ".trash", "A.md"))  # deletes are recoverable
        assert not [f for f in os.listdir(d) if f.startswith(".sync-tmp-")]
        v.save_base("peer1", {"hashes": {"B.md": "x" * 64}, "texts": {}})
        assert v.load_base("peer1")["hashes"] == {"B.md": "x" * 64} and v.load_base("nobody") == {"hashes": {}, "texts": {}}


def _selftest_service():
    """The same two devices, but through SyncService threads as the app runs them: pairing by code,
    a save poking the other device, status callbacks. Localhost only."""
    import iroh
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:  # a service thread may still be writing as it closes (macOS)
        vaults = {k: os.path.join(root, k) for k in "ab"}
        for v in vaults.values():
            core.ensure_vault(v)
        svcs, seen = {}, {"a": [], "b": []}
        ports = {}

        def resolver(peer):
            other = next(k for k, sv in svcs.items() if endpoint_id(sv.state) == peer)
            return iroh.EndpointAddr(iroh.EndpointId.from_string(peer), None,
                                     [f"127.0.0.1:{x.rsplit(':', 1)[1]}" for x in svcs[other].ep.bound_sockets()])

        for k in "ab":
            svcs[k] = SyncService(DiskVault(vaults[k]), on_status=seen[k].append,
                                  state_file=os.path.join(root, f"{k}.json"), preset=iroh.preset_minimal(), resolver=resolver)
            svcs[k].start()
        try:
            for sv in svcs.values():
                assert sv.ready.wait(20) and not sv.error, sv.error
            assert any(x["state"] == "idle" for x in seen["a"]) or seen["a"]  # reported something while unpaired
            try:
                svcs["a"].pair("not a code")
                raise AssertionError("bad code accepted")
            except ValueError:
                pass
            assert svcs["a"].pair(svcs["b"].code(), timeout=30) == endpoint_id(svcs["b"].state)
            assert svcs["a"].peers() == [endpoint_id(svcs["b"].state)] and svcs["b"].peers() == [endpoint_id(svcs["a"].state)]
            assert paired_devices(os.path.join(root, "a.json")) == svcs["a"].peers()
            # a save on A is poked across without waiting for the timer
            core.write_note("Trip.md", "# Trip\npacked\n", vaults["a"])
            svcs["a"].poke()
            deadline = time.time() + 20
            while time.time() < deadline and not os.path.exists(os.path.join(vaults["b"], "Trip.md")):
                time.sleep(0.2)
            assert core.read_note("Trip.md", vaults["b"]) == "# Trip\npacked\n"
            assert any(x["state"] == "ok" for x in seen["a"])
            # a replaced code can't be used to add another device
            old = svcs["b"].code()
            assert svcs["b"].new_code() != old
        finally:
            for sv in svcs.values():
                sv.stop()
        assert paired_devices(os.path.join(root, "a.json"))


async def _selftest_network():
    """Two devices syncing through real iroh endpoints bound to localhost, relay off: no internet needed."""
    import iroh
    with tempfile.TemporaryDirectory() as root:
        va, vb = os.path.join(root, "a"), os.path.join(root, "b")
        os.makedirs(va), os.makedirs(vb)
        sa, sb = load_state(os.path.join(root, "sa.json")), load_state(os.path.join(root, "sb.json"))
        ctx_a = Context(lambda: DiskVault(va), sa, os.path.join(root, "sa.json"))
        got_b = []
        ctx_b = Context(lambda: DiskVault(vb), sb, os.path.join(root, "sb.json"), on_change=got_b.extend)
        eps = []
        for st in (sa, sb):
            eps.append(await iroh.Endpoint.bind(iroh.EndpointOptions(
                preset=iroh.preset_minimal(), secret_key=bytes.fromhex(st["key"]), alpns=[ALPN],
                bind_addr="127.0.0.1:0")))
        ep_a, ep_b = eps

        def addr_of(ep):
            return iroh.EndpointAddr(ep.id(), None, [s for s in ep.bound_sockets()])

        async def listen(ctx, ep):
            while True:
                inc = await ep.accept_next()
                if inc is None:
                    return
                conn = await (await inc.accept()).connect()
                await serve_connection(ctx, conn)

        tasks = [asyncio.create_task(listen(ctx_b, ep_b))]
        try:
            id_a, id_b = str(ep_a.id()), str(ep_b.id())
            assert id_a == endpoint_id(sa) and id_b == endpoint_id(sb)
            # an unpaired device is refused
            try:
                await sync_with_peer(ctx_a, ep_a, id_b, addr_of(ep_b))
                raise AssertionError("unpaired sync was accepted")
            except ConnectionError:
                pass
            # pairing needs the right code (the listener only trusts a device that proves it has the secret)
            real = make_code(id_b, sb["token"])
            wrong = make_code(id_b, secrets.token_hex(16))
            try:
                await pair_with(ep_a, wrong, addr_of(ep_b))
                raise AssertionError("wrong code accepted")
            except ConnectionError:
                pass
            assert sb["peers"] == []
            assert await pair_with(ep_a, real, addr_of(ep_b)) == id_b
            assert sb["peers"] == [id_a]
            ctx_a.trust(id_b)
            # first sync: A has notes, B is a fresh vault with only the starter notes
            core.ensure_vault(vb)
            with open(os.path.join(va, ".config"), "w") as f:
                f.write("ICS_URL=https://example.invalid/SECRET-LINK\n")
            core.write_note("Plan.md", "# Plan\nfrom A\n", va)
            core.write_note("Inbox.md", "- milk\n", va)
            r = await sync_with_peer(ctx_a, ep_a, id_b, addr_of(ep_b))
            assert core.read_note("Plan.md", vb) == "# Plan\nfrom A\n" and "milk" in core.read_note("Inbox.md", vb)
            assert r["conflicts"] == 0 and "Plan.md" in got_b
            # a second sync with nothing new does nothing
            r = await sync_with_peer(ctx_a, ep_a, id_b, addr_of(ep_b))
            assert r["pulled"] == r["pushed"] == r["conflicts"] == r["merged"] == 0
            # both edit the same note, both add inbox lines: nothing lost
            core.write_note("Plan.md", "# Plan\nfrom A, edited\n", va)
            core.write_note("Plan.md", "# Plan\nfrom B, edited\n", vb)
            with open(os.path.join(va, "Inbox.md"), "a") as f:
                f.write("- eggs\n")
            with open(os.path.join(vb, "Inbox.md"), "a") as f:
                f.write("- bread\n")
            r = await sync_with_peer(ctx_a, ep_a, id_b, addr_of(ep_b))
            assert r["conflicts"] == 1 and r["merged"] == 1
            for v in (va, vb):
                notes = core.list_notes(v)
                assert core.read_note("Plan.md", v) == "# Plan\nfrom A, edited\n"
                copies = [n for n in notes if n.startswith("Plan (conflict")]
                assert len(copies) == 1 and core.read_note(copies[0], v) == "# Plan\nfrom B, edited\n"
                assert set(core.read_note("Inbox.md", v).split()) >= {"milk", "eggs", "bread"}
            assert core.read_note("Inbox.md", va) == core.read_note("Inbox.md", vb)
            # a delete on one side reaches the other, into the trash
            core.delete_note("Plan.md", vb)
            await sync_with_peer(ctx_a, ep_a, id_b, addr_of(ep_b))
            assert not os.path.exists(os.path.join(va, "Plan.md")) and os.path.exists(os.path.join(va, ".trash", "Plan.md"))
            # the vault's secret calendar link never left device A
            assert "SECRET-LINK" not in open(os.path.join(vb, ".config")).read()
        finally:
            for t in tasks:
                t.cancel()
            for ep in eps:
                await ep.close()


if __name__ == "__main__":
    selftest()
