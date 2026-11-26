"""PostgreSQL (Supabase) ke liye chhota driver: system ki libpq ko ctypes se use karta hai.
Koi pip package nahi chahiye (VPS par sirf `apt install libpq5`). TLS aur password auth libpq khud sambhalta hai.
Interface sqlite3 jaisa rakha hai: conn.execute(sql, params) -> cursor (fetchone/fetchall/lastrowid/rowcount).
"""
import ctypes
import ctypes.util
import re
import threading
import time
from decimal import Decimal

_path = ctypes.util.find_library("pq") or "libpq.so.5"
try:
    lib = ctypes.CDLL(_path)
except OSError as e:  # pragma: no cover
    raise RuntimeError("libpq nahi mila. Ubuntu par: sudo apt install libpq5") from e

c_void_pp = ctypes.POINTER(ctypes.c_void_p)
lib.PQconnectdb.argtypes = [ctypes.c_char_p]; lib.PQconnectdb.restype = ctypes.c_void_p
lib.PQstatus.argtypes = [ctypes.c_void_p]; lib.PQstatus.restype = ctypes.c_int
lib.PQerrorMessage.argtypes = [ctypes.c_void_p]; lib.PQerrorMessage.restype = ctypes.c_char_p
lib.PQfinish.argtypes = [ctypes.c_void_p]; lib.PQfinish.restype = None
lib.PQreset.argtypes = [ctypes.c_void_p]; lib.PQreset.restype = None
lib.PQtransactionStatus.argtypes = [ctypes.c_void_p]; lib.PQtransactionStatus.restype = ctypes.c_int
lib.PQexec.argtypes = [ctypes.c_void_p, ctypes.c_char_p]; lib.PQexec.restype = ctypes.c_void_p
lib.PQexecParams.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_int),
                             ctypes.POINTER(ctypes.c_int), ctypes.c_int]
lib.PQexecParams.restype = ctypes.c_void_p
lib.PQresultStatus.argtypes = [ctypes.c_void_p]; lib.PQresultStatus.restype = ctypes.c_int
lib.PQresultErrorMessage.argtypes = [ctypes.c_void_p]; lib.PQresultErrorMessage.restype = ctypes.c_char_p
lib.PQresultErrorField.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.PQresultErrorField.restype = ctypes.c_char_p
lib.PQntuples.argtypes = [ctypes.c_void_p]; lib.PQntuples.restype = ctypes.c_int
lib.PQnfields.argtypes = [ctypes.c_void_p]; lib.PQnfields.restype = ctypes.c_int
lib.PQfname.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.PQfname.restype = ctypes.c_char_p
lib.PQftype.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.PQftype.restype = ctypes.c_uint
lib.PQgetvalue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]; lib.PQgetvalue.restype = ctypes.c_char_p
lib.PQgetisnull.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]; lib.PQgetisnull.restype = ctypes.c_int
lib.PQcmdTuples.argtypes = [ctypes.c_void_p]; lib.PQcmdTuples.restype = ctypes.c_char_p
lib.PQclear.argtypes = [ctypes.c_void_p]; lib.PQclear.restype = None

CONNECTION_OK = 0
PGRES_COMMAND_OK, PGRES_TUPLES_OK = 1, 2
PG_DIAG_SQLSTATE = ord("C")
POOL_MAX_IDLE = 8
POOL_MAX_AGE = 240  # seconds; Supabase pooler idle connections band kar deta hai


class Error(Exception):
    def __init__(self, msg, sqlstate=""):
        super().__init__(msg)
        self.sqlstate = sqlstate


class IntegrityError(Error):
    pass


class Row(tuple):
    """sqlite3.Row jaisa: row[0], row["col"], dict(row), row.keys()"""

    def __new__(cls, values, names, index):
        r = tuple.__new__(cls, values)
        r._names = names
        r._index = index
        return r

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._index[k])
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._names)


class Cursor:
    def __init__(self, rows, lastrowid=None, rowcount=-1):
        self._rows = rows
        self._pos = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._pos < len(self._rows):
            self._pos += 1
            return self._rows[self._pos - 1]
        return None

    def fetchall(self):
        out = self._rows[self._pos:]
        self._pos = len(self._rows)
        return out

    def __iter__(self):
        return iter(self.fetchall())


def _decode(oid, s):
    if oid in (20, 21, 23, 26):
        return int(s)
    if oid in (700, 701):
        return float(s)
    if oid == 1700:  # numeric: SUM() yahan aata hai
        return int(s) if re.fullmatch(r"-?\d+", s) else float(Decimal(s))
    if oid == 16:
        return s == "t"
    return s


def _encode(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return b"1" if v else b"0"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return b"\\x" + bytes(v).hex().encode()
    if isinstance(v, (int, float, Decimal)):
        return str(v).encode()
    return str(v).encode("utf-8")


_QMARK = re.compile(r"'(?:[^']|'')*'|\?")


def _translate(sql):
    """sqlite ke ? placeholders ko $1, $2... mein badlo (quotes ke andar ke ? chhodkar)."""
    n = [0]

    def sub(m):
        if m.group(0) == "?":
            n[0] += 1
            return "$%d" % n[0]
        return m.group(0)
    return _QMARK.sub(sub, sql), n[0]


_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)


class Connection:
    def __init__(self, conninfo, schema, id_tables):
        self._conninfo = conninfo
        self._schema = schema
        self._id_tables = id_tables
        self._h = None
        self.born = 0.0
        self._connect()

    # ---- low level
    def _connect(self):
        if self._h:
            lib.PQfinish(self._h)
        self._h = lib.PQconnectdb(self._conninfo.encode())
        if not self._h or lib.PQstatus(self._h) != CONNECTION_OK:
            msg = (lib.PQerrorMessage(self._h) or b"").decode("utf-8", "replace").strip() if self._h else "connect fail"
            if self._h:
                lib.PQfinish(self._h)
                self._h = None
            raise Error("Database se connect nahi ho paya: " + msg.splitlines()[0] if msg else "connect fail")
        self.born = time.time()
        if self._schema:
            self._simple('SET search_path TO "%s"' % self._schema)

    def _check(self, res):
        st = lib.PQresultStatus(res)
        if st in (PGRES_COMMAND_OK, PGRES_TUPLES_OK):
            return st
        msg = (lib.PQresultErrorMessage(res) or b"").decode("utf-8", "replace").strip()
        code = (lib.PQresultErrorField(res, PG_DIAG_SQLSTATE) or b"").decode()
        lib.PQclear(res)
        cls = IntegrityError if code.startswith("23") else Error
        raise cls(msg, code)

    def _simple(self, sql):
        res = lib.PQexec(self._h, sql.encode())
        if not res:
            raise Error("connection toot gaya", "08000")
        self._check(res)
        lib.PQclear(res)

    @property
    def in_tx(self):
        return lib.PQtransactionStatus(self._h) in (2, 3)

    def healthy(self):
        return bool(self._h) and lib.PQstatus(self._h) == CONNECTION_OK

    # ---- public (sqlite3-jaisa)
    def execute(self, sql, params=()):
        sql, n = _translate(sql)
        if n != len(params):
            raise Error("placeholders (%d) aur params (%d) barabar nahi" % (n, len(params)))
        returning = False
        m = _INSERT.match(sql)
        if m and m.group(1).lower() in self._id_tables and "RETURNING" not in sql.upper():
            sql += " RETURNING id"
            returning = True
        for attempt in (0, 1):
            try:
                return self._run(sql, params, returning)
            except Error as e:
                # idle pooled connection server ne band kar diya ho to ek baar reconnect (transaction ke bahar)
                if attempt == 0 and (e.sqlstate.startswith("08") or not self.healthy()) and not self.in_tx:
                    self._connect()
                    continue
                raise

    def _run(self, sql, params, returning):
        k = len(params)
        vals = (ctypes.c_char_p * k)(*[_encode(p) for p in params]) if k else None
        res = lib.PQexecParams(self._h, sql.encode("utf-8"), k, None, vals, None, None, 0)
        if not res:
            raise Error("connection toot gaya", "08000")
        st = self._check(res)
        try:
            rows, lastid = [], None
            if st == PGRES_TUPLES_OK:
                nf, nt = lib.PQnfields(res), lib.PQntuples(res)
                names = [lib.PQfname(res, i).decode() for i in range(nf)]
                index = {nm: i for i, nm in reversed(list(enumerate(names)))}
                oids = [lib.PQftype(res, i) for i in range(nf)]
                for r in range(nt):
                    row = []
                    for c in range(nf):
                        if lib.PQgetisnull(res, r, c):
                            row.append(None)
                        else:
                            row.append(_decode(oids[c], lib.PQgetvalue(res, r, c).decode("utf-8")) if oids[c] != 17
                                       else bytes.fromhex(lib.PQgetvalue(res, r, c).decode()[2:]))
                    rows.append(Row(row, names, index))
                if returning and rows:
                    lastid = rows[0][0]
            ct = lib.PQcmdTuples(res)
            rc = int(ct) if ct and ct.isdigit() else -1
            return Cursor(rows, lastid, rc)
        finally:
            lib.PQclear(res)

    def executescript(self, sql):
        self._simple(sql)

    def begin(self):
        self._simple("BEGIN")

    def commit(self):
        self._simple("COMMIT")

    def rollback(self):
        if self.healthy():
            self._simple("ROLLBACK")

    def close(self):
        """Pool mein wapas (ya band, agar kharab ho)."""
        _release(self)

    def _really_close(self):
        if self._h:
            lib.PQfinish(self._h)
            self._h = None


# ---------------------------------------------------------------- pool
_pool = []
_lock = threading.Lock()


def acquire(conninfo, schema, id_tables):
    now = time.time()
    while True:
        with _lock:
            c = _pool.pop() if _pool else None
        if c is None:
            return Connection(conninfo, schema, id_tables)
        if c.healthy() and now - c.born < POOL_MAX_AGE and c._schema == schema and c._conninfo == conninfo:
            return c
        c._really_close()


def _release(c):
    try:
        if c.healthy() and c.in_tx:
            c.rollback()
    except Error:
        pass
    if c.healthy():
        with _lock:
            if len(_pool) < POOL_MAX_IDLE:
                _pool.append(c)
                return
    c._really_close()
