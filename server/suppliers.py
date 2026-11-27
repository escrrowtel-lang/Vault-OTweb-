"""Supplier (reseller) API credentials, managed from the admin panel.

The API key is stored server-side only. It is never sent back to a browser (only a masked tail),
and outbound requests are limited to public https hosts.
"""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

import store
from db import ApiError, tx

HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,40}$")


def mask(key):
    return ("\u2022" * 8 + key[-4:]) if len(key) >= 8 else ("\u2022" * 8 if key else "")


def public(row):
    return {"id": row["id"], "name": row["name"], "base_url": row["base_url"], "auth_mode": row["auth_mode"],
            "auth_header": row["auth_header"], "active": bool(row["active"]), "key_hint": mask(row["api_key"]),
            "has_key": bool(row["api_key"])}


def check_url(url):
    u = urllib.parse.urlparse(url or "")
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise ApiError(400, "Base URL must be a public https:// address")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ApiError(400, "Could not resolve this host")
    for i in infos:
        ip = ipaddress.ip_address(i[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ApiError(400, "Private or local addresses are not allowed")
    return url.rstrip("/")


def save(conn, data, existing_id=None):
    name = str(data.get("name", "")).strip()[:60]
    if not name:
        raise ApiError(400, "Name is required")
    base = check_url(str(data.get("base_url", "")).strip())
    mode = data.get("auth_mode", "header")
    if mode not in ("header", "bearer"):
        raise ApiError(400, "Invalid auth mode")
    header = str(data.get("auth_header", "X-API-Key")).strip() or "X-API-Key"
    if not HEADER_RE.match(header):
        raise ApiError(400, "Invalid header name")
    key = str(data.get("api_key", "")).strip()
    if len(key) > 500 or re.search(r"[\s\r\n]", key):
        raise ApiError(400, "Invalid API key")
    active = 1 if data.get("active", 1) in (1, True, "1") else 0
    with tx(conn):
        if existing_id:
            cur = conn.execute("SELECT * FROM suppliers WHERE id=?", (existing_id,)).fetchone()
            if not cur:
                raise ApiError(404, "Supplier not found")
            key = key or cur["api_key"]  # blank = keep the saved key
            conn.execute("UPDATE suppliers SET name=?,base_url=?,auth_mode=?,auth_header=?,api_key=?,active=? WHERE id=?",
                         (name, base, mode, header, key, active, existing_id))
            return existing_id
        return conn.execute("INSERT INTO suppliers(name,base_url,auth_mode,auth_header,api_key,active,created_at) VALUES(?,?,?,?,?,?,?)",
                            (name, base, mode, header, key, active, store.now())).lastrowid


def request(row, path, timeout=10):
    """GET base_url + path using the stored key. Returns (status, content_type, text)."""
    if not str(path).startswith("/") or "\n" in path or "\r" in path or " " in path:
        raise ApiError(400, "Path must start with / (for example /v1/balance)")
    url = check_url(row["base_url"]) + path
    headers = {"Accept": "application/json", "User-Agent": "VaultStore/1"}
    if row["api_key"]:
        if row["auth_mode"] == "bearer":
            headers["Authorization"] = "Bearer " + row["api_key"]
        else:
            headers[row["auth_header"]] = row["api_key"]

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(20_000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise ApiError(502, "Could not reach the supplier: %s" % type(e).__name__)


def test(row, path):
    status, ctype, body = request(row, path)
    if row["api_key"]:
        body = body.replace(row["api_key"], "[hidden]")
    out = {"status": status, "ok": 200 <= status < 300, "content_type": ctype, "preview": body[:700]}
    try:
        j = json.loads(body)
        out["json"] = True
        out["keys"] = list(j.keys())[:12] if isinstance(j, dict) else "list(%d)" % len(j)
    except ValueError:
        out["json"] = False
    return out
