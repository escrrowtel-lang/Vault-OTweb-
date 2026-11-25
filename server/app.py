"""HTTP server (sirf Python standard library, koi pip install nahi).

Run:  python3 server/app.py            (default 127.0.0.1:8000)
Env:  VAULT_DB, VAULT_UPLOADS, PORT, HOST
"""
import base64
import json
import mimetypes
import os
import re
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import store
from db import ApiError, connect, tx, to_cents, get_settings

WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))
MAX_BODY = 64 * 1024
MAX_UPLOAD_BODY = 2_500_000
IMG_MAGIC = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}

ROUTES = []  # (method, compiled regex, func, level)  level: pub | user | admin


def route(method, pattern, level="user"):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, level))
        return fn
    return deco


# ------------------------------------------------------------ rate limit (memory)
_hits = {}


def limited(key, limit, window):
    t = time.time()
    arr = [x for x in _hits.get(key, []) if x > t - window]
    if len(arr) >= limit:
        _hits[key] = arr
        return True
    arr.append(t)
    _hits[key] = arr
    return False


class Req:
    def __init__(self, h, params, body, user, conn, ip):
        self.h, self.params, self.body, self.user, self.conn, self.ip = h, params, body, user, conn, ip
        self.set_cookie = None

    def need(self, *keys):
        for k in keys:
            if k not in self.body:
                raise ApiError(400, "%s chahiye" % k)
        return [self.body[k] for k in keys]


def rowdict(r):
    return {k: r[k] for k in r.keys()}


def money(rows, keys):
    out = []
    for r in rows:
        d = rowdict(r)
        for k in keys:
            d[k] = d[k] / 100
        out.append(d)
    return out


# ============================================================ PUBLIC / AUTH
@route("GET", "/api/catalog", "pub")
def api_catalog(r):
    return {"categories": store.public_catalog(r.conn)}


@route("GET", "/api/settings", "pub")
def api_settings(r):
    s = get_settings(r.conn)
    en = s["methods_enabled"].split(",")
    return {
        "store_name": s["store_name"], "methods": en,
        "min_deposit": s["min_deposit"], "max_deposit": s["max_deposit"], "usd_inr_rate": s["usd_inr_rate"],
        "upi_id": s["upi_id"] if "upi" in en else "", "upi_name": s["upi_name"],
        "binance_id": s["binance_id"] if "binance_id" in en else "",
        "usdt_address": s["usdt_address"] if "usdt_bep20" in en else "",
        "support_text": s["support_text"], "support_url": s["support_url"],
    }


def _user_json(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"]),
            "balance": u["balance"] / 100, "ref_code": u["ref_code"]}


@route("POST", "/api/auth/register", "pub")
def api_register(r):
    if limited(("reg", r.ip), 8, 3600):
        raise ApiError(429, "Bahut zyada koshish, baad mein try karo")
    email, pw = r.need("email", "password")
    store.create_user(r.conn, email, pw, r.body.get("name", ""), r.body.get("ref", ""))
    token, u = store.login(r.conn, email, pw)
    r.set_cookie = token
    return {"user": _user_json(u)}


@route("POST", "/api/auth/login", "pub")
def api_login(r):
    if limited(("login", r.ip), 10, 300):
        raise ApiError(429, "Bahut zyada koshish, 5 minute baad try karo")
    email, pw = r.need("email", "password")
    token, u = store.login(r.conn, email, pw)
    r.set_cookie = token
    return {"user": _user_json(u)}


@route("POST", "/api/auth/logout", "pub")
def api_logout(r):
    store.logout(r.conn, r.h.cookie_token())
    r.set_cookie = ""
    return {"ok": True}


@route("GET", "/api/me", "pub")
def api_me(r):
    return {"user": _user_json(r.user) if r.user else None}


# ============================================================ CUSTOMER
@route("POST", "/api/coupon/check")
def api_coupon(r):
    return {"percent": store.check_coupon(r.conn, r.user["id"], r.body.get("code", ""))}


@route("POST", "/api/buy")
def api_buy(r):
    if limited(("buy", r.user["id"]), 20, 60):
        raise ApiError(429, "Thoda ruko, phir try karo")
    vid, qty = r.need("variation_id", "qty")
    oid = store.buy(r.conn, r.user["id"], vid, qty, r.body.get("coupon", ""))
    o = r.conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    u = r.conn.execute("SELECT balance FROM users WHERE id=?", (r.user["id"],)).fetchone()
    return {"order": _order_json(o), "balance": u["balance"] / 100}


def _order_json(o):
    d = rowdict(o)
    for k in ("unit_price", "discount", "total"):
        d[k] = d[k] / 100
    d.pop("user_id", None)
    return d


@route("GET", "/api/orders")
def api_orders(r):
    rows = r.conn.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 200", (r.user["id"],)).fetchall()
    return {"orders": [_order_json(o) for o in rows]}


@route("GET", "/api/wallet")
def api_wallet(r):
    led = r.conn.execute("SELECT delta,reason,ref,balance_after,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 100",
                         (r.user["id"],)).fetchall()
    deps = r.conn.execute("SELECT id,method,amount,reference,status,note,created_at FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 50",
                          (r.user["id"],)).fetchall()
    u = r.conn.execute("SELECT balance FROM users WHERE id=?", (r.user["id"],)).fetchone()
    return {"balance": u["balance"] / 100,
            "ledger": money(led, ["delta", "balance_after"]), "deposits": money(deps, ["amount"])}


@route("POST", "/api/deposits/crypto-intent")
def api_crypto_intent(r):
    if limited(("intent", r.user["id"]), 10, 3600):
        raise ApiError(429, "Bahut requests, baad mein try karo")
    (amount,) = r.need("amount")
    return store.create_crypto_intent(r.conn, r.user["id"], amount)


@route("POST", "/api/deposits")
def api_deposit(r):
    if limited(("dep", r.user["id"]), 15, 3600):
        raise ApiError(429, "Bahut requests, baad mein try karo")
    method, ref = r.need("method", "reference")
    return store.create_deposit(r.conn, r.user["id"], method, r.body.get("amount", 0), ref)


@route("GET", "/api/referral")
def api_referral(r):
    n = r.conn.execute("SELECT COUNT(*) n FROM users WHERE referred_by=?", (r.user["id"],)).fetchone()["n"]
    ok = r.conn.execute("SELECT COUNT(*) n FROM users WHERE referred_by=? AND ref_rewarded=1", (r.user["id"],)).fetchone()["n"]
    earned = r.conn.execute("SELECT COALESCE(SUM(delta),0) s FROM ledger WHERE user_id=? AND reason='referral'",
                            (r.user["id"],)).fetchone()["s"]
    s = get_settings(r.conn)
    return {"code": r.user["ref_code"], "invited": n, "rewarded": ok, "earned": earned / 100, "reward": s["referral_reward"]}


# ============================================================ ADMIN
@route("GET", "/api/admin/stats", "admin")
def adm_stats(r):
    q = lambda sql, *a: r.conn.execute(sql, a).fetchone()[0]
    return {
        "users": q("SELECT COUNT(*) FROM users"),
        "orders": q("SELECT COUNT(*) FROM orders"),
        "revenue": q("SELECT COALESCE(SUM(total),0) FROM orders WHERE status IN ('processing','completed','pending')") / 100,
        "pending_deposits": q("SELECT COUNT(*) FROM deposits WHERE status='pending'"),
        "processing_orders": q("SELECT COUNT(*) FROM orders WHERE status='processing'"),
        "preorders_waiting": q("SELECT COUNT(*) FROM orders WHERE status='pending' AND preorder=1"),
        "wallet_liability": q("SELECT COALESCE(SUM(balance),0) FROM users") / 100,
    }


@route("GET", "/api/admin/catalog", "admin")
def adm_catalog(r):
    out = []
    for c in r.conn.execute("SELECT * FROM categories ORDER BY position,id"):
        cd = rowdict(c)
        cd["products"] = []
        for p in r.conn.execute("SELECT * FROM products WHERE category_id=? ORDER BY position,id", (c["id"],)):
            pd = rowdict(p)
            pd["variations"] = []
            for v in r.conn.execute("SELECT * FROM variations WHERE product_id=? ORDER BY position,id", (p["id"],)):
                vd = rowdict(v)
                vd["price"] = vd["price"] / 100
                vd["available"] = store.available(r.conn, v["id"], p["mode"])
                pd["variations"].append(vd)
            cd["products"].append(pd)
        out.append(cd)
    return {"categories": out}


def _b(v):
    return 1 if v in (True, 1, "1", "true", "on") else 0


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _color(v):
    v = str(v or "#7c3aed")
    return v if re.match(r"^#[0-9a-fA-F]{6}$", v) else "#7c3aed"


def _image(v):
    v = str(v or "").strip()
    if v and not re.match(r"^(/uploads/[A-Za-z0-9._-]+|https://[^\s\"'<>]+)$", v):
        raise ApiError(400, "Image sirf upload ya https link ho sakti hai")
    return v


@route("POST", "/api/admin/category", "admin")
def adm_category(r):
    (name,) = r.need("name")
    b = r.body
    if not str(name).strip():
        raise ApiError(400, "Naam chahiye")
    if b.get("id"):
        r.conn.execute("UPDATE categories SET name=?,emoji=?,position=?,active=? WHERE id=?",
                       (str(name).strip(), str(b.get("emoji", ""))[:8], _int(b.get("position")), _b(b.get("active", 1)), _int(b["id"])))
    else:
        r.conn.execute("INSERT INTO categories(name,emoji,position,active) VALUES(?,?,?,?)",
                       (str(name).strip(), str(b.get("emoji", ""))[:8], _int(b.get("position")), _b(b.get("active", 1))))
    return {"ok": True}


@route("POST", "/api/admin/product", "admin")
def adm_product(r):
    cat, name = r.need("category_id", "name")
    b = r.body
    mode = b.get("mode", "auto")
    if mode not in ("auto", "manual"):
        raise ApiError(400, "Mode sahi nahi hai")
    vals = (_int(cat), str(name).strip()[:100], str(b.get("description", ""))[:4000], _image(b.get("image")),
            str(b.get("glyph", "star"))[:20], _color(b.get("color")), mode, _b(b.get("quick_drop")),
            _int(b.get("position")), _b(b.get("active", 1)))
    if not r.conn.execute("SELECT 1 FROM categories WHERE id=?", (_int(cat),)).fetchone():
        raise ApiError(404, "Category nahi mili")
    if b.get("id"):
        r.conn.execute("UPDATE products SET category_id=?,name=?,description=?,image=?,glyph=?,color=?,mode=?,quick_drop=?,position=?,active=? WHERE id=?",
                       vals + (_int(b["id"]),))
    else:
        r.conn.execute("INSERT INTO products(category_id,name,description,image,glyph,color,mode,quick_drop,position,active) VALUES(?,?,?,?,?,?,?,?,?,?)", vals)
    return {"ok": True}


@route("POST", "/api/admin/variation", "admin")
def adm_variation(r):
    pid, name, price = r.need("product_id", "name", "price")
    b = r.body
    mn, mx = max(1, _int(b.get("min_qty"), 1)), max(1, _int(b.get("max_qty"), 1))
    if mx < mn:
        raise ApiError(400, "Max qty min se kam nahi ho sakti")
    if not r.conn.execute("SELECT 1 FROM products WHERE id=?", (_int(pid),)).fetchone():
        raise ApiError(404, "Product nahi mila")
    cents = to_cents(price)
    if b.get("id"):
        r.conn.execute("UPDATE variations SET name=?,price=?,min_qty=?,max_qty=?,stock=?,position=?,active=? WHERE id=?",
                       (str(name).strip()[:60], cents, mn, mx, max(0, _int(b.get("stock"))), _int(b.get("position")),
                        _b(b.get("active", 1)), _int(b["id"])))
    else:
        r.conn.execute("INSERT INTO variations(product_id,name,price,min_qty,max_qty,stock,position,active) VALUES(?,?,?,?,?,?,?,?)",
                       (_int(pid), str(name).strip()[:60], cents, mn, mx, max(0, _int(b.get("stock"))), _int(b.get("position")),
                        _b(b.get("active", 1))))
    return {"ok": True}


@route("POST", "/api/admin/inventory", "admin")
def adm_inv_add(r):
    vid, text = r.need("variation_id", "text")
    return store.add_inventory(r.conn, _int(vid), str(text).splitlines())


@route("GET", "/api/admin/inventory", "admin")
def adm_inv_list(r):
    vid = _int(r.params.get("variation_id"))
    rows = r.conn.execute("SELECT id,content,status,order_id FROM inventory WHERE variation_id=? ORDER BY id DESC LIMIT 500", (vid,)).fetchall()
    return {"items": [rowdict(x) for x in rows]}


@route("POST", "/api/admin/inventory/delete", "admin")
def adm_inv_del(r):
    (iid,) = r.need("id")
    cur = r.conn.execute("DELETE FROM inventory WHERE id=? AND status='available'", (_int(iid),))
    if cur.rowcount == 0:
        raise ApiError(409, "Sirf available item delete ho sakta hai")
    return {"ok": True}


@route("GET", "/api/admin/orders", "admin")
def adm_orders(r):
    st = r.params.get("status", "")
    sql = ("SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id "
           + ("WHERE o.status=? " if st else "") + "ORDER BY o.id DESC LIMIT 300")
    rows = r.conn.execute(sql, (st,) if st else ()).fetchall()
    out = []
    for o in rows:
        d = _order_json(o)
        d["email"] = o["email"]
        out.append(d)
    return {"orders": out}


@route("POST", "/api/admin/order/deliver", "admin")
def adm_deliver(r):
    oid, text = r.need("id", "text")
    store.deliver_manual(r.conn, _int(oid), text)
    return {"ok": True}


@route("POST", "/api/admin/order/refund", "admin")
def adm_refund(r):
    (oid,) = r.need("id")
    store.refund_order(r.conn, _int(oid))
    return {"ok": True}


@route("GET", "/api/admin/deposits", "admin")
def adm_deposits(r):
    st = r.params.get("status", "")
    rows = r.conn.execute("SELECT d.*, u.email FROM deposits d JOIN users u ON u.id=d.user_id "
                          + ("WHERE d.status=? " if st else "") + "ORDER BY d.id DESC LIMIT 300",
                          (st,) if st else ()).fetchall()
    rate = float(get_settings(r.conn).get("usd_inr_rate", "100") or 100)
    out = money(rows, ["amount"])
    for d in out:
        d["inr_expected"] = round(d["amount"] * rate, 2)
    return {"deposits": out}


@route("POST", "/api/admin/deposit/decide", "admin")
def adm_decide(r):
    did, action = r.need("id", "action")
    store.decide_deposit(r.conn, _int(did), action, r.body.get("note", ""))
    return {"ok": True}


@route("GET", "/api/admin/users", "admin")
def adm_users(r):
    rows = r.conn.execute("SELECT id,email,name,is_admin,blocked,balance,created_at FROM users ORDER BY id DESC LIMIT 500").fetchall()
    return {"users": money(rows, ["balance"])}


@route("POST", "/api/admin/user/adjust", "admin")
def adm_adjust(r):
    uid, amount = r.need("id", "amount")
    try:
        from decimal import Decimal
        sign = -1 if Decimal(str(amount)) < 0 else 1
    except Exception:
        raise ApiError(400, "Amount sahi nahi hai")
    cents = to_cents(str(amount).lstrip("-")) * sign
    if cents == 0:
        raise ApiError(400, "Amount 0 nahi ho sakta")
    reason = "admin:" + str(r.body.get("reason", "adjust"))[:60]
    with tx(r.conn):
        if not r.conn.execute("SELECT 1 FROM users WHERE id=?", (_int(uid),)).fetchone():
            raise ApiError(404, "User nahi mila")
        store.credit(r.conn, _int(uid), cents, reason)
    return {"ok": True}


@route("POST", "/api/admin/user/block", "admin")
def adm_block(r):
    uid, blocked = r.need("id", "blocked")
    if _int(uid) == r.user["id"]:
        raise ApiError(400, "Khud ko block nahi kar sakte")
    r.conn.execute("UPDATE users SET blocked=? WHERE id=?", (_b(blocked), _int(uid)))
    if _b(blocked):
        r.conn.execute("DELETE FROM sessions WHERE user_id=?", (_int(uid),))
    return {"ok": True}


@route("GET", "/api/admin/coupons", "admin")
def adm_coupons(r):
    return {"coupons": [rowdict(x) for x in r.conn.execute("SELECT * FROM coupons ORDER BY id DESC")]}


@route("POST", "/api/admin/coupon", "admin")
def adm_coupon(r):
    code, pct = r.need("code", "percent")
    code = re.sub(r"[^A-Za-z0-9_-]", "", str(code)).upper()[:24]
    pct = _int(pct)
    if not code or not 1 <= pct <= 100:
        raise ApiError(400, "Code aur percent (1-100) sahi daalo")
    if r.body.get("id"):
        r.conn.execute("UPDATE coupons SET active=? WHERE id=?", (_b(r.body.get("active", 1)), _int(r.body["id"])))
    else:
        try:
            r.conn.execute("INSERT INTO coupons(code,percent,max_uses) VALUES(?,?,?)", (code, pct, max(1, _int(r.body.get("max_uses"), 1))))
        except Exception:
            raise ApiError(409, "Ye coupon code pehle se hai")
    return {"ok": True}


@route("GET", "/api/admin/settings", "admin")
def adm_settings_get(r):
    return {"settings": get_settings(r.conn)}


@route("POST", "/api/admin/settings", "admin")
def adm_settings_set(r):
    allowed = set(db.DEFAULT_SETTINGS)
    with tx(r.conn):
        for k, v in r.body.items():
            if k in allowed:
                v = str(v).strip()
                if k in ("min_deposit", "max_deposit", "referral_reward"):
                    to_cents(v)
                if k == "usd_inr_rate" and not re.match(r"^\d+(\.\d+)?$", v):
                    raise ApiError(400, "INR rate sahi nahi hai")
                if k == "usdt_address" and v and not re.match(r"^0x[0-9a-fA-F]{40}$", v):
                    raise ApiError(400, "USDT address sahi nahi hai")
                if k == "methods_enabled":
                    v = ",".join(x for x in v.split(",") if x in ("upi", "binance_id", "usdt_bep20"))
                if k in ("bsc_rpc", "support_url") and v and not v.startswith("https://"):
                    raise ApiError(400, "%s https:// se shuru hona chahiye" % k)
                r.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
    return {"ok": True}


@route("POST", "/api/admin/upload", "admin")
def adm_upload(r):
    (data,) = r.need("data")
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        raise ApiError(400, "File sahi nahi hai")
    if len(raw) > 1_000_000:
        raise ApiError(400, "Image 1MB se chhoti honi chahiye")
    ext = next((e for m, e in IMG_MAGIC.items() if raw.startswith(m)), None)
    if ext == ".webp" and raw[8:12] != b"WEBP":
        ext = None
    if not ext:
        raise ApiError(400, "Sirf PNG, JPG ya WEBP image allowed hai")
    name = secrets.token_hex(8) + ext
    with open(os.path.join(db.UPLOAD_DIR, name), "wb") as f:
        f.write(raw)
    return {"url": "/uploads/" + name}


# ============================================================ server
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    server_version = "VaultStore"
    timeout = 30  # slow/atak gaye connections band
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid":
                return v
        return ""

    def client_ip(self):
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return self.headers.get("X-Real-IP") or self.client_address[0]
        return self.client_address[0]

    def send_json(self, status, obj, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        if cookie is not None:
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            if cookie:
                self.send_header("Set-Cookie", "sid=%s; HttpOnly; SameSite=Lax; Path=/; Max-Age=%d%s" % (cookie, store.SESSION_TTL, secure))
            else:
                self.send_header("Set-Cookie", "sid=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0%s" % secure)
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self, method):
        u = urlparse(self.path)
        path = u.path
        if path.startswith("/api/"):
            return self.handle_api(method, path, {k: v[0] for k, v in parse_qs(u.query).items()})
        if method == "GET" and path.startswith("/uploads/"):
            return self.serve_file(db.UPLOAD_DIR, path[len("/uploads/"):], upload=True)
        if method == "GET":
            return self.serve_file(WEB_DIR, path.lstrip("/") or "index.html")
        self.send_json(404, {"error": "Not found"})

    def handle_api(self, method, path, params):
        conn = None
        self._body_read = method != "POST"
        try:
            fn = level = None
            m = None
            for meth, rx, f, lv in ROUTES:
                mm = rx.match(path)
                if mm:
                    if meth == method:
                        fn, level, m = f, lv, mm
                        break
                    m = "method"
            if fn is None:
                raise ApiError(405 if m else 404, "Not found")
            body = {}
            if method == "POST":
                if self.headers.get("X-Requested-With") != "fetch":
                    raise ApiError(403, "Bad request")
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    raise ApiError(400, "Bad request")
                if n < 0:
                    raise ApiError(400, "Bad request")
                if n > (MAX_UPLOAD_BODY if path == "/api/admin/upload" else MAX_BODY):
                    raise ApiError(413, "Request bahut badi hai")
                raw = self.rfile.read(n) if n else b"{}"
                self._body_read = True
                try:
                    body = json.loads(raw.decode() or "{}")
                except ValueError:
                    raise ApiError(400, "JSON sahi nahi hai")
                if not isinstance(body, dict):
                    raise ApiError(400, "JSON object chahiye")
            conn = connect()
            user = store.user_by_token(conn, self.cookie_token())
            if level in ("user", "admin") and not user:
                raise ApiError(401, "Pehle login karo")
            if level == "admin" and not user["is_admin"]:
                raise ApiError(403, "Admin access chahiye")
            req = Req(self, params, body, user, conn, self.client_ip())
            out = fn(req)
            self.send_json(200, out, cookie=req.set_cookie)
        except ApiError as e:
            if not self._body_read:
                self.close_connection = True
            self.send_json(e.status, {"error": e.msg})
        except Exception as e:  # noqa
            if not self._body_read:
                self.close_connection = True
            sys.stderr.write("ERROR %r\n" % (e,))
            import traceback
            traceback.print_exc()
            self.send_json(500, {"error": "Server error"})
        finally:
            if conn:
                conn.close()

    def serve_file(self, root, rel, upload=False):
        root = os.path.realpath(root)
        full = os.path.realpath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self.send_json(404, {"error": "Not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if upload and ctype not in ("image/png", "image/jpeg", "image/webp"):
            return self.send_json(404, {"error": "Not found"})
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if upload:
            self.send_header("Content-Security-Policy", "default-src 'none'")
        elif ctype == "text/html":
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


def main():
    db.init()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    print("Vault Store server http://%s:%d" % (host, port), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
