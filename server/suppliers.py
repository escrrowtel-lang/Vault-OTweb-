"""Supplier (reseller) API credentials, managed from the admin panel.

The API key is stored server-side only. It is never sent back to a browser (only a masked tail),
and outbound requests are limited to public https hosts.
"""
import ipaddress
import json
import os
import re
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import db
import store
from db import ApiError, tx

HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,40}$")


def mask(key):
    return ("\u2022" * 8 + key[-4:]) if len(key) >= 8 else ("\u2022" * 8 if key else "")


def public(row):
    return {"id": row["id"], "name": row["name"], "base_url": row["base_url"], "auth_mode": row["auth_mode"],
            "auth_header": row["auth_header"], "active": bool(row["active"]), "kind": row["kind"], "auto_sync": bool(row["auto_sync"]),
            "catalog_path": row["catalog_path"], "markup": row["markup"], "key_hint": mask(row["api_key"]),
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
    kind = data.get("kind", "generic")
    if kind not in ("generic", "prodseller"):
        raise ApiError(400, "Invalid API type")
    sync = 1 if data.get("auto_sync", 0) in (1, True, "1") else 0
    with tx(conn):
        if existing_id:
            cur = conn.execute("SELECT * FROM suppliers WHERE id=?", (existing_id,)).fetchone()
            if not cur:
                raise ApiError(404, "Supplier not found")
            key = key or cur["api_key"]  # blank = keep the saved key
            conn.execute("UPDATE suppliers SET name=?,base_url=?,auth_mode=?,auth_header=?,api_key=?,active=?,kind=?,auto_sync=? WHERE id=?",
                         (name, base, mode, header, key, active, kind, sync, existing_id))
            return existing_id
        return conn.execute("INSERT INTO suppliers(name,base_url,auth_mode,auth_header,api_key,active,created_at,kind,auto_sync) VALUES(?,?,?,?,?,?,?,?,?)",
                            (name, base, mode, header, key, active, store.now(), kind, sync)).lastrowid


def _join(base, path):
    """base_url + path, without doubling a prefix the base already ends with (e.g. base .../v1 and path /v1/products)."""
    bp = urllib.parse.urlparse(base).path.rstrip("/")
    if bp and (path == bp or path.startswith(bp + "/")):
        path = path[len(bp):] or "/"
    return base + path


def request(row, path, timeout=10, limit=200_000, method="GET", body=None, extra=None):
    """Call base_url + path using the stored key. Returns (status, content_type, text)."""
    if not str(path).startswith("/") or "\n" in path or "\r" in path or " " in path:
        raise ApiError(400, "Path must start with / (for example /balance)")
    url = _join(check_url(row["base_url"]), path)
    headers = {"Accept": "application/json", "User-Agent": "VaultStore/1"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra or {})
    if row["api_key"]:
        if row["auth_mode"] == "bearer":
            headers["Authorization"] = "Bearer " + row["api_key"]
        else:
            headers[row["auth_header"]] = row["api_key"]

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(limit).decode("utf-8", "replace")
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


# ------------------------------------------------------------------ catalog discovery + import
CANDIDATES = ["/products", "/v1/products", "/api/products", "/api/v1/products", "/catalog", "/v1/catalog", "/api/catalog",
              "/api/reseller/products", "/api/reseller/v1/products", "/api/reseller/catalog", "/products/list", "/shop/products",
              "/categories", "/v1/categories"]
LIST_KEYS = ("products", "data", "items", "results", "result", "catalog", "categories", "list", "plans")


def _get(d, names):
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, "", [], {}):
            return v
    return None


def extract(j, cat=""):
    """Find product-like dicts in any reasonable catalog JSON. Returns [(category_name, item_dict)]."""
    out = []
    if isinstance(j, dict):
        for k in LIST_KEYS:
            if k in j and isinstance(j[k], (list, dict)):
                return extract(j[k], cat)
        return []
    if isinstance(j, list):
        for it in j:
            if not isinstance(it, dict):
                continue
            sub = _get(it, ["products", "items", "plans"])
            if isinstance(sub, list) and sub and isinstance(sub[0], dict) and not _get(it, ["price", "unit_price"]):
                out += extract(sub, str(_get(it, ["name", "title"]) or cat))
            else:
                out.append((cat, it))
    return out


def to_cents(v, cents_unit):
    try:
        d = Decimal(re.sub(r"[^0-9.\-]", "", str(v)) or "x")
    except InvalidOperation:
        return None
    if cents_unit:
        d = d / 100
    if d < 0:
        return None
    return int((d * 100).to_integral_value(ROUND_HALF_UP))


def normalize(j, cents_unit=False):
    items = []
    for cat, it in extract(j):
        price = to_cents(_get(it, ["resellerPrice", "reseller_price", "wholesale_price", "wholesalePrice", "price", "unitPrice", "unit_price",
                                   "sellPrice", "sell_price", "cost", "rate", "amount"]), cents_unit)
        name = _get(it, ["name", "title", "productName", "product_name"])
        ext = _get(it, ["id", "_id", "productId", "product_id", "sku", "uuid", "slug", "code"])
        if price is None or not name or ext is None:
            continue
        c = _get(it, ["category", "categoryName", "category_name", "type", "group"])
        if isinstance(c, dict):
            c = _get(c, ["name", "title"])
        stock = _get(it, ["stock", "quantity", "qty", "available", "inStock", "in_stock"])
        if stock is None and "stock" in {str(k).lower() for k in it}:
            stock = _get(it, ["inStock", "in_stock"])  # stock: null (custom delivery) + inStock flag
        note = ""
        if isinstance(stock, bool):
            stock, note = (999 if stock else 0), "availability only"
        elif stock is None and isinstance(_get(it, ["inStock", "in_stock", "available"]), bool):
            stock, note = (999 if _get(it, ["inStock", "in_stock", "available"]) else 0), "availability only"
        else:
            try:
                stock = max(0, int(float(stock))) if stock is not None else 0
            except (TypeError, ValueError):
                stock = 0
        img = _get(it, ["imageUrl", "image_url", "image", "thumbnail", "logo", "icon", "img", "picture"])
        if isinstance(img, dict):
            img = _get(img, ["url", "src"])
        items.append({"ext": str(ext)[:120], "name": str(name).strip()[:120], "category": str(c or cat or "General")[:60],
                      "description": str(_get(it, ["description", "desc", "details", "about"]) or "")[:2000],
                      "cost": price, "needs_email": bool(_get(it, ["requiresEmailActivation", "requires_email_activation", "requiresEmail"])), "stock": stock, "stock_note": note, "image": img if isinstance(img, str) else ""})
    return items


def discover(row):
    found = []
    for path in CANDIDATES:
        try:
            status, ctype, body = request(row, path, timeout=6)
            j = json.loads(body) if status == 200 else None
        except (ApiError, ValueError):
            continue
        if j is None:
            continue
        n = len(normalize(j))
        if n:
            found.append({"path": path, "count": n})
    return found


def _download_image(url):
    try:
        check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "VaultStore/1", "Accept": "image/*"})
        with urllib.request.build_opener().open(req, timeout=10) as r:
            raw = r.read(1_000_001)
    except Exception:
        return ""
    if len(raw) > 1_000_000 or len(raw) < 100:
        return ""
    ext = ".png" if raw.startswith(b"\x89PNG") else ".jpg" if raw.startswith(b"\xff\xd8\xff") else ".webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else ""
    if not ext:
        return ""
    name = secrets.token_hex(8) + ext
    try:
        with open(os.path.join(db.UPLOAD_DIR, name), "wb") as f:
            f.write(raw)
    except OSError:
        return ""
    return "/uploads/" + name


def import_catalog(conn, row, path, markup_pct, cents_unit, dry=True):
    status, ctype, body = request(row, path, timeout=20, limit=3_000_000)
    if status != 200:
        raise ApiError(400, "Supplier returned HTTP %d for %s" % (status, path))
    try:
        items = normalize(json.loads(body), cents_unit)
    except ValueError:
        raise ApiError(400, "The supplier did not return JSON")
    if not items:
        raise ApiError(400, "No products found in this response. Check the path.")
    k = Decimal(1) + Decimal(str(markup_pct)) / 100
    for it in items:
        it["price"] = int((Decimal(it["cost"]) * k).to_integral_value(ROUND_HALF_UP))
    if dry:
        return {"total": len(items), "preview": items[:12]}
    created = updated = 0
    cats = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM categories").fetchall()}
    for it in items:
        with tx(conn):
            cid = cats.get(it["category"])
            if cid is None:
                cid = cats[it["category"]] = conn.execute("INSERT INTO categories(name) VALUES(?)", (it["category"],)).lastrowid
            m = conn.execute("SELECT * FROM supplier_items WHERE supplier_id=? AND external_id=?", (row["id"], it["ext"])).fetchone()
            if m:  # re-sync: refresh price and stock only, keep the admin's own edits to name/description/image
                conn.execute("UPDATE variations SET price=?, stock=? WHERE id=?", (it["price"], it["stock"], m["variation_id"]))
                conn.execute("UPDATE supplier_items SET cost=?, needs_email=? WHERE id=?", (it["cost"], 1 if it["needs_email"] else 0, m["id"]))
                updated += 1
                continue
            pid = conn.execute("INSERT INTO products(category_id,name,description,mode,glyph,color) VALUES(?,?,?,?,?,?)",
                               (cid, it["name"], it["description"], "manual", "mono", "#0ea5e9")).lastrowid
            vid = conn.execute("INSERT INTO variations(product_id,name,price,min_qty,max_qty,stock) VALUES(?,?,?,?,?,?)",
                               (pid, "Standard", it["price"], 1, 10 if row["kind"] == "prodseller" else 1, it["stock"])).lastrowid
            conn.execute("INSERT INTO supplier_items(supplier_id,external_id,product_id,variation_id,cost,needs_email) VALUES(?,?,?,?,?,?)",
                         (row["id"], it["ext"], pid, vid, it["cost"], 1 if it["needs_email"] else 0))
            created += 1
    # products the supplier no longer lists become unavailable instead of keeping stale stock
    seen = {it["ext"] for it in items}
    with tx(conn):
        for m in conn.execute("SELECT external_id, variation_id FROM supplier_items WHERE supplier_id=?", (row["id"],)).fetchall():
            if m["external_id"] not in seen:
                conn.execute("UPDATE variations SET stock=0 WHERE id=?", (m["variation_id"],))
        conn.execute("UPDATE suppliers SET catalog_path=?, markup=?, cents=? WHERE id=?", (path, str(markup_pct), 1 if cents_unit else 0, row["id"]))
    # images (outside the DB transaction), bounded so one request cannot run forever
    t0, imgs = time.time(), 0
    for it in items:
        if not it["image"] or time.time() - t0 > 45:
            continue
        m = conn.execute("SELECT product_id FROM supplier_items WHERE supplier_id=? AND external_id=?", (row["id"], it["ext"])).fetchone()
        cur = conn.execute("SELECT image FROM products WHERE id=?", (m["product_id"],)).fetchone() if m else None
        if cur and not cur["image"]:
            url = _download_image(it["image"])
            if url:
                with tx(conn):
                    conn.execute("UPDATE products SET image=? WHERE id=?", (url, m["product_id"]))
                imgs += 1
    return {"created": created, "updated": updated, "images": imgs, "total": len(items)}
