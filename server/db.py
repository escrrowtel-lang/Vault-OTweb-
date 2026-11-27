"""Database layer: SQLite (default) ya PostgreSQL/Supabase (DATABASE_URL set ho to).
Sab paisa integer CENTS (1/100 USD) mein store hota hai."""
import os
import re
import sqlite3
import sys
from urllib.parse import urlparse
from contextlib import contextmanager
from decimal import Decimal, ROUND_DOWN, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("VAULT_DB", os.path.join(HERE, "..", "data", "store.db"))
UPLOAD_DIR = os.environ.get("VAULT_UPLOADS", os.path.join(HERE, "..", "data", "uploads"))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))
PG_SCHEMA = os.environ.get("VAULT_PG_SCHEMA", "vaultstore")
# Supabase ke apne schemas: inme tables nahi banane (jaise "vault" unka secrets feature hai)
PG_RESERVED = {"vault", "auth", "storage", "extensions", "graphql", "graphql_public", "realtime", "pgsodium",
               "pgsodium_masks", "supabase_functions", "supabase_migrations", "net", "cron", "pgbouncer",
               "pg_catalog", "information_schema", "pg_toast"}
PG_LOCK_KEY = 7236001  # har write transaction ye lock leti hai (SQLite ke BEGIN IMMEDIATE jaisa: ek time par ek writer)


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
CREATE TABLE IF NOT EXISTS suppliers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  auth_mode TEXT NOT NULL DEFAULT 'header',
  auth_header TEXT NOT NULL DEFAULT 'X-API-Key',
  api_key TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'generic',
  catalog_path TEXT NOT NULL DEFAULT '',
  markup TEXT NOT NULL DEFAULT '20',
  cents INTEGER NOT NULL DEFAULT 0,
  auto_sync INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS supplier_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  external_id TEXT NOT NULL,
  product_id INTEGER NOT NULL REFERENCES products(id),
  variation_id INTEGER NOT NULL REFERENCES variations(id),
  cost INTEGER NOT NULL DEFAULT 0,
  needs_email INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS supplier_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id),
  supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
  product_ext TEXT NOT NULL,
  emails TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  external_id TEXT NOT NULL DEFAULT '',
  cost INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS supplier_orders_order ON supplier_orders(order_id);
CREATE UNIQUE INDEX IF NOT EXISTS supplier_items_ext ON supplier_items(supplier_id, external_id);
CREATE TABLE IF NOT EXISTS incoming(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  ref TEXT NOT NULL,
  amount INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  deposit_id INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS incoming_ref ON incoming(source, ref);
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
    "upi_auto": "0",
    "upi_alert_senders": "",
    "upi_require_dkim": "1",
    "binance_auto": "0",
}


def to_cents(value):
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ApiError(400, "Invalid amount")
    if not d.is_finite() or d < 0:
        raise ApiError(400, "Invalid amount")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_DOWN))


def fmt(cents):
    return "%d.%02d" % (cents // 100, cents % 100)


def _pg_conninfo():
    u = urlparse(DATABASE_URL)
    info = DATABASE_URL
    sep = "&" if "?" in info else "?"
    extra = []
    if "connect_timeout" not in info:
        extra.append("connect_timeout=10")
    local = (u.hostname or "") in ("", "localhost", "127.0.0.1", "::1")
    if "sslmode" not in info and not local:
        extra.append("sslmode=require")  # remote DB (Supabase) hamesha encrypted
    return info + (sep + "&".join(extra) if extra else "")


def _tables():
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\(", SCHEMA)


def _id_tables():
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\(\s*id INTEGER PRIMARY KEY AUTOINCREMENT", SCHEMA))


def pg_schema_sql():
    s = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace("BLOB", "BYTEA")
    return re.sub(r"\bINTEGER\b", "BIGINT", s)


def connect():
    if USE_PG:
        import pg
        return pg.acquire(_pg_conninfo(), PG_SCHEMA, _id_tables())
    c = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


@contextmanager
def tx(conn):
    if USE_PG:
        conn.begin()
        try:
            conn.execute("SELECT pg_advisory_xact_lock(%d)" % PG_LOCK_KEY)
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


MIGRATIONS = [("suppliers", "kind", "TEXT NOT NULL DEFAULT 'generic'"), ("suppliers", "catalog_path", "TEXT NOT NULL DEFAULT ''"),
              ("suppliers", "markup", "TEXT NOT NULL DEFAULT '20'"), ("suppliers", "cents", "INTEGER NOT NULL DEFAULT 0"),
              ("suppliers", "auto_sync", "INTEGER NOT NULL DEFAULT 0"), ("supplier_items", "needs_email", "INTEGER NOT NULL DEFAULT 0")]


def _migrate(c):
    """Add columns that older databases do not have yet (CREATE TABLE IF NOT EXISTS never alters)."""
    for table, col, ddl in MIGRATIONS:
        if USE_PG:
            c.executescript('ALTER TABLE "%s" ADD COLUMN IF NOT EXISTS %s %s' % (table, col, ddl.replace("INTEGER", "BIGINT")))
        else:
            have = [r[1] for r in c.execute("PRAGMA table_info(%s)" % table).fetchall()]
            if col not in have:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, ddl))


def init():
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    except OSError as e:  # manage.py jaise tools ko upload folder ki zaroorat nahi; server ko hai (systemd mein sahi path set hai)
        print("warning: could not create the upload folder (%s): %s" % (UPLOAD_DIR, e), file=sys.stderr)
    if USE_PG:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", PG_SCHEMA):
            raise SystemExit("VAULT_PG_SCHEMA is invalid")
        if PG_SCHEMA in PG_RESERVED or PG_SCHEMA.startswith("pg_"):
            raise SystemExit("Schema name '%s' is reserved by Supabase. Use a different name (default: vaultstore)." % PG_SCHEMA)
        import pg
        # schema alag se banao (search_path abhi set nahi), phir tables
        c = pg.Connection(_pg_conninfo(), "", _id_tables())
        c.executescript('CREATE SCHEMA IF NOT EXISTS "%s"' % PG_SCHEMA)
        c._really_close()  # ye connection bina search_path ka hai, pool mein nahi jaana chahiye
        c = connect()
        with tx(c):
            c.executescript(pg_schema_sql())
            _migrate(c)
            for tname in _tables():
                # Supabase ka public REST API in tables ko na chhu sake: RLS ON, koi policy nahi
                c.executescript('ALTER TABLE "%s" ENABLE ROW LEVEL SECURITY' % tname)
            c.executescript(
                "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN "
                "EXECUTE 'REVOKE ALL ON SCHEMA \"%(s)s\" FROM anon, authenticated'; "
                "EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA \"%(s)s\" FROM anon, authenticated'; "
                "EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA \"%(s)s\" FROM anon, authenticated'; "
                "END IF; END $$" % {"s": PG_SCHEMA})
        _seed_settings(c)
        c.close()
        return
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = connect()
    c.executescript(SCHEMA)
    _migrate(c)
    _seed_settings(c)
    c.close()


def _seed_settings(c):
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING", (k, v))


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings")}
