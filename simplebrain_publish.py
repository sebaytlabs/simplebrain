#!/usr/bin/env python3
"""Publish the notes marked public as pages on your own website: WordPress (REST API, an application password),
Shopify (Admin GraphQL API), or any other site (plain HTML pages written into a folder you upload or sync).
Pure logic plus HTTP calls; the app runs `publish` on a worker thread after saves.

Usage: python3 simplebrain_publish.py [--selftest]
"""
import hashlib
import html
import json
import os
import re
import sys
import base64
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import simplebrain_core as core

API_VERSION = "2025-10"
SHOP_FILE = "shopify.json"  # {"shop": "xxx.myshopify.com", "client_id", "client_secret"} in the per-user config folder: never in the vault
STATE_FILE = ".publish-state.json"  # {note file: {"id", "handle", "hash"}} so a changed note updates its page, not duplicates it
INDEX_FILE = "\0index"  # state key for the generated list-of-notes page
INDEX_TITLE = "Notes"
INDEX_INTRO = ("<p>These are our own notes, written in SimpleBrain and published here the moment we save them. "
               "Most are reading notes, taken with the photoreading method: skim the whole book first, then "
               "write down what you actually want from it. They're raw and they change as we learn more.</p>")
INDEX_HANDLE = "notes"
SITE_FILE = "website.json"  # {"kind": "wordpress" | "shopify" | "folder" | "off", ...}; per-user config folder, never the vault
KINDS = {"wordpress": ("url", "user", "password"), "shopify": ("shop", "client_id", "client_secret"), "folder": ("folder",)}


def _save_private(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")  # born private (0600): the secret is never readable, even briefly
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def site_config():
    """The website notes publish to, or None. A store set up before there was a choice (shopify.json) still counts."""
    d = core.load_settings(os.path.join(core.user_config_dir(), SITE_FILE))
    kind = d.get("kind")
    if kind == "off":
        return None
    if kind in KINDS and all(str(d.get(k) or "").strip() for k in KINDS[kind]):
        return d
    shop = shop_config()
    return {"kind": "shopify", **shop} if shop else None


def save_site_config(cfg):
    """Save the website (values trimmed), or {"kind": "off"}: off also forgets the old Shopify secret."""
    cfg = {k: v.strip() if isinstance(v, str) else v for k, v in cfg.items()}
    if cfg.get("kind") == "wordpress":
        cfg["url"] = site_url(cfg["url"])
    _save_private(os.path.join(core.user_config_dir(), SITE_FILE), cfg)
    if cfg.get("kind") == "off":
        try:
            os.remove(os.path.join(core.user_config_dir(), SHOP_FILE))
        except OSError:
            pass


def site_url(url):
    """'mysite.com/' -> 'https://mysite.com': what people type into a site address box."""
    url = url.strip().rstrip("/")
    return url if re.match(r"(?i)https?://", url) else "https://" + url


def shop_config():
    data = core.load_settings(os.path.join(core.user_config_dir(), SHOP_FILE))
    return data if data.get("shop") and data.get("client_id") and data.get("client_secret") else None


def save_shop_config(shop, client_id, client_secret):
    _save_private(os.path.join(core.user_config_dir(), SHOP_FILE),
                  {"shop": shop.strip(), "client_id": client_id.strip(), "client_secret": client_secret.strip()})


def access_token(cfg, opener=urllib.request.urlopen):
    """Dev Dashboard apps have no permanent token: trade the app's id and secret for a day-long one."""
    req = urllib.request.Request(
        f"https://{cfg['shop']}/admin/oauth/access_token",
        data=json.dumps({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                         "grant_type": "client_credentials"}).encode(),
        headers={"Content-Type": "application/json"})
    with opener(req, timeout=20) as r:
        return json.load(r)["access_token"]


def slug(title):
    s = re.sub(r"[^\w]+", "-", title.lower(), flags=re.UNICODE).strip("-_")
    return s or hashlib.sha1(title.encode()).hexdigest()[:8]


def _inline(s, link_for):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)

    def wiki(m):
        title = html.unescape(m.group(1)).strip()
        url = link_for(title)
        return f'<a href="{html.escape(url)}">{m.group(1)}</a>' if url else m.group(1)  # a private note is plain text, not a dead link
    return core.WIKILINK_RE.sub(wiki, s)


def md_to_html(text, link_for):
    """Small Markdown subset: headings, lists, quotes, code fences, bold/italic/code, links, [[wikilinks]].
    `link_for(title)` gives the page URL of a public note, or None."""
    out, para, lst, fence = [], [], None, None

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>" + "<br>".join(_inline(p, link_for) for p in para) + "</p>")
            para = []
        if lst:
            out.append(f"<{lst[0]}>" + "".join(f"<li>{_inline(i, link_for)}</li>" for i in lst[1]) + f"</{lst[0]}>")
            lst = None

    for line in text.split("\n"):
        if line.startswith("```"):
            if fence is None:
                flush()
                fence = []
            else:
                out.append("<pre><code>" + html.escape("\n".join(fence)) + "</code></pre>")
                fence = None
            continue
        if fence is not None:
            fence.append(line)
            continue
        if not line.strip():
            flush()
            continue
        if m := re.match(r"(#{1,6})\s+(.*)", line):
            flush()
            out.append(f"<h{len(m.group(1))}>{_inline(m.group(2), link_for)}</h{len(m.group(1))}>")
        elif m := re.match(r"\s*([-*]|\d+\.)\s+(.*)", line):
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if lst and lst[0] != kind:
                flush()
            if not lst:
                flush()
                lst = (kind, [])
            lst[1].append(m.group(2))
        elif line.startswith(">"):
            flush()
            out.append(f"<blockquote>{_inline(line.lstrip('> '), link_for)}</blockquote>")
        else:
            if lst:
                flush()
            para.append(line)
    flush()
    if fence is not None:
        out.append("<pre><code>" + html.escape("\n".join(fence)) + "</code></pre>")
    return "\n".join(out)


def strip_private(text):
    """Lines that only make sense inside the app: tasks and the inbox/calendar shorthand."""
    return "\n".join(l for l in text.split("\n") if not re.match(r"\s*([tic]\s+\S|file::)", l))


def graphql(shop_cfg, query, variables, opener=urllib.request.urlopen):
    req = urllib.request.Request(
        f"https://{shop_cfg['shop']}/admin/api/{API_VERSION}/graphql.json",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": shop_cfg["token"]})
    with opener(req, timeout=20) as r:
        data = json.load(r)
    if data.get("errors"):
        raise RuntimeError("; ".join(e.get("message", "?") for e in data["errors"]))
    return data["data"]


CREATE = "mutation($page: PageCreateInput!){pageCreate(page:$page){page{id handle} userErrors{message}}}"
UPDATE = "mutation($id: ID!, $page: PageUpdateInput!){pageUpdate(id:$id, page:$page){page{id handle} userErrors{message}}}"
DELETE = "mutation($id: ID!){pageDelete(id:$id){deletedPageId userErrors{message}}}"


def _call(cfg, query, variables, key, opener):
    res = graphql(cfg, query, variables, opener)[key]
    if res["userErrors"]:
        raise RuntimeError("; ".join(e["message"] for e in res["userErrors"]))
    return res


class ShopifySite:
    """Pages in a Shopify store, through a Dev Dashboard app's id and secret."""
    def __init__(self, cfg, opener=urllib.request.urlopen):
        self.cfg, self.opener = {**cfg, "token": cfg.get("token") or access_token(cfg, opener)}, opener
        self.state_file = STATE_FILE  # the name from before there was a choice, so existing pages are kept

    def link(self, handle):
        return f"/pages/{handle}"

    def create(self, title, handle, body):
        p = _call(self.cfg, CREATE, {"page": {"title": title, "handle": handle, "body": body, "isPublished": True}},
                  "pageCreate", self.opener)["page"]
        return p["id"], p["handle"]

    def update(self, pid, title, handle, body):
        p = _call(self.cfg, UPDATE, {"id": pid, "page": {"title": title, "handle": handle, "body": body, "isPublished": True}},
                  "pageUpdate", self.opener)["page"]
        return p["id"], p["handle"]

    def delete(self, pid):
        _call(self.cfg, DELETE, {"id": pid}, "pageDelete", self.opener)


class WordPressSite:
    """Pages on a WordPress site (5.6 or newer) through its REST API and an application password.
    ?rest_route= works whatever the site's permalink setting is."""
    def __init__(self, cfg, opener=urllib.request.urlopen):
        self.base, self.opener = site_url(cfg["url"]), opener
        self.auth = "Basic " + base64.b64encode(f"{cfg['user']}:{cfg['password'].replace(' ', '')}".encode()).decode()
        self.state_file = f".publish-state-wordpress-{hashlib.sha1(self.base.encode()).hexdigest()[:8]}.json"

    def call(self, method, route, body=None, params=""):
        url = f"{self.base}/?rest_route={urllib.parse.quote(route)}{params}"
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json",
                                              "User-Agent": "SimpleBrain"})
        try:
            with self.opener(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                why = json.load(e).get("message") or e.reason
            except (ValueError, AttributeError):
                why = e.reason
            raise RuntimeError(f"WordPress said {e.code}: {why}") from None

    def whoami(self):
        return self.call("GET", "/wp/v2/users/me").get("name") or "you"

    def link(self, handle):
        return f"{self.base}/{handle}/"

    def create(self, title, handle, body):
        p = self.call("POST", "/wp/v2/pages", {"title": title, "slug": handle, "content": body, "status": "publish"})
        return p["id"], p.get("slug") or handle

    def update(self, pid, title, handle, body):
        p = self.call("POST", f"/wp/v2/pages/{pid}", {"title": title, "slug": handle, "content": body, "status": "publish"})
        return p["id"], p.get("slug") or handle

    def delete(self, pid):
        try:
            self.call("DELETE", f"/wp/v2/pages/{pid}", params="&force=true")  # past the trash, like Shopify's delete
        except RuntimeError as e:
            if " 404:" not in str(e) and " 410:" not in str(e):  # already deleted on the site: nothing to do
                raise


PAGE_HTML = ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{title}</title>"
             "<style>body{{max-width:42rem;margin:2rem auto;padding:0 1rem;font:17px/1.6 Georgia,serif;color:#222}}"
             "a{{color:#8a5a12}}pre{{overflow:auto;background:#f4f1ea;padding:.75rem}}"
             "blockquote{{border-left:3px solid #e3b25a;margin-left:0;padding-left:1rem;color:#555}}</style></head>"
             "<body><p><a href=\"index.html\">All notes</a></p><h1>{title}</h1>\n{body}\n</body></html>\n")


class FolderSite:
    """Any other website: each page is an .html file in a folder (plus index.html, the list of notes). Upload the
    folder, or keep it where your site is served from (Netlify, GitHub Pages, Neocities, your host's files)."""
    def __init__(self, cfg, opener=None):
        self.folder = os.path.expanduser(cfg["folder"])
        self.state_file = f".publish-state-folder-{hashlib.sha1(self.folder.encode()).hexdigest()[:8]}.json"

    def link(self, handle):
        return f"{handle}.html"

    def _write(self, handle, title, body):
        os.makedirs(self.folder, exist_ok=True)
        page = PAGE_HTML.format(title=html.escape(title), body=body)
        for name in [handle] + (["index"] if handle == INDEX_HANDLE else []):
            core.write_atomic(os.path.join(self.folder, f"{name}.html"), page)
        return handle, handle

    def create(self, title, handle, body):
        return self._write(handle, title, body)

    def update(self, pid, title, handle, body):
        if pid != handle:
            self.delete(pid)
        return self._write(handle, title, body)

    def delete(self, pid):
        for name in [pid] + (["index"] if pid == INDEX_HANDLE else []):
            try:
                os.remove(os.path.join(self.folder, f"{name}.html"))
            except OSError:
                pass


SITES = {"shopify": ShopifySite, "wordpress": WordPressSite, "folder": FolderSite}


def connect(cfg, opener=urllib.request.urlopen):
    """The site for a saved setup: logs in (a test of the setup), raises with a reason when it can't."""
    return SITES[cfg.get("kind", "shopify")](cfg, opener)


def check(cfg, opener=urllib.request.urlopen):
    """Try a setup before saving it. Returns a line saying it worked; raises with the reason it didn't."""
    kind = cfg.get("kind")
    if kind == "wordpress":
        return f"Connected to {site_url(cfg['url'])} as {connect(cfg, opener).whoami()}."
    if kind == "shopify":
        connect(cfg, opener)
        return f"Connected to {cfg['shop']}."
    folder = os.path.expanduser(cfg["folder"])
    os.makedirs(folder, exist_ok=True)
    probe = os.path.join(folder, ".simplebrain-check")
    with open(probe, "w") as f:
        f.write("ok")
    os.remove(probe)
    return f"Pages will be written to {folder}."


def publish(vault=None, cfg=None, opener=urllib.request.urlopen):
    """Make the website's pages match the public notes. Returns (created, updated, deleted) counts.
    A page is only sent when its content changed, so a save of an unrelated note costs one hash check."""
    vault, cfg = vault or core.VAULT, cfg or site_config()
    if not cfg:
        raise RuntimeError("No website is set up yet (File > Website)")
    site = connect({"kind": "shopify", **cfg}, opener)
    state_path = os.path.join(vault, site.state_file)
    state = core.load_settings(state_path)
    notes = [n for n in core.public_notes(vault) if n not in (core.INBOX_FILE, core.CALENDAR_FILE)]
    handles = {core.note_title(n): state.get(n, {}).get("handle") or slug(core.note_title(n)) for n in notes}
    used = {}
    for title, h in list(handles.items()):  # two titles can slug alike: the second gets a suffix, and keeps it
        if h in used or h in (INDEX_HANDLE, "index"):
            h = f"{h}-{hashlib.sha1(title.encode()).hexdigest()[:6]}"
        used[h] = title
        handles[title] = h

    def link_for(title):
        return site.link(handles[title]) if title in handles else None

    pages = {}
    for n in notes:
        title = core.note_title(n)
        body = md_to_html(strip_private(core.read_note(n, vault)), link_for)
        pages[n] = (title, handles[title], body)
    listing = INDEX_INTRO + "<ul>" + "".join(f'<li><a href="{html.escape(site.link(h))}">{html.escape(t)}</a></li>'
                                             for t, h, _ in sorted(pages.values())) + "</ul>"
    pages[INDEX_FILE] = (INDEX_TITLE, INDEX_HANDLE, listing)
    created = updated = deleted = 0
    try:
        for key, (title, handle, body) in pages.items():
            digest = hashlib.sha1(f"{title}\0{handle}\0{body}".encode()).hexdigest()
            old = state.get(key)
            if old and old["hash"] == digest:
                continue
            if old:
                pid, got = site.update(old["id"], title, handle, body)
                updated += 1
            else:
                pid, got = site.create(title, handle, body)
                created += 1
            state[key] = {"id": pid, "handle": got, "hash": digest}
        for key in [k for k in state if k not in pages]:  # unticked, or the note is gone
            site.delete(state[key]["id"])
            del state[key]
            deleted += 1
    finally:
        core.save_settings(state, state_path)  # keep progress even if a later page failed
    return created, updated, deleted


def selftest():
    with tempfile.TemporaryDirectory() as d:  # the secret file is never readable by others, and a re-save replaces it whole
        real = core.user_config_dir
        core.user_config_dir = lambda: os.path.join(d, "cfg")
        try:
            save_shop_config(" a.myshopify.com ", "id", "old-secret")
            save_shop_config("a.myshopify.com", "id", "new-secret")
            assert shop_config() == {"shop": "a.myshopify.com", "client_id": "id", "client_secret": "new-secret"}
            assert os.listdir(os.path.join(d, "cfg")) == [SHOP_FILE]
            if os.name == "posix":
                assert os.stat(os.path.join(d, "cfg", SHOP_FILE)).st_mode & 0o777 == 0o600
        finally:
            core.user_config_dir = real
    links = {"B": "/pages/b"}.get
    assert md_to_html("# Hi\n\nsome **bold** and *it* and `c`\n- a\n- b [[B]] [[Secret]]", links) == (
        '<h1>Hi</h1>\n<p>some <strong>bold</strong> and <em>it</em> and <code>c</code></p>\n'
        '<ul><li>a</li><li>b <a href="/pages/b">B</a> Secret</li></ul>')
    assert "<script>" not in md_to_html("<script>x</script>", links) and "&lt;script&gt;" in md_to_html("<script>x</script>", links)
    assert md_to_html("```\n<a>\n```", links) == "<pre><code>&lt;a&gt;</code></pre>"
    assert slug("My Note: 2026!") == "my-note-2026" and len(slug("!!!")) == 8
    assert strip_private("keep\nt call bank due:10-01-2026\ni idea\nc 10-05-2026 meet\nthe cat") == "keep\nthe cat"
    calls, store = [], {}

    def fake(req, timeout=0):
        body = json.loads(req.data)
        if req.full_url.endswith("/admin/oauth/access_token"):
            assert body == {"client_id": "id", "client_secret": "sec", "grant_type": "client_credentials"}
            calls.append(("token",))

            class T:
                def __enter__(s): return s
                def __exit__(s, *a): pass
                def read(s, *a): return b'{"access_token": "tok"}'
            return T()
        assert req.get_header("X-shopify-access-token") == "tok" and req.full_url.startswith("https://s.myshopify.com/admin/api/")
        v = body["variables"]
        if "pageCreate" in body["query"]:
            gid = f"gid://shopify/Page/{len(store) + 1}"
            store[gid] = v["page"]
            calls.append(("create", v["page"]["handle"]))
            data = {"pageCreate": {"page": {"id": gid, "handle": v["page"]["handle"]}, "userErrors": []}}
        elif "pageUpdate" in body["query"]:
            store[v["id"]] = v["page"]
            calls.append(("update", v["page"]["handle"]))
            data = {"pageUpdate": {"page": {"id": v["id"], "handle": v["page"]["handle"]}, "userErrors": []}}
        else:
            del store[v["id"]]
            calls.append(("delete", v["id"]))
            data = {"pageDelete": {"deletedPageId": v["id"], "userErrors": []}}

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s, *a): return json.dumps({"data": data}).encode()
        return R()
    cfg = {"shop": "s.myshopify.com", "client_id": "id", "client_secret": "sec"}
    with tempfile.TemporaryDirectory() as v:
        core.write_note("A.md", "# A\nsee [[B]] and [[Private]]", v)
        core.write_note("B.md", "text", v)
        core.write_note("Private.md", "secret", v)
        core.set_public("A.md", True, v)
        core.set_public("B.md", True, v)
        core.set_public("Gone.md", True, v)  # marked, then deleted: ignored
        assert publish(v, cfg, fake) == (3, 0, 0)  # A, B and the index
        assert sorted(p["title"] for p in store.values()) == ["A", "B", "Notes"]
        assert 'href="/pages/b"' in next(p["body"] for p in store.values() if p["title"] == "A")
        assert "secret" not in json.dumps(store) and "Private</a>" not in json.dumps(store)
        calls.clear()
        assert publish(v, cfg, fake) == (0, 0, 0) and calls == [("token",)]  # unchanged: no page is sent
        core.write_note("B.md", "text more", v)
        assert publish(v, cfg, fake) == (0, 1, 0)
        core.set_public("B.md", False, v)
        assert publish(v, cfg, fake) == (0, 2, 1)  # B's page removed; A's link to it and the index change
        assert sorted(p["title"] for p in store.values()) == ["A", "Notes"]
        assert "/pages/b" not in json.dumps(store)
    wp, calls = {}, []

    def wp_fake(req, timeout=0):  # a WordPress site: pages by id, ?rest_route= addresses, Basic auth
        assert req.get_header("Authorization") == "Basic " + base64.b64encode(b"me:abcd efgh".replace(b" ", b"")).decode()
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        route, method = q["rest_route"][0], req.get_method()
        assert req.full_url.startswith("https://blog.example/?rest_route=")
        calls.append((method, route))
        if route == "/wp/v2/users/me":
            out = {"name": "Me"}
        elif method == "POST" and route == "/wp/v2/pages":
            b = json.loads(req.data)
            pid = len(wp) + 1 + sum(1 for c in calls if c[0] == "DELETE")
            wp[pid] = b
            out = {"id": pid, "slug": b["slug"]}
        elif method == "POST":
            pid = int(route.rsplit("/", 1)[1])
            wp[pid] = json.loads(req.data)
            out = {"id": pid, "slug": wp[pid]["slug"]}
        else:
            assert q.get("force") == ["true"]
            del wp[int(route.rsplit("/", 1)[1])]
            out = {"deleted": True}

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s, *a): return json.dumps(out).encode()
        return R()
    wcfg = {"kind": "wordpress", "url": "https://blog.example/", "user": "me", "password": "abcd efgh"}
    assert check(wcfg, wp_fake) == "Connected to https://blog.example as Me."
    with tempfile.TemporaryDirectory() as v:
        core.write_note("A.md", "# A\nsee [[B]]", v)
        core.write_note("B.md", "text", v)
        core.set_public("A.md", True, v)
        core.set_public("B.md", True, v)
        assert publish(v, wcfg, wp_fake) == (3, 0, 0)
        assert 'href="https://blog.example/b/"' in next(p["content"] for p in wp.values() if p["title"] == "A")
        assert all(p["status"] == "publish" for p in wp.values())
        core.set_public("B.md", False, v)
        assert publish(v, wcfg, wp_fake) == (0, 2, 1)
        assert sorted(p["title"] for p in wp.values()) == ["A", "Notes"]
    with tempfile.TemporaryDirectory() as v, tempfile.TemporaryDirectory() as site:  # any other site: files in a folder
        fcfg = {"kind": "folder", "folder": os.path.join(site, "public")}
        assert check(fcfg).startswith("Pages will be written to")
        core.write_note("A.md", "# A\nsee [[B]] <b>", v)
        core.write_note("B.md", "text", v)
        core.set_public("A.md", True, v)
        core.set_public("B.md", True, v)
        assert publish(v, fcfg) == (3, 0, 0)
        out = os.path.join(site, "public")
        assert sorted(os.listdir(out)) == ["a.html", "b.html", "index.html", "notes.html"]
        a = open(os.path.join(out, "a.html"), encoding="utf-8").read()
        assert '<a href="b.html">B</a>' in a and "&lt;b&gt;" in a and "<title>A</title>" in a
        assert 'href="a.html"' in open(os.path.join(out, "index.html"), encoding="utf-8").read()
        core.set_public("B.md", False, v)
        assert publish(v, fcfg) == (0, 2, 1) and not os.path.exists(os.path.join(out, "b.html"))
    with tempfile.TemporaryDirectory() as d:  # which website: the new file, else a store from before; off forgets both
        real = core.user_config_dir
        core.user_config_dir = lambda: os.path.join(d, "cfg")
        try:
            assert site_config() is None
            save_shop_config("a.myshopify.com", "id", "sec")
            assert site_config() == {"kind": "shopify", "shop": "a.myshopify.com", "client_id": "id", "client_secret": "sec"}
            save_site_config({"kind": "wordpress", "url": " blog.example/ ", "user": "me", "password": "p w"})
            assert site_config()["url"] == "https://blog.example" and site_config()["kind"] == "wordpress"
            if os.name == "posix":
                assert os.stat(os.path.join(d, "cfg", SITE_FILE)).st_mode & 0o777 == 0o600
            save_site_config({"kind": "wordpress", "url": "x", "user": "", "password": "p"})
            assert site_config()["kind"] == "shopify"  # half a setup isn't one: the old store still counts
            save_site_config({"kind": "off"})
            assert site_config() is None and not os.path.exists(os.path.join(d, "cfg", SHOP_FILE))
        finally:
            core.user_config_dir = real
    print("publish selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv or len(sys.argv) == 1 else None
