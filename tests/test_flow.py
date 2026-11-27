import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer

tmp = tempfile.mkdtemp()
os.environ["VAULT_DB"] = os.path.join(tmp, "t.db")
os.environ["VAULT_UPLOADS"] = os.path.join(tmp, "up")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import db, store, payments, app  # noqa
from db import ApiError, connect

db.init()
conn = connect()
ME = "0x" + "ab" * 20
USDT = "0x55d398326f99059fF775485246999027B3197955"
conn.execute("UPDATE settings SET value=? WHERE key='usdt_address'", (ME,))
conn.execute("UPDATE settings SET value='upi_id_x' WHERE key='upi_id'")


def mk(email="a@example.com", **kw):
    return store.create_user(conn, email, "password123", **kw)


def catalog(mode="auto", price="4.80", quick=0):
    cid = conn.execute("INSERT INTO categories(name) VALUES('C')").lastrowid
    pid = conn.execute("INSERT INTO products(category_id,name,mode,quick_drop) VALUES(?,?,?,?)", (cid, "P", mode, quick)).lastrowid
    vid = conn.execute("INSERT INTO variations(product_id,name,price,min_qty,max_qty,stock) VALUES(?,?,?,1,3,?)",
                       (pid, "1 Month", db.to_cents(price), 2 if mode == "manual" else 0)).lastrowid
    return pid, vid


def fund(uid, usd):
    with db.tx(conn):
        store.credit(conn, uid, db.to_cents(usd), "test")


def bal(uid):
    return conn.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"]


def fake_rpc(logs_to=ME, amount_units=10_0037 * 10 ** 14, block=100, head=120, status="0x1", contract=USDT):
    topic_to = "0x" + "0" * 24 + logs_to[2:]

    def call(url, method, params):
        if method == "eth_blockNumber":
            return hex(head)
        return {"status": status, "blockNumber": hex(block), "logs": [{
            "address": contract, "topics": [payments.TRANSFER_TOPIC, "0x" + "0" * 64, topic_to], "data": hex(amount_units)}]}
    return call


class Flow(unittest.TestCase):
    def test_auto_purchase_and_stock(self):
        uid = mk("auto@example.com")
        pid, vid = catalog()
        r = store.add_inventory(conn, vid, ["acc1:pw", "acc2:pw", "acc1:pw", ""])
        self.assertEqual((r["added"], r["skipped_duplicates"]), (2, 1))
        with self.assertRaises(ApiError):  # balance kam
            store.buy(conn, uid, vid, 1)
        fund(uid, "20")
        oid = store.buy(conn, uid, vid, 2)
        o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        self.assertEqual((o["status"], o["total"], o["delivery_text"]), ("completed", 960, "acc1:pw\nacc2:pw"))
        self.assertEqual(bal(uid), 2000 - 960)
        self.assertEqual(store.available(conn, vid, "auto"), 0)

    def test_preorder_fulfilled_on_restock_in_order(self):
        u1, u2 = mk("p1@example.com"), mk("p2@example.com")
        pid, vid = catalog()
        fund(u1, "10"); fund(u2, "10")
        o1 = store.buy(conn, u1, vid, 1)
        o2 = store.buy(conn, u2, vid, 1)
        self.assertEqual(conn.execute("SELECT status,preorder FROM orders WHERE id=?", (o1,)).fetchone()[:], ("pending", 1))
        r = store.add_inventory(conn, vid, ["x1"])
        self.assertEqual(r["preorders_fulfilled"], 1)
        self.assertEqual(conn.execute("SELECT status,delivery_text FROM orders WHERE id=?", (o1,)).fetchone()[:], ("completed", "x1"))
        self.assertEqual(conn.execute("SELECT status FROM orders WHERE id=?", (o2,)).fetchone()[0], "pending")

    def test_manual_flow_refund_and_coupon(self):
        uid = mk("man@example.com")
        pid, vid = catalog("manual", "10.00")
        fund(uid, "30")
        conn.execute("INSERT INTO coupons(code,percent) VALUES('SAVE10',10)")
        oid = store.buy(conn, uid, vid, 1, "save10")
        o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        self.assertEqual((o["status"], o["total"], o["discount"]), ("processing", 900, 100))
        with self.assertRaises(ApiError):  # coupon dobara nahi
            store.buy(conn, uid, vid, 1, "SAVE10")
        self.assertEqual(conn.execute("SELECT stock FROM variations WHERE id=?", (vid,)).fetchone()[0], 1)
        store.deliver_manual(conn, oid, "login: x")
        self.assertEqual(conn.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "completed")
        store.refund_order(conn, oid)
        self.assertEqual(bal(uid), 3000)
        with self.assertRaises(ApiError):  # double refund
            store.refund_order(conn, oid)

    def test_quantity_limits_and_quick_drop(self):
        uid = mk("q@example.com")
        pid, vid = catalog(quick=1)
        fund(uid, "50")
        store.add_inventory(conn, vid, ["a", "b"])
        with self.assertRaises(ApiError):
            store.buy(conn, uid, vid, 4)
        with self.assertRaises(ApiError):
            store.buy(conn, uid, vid, 3)  # stock 2
        store.buy(conn, uid, vid, 2)
        self.assertEqual(conn.execute("SELECT active FROM products WHERE id=?", (pid,)).fetchone()[0], 0)

    def test_manual_deposit_referral_and_duplicate_utr(self):
        ref = mk("ref@example.com")
        code = conn.execute("SELECT ref_code FROM users WHERE id=?", (ref,)).fetchone()[0]
        uid = mk("new@example.com", ref=code)
        d = store.create_deposit(conn, uid, "upi", "5", "123456789012")
        self.assertEqual(d["status"], "pending")
        with self.assertRaises(ApiError):
            store.create_deposit(conn, ref, "upi", "5", "123456789012")
        with self.assertRaises(ApiError):
            store.create_deposit(conn, uid, "upi", "5", "12345")
        with self.assertRaises(ApiError):
            store.create_deposit(conn, uid, "upi", "0.5", "999999999999")  # min $1
        self.assertEqual(bal(uid), 0)
        store.decide_deposit(conn, d["id"], "approve")
        self.assertEqual(bal(uid), 500)
        self.assertEqual(bal(ref), 10)  # referral reward
        with self.assertRaises(ApiError):
            store.decide_deposit(conn, d["id"], "approve")  # double approve
        d2 = store.create_deposit(conn, uid, "upi", "5", "222222222222")
        store.decide_deposit(conn, d2["id"], "approve")
        self.assertEqual(bal(ref), 10)  # reward sirf ek baar

    def test_usdt_verification(self):
        a, b = mk("u1@example.com"), mk("u2@example.com")
        it = store.create_crypto_intent(conn, a, "10")
        units = int(it["expected"].replace(".", ""))
        self.assertTrue(it["expected"].startswith("10.00"))
        tx_hash = "0x" + "11" * 32
        rpc = fake_rpc(amount_units=units * 10 ** 14)
        # doosra user (b) claim nahi kar sakta
        with self.assertRaises(ApiError):
            store.create_deposit(conn, b, "usdt_bep20", 0, tx_hash, rpc)
        self.assertEqual(bal(b), 0)
        d = store.create_deposit(conn, a, "usdt_bep20", 0, tx_hash, rpc)
        self.assertEqual(d["status"], "approved")
        self.assertEqual(bal(a), units // 100)
        with self.assertRaises(ApiError):  # dobara same hash
            store.create_deposit(conn, a, "usdt_bep20", 0, tx_hash, rpc)

    def test_usdt_rejects_bad_tx(self):
        a = mk("u3@example.com")
        h = "0x" + "22" * 32
        for rpc, why in [(fake_rpc(head=102), "confirmations"), (fake_rpc(status="0x0"), "failed"),
                         (fake_rpc(logs_to="0x" + "cd" * 20), "wrong address"),
                         (fake_rpc(contract="0x" + "ee" * 20), "wrong token")]:
            with self.assertRaises(ApiError, msg=why):
                store.create_deposit(conn, a, "usdt_bep20", 0, h, rpc)
        with self.assertRaises(ApiError):
            store.create_deposit(conn, a, "usdt_bep20", 0, h, lambda *x: None)  # tx nahi mili
        self.assertEqual(bal(a), 0)


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None, headers=None, opener=None):
        h = {"Content-Type": "application/json"}
        if method == "POST":
            h["X-Requested-With"] = "fetch"
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=h, method=method)
        try:
            with (opener or self.op).open(req) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_http_end_to_end(self):
        s, _ = self.call("POST", "/api/auth/register", {"email": "web@example.com", "password": "password123"})
        self.assertEqual(s, 200)
        self.assertEqual(self.call("GET", "/api/me")[1]["user"]["email"], "web@example.com")
        self.assertEqual(self.call("GET", "/api/admin/stats")[0], 403)  # user admin nahi
        # CSRF: header ke bina POST rejected
        req = urllib.request.Request(self.base + "/api/buy", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.op.open(req)
        self.assertEqual(cm.exception.code, 403)
        # anonymous
        anon = urllib.request.build_opener()
        self.assertEqual(self.call("GET", "/api/orders", opener=anon)[0], 401)
        self.assertEqual(self.call("GET", "/api/catalog", opener=anon)[0], 200)
        # settings mein secret nahi
        st = self.call("GET", "/api/settings", opener=anon)[1]
        self.assertNotIn("bsc_rpc", st)
        # admin flow
        store.create_user(conn, "boss@example.com", "password123", is_admin=1)
        admin = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self.assertEqual(self.call("POST", "/api/auth/login", {"email": "resetadmin@example.com", "password": "password123"}, opener=admin)[0], 200)
        c = lambda p, b: self.call("POST", p, b, opener=admin)
        self.assertEqual(c("/api/admin/category", {"name": "Streaming", "emoji": "🎬"})[0], 200)
        cid = self.call("GET", "/api/admin/catalog", opener=admin)[1]["categories"][-1]["id"]
        self.assertEqual(c("/api/admin/product", {"category_id": cid, "name": "Web P", "mode": "auto", "image": "javascript:alert(1)"})[0], 400)
        self.assertEqual(c("/api/admin/product", {"category_id": cid, "name": "Web P", "mode": "auto"})[0], 200)
        pid = self.call("GET", "/api/admin/catalog", opener=admin)[1]["categories"][-1]["products"][-1]["id"]
        self.assertEqual(c("/api/admin/variation", {"product_id": pid, "name": "1 Month", "price": "4.80", "max_qty": 2})[0], 200)
        vid = self.call("GET", "/api/admin/catalog", opener=admin)[1]["categories"][-1]["products"][-1]["variations"][0]["id"]
        self.assertEqual(c("/api/admin/inventory", {"variation_id": vid, "text": "u1:p1\nu2:p2"})[1]["added"], 2)
        # catalog mein inventory content leak nahi
        cat = json.dumps(self.call("GET", "/api/catalog", opener=anon)[1])
        self.assertNotIn("u1:p1", cat)
        # user ko wallet chahiye
        self.assertEqual(self.call("POST", "/api/buy", {"variation_id": vid, "qty": 1})[0], 402)
        uid = conn.execute("SELECT id FROM users WHERE email='web@example.com'").fetchone()[0]
        c("/api/admin/user/adjust", {"id": uid, "amount": "10", "reason": "test"})
        s, out = self.call("POST", "/api/buy", {"variation_id": vid, "qty": 1})
        self.assertEqual((s, out["order"]["delivery_text"], out["balance"]), (200, "u1:p1", 5.2))
        # upload: svg/script rejected, png ok
        import base64
        bad = base64.b64encode(b"<svg onload=alert(1)>").decode()
        self.assertEqual(c("/api/admin/upload", {"data": bad})[0], 400)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 20).decode()
        s, up = c("/api/admin/upload", {"data": png})
        self.assertEqual(s, 200)
        self.assertEqual(urllib.request.urlopen(self.base + up["url"]).headers["Content-Type"], "image/png")
        # path traversal
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.base + "/%2e%2e/server/db.py")

    def test_forgot_no_enumeration_and_admin_reset_link(self):
        def op():
            return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        victim = mk("victim@example.com")
        mk("resetadmin@example.com", is_admin=1)
        anon = op()
        a = self.call("POST", "/api/auth/forgot", {"email": "nobody@example.com"}, opener=anon)
        b = self.call("POST", "/api/auth/forgot", {"email": "victim@example.com"}, opener=op())
        self.assertEqual((a[0], a[1]), (b[0], b[1]))          # registered ho ya nahi, same jawab
        self.assertEqual(self.call("POST", "/api/auth/reset", {"token": "bogus", "password": "whatever123"}, opener=anon)[0], 400)
        admin = op()
        self.assertEqual(self.call("POST", "/api/auth/login", {"email": "resetadmin@example.com", "password": "password123"}, opener=admin)[0], 200)
        s, out = self.call("POST", "/api/admin/user/reset-link", {"id": victim}, opener=admin)
        self.assertEqual(s, 200)
        tok = out["path"].split("token=")[1]
        self.assertEqual(self.call("POST", "/api/auth/reset", {"token": tok, "password": "newer-pass-123"}, opener=anon)[0], 200)
        self.assertEqual(self.call("POST", "/api/auth/reset", {"token": tok, "password": "newer-pass-456"}, opener=anon)[0], 400)
        # normal (anonymous) user reset-link nahi bana sakta
        self.assertIn(self.call("POST", "/api/admin/user/reset-link", {"id": victim}, opener=op())[0], (401, 403))
        self.assertTrue(self.call("GET", "/api/admin/audit", opener=admin)[1]["audit"])


class Concurrency(unittest.TestCase):
    """Asli parallel connections (har thread ka apna connection). SQLite aur PostgreSQL dono par chalta hai."""

    def run_parallel(self, jobs):
        gate = threading.Barrier(len(jobs))
        results = [None] * len(jobs)

        def work(i, fn):
            c = connect()
            try:
                gate.wait(10)
                results[i] = ("ok", fn(c))
            except ApiError as e:
                results[i] = ("api", e.status)
            except BaseException as e:  # noqa - koi bhi aur error = bug
                results[i] = ("BUG", repr(e))
            finally:
                c.close()
        ths = [threading.Thread(target=work, args=(i, fn)) for i, fn in enumerate(jobs)]
        [x.start() for x in ths]
        [x.join(30) for x in ths]
        self.assertFalse([r for r in results if r is None or r[0] == "BUG"], results)
        return results

    def bal(self, uid):
        return conn.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()[0]

    def test_last_item_sold_once(self):
        # Sold-out auto plan par pre-order banta hai (design). Isliye: item ek hi ko mile, baaki pending pre-order.
        pid, vid = catalog("auto", "4.80")
        store.add_inventory(conn, vid, ["only:one"])
        users = [mk("race_last%d@example.com" % i) for i in range(10)]
        for u in users:
            fund(u, "50")
        res = self.run_parallel([(lambda c, u=u: store.buy(c, u, vid, 1)) for u in users])
        self.assertEqual(sum(1 for r in res if r[0] == "ok"), 10, res)
        q = lambda s: conn.execute(s, (vid,)).fetchone()[0]
        self.assertEqual(q("SELECT COUNT(*) FROM orders WHERE variation_id=? AND status='completed'"), 1)
        self.assertEqual(q("SELECT COUNT(*) FROM orders WHERE variation_id=? AND status='pending' AND preorder=1"), 9)
        self.assertEqual(q("SELECT COUNT(*) FROM inventory WHERE variation_id=? AND status='sold'"), 1)
        self.assertEqual(q("SELECT COUNT(*) FROM orders WHERE variation_id=? AND delivery_text LIKE '%only:one%'"), 1)
        self.assertEqual(sum(self.bal(u) for u in users), 10 * 5000 - 10 * 480)  # sab ne ek baar hi pay kiya

    def test_stock_two_five_buyers(self):
        # 2 item, 5 khareedar: pre-order se pehle sirf 2 ko item milna chahiye, kisi item ke do owner nahi
        pid, vid = catalog("auto", "4.80")
        store.add_inventory(conn, vid, ["a:1", "b:2"])
        users = [mk("race_two%d@example.com" % i) for i in range(5)]
        for u in users:
            fund(u, "50")
        self.run_parallel([(lambda c, u=u: store.buy(c, u, vid, 1)) for u in users])
        q = lambda s: conn.execute(s, (vid,)).fetchone()[0]
        self.assertEqual(q("SELECT COUNT(*) FROM orders WHERE variation_id=? AND status='completed'"), 2)
        self.assertEqual(q("SELECT COUNT(DISTINCT order_id) FROM inventory WHERE variation_id=? AND status='sold'"), 2)
        self.assertEqual(q("SELECT COUNT(*) FROM inventory WHERE variation_id=? AND status='sold'"), 2)

    def test_wallet_cannot_overspend(self):
        pid, vid = catalog("auto", "4.80")
        store.add_inventory(conn, vid, ["i%d:p" % i for i in range(20)])
        uid = mk("race_wallet@example.com")
        fund(uid, "9.60")  # sirf 2 item ke paise
        res = self.run_parallel([(lambda c: store.buy(c, uid, vid, 1)) for _ in range(8)])
        self.assertEqual(sum(1 for r in res if r[0] == "ok"), 2, res)
        self.assertEqual(self.bal(uid), 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventory WHERE variation_id=? AND status='sold'", (vid,)).fetchone()[0], 2)

    def test_deposit_approved_once(self):
        uid = mk("race_dep@example.com")
        d = store.create_deposit(conn, uid, "upi", "10", "555000111222")
        before = self.bal(uid)
        res = self.run_parallel([(lambda c: store.decide_deposit(c, d["id"], "approve")) for _ in range(6)])
        self.assertEqual(sum(1 for r in res if r[0] == "ok"), 1, res)
        self.assertEqual(self.bal(uid), before + 1000)

    def test_same_utr_from_many_users(self):
        users = [mk("race_utr%d@example.com" % i) for i in range(6)]
        res = self.run_parallel([(lambda c, u=u: store.create_deposit(c, u, "upi", "5", "777000888999")) for u in users])
        self.assertEqual(sum(1 for r in res if r[0] == "ok"), 1, res)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM deposits WHERE reference='777000888999'").fetchone()[0], 1)


class Reset(unittest.TestCase):
    def test_reset_token_single_use_and_logs_out(self):
        uid = mk("reset@example.com")
        old_token, _ = store.login(conn, "reset@example.com", "password123")
        tok = store.make_reset_token(conn, uid)
        with self.assertRaises(ApiError):
            store.reset_password(conn, tok, "short")          # chhota password
        store.reset_password(conn, tok, "brandnew-pass-1")
        with self.assertRaises(ApiError):
            store.reset_password(conn, tok, "another-pass-2")  # token dobara nahi chalta
        with self.assertRaises(ApiError):
            store.login(conn, "reset@example.com", "password123")
        store.login(conn, "reset@example.com", "brandnew-pass-1")
        self.assertIsNone(store.user_by_token(conn, old_token))  # purane session band

    def test_reset_token_expires_and_new_replaces_old(self):
        uid = mk("reset2@example.com")
        t1 = store.make_reset_token(conn, uid)
        t2 = store.make_reset_token(conn, uid)
        with self.assertRaises(ApiError):
            store.reset_password(conn, t1, "brandnew-pass-1")  # naya token aate hi purana bekaar
        conn.execute("UPDATE password_resets SET expires_at=1")
        with self.assertRaises(ApiError):
            store.reset_password(conn, t2, "brandnew-pass-1")

    def test_audit_written(self):
        store.audit(conn, None, "x" * 100, "y" * 500)
        row = conn.execute("SELECT action,detail FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((len(row["action"]), len(row["detail"])), (40, 300))


class Profile(unittest.TestCase):
    def test_change_password_and_name(self):
        uid = mk("prof@example.com")
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        with self.assertRaises(ApiError):
            store.change_password(conn, u, "wrong-pass", "newpassword1")
        with self.assertRaises(ApiError):
            store.change_password(conn, u, "password123", "short")
        store.change_password(conn, u, "password123", "newpassword1")
        store.login(conn, "prof@example.com", "newpassword1")
        with self.assertRaises(ApiError):
            store.login(conn, "prof@example.com", "password123")
        self.assertEqual(store.update_profile(conn, uid, "  Asha   K  "), "Asha K")


class AutoPay(unittest.TestCase):
    BANK = ("Subject: Credited\nDear customer, Rs. 500.00 has been credited to your account "
            "via UPI. UPI Ref No 412345678901. Thank you.")

    def setUp(self):
        import autopay
        self.ap = autopay
        for k, v in (("upi_auto", "1"), ("upi_alert_senders", "alerts@bank.example"), ("binance_auto", "1")):
            conn.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
        conn.execute("UPDATE settings SET value='100' WHERE key='usd_inr_rate'")
        os.environ.update(IMAP_HOST="x", IMAP_USER="u", IMAP_PASS="p", BINANCE_API_KEY="k", BINANCE_API_SECRET="s")

    def test_parser(self):
        self.assertEqual(self.ap.parse_alert(self.BANK), (50000, "412345678901"))
        self.assertEqual(self.ap.parse_alert("INR 1,250.50 received from X. 123456789012"), (125050, "123456789012"))
        self.assertIsNone(self.ap.parse_alert("Rs. 500 debited from your account. UTR 412345678901"))
        self.assertIsNone(self.ap.parse_alert("Rs 500 credited. Numbers 111111111111 and 222222222222"))  # guess nahi
        self.assertIsNone(self.ap.parse_alert("Hello, win Rs 500 now"))

    def _dep(self, email, usd, utr):
        uid = mk(email)
        return uid, store.create_deposit(conn, uid, "upi", usd, utr)

    def test_email_after_submit_approves_once_with_enough_amount(self):
        uid, d = self._dep("ap1@example.com", "5.00", "412345678901")
        self.assertEqual(d["status"], "pending")
        self.assertTrue(self.ap.record_incoming(conn, "upi", "412345678901", 50000, "INR"))
        self.assertTrue(self.ap.match_incoming(conn, "upi", "412345678901"))
        self.assertFalse(self.ap.match_incoming(conn, "upi", "412345678901"))
        self.assertEqual(conn.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"], 500)

    def test_short_payment_not_approved_and_email_before_submit(self):
        self.ap.record_incoming(conn, "upi", "999999999991", 40000, "INR")  # email pehle
        uid = mk("ap2@example.com")
        d = store.create_deposit(conn, uid, "upi", "5.00", "999999999991")
        self.assertFalse(self.ap.try_match_deposit(conn, "upi", "999999999991"))  # Rs400 < Rs500
        self.assertEqual(conn.execute("SELECT status FROM deposits WHERE id=?", (d["id"],)).fetchone()["status"], "pending")
        self.ap.record_incoming(conn, "upi", "999999999992", 50000, "INR")
        d2 = store.create_deposit(conn, uid, "upi", "5.00", "999999999992")
        self.assertTrue(self.ap.try_match_deposit(conn, "upi", "999999999992"))

    def test_sender_and_dkim(self):
        import email as em
        ok = em.message_from_string("From: Bank <alerts@bank.example>\nAuthentication-Results: mx; dkim=pass\n\nx")
        self.assertTrue(self.ap.sender_ok(ok, "alerts@bank.example"))
        nodkim = em.message_from_string("From: alerts@bank.example\n\nx")
        self.assertFalse(self.ap.sender_ok(nodkim, "alerts@bank.example"))
        fake = em.message_from_string("From: evil@x.example\nAuthentication-Results: mx; dkim=pass\n\nx")
        self.assertFalse(self.ap.sender_ok(fake, "alerts@bank.example"))
        self.assertTrue(self.ap.sender_ok(ok, "@bank.example"))

    def test_poll_mail_with_fake_imap(self):
        uid, d = self._dep("ap3@example.com", "5.00", "555555555555")
        raw = ("From: alerts@bank.example\nSubject: Credit alert\nAuthentication-Results: mx; dkim=pass\n\n"
               "Rs. 500.00 credited. UTR 555555555555").encode()
        spoof = ("From: alerts@bank.example\nSubject: Credit alert\n\nRs. 500.00 credited. UTR 777777777777").encode()
        stored = []

        class FakeIMAP:
            def login(self, u, p): pass
            def select(self, b): return "OK", [b"2"]
            def search(self, *a): return "OK", [b"1 2"]
            def fetch(self, n, what): return "OK", [(b"x", spoof if n == b"2" else raw)]
            def store(self, n, *a): stored.append(n)
            def logout(self): pass

        self.assertEqual(self.ap.poll_mail(conn, lambda: FakeIMAP()), 1)
        self.assertEqual(stored, [b"1", b"2"])
        self.assertIsNone(conn.execute("SELECT 1 FROM incoming WHERE ref='777777777777'").fetchone())  # DKIM nahi => ignore

    def test_binance_poll(self):
        uid = mk("ap4@example.com")
        d = store.create_deposit(conn, uid, "binance_id", "3.00", "M_P_1234567890")
        data = {"code": "000000", "data": [
            {"orderType": "C2C", "transactionId": "M_P_1234567890", "amount": "3.00", "currency": "USDT"},
            {"orderType": "C2C", "transactionId": "OUT1", "amount": "-9", "currency": "USDT"},
            {"orderType": "C2C", "transactionId": "BNB1", "amount": "1", "currency": "BNB"}]}
        self.assertEqual(self.ap.poll_binance(conn, lambda *a: data), 1)
        self.assertEqual(self.ap.poll_binance(conn, lambda *a: data), 0)
        self.assertEqual(conn.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"], 300)
        self.assertIsNone(conn.execute("SELECT 1 FROM incoming WHERE ref IN ('OUT1','BNB1')").fetchone())


if __name__ == "__main__":
    unittest.main(verbosity=2)
