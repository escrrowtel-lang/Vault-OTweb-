"""Admin tools.

  python3 server/manage.py create-admin you@example.com      (password poochega, screen par nahi dikhega)
  python3 server/manage.py set-password you@example.com
  python3 server/manage.py seed-demo                         (sirf layout dekhne ke liye DEMO products)
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import store
from db import connect, ApiError


def ask_password():
    p1 = getpass.getpass("Password (kam se kam 8 characters): ")
    if p1 != getpass.getpass("Dobara likho: "):
        sys.exit("Dono password alag hain")
    return p1


def main():
    db.init()
    conn = connect()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "create-admin" and len(sys.argv) == 3:
            store.create_user(conn, sys.argv[2], ask_password(), "Admin", is_admin=1)
            print("Admin ban gaya:", sys.argv[2])
        elif cmd == "set-password" and len(sys.argv) == 3:
            import secrets
            u = conn.execute("SELECT id FROM users WHERE email=?", (sys.argv[2].lower(),)).fetchone()
            if not u:
                sys.exit("User nahi mila")
            pw = ask_password()
            salt = secrets.token_bytes(16)
            conn.execute("UPDATE users SET pass_hash=?, pass_salt=?, is_admin=is_admin WHERE id=?", (store._hash(pw, salt), salt, u["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
            print("Password badal diya")
        elif cmd == "seed-demo":
            seed_demo(conn)
            print("Demo data daal diya. Asli launch se pehle admin panel se hata do (inactive kar do).")
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
                               (cid, pn, "Demo description. Yahan activation steps likho.", glyph, color, mode)).lastrowid
            for vn, price in vars_:
                conn.execute("INSERT INTO variations(product_id,name,price,min_qty,max_qty,stock) VALUES(?,?,?,?,?,?)",
                             (pid, vn, db.to_cents(price), 1, 3, 5 if mode == "manual" else 0))


if __name__ == "__main__":
    main()
