"""Admin tools.

  python3 server/manage.py create-admin you@example.com      (prompts for the password; it is not shown on screen)
  python3 server/manage.py set-password you@example.com
  python3 server/manage.py seed-demo                         (sirf layout dekhne ke liye DEMO products)
  python3 server/manage.py migrate-sqlite /path/store.db     (purana SQLite data -> Postgres/Supabase; DATABASE_URL set ho)
  python3 server/manage.py backup-json /path/backup.json     (poora backup, SQLite ya Postgres dono se)
  python3 server/manage.py restore-json /path/backup.json    (restore into an empty database)
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import store
from db import connect, ApiError


def ask_password():
    p1 = getpass.getpass("Password (at least 8 characters): ")
    if p1 != getpass.getpass("Confirm password: "):
        sys.exit("The passwords do not match")
    return p1


SKIP_TABLES = ("sessions", "password_resets")  # logins dobara karne honge


def _load(dst, data):
    """data = {table: [row-dict]} ko khaali database mein daalo (ids ke saath). SQLite aur Postgres dono par."""
    if dst.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        sys.exit("Database mein pehle se users hain. Ye kaam sirf khaali database mein hota hai.")
    counts = {}
    with db.tx(dst):
        for tname in db._tables():
            if tname in SKIP_TABLES or tname not in data:
                continue
            rows = data[tname]
            counts[tname] = len(rows)
            for r in rows:
                cols = list(r.keys())
                sql = "INSERT INTO %s(%s) VALUES(%s)" % (tname, ",".join(cols), ",".join("?" * len(cols)))
                if tname == "settings":
                    sql += " ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                dst.execute(sql, tuple(r[c] for c in cols))
        if db.USE_PG:
            for tname in sorted(db._id_tables()):
                dst.execute("SELECT setval(pg_get_serial_sequence('%s','id'), COALESCE((SELECT MAX(id) FROM %s),1), "
                            "(SELECT MAX(id) FROM %s) IS NOT NULL)" % (tname, tname, tname))
        for tname, n in counts.items():
            got = dst.execute("SELECT COUNT(*) FROM %s" % tname).fetchone()[0]
            if got != n:
                raise SystemExit("Row count mismatch (%s: %d -> %d). Some rows were not copied." % (tname, n, got))
        bad = dst.execute("SELECT COUNT(*) FROM users u WHERE u.balance <> COALESCE((SELECT SUM(delta) FROM ledger l WHERE l.user_id=u.id),0)").fetchone()[0]
    print("Loaded:", ", ".join("%s=%d" % kv for kv in counts.items() if kv[1]))
    if bad:
        print("WARNING: %d users have a balance that does not match their ledger total." % bad)


def migrate_sqlite(src_path):
    """SQLite ka poora data khaali Postgres database mein copy karo."""
    import sqlite3
    if not db.USE_PG:
        sys.exit("Set DATABASE_URL first (postgresql://...)")
    if not os.path.isfile(src_path):
        sys.exit("SQLite file not found: %s" % src_path)
    src = sqlite3.connect("file:%s?mode=ro" % src_path, uri=True)
    src.row_factory = sqlite3.Row
    data = {tn: [dict(zip(r.keys(), tuple(r))) for r in src.execute("SELECT * FROM %s" % tn).fetchall()]
            for tn in db._tables() if tn not in SKIP_TABLES}
    _load(connect(), data)


def _enc(v):
    return {"$hex": bytes(v).hex()} if isinstance(v, (bytes, bytearray)) else v


def _dec(v):
    return bytes.fromhex(v["$hex"]) if isinstance(v, dict) and "$hex" in v else v


def backup_json(path):
    """Poora database ek JSON file mein (SQLite ya Postgres, dono se). File mein password hashes aur inventory hai: private rakho."""
    import json
    conn = connect()
    data = {}
    for tn in db._tables():
        if tn in SKIP_TABLES:
            continue
        data[tn] = [{k: _enc(r[k]) for k in r.keys()} for r in conn.execute("SELECT * FROM %s" % tn).fetchall()]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"version": 1, "tables": data}, f)
    os.chmod(path, 0o600)
    print("Backup ready:", path, "(%d tables)" % len(data))


def restore_json(path):
    import json
    with open(path) as f:
        doc = json.load(f)
    if doc.get("version") != 1:
        sys.exit("This backup file is not recognised")
    data = {tn: [{k: _dec(v) for k, v in r.items()} for r in rows] for tn, rows in doc["tables"].items()}
    _load(connect(), data)


def main():
    if len(sys.argv) > 2 and sys.argv[1] in ("migrate-sqlite", "backup-json", "restore-json"):
        db.init()
        {"migrate-sqlite": migrate_sqlite, "backup-json": backup_json, "restore-json": restore_json}[sys.argv[1]](sys.argv[2])
        return
    db.init()
    conn = connect()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "create-admin" and len(sys.argv) == 3:
            store.create_user(conn, sys.argv[2], ask_password(), "Admin", is_admin=1)
            print("Admin created:", sys.argv[2])
        elif cmd == "set-password" and len(sys.argv) == 3:
            import secrets
            u = conn.execute("SELECT id FROM users WHERE email=?", (sys.argv[2].lower(),)).fetchone()
            if not u:
                sys.exit("User not found")
            pw = ask_password()
            salt = secrets.token_bytes(16)
            conn.execute("UPDATE users SET pass_hash=?, pass_salt=?, is_admin=is_admin WHERE id=?", (store._hash(pw, salt), salt, u["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
            print("Password updated")
        elif cmd == "seed-demo":
            seed_demo(conn)
            print("Demo data added. Hide or remove it in the admin panel before launch.")
        else:
            print(__doc__)
    except ApiError as e:
        sys.exit(e.msg)


def seed_demo(conn):
    if conn.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
        sys.exit("Catalog mein pehle se data hai")
    rows = [
        ("Streaming", "🎬", [("Demo Video Plan", "play", "#7c3aed", "auto", [("1 Month", "4.80"), ("1 Year", "39.00")])]),
        ("Music", "🎧", [("Demo Music Plan", "music", "#ec4899", "auto", [("3 Month", "9.60")])]),
        ("AI Tools", "🤖", [("Demo AI Plan", "spark", "#0d9488", "manual", [("1 Month", "12.00")])]),
    ]
    for pos, (cn, em, prods) in enumerate(rows):
        cid = conn.execute("INSERT INTO categories(name,emoji,position) VALUES(?,?,?)", (cn, em, pos)).lastrowid
        for pn, glyph, color, mode, vars_ in prods:
            pid = conn.execute("INSERT INTO products(category_id,name,description,glyph,color,mode) VALUES(?,?,?,?,?,?)",
                               (cid, pn, "Demo description. Add activation steps here.", glyph, color, mode)).lastrowid
            for vn, price in vars_:
                conn.execute("INSERT INTO variations(product_id,name,price,min_qty,max_qty,stock) VALUES(?,?,?,?,?,?)",
                             (pid, vn, db.to_cents(price), 1, 3, 5 if mode == "manual" else 0))


if __name__ == "__main__":
    main()
