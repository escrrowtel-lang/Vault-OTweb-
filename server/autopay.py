"""Automatic payment verification.

- UPI: bank / FamPay ke "credited" alert email (IMAP) se. Email se amount + 12-digit UTR nikalte hain.
- Binance ID: Binance Pay trade history API (read-only key) se incoming transfer.

Dono jagah user ka bataya hua amount kabhi nahi maana jata: amount hamesha email / API se aata hai.
Secrets sirf environment se (IMAP_HOST, IMAP_USER, IMAP_PASS, BINANCE_API_KEY, BINANCE_API_SECRET).
"""
import email
import hashlib
import hmac
import imaplib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr
from html import unescape

import store
from db import ApiError, connect, get_settings, tx

AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
UTR_LABEL_RE = re.compile(r"(?:utr|rrn|ref(?:erence)?(?:\s*(?:no|number|id))?|upi\s*ref\w*)\D{0,12}(\d{12})\b", re.I)
TWELVE_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
CREDIT_RE = re.compile(r"credited|received|credit of|money in|deposited", re.I)
DEBIT_RE = re.compile(r"debited|sent to|paid to|withdrawn", re.I)

STABLE = {"USDT", "USDC", "BUSD", "FDUSD"}  # 1:1 USD maane jaate hain


# ------------------------------------------------------------------ parsing
def parse_alert(text):
    """Return (paise:int, utr:str) ya None agar ye saaf 'credit' alert nahi hai."""
    t = re.sub(r"\s+", " ", text or "")
    if not CREDIT_RE.search(t):
        return None
    if DEBIT_RE.search(t) and not re.search(r"credited", t, re.I):
        return None
    m = AMOUNT_RE.search(t)
    if not m:
        return None
    try:
        paise = int((Decimal(m.group(1).replace(",", "")) * 100).to_integral_value())
    except InvalidOperation:
        return None
    if paise <= 0:
        return None
    u = UTR_LABEL_RE.search(t)
    if u:
        utr = u.group(1)
    else:
        found = set(TWELVE_RE.findall(t))
        if len(found) != 1:  # 0 ya ek se zyada: guess nahi karte
            return None
        utr = found.pop()
    return paise, utr


def _text_of(msg):
    parts, html = [], []
    for p in msg.walk():
        ct = p.get_content_type()
        if ct in ("text/plain", "text/html"):
            try:
                body = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            (parts if ct == "text/plain" else html).append(body)
    if parts:
        return "\n".join(parts)
    return unescape(re.sub(r"<[^>]+>", " ", "\n".join(html)))


def sender_ok(msg, allowed, require_dkim=True):
    name, addr = parseaddr(msg.get("From", ""))
    addr = addr.lower()
    allowed = [a.strip().lower() for a in (allowed or "").split(",") if a.strip()]
    if not addr or not allowed:
        return False
    if not any(addr == a or (a.startswith("@") and addr.endswith(a)) for a in allowed):
        return False
    if require_dkim:
        res = " ".join(msg.get_all("Authentication-Results", [])).lower()
        if "dkim=pass" not in res:
            return False
    return True


# ------------------------------------------------------------------ matching
def _rate(settings):
    try:
        return Decimal(settings.get("usd_inr_rate") or "100")
    except InvalidOperation:
        return Decimal(100)


def record_incoming(conn, source, ref, amount, currency=""):
    """Naya incoming payment save karo (duplicate ignore). True agar naya tha."""
    with tx(conn):
        if conn.execute("SELECT 1 FROM incoming WHERE source=? AND ref=?", (source, ref)).fetchone():
            return False
        conn.execute("INSERT INTO incoming(source,ref,amount,currency,created_at) VALUES(?,?,?,?,?)",
                     (source, ref, amount, currency, store.now()))
        return True


def match_incoming(conn, source, ref):
    """Pending deposit se milao; amount kaafi ho to approve. True agar approve hua."""
    settings = get_settings(conn)
    method = "upi" if source == "upi" else "binance_id"
    inc = conn.execute("SELECT * FROM incoming WHERE source=? AND ref=?", (source, ref)).fetchone()
    if not inc or inc["deposit_id"]:
        return False
    d = conn.execute("SELECT * FROM deposits WHERE method=? AND reference=? AND status='pending'",
                     (method, ref)).fetchone()
    if not d:
        return False
    if source == "upi":
        need = int((Decimal(d["amount"]) * _rate(settings)).to_integral_value())  # cents -> paise
    else:
        need = d["amount"]
    if inc["amount"] < need:
        return False  # kam paisa aaya: admin dekhega
    try:
        store.decide_deposit(conn, d["id"], "approve", "auto-verified (%s)" % source)
    except ApiError:
        return False  # kisi aur ne pehle decide kar diya
    with tx(conn):
        conn.execute("UPDATE incoming SET deposit_id=? WHERE id=?", (d["id"], inc["id"]))
    return True


def try_match_deposit(conn, method, ref):
    """Deposit submit hote hi try karo (email pehle aa chuki ho sakti hai)."""
    try:
        return match_incoming(conn, "upi" if method == "upi" else "binance_id", ref)
    except Exception as e:  # submit kabhi fail na ho
        print("autopay match error: %s" % e, file=sys.stderr)
        return False


# ------------------------------------------------------------------ UPI (IMAP)
def poll_mail(conn, client_factory=None):
    s = get_settings(conn)
    if s.get("upi_auto") != "1":
        return 0
    host, user, pw = os.environ.get("IMAP_HOST", ""), os.environ.get("IMAP_USER", ""), os.environ.get("IMAP_PASS", "")
    if not (host and user and pw):
        return 0
    box = (client_factory or (lambda: imaplib.IMAP4_SSL(host, int(os.environ.get("IMAP_PORT", "993")), timeout=30)))()
    n = 0
    try:
        box.login(user, pw)
        box.select("INBOX")
        typ, data = box.search(None, "UNSEEN")
        for num in (data[0].split() if typ == "OK" and data and data[0] else [])[:200]:
            typ, parts = box.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            msg = email.message_from_bytes(parts[0][1])
            if sender_ok(msg, s.get("upi_alert_senders", ""), s.get("upi_require_dkim", "1") != "0"):
                got = parse_alert(msg.get("Subject", "") + "\n" + _text_of(msg))
                if got:
                    paise, utr = got
                    record_incoming(conn, "upi", utr, paise, "INR")
                    if match_incoming(conn, "upi", utr):
                        n += 1
            box.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return n


# ------------------------------------------------------------------ Binance Pay history
def _binance_get(path, params, key, secret):
    params = dict(params, timestamp=int(time.time() * 1000), recvWindow=10000)
    q = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("https://api.binance.com%s?%s&signature=%s" % (path, q, sig),
                                 headers={"X-MBX-APIKEY": key})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def poll_binance(conn, call=_binance_get):
    s = get_settings(conn)
    key, secret = os.environ.get("BINANCE_API_KEY", ""), os.environ.get("BINANCE_API_SECRET", "")
    if s.get("binance_auto") != "1" or not (key and secret):
        return 0
    out = call("/sapi/v1/pay/transactions", {"startTime": int((time.time() - 3 * 86400) * 1000), "limit": 100}, key, secret)
    if str(out.get("code")) != "000000":
        raise RuntimeError("Binance error: %s" % out.get("message"))
    n = 0
    for t in out.get("data") or []:
        if t.get("orderType") not in ("C2C", "C2C_HOLDING", "PAY"):
            continue
        cur = str(t.get("currency", "")).upper()
        try:
            amt = Decimal(str(t.get("amount")))
        except InvalidOperation:
            continue
        tid = str(t.get("transactionId", ""))
        if amt <= 0 or cur not in STABLE or not tid:
            continue  # sirf incoming stablecoin; baaki (BNB etc.) admin manual
        cents = int((amt * 100).to_integral_value(rounding="ROUND_DOWN"))
        record_incoming(conn, "binance_id", tid, cents, cur)
        if match_incoming(conn, "binance_id", tid):
            n += 1
    return n


# ------------------------------------------------------------------ background
STATUS = {"mail": "", "binance": "", "at": 0}


def _loop():
    conn = None
    while True:
        try:
            conn = conn or connect()
            for name, fn in (("mail", poll_mail), ("binance", poll_binance)):
                try:
                    STATUS[name] = "ok (%d)" % fn(conn)
                except Exception as e:
                    STATUS[name] = "error: %s" % str(e)[:120]
                    print("autopay %s: %s" % (name, e), file=sys.stderr, flush=True)
            STATUS["at"] = int(time.time())
        except Exception as e:
            print("autopay loop: %s" % e, file=sys.stderr, flush=True)
            try:
                conn and conn.close()
            except Exception:
                pass
            conn = None
        time.sleep(int(os.environ.get("AUTOPAY_INTERVAL", "30")))


def start():
    threading.Thread(target=_loop, daemon=True, name="autopay").start()
