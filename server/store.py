"""Business logic: wallet, orders, inventory, deposits, referral."""
import hashlib
import hmac
import re
import secrets
import time

import payments
from db import ApiError, tx, to_cents, get_settings

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
SESSION_TTL = 30 * 86400


def now():
    return int(time.time())


# ---------------------------------------------------------------- auth
def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _ref_code(conn):
    while True:
        c = secrets.token_hex(4).upper()
        if not conn.execute("SELECT 1 FROM users WHERE ref_code=?", (c,)).fetchone():
            return c


def create_user(conn, email, password, name="", ref="", is_admin=0):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Email sahi nahi hai")
    if len(password or "") < 8 or len(password) > 200:
        raise ApiError(400, "Password kam se kam 8 characters ka ho")
    salt = secrets.token_bytes(16)
    ph = _hash(password, salt)
    with tx(conn):
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise ApiError(409, "Ye email pehle se registered hai")
        referrer = None
        if ref:
            r = conn.execute("SELECT id FROM users WHERE ref_code=?", (ref.strip().upper(),)).fetchone()
            referrer = r["id"] if r else None
        cur = conn.execute(
            "INSERT INTO users(email,name,pass_hash,pass_salt,is_admin,ref_code,referred_by,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (email, (name or "").strip()[:60], ph, salt, 1 if is_admin else 0, _ref_code(conn), referrer, now()))
        return cur.lastrowid


def login(conn, email, password):
    email = (email or "").strip().lower()
    u = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    # constant-ish time: hash hamesha karo
    salt = u["pass_salt"] if u else b"\0" * 16
    ph = _hash(password or "", salt)
    if not u or not hmac.compare_digest(ph, u["pass_hash"]):
        raise ApiError(401, "Email ya password galat hai")
    if u["blocked"]:
        raise ApiError(403, "Ye account block hai")
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                 (hashlib.sha256(token.encode()).hexdigest(), u["id"], now() + SESSION_TTL))
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    return token, u


def user_by_token(conn, token):
    if not token:
        return None
    return conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.blocked=0",
        (hashlib.sha256(token.encode()).hexdigest(), now())).fetchone()


def logout(conn, token):
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


RESET_TTL = 3600


def audit(conn, admin_id, action, detail=""):
    conn.execute("INSERT INTO audit(admin_id,action,detail,created_at) VALUES(?,?,?,?)",
                 (admin_id, action[:40], str(detail)[:300], now()))


def make_reset_token(conn, user_id):
    token = secrets.token_urlsafe(32)
    with tx(conn):
        conn.execute("DELETE FROM password_resets WHERE user_id=? OR expires_at<?", (user_id, now()))
        conn.execute("INSERT INTO password_resets(token_hash,user_id,expires_at) VALUES(?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), user_id, now() + RESET_TTL))
    return token


def reset_password(conn, token, password):
    if len(password or "") < 8 or len(password) > 200:
        raise ApiError(400, "Password kam se kam 8 characters ka ho")
    th = hashlib.sha256((token or "").encode()).hexdigest()
    salt = secrets.token_bytes(16)
    ph = _hash(password, salt)
    with tx(conn):
        row = conn.execute("SELECT user_id FROM password_resets WHERE token_hash=? AND expires_at>?", (th, now())).fetchone()
        if not row:
            raise ApiError(400, "Reset link galat ya expire ho gaya")
        # token sirf ek baar chalta hai
        conn.execute("DELETE FROM password_resets WHERE token_hash=?", (th,))
        conn.execute("UPDATE users SET pass_hash=?, pass_salt=? WHERE id=?", (ph, salt, row["user_id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
    return row["user_id"]


# ---------------------------------------------------------------- wallet
def credit(conn, user_id, delta, reason, ref=""):
    """tx ke andar hi call karo."""
    row = conn.execute("SELECT balance FROM users WHERE id=?", (user_id,)).fetchone()
    nb = row["balance"] + delta
    if nb < 0:
        raise ApiError(402, "Balance kam hai")
    conn.execute("UPDATE users SET balance=? WHERE id=?", (nb, user_id))
    conn.execute("INSERT INTO ledger(user_id,delta,reason,ref,balance_after,created_at) VALUES(?,?,?,?,?,?)",
                 (user_id, delta, reason, str(ref), nb, now()))
    return nb


# ---------------------------------------------------------------- catalog
def available(conn, variation_id, mode):
    if mode == "auto":
        return conn.execute("SELECT COUNT(*) n FROM inventory WHERE variation_id=? AND status='available'",
                            (variation_id,)).fetchone()["n"]
    return conn.execute("SELECT stock FROM variations WHERE id=?", (variation_id,)).fetchone()["stock"]


def public_catalog(conn):
    out = []
    for c in conn.execute("SELECT * FROM categories WHERE active=1 ORDER BY position,id"):
        prods = []
        for p in conn.execute("SELECT * FROM products WHERE category_id=? AND active=1 ORDER BY position,id", (c["id"],)):
            vs = []
            for v in conn.execute("SELECT * FROM variations WHERE product_id=? AND active=1 ORDER BY position,price,id", (p["id"],)):
                stock = available(conn, v["id"], p["mode"])
                vs.append({"id": v["id"], "name": v["name"], "price": v["price"] / 100, "stock": stock,
                           "min_qty": v["min_qty"], "max_qty": v["max_qty"],
                           "prebook": p["mode"] == "auto" and stock == 0})
            if vs:
                prods.append({"id": p["id"], "name": p["name"], "description": p["description"], "image": p["image"],
                              "glyph": p["glyph"], "color": p["color"], "mode": p["mode"], "variations": vs})
        if prods:
            out.append({"id": c["id"], "name": c["name"], "emoji": c["emoji"], "products": prods})
    return out


# ---------------------------------------------------------------- orders
def _find_coupon(conn, code, user_id):
    code = (code or "").strip().upper()
    if not code:
        return None
    c = conn.execute("SELECT * FROM coupons WHERE code=? AND active=1", (code,)).fetchone()
    if not c or c["uses"] >= c["max_uses"]:
        raise ApiError(400, "Coupon sahi nahi hai ya use ho chuka hai")
    if conn.execute("SELECT 1 FROM coupon_uses WHERE coupon_id=? AND user_id=?", (c["id"], user_id)).fetchone():
        raise ApiError(400, "Ye coupon aap pehle use kar chuke ho")
    return c


def check_coupon(conn, user_id, code):
    c = _find_coupon(conn, code, user_id)
    return c["percent"] if c else 0


def _close_if_sold_out(conn, product_id):
    p = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not p["quick_drop"]:
        return
    for v in conn.execute("SELECT id FROM variations WHERE product_id=? AND active=1", (product_id,)):
        if available(conn, v["id"], p["mode"]) > 0:
            return
    conn.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))


def _deliver_items(conn, variation_id, qty, order_id):
    rows = conn.execute("SELECT id,content FROM inventory WHERE variation_id=? AND status='available' ORDER BY id LIMIT ?",
                        (variation_id, qty)).fetchall()
    if len(rows) < qty:
        return None
    for r in rows:
        conn.execute("UPDATE inventory SET status='sold', order_id=? WHERE id=?", (order_id, r["id"]))
    return "\n".join(r["content"] for r in rows)


def buy(conn, user_id, variation_id, qty, coupon_code=""):
    try:
        qty = int(qty)
        variation_id = int(variation_id)
    except (TypeError, ValueError):
        raise ApiError(400, "Request sahi nahi hai")
    with tx(conn):
        u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not u or u["blocked"]:
            raise ApiError(403, "Account block hai")
        v = conn.execute(
            "SELECT v.*, p.name pname, p.mode, p.active pa, p.id pid, c.active ca FROM variations v "
            "JOIN products p ON p.id=v.product_id JOIN categories c ON c.id=p.category_id WHERE v.id=?",
            (variation_id,)).fetchone()
        if not v or not (v["active"] and v["pa"] and v["ca"]):
            raise ApiError(404, "Ye plan available nahi hai")
        if qty < v["min_qty"] or qty > v["max_qty"]:
            raise ApiError(400, "Quantity %d se %d ke beech chuno" % (v["min_qty"], v["max_qty"]))
        stock = available(conn, variation_id, v["mode"])
        preorder = 0
        if v["mode"] == "auto":
            if stock == 0:
                preorder = 1
            elif stock < qty:
                raise ApiError(409, "Sirf %d available hain" % stock)
        elif stock < qty:
            raise ApiError(409, "Stock kam hai (%d bacha hai)" % stock)
        gross = v["price"] * qty
        coupon = _find_coupon(conn, coupon_code, user_id)
        discount = gross * coupon["percent"] // 100 if coupon else 0
        total = gross - discount
        if u["balance"] < total:
            raise ApiError(402, "Wallet balance kam hai. Pehle top-up karo")
        t = now()
        status = "pending" if preorder else ("completed" if v["mode"] == "auto" else "processing")
        cur = conn.execute(
            "INSERT INTO orders(user_id,variation_id,product_name,plan_name,mode,qty,unit_price,discount,total,coupon_code,"
            "preorder,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, variation_id, v["pname"], v["name"], v["mode"], qty, v["price"], discount, total,
             coupon["code"] if coupon else "", preorder, status, t, t))
        oid = cur.lastrowid
        credit(conn, user_id, -total, "order", oid)
        if coupon:
            conn.execute("UPDATE coupons SET uses=uses+1 WHERE id=?", (coupon["id"],))
            conn.execute("INSERT INTO coupon_uses(coupon_id,user_id,order_id) VALUES(?,?,?)", (coupon["id"], user_id, oid))
        if v["mode"] == "auto" and not preorder:
            text = _deliver_items(conn, variation_id, qty, oid)
            conn.execute("UPDATE orders SET delivery_text=? WHERE id=?", (text, oid))
        elif v["mode"] == "manual":
            conn.execute("UPDATE variations SET stock=stock-? WHERE id=?", (qty, variation_id))
        _close_if_sold_out(conn, v["pid"])
        return oid


def fulfil_preorders(conn, variation_id):
    """Inventory aane par pending pre-orders (purane pehle) apne aap deliver. tx ke andar call karo."""
    done = 0
    for o in conn.execute("SELECT * FROM orders WHERE variation_id=? AND preorder=1 AND status='pending' ORDER BY id",
                          (variation_id,)).fetchall():
        text = _deliver_items(conn, variation_id, o["qty"], o["id"])
        if text is None:
            break
        conn.execute("UPDATE orders SET status='completed', delivery_text=?, updated_at=? WHERE id=?", (text, now(), o["id"]))
        done += 1
    return done


def add_inventory(conn, variation_id, lines):
    lines = [l.strip() for l in lines if l and l.strip()]
    with tx(conn):
        v = conn.execute("SELECT v.id, p.mode, p.id pid FROM variations v JOIN products p ON p.id=v.product_id WHERE v.id=?",
                         (variation_id,)).fetchone()
        if not v:
            raise ApiError(404, "Plan nahi mila")
        if v["mode"] != "auto":
            raise ApiError(400, "Inventory sirf AUTO plans ke liye hai. Manual plan mein stock number badlo")
        have = {r["content"] for r in conn.execute("SELECT content FROM inventory WHERE variation_id=?", (variation_id,))}
        added = skipped = 0
        for l in lines:
            if l in have:
                skipped += 1
                continue
            have.add(l)
            conn.execute("INSERT INTO inventory(variation_id,content,created_at) VALUES(?,?,?)", (variation_id, l, now()))
            added += 1
        fulfilled = fulfil_preorders(conn, variation_id)
        return {"added": added, "skipped_duplicates": skipped, "preorders_fulfilled": fulfilled}


def deliver_manual(conn, order_id, text):
    text = (text or "").strip()
    if not text:
        raise ApiError(400, "Delivery details likho")
    with tx(conn):
        o = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o or o["status"] != "processing":
            raise ApiError(409, "Sirf 'processing' order deliver ho sakta hai")
        conn.execute("UPDATE orders SET status='completed', delivery_text=?, updated_at=? WHERE id=?", (text, now(), order_id))


def refund_order(conn, order_id):
    with tx(conn):
        o = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o or o["status"] in ("refunded", "cancelled"):
            raise ApiError(409, "Ye order refund nahi ho sakta")
        if o["status"] in ("pending", "processing") and o["mode"] == "manual":
            conn.execute("UPDATE variations SET stock=stock+? WHERE id=?", (o["qty"], o["variation_id"]))
        credit(conn, o["user_id"], o["total"], "refund", order_id)
        conn.execute("UPDATE orders SET status='refunded', updated_at=? WHERE id=?", (now(), order_id))


# ---------------------------------------------------------------- deposits
def _reward_referrer(conn, user_id):
    u = conn.execute("SELECT referred_by, ref_rewarded FROM users WHERE id=?", (user_id,)).fetchone()
    if u and u["referred_by"] and not u["ref_rewarded"]:
        reward = to_cents(get_settings(conn).get("referral_reward", "0"))
        conn.execute("UPDATE users SET ref_rewarded=1 WHERE id=?", (user_id,))
        if reward > 0:
            credit(conn, u["referred_by"], reward, "referral", user_id)


def _check_limits(settings, cents):
    lo, hi = to_cents(settings["min_deposit"]), to_cents(settings["max_deposit"])
    if cents < lo or cents > hi:
        raise ApiError(400, "Deposit $%s se $%s ke beech hona chahiye" % (settings["min_deposit"], settings["max_deposit"]))


INTENT_TTL = 2 * 3600


def create_crypto_intent(conn, user_id, amount):
    """User ko unique exact USDT amount deta hai, taaki tx hash sirf usi se match ho (doosra user claim na kar sake)."""
    settings = get_settings(conn)
    if "usdt_bep20" not in settings["methods_enabled"].split(","):
        raise ApiError(400, "USDT payment abhi band hai")
    base = to_cents(amount)
    _check_limits(settings, base)
    with tx(conn):
        t = now()
        conn.execute("UPDATE crypto_intents SET used=2 WHERE used=0 AND expires_at<?", (t,))
        ks = list(range(1, 100))
        secrets.SystemRandom().shuffle(ks)
        for k in ks:
            exp = base * 100 + k
            if not conn.execute("SELECT 1 FROM crypto_intents WHERE expected=? AND used=0", (exp,)).fetchone():
                conn.execute("INSERT INTO crypto_intents(user_id,expected,created_at,expires_at) VALUES(?,?,?,?)",
                             (user_id, exp, t, t + INTENT_TTL))
                return {"expected": "%d.%04d" % (exp // 10000, exp % 10000), "expires_in_minutes": INTENT_TTL // 60}
        raise ApiError(503, "Abhi bahut requests hain, thodi der baad try karo")


def create_deposit(conn, user_id, method, amount, reference, rpc=payments.rpc_call):
    settings = get_settings(conn)
    if method not in settings["methods_enabled"].split(","):
        raise ApiError(400, "Ye payment method abhi band hai")
    ref = payments.validate_reference(method, reference)
    if conn.execute("SELECT 1 FROM deposits WHERE method=? AND reference=? AND status IN ('pending','approved')",
                    (method, ref)).fetchone():
        raise ApiError(409, "Ye reference pehle se submit ho chuka hai")
    units = None
    if method == "usdt_bep20":
        usdt = payments.verify_usdt_bep20(ref, settings, rpc)
        scaled = usdt * 10000
        if scaled != scaled.to_integral_value():
            raise ApiError(400, "Amount exact match nahi hua. Bataya hua exact amount hi bhejna hota hai; support se baat karo")
        units = int(scaled)
        cents = units // 100
        _check_limits_min_only(settings, cents)
        status = "approved"
    else:
        cents = to_cents(amount)
        _check_limits(settings, cents)
        status = "pending"
    with tx(conn):
        if units is not None:
            it = conn.execute("SELECT id FROM crypto_intents WHERE user_id=? AND expected=? AND used=0 AND expires_at>=?",
                              (user_id, units, now())).fetchone()
            if not it:
                raise ApiError(409, "Ye payment aapki kisi active top-up request se match nahi hui. "
                                    "Pehle 'USDT top-up' request banao aur bataya hua exact amount bhejo; "
                                    "galti hui ho to support se baat karo")
            conn.execute("UPDATE crypto_intents SET used=1 WHERE id=?", (it["id"],))
        if conn.execute("SELECT 1 FROM deposits WHERE method=? AND reference=? AND status IN ('pending','approved')",
                        (method, ref)).fetchone():
            raise ApiError(409, "Ye reference pehle se submit ho chuka hai")
        t = now()
        cur = conn.execute("INSERT INTO deposits(user_id,method,amount,reference,status,created_at,decided_at) VALUES(?,?,?,?,?,?,?)",
                           (user_id, method, cents, ref, status, t, t if status == "approved" else None))
        if status == "approved":
            credit(conn, user_id, cents, "deposit", cur.lastrowid)
            _reward_referrer(conn, user_id)
        return {"id": cur.lastrowid, "status": status, "amount": cents / 100}


def _check_limits_min_only(settings, cents):
    if cents < to_cents(settings["min_deposit"]):
        raise ApiError(400, "Minimum deposit $%s hai" % settings["min_deposit"])


def decide_deposit(conn, deposit_id, action, note=""):
    if action not in ("approve", "reject"):
        raise ApiError(400, "Action sahi nahi hai")
    with tx(conn):
        d = conn.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
        if not d or d["status"] != "pending":
            raise ApiError(409, "Ye deposit pending nahi hai")
        st = "approved" if action == "approve" else "rejected"
        conn.execute("UPDATE deposits SET status=?, note=?, decided_at=? WHERE id=?", (st, (note or "")[:200], now(), deposit_id))
        if st == "approved":
            credit(conn, d["user_id"], d["amount"], "deposit", deposit_id)
            _reward_referrer(conn, d["user_id"])
