"""Forward orders to a supplier API and keep them in sync.

Flow for a supplier-backed product (suppliers.kind = 'prodseller'):
  1. store.buy() charges the wallet and queues a row in supplier_orders (same transaction).
  2. forward() sends POST /orders with a stable Idempotency-Key, so a retry can never double-buy.
  3. Instant delivery  -> the order is completed with the delivered key(s).
     Email activation  -> the supplier activates the customer's email; we poll until it is delivered.
     Definite rejection (out of stock, supplier balance too low, bad key) -> customer is refunded automatically.
     Network trouble / 5xx -> stays queued and is retried; after too many attempts it is flagged for the admin.
"""
import json
import sys
import threading
import time
from decimal import Decimal, InvalidOperation

import store
import suppliers
from db import ApiError, connect, tx

MAX_ATTEMPTS = 8
SYNC_EVERY = 600


def _cents(v):
    try:
        return int((Decimal(str(v)) * 100).to_integral_value())
    except (InvalidOperation, TypeError, ValueError):
        return 0


def _lines(j):
    keys = j.get("deliveredKeys")
    if not keys and j.get("deliveredKey"):
        keys = [j["deliveredKey"]]
    out = [str(k) for k in (keys or [])]
    for name in ("activationInstructions", "actionInstructions"):
        v = j.get(name)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, list):
            out += [str(x) for x in v if str(x).strip()]
    return "\n".join(out)


def _log(conn, so, msg):
    try:
        with tx(conn):
            store.audit(conn, None, "supplier_order", "order #%d: %s" % (so["order_id"], msg))
    except Exception:
        pass


def kick(so_id):
    """Forward right after checkout, on its own connection, so the customer does not wait for the 20 s loop."""
    def run():
        c = None
        try:
            c = connect()
            forward(c, so_id)
        except Exception as e:
            print("fulfil kick: %s" % e, file=sys.stderr, flush=True)
        finally:
            try:
                c and c.close()
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


def _set(conn, sid, **cols):
    cols["updated_at"] = store.now()
    with tx(conn):
        conn.execute("UPDATE supplier_orders SET %s WHERE id=?" % ",".join("%s=?" % k for k in cols), list(cols.values()) + [sid])


def _complete(conn, so, j):
    text = _lines(j)
    with tx(conn):
        o = conn.execute("SELECT status FROM orders WHERE id=?", (so["order_id"],)).fetchone()
        if o and o["status"] == "processing":
            conn.execute("UPDATE orders SET status='completed', delivery_text=?, updated_at=? WHERE id=?", (text, store.now(), so["order_id"]))
    _set(conn, so["id"], status="delivered", external_id=str(j.get("orderId", so["external_id"]))[:120], cost=_cents(j.get("amount")), error="")
    _log(conn, so, "delivered by supplier (cost $%.2f)" % (_cents(j.get("amount")) / 100))


def _fail(conn, so, why, refund=True):
    _set(conn, so["id"], status="failed" if refund else "attention", error=str(why)[:300])
    _log(conn, so, "supplier could not fulfil it (%s)%s" % (str(why)[:120], "; customer refunded" if refund else ""))
    if refund:
        try:
            store.refund_order(conn, so["order_id"])
        except ApiError:
            pass


def _api_error(body):
    try:
        return str(json.loads(body).get("error", ""))[:200]
    except (ValueError, AttributeError):
        return ""


def forward(conn, so_id):
    """Send one queued supplier order. Safe to call repeatedly."""
    so = conn.execute("SELECT * FROM supplier_orders WHERE id=?", (so_id,)).fetchone()
    if not so or so["status"] not in ("queued", "attention"):
        return so
    sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (so["supplier_id"],)).fetchone()
    o = conn.execute("SELECT * FROM orders WHERE id=?", (so["order_id"],)).fetchone()
    if not sup or not o or o["status"] != "processing":
        return so
    body = {"productId": so["product_ext"], "quantity": o["qty"]}
    emails = [e for e in so["emails"].split(",") if e]
    if len(emails) == 1:
        body["email"] = emails[0]
    elif emails:
        body["emails"] = emails
    _set(conn, so["id"], attempts=so["attempts"] + 1)
    try:
        status, _, text = suppliers.request(sup, "/orders", timeout=25, method="POST", body=body,
                                            extra={"Idempotency-Key": "vaultstore-order-%d" % so["order_id"]})
    except ApiError as e:
        if so["attempts"] + 1 >= MAX_ATTEMPTS:
            _set(conn, so["id"], status="attention", error="Supplier unreachable: %s" % e.msg)
            _log(conn, so, "needs attention: supplier unreachable")
        else:
            _set(conn, so["id"], status="queued", error=e.msg)
        return conn.execute("SELECT * FROM supplier_orders WHERE id=?", (so_id,)).fetchone()
    try:
        j = json.loads(text)
    except ValueError:
        j = {}
    so = conn.execute("SELECT * FROM supplier_orders WHERE id=?", (so_id,)).fetchone()
    if 200 <= status < 300:
        _set(conn, so_id, external_id=str(j.get("orderId", ""))[:120], cost=_cents(j.get("amount")), status="sent")
        _log(conn, so, "sent to supplier (supplier order %s)" % str(j.get("orderId", "?"))[:40])
        so = conn.execute("SELECT * FROM supplier_orders WHERE id=?", (so_id,)).fetchone()
        if j.get("status") == "delivered" and _lines(j):
            _complete(conn, so, j)
        elif j.get("status") == "failed":
            _fail(conn, so, "Supplier reported the order as failed")
    elif status in (400, 402, 404, 409, 401, 403):
        why = _api_error(text) or "HTTP %d" % status
        if status in (401, 403):
            why = "Supplier rejected the API key (%s)" % why
        elif status == 402:
            why = "Supplier balance too low (%s)" % why
        _fail(conn, so, why)
    else:  # 429 / 5xx: try again later with the same idempotency key
        if so["attempts"] >= MAX_ATTEMPTS:
            _set(conn, so_id, status="attention", error="HTTP %d after %d attempts" % (status, so["attempts"]))
            _log(conn, so, "needs attention: HTTP %d" % status)
        else:
            _set(conn, so_id, status="queued", error="HTTP %d, will retry" % status)
    return conn.execute("SELECT * FROM supplier_orders WHERE id=?", (so_id,)).fetchone()


def poll(conn, so):
    """Check an order the supplier accepted but has not delivered yet (e.g. email activation)."""
    sup = conn.execute("SELECT * FROM suppliers WHERE id=?", (so["supplier_id"],)).fetchone()
    if not sup or not so["external_id"]:
        return
    status, _, text = suppliers.request(sup, "/orders/" + so["external_id"], timeout=15)
    if status != 200:
        return
    j = json.loads(text)
    if j.get("status") == "delivered" and _lines(j):
        _complete(conn, so, j)
    elif j.get("status") == "failed":
        _fail(conn, so, "Supplier reported the order as failed")


def run_once(conn):
    t = store.now()
    for so in conn.execute("SELECT * FROM supplier_orders WHERE status='queued' ORDER BY id LIMIT 50").fetchall():
        if so["attempts"] == 0 or t - so["updated_at"] >= min(30 * so["attempts"], 300):
            forward(conn, so["id"])
    for so in conn.execute("SELECT * FROM supplier_orders WHERE status='sent' ORDER BY id LIMIT 50").fetchall():
        try:
            poll(conn, so)
        except (ApiError, ValueError):
            pass


def sync_catalogs(conn):
    for sup in conn.execute("SELECT * FROM suppliers WHERE active=1 AND auto_sync=1 AND catalog_path<>''").fetchall():
        try:
            suppliers.import_catalog(conn, sup, sup["catalog_path"], float(sup["markup"] or 0), bool(sup["cents"]), dry=False)
        except Exception as e:
            print("supplier sync %s: %s" % (sup["name"], e), file=sys.stderr, flush=True)


def _loop():
    conn, last = None, 0
    while True:
        try:
            conn = conn or connect()
            run_once(conn)
            if time.time() - last > SYNC_EVERY:
                last = time.time()
                sync_catalogs(conn)
        except Exception as e:
            print("fulfil loop: %s" % e, file=sys.stderr, flush=True)
            try:
                conn and conn.close()
            except Exception:
                pass
            conn = None
        time.sleep(20)


def start():
    threading.Thread(target=_loop, daemon=True, name="fulfil").start()
