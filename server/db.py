"""SQLite layer. Sab paisa integer CENTS (1/100 USD) mein store hota hai."""
import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, ROUND_DOWN, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("VAULT_DB", os.path.join(HERE, "..", "data", "store.db"))
UPLOAD_DIR = os.environ.get("VAULT_UPLOADS", os.path.join(HERE, "..", "data", "uploads"))


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  pass_hash BLOB NOT NULL,
  pass_salt BLOB NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  blocked INTEGER NOT NULL DEFAULT 0,
  balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
  ref_code TEXT NOT NULL UNIQUE,
  referred_by INTEGER REFERENCES users(id),
  ref_rewarded INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  emoji TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  image TEXT NOT NULL DEFAULT '',
  glyph TEXT NOT NULL DEFAULT 'star',
  color TEXT NOT NULL DEFAULT '#7c3aed',
  mode TEXT NOT NULL DEFAULT 'auto' CHECK(mode IN ('auto','manual')),
  quick_drop INTEGER NOT NULL DEFAULT 0,
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS variations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  name TEXT NOT NULL,
  price INTEGER NOT NULL CHECK(price >= 0),
  min_qty INTEGER NOT NULL DEFAULT 1,
  max_qty INTEGER NOT NULL DEFAULT 1,
  stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
  position INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS inventory(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  variation_id INTEGER NOT NULL REFERENCES variations(id),
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available','sold')),
  order_id INTEGER,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS inv_var ON inventory(variation_id, status);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  variation_id INTEGER NOT NULL REFERENCES variations(id),
  product_name TEXT NOT NULL,
  plan_name TEXT NOT NULL,
  mode TEXT NOT NULL,
  qty INTEGER NOT NULL,
  unit_price INTEGER NOT NULL,
  discount INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL,
  coupon_code TEXT NOT NULL DEFAULT '',
  preorder INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK(status IN ('pending','processing','completed','cancelled','refunded')),
  delivery_text TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ord_user ON orders(user_id, id);
CREATE TABLE IF NOT EXISTS coupons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 100),
  max_uses INTEGER NOT NULL DEFAULT 1,
  uses INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS coupon_uses(
  coupon_id INTEGER NOT NULL REFERENCES coupons(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  order_id INTEGER NOT NULL,
  PRIMARY KEY(coupon_id, user_id)
);
CREATE TABLE IF NOT EXISTS deposits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  method TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK(amount > 0),
  reference TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
  note TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  decided_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS dep_ref ON deposits(method, reference) WHERE status IN ('pending','approved');
CREATE TABLE IF NOT EXISTS crypto_intents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  expected INTEGER NOT NULL,   -- USDT, 1e-4 units mein (10.0037 USDT = 100037)
  used INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ci_exp ON crypto_intents(expected, used);
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  delta INTEGER NOT NULL,
  reason TEXT NOT NULL,
  ref TEXT NOT NULL DEFAULT '',
  balance_after INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS led_user ON ledger(user_id, id);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  admin_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
"""

# Dollar wali values decimal string mein (admin ke liye aasaan)
DEFAULT_SETTINGS = {
    "store_name": "Vault Store",
    "upi_id": "",
    "upi_name": "",
    "binance_id": "",
    "usdt_address": "",
    "usdt_contract": "0x55d398326f99059fF775485246999027B3197955",
    "bsc_rpc": "https://bsc-dataseed.binance.org",
    "confirmations": "10",
    "methods_enabled": "upi,binance_id,usdt_bep20",
    "min_deposit": "1.00",
    "max_deposit": "500.00",
    "usd_inr_rate": "100",
    "referral_reward": "0.10",
    "support_text": "",
    "support_url": "",
    "site_url": "",
}


def to_cents(value):
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ApiError(400, "Amount sahi nahi hai")
    if not d.is_finite() or d < 0:
        raise ApiError(400, "Amount sahi nahi hai")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_DOWN))


def fmt(cents):
    return "%d.%02d" % (cents // 100, cents % 100)


def connect():
    c = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


@contextmanager
def tx(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    c = connect()
    c.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    c.close()


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings")}
