"""Scope and safety, all in code. The model never decides who sees what.

- scope(user): the stores a user may see, from users.json. Unknown user -> ScopeError.
- out_of_scope(question, stores): store ids or regions named in the question that the user may not see.
- check_sql(sql, stores): one SELECT/WITH statement, no store literal outside scope.
- run(sql, stores): read-only connection, per-user TEMP views, authorizer, timeout, row limit.
"""
import json
import os
import re
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "config.json")))
USERS = json.load(open(os.path.join(HERE, CONFIG["users_path"])))
DB = os.path.join(HERE, CONFIG["db_path"])

ALL_STORES = [f"S{i:02d}" for i in range(1, 13)]
VIEWS = {"sales": "my_sales", "stores": "my_stores"}  # base table -> the only view allowed to read it


class ScopeError(Exception):
    """The question or the SQL reaches outside the user's stores."""


class SqlError(Exception):
    """The SQL is not allowed or failed to run. The message is safe to send back to the model."""


def scope(user):
    if user not in USERS:
        raise ScopeError("unknown user")
    return list(USERS[user]["stores"])


def store_directory():
    """store_id -> (name, city, region). Notes are free text and are never read here."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return {r[0]: r[1:] for r in con.execute("SELECT store_id, store_name, city, region FROM stores")}
    finally:
        con.close()


STORE_DIR = store_directory()


def out_of_scope(question, stores):
    """Store ids, store names or regions in the question that belong only to stores outside scope."""
    hits = []
    allowed = set(stores)
    for sid in set(re.findall(r"\bS\d\d\b", question.upper())):
        if sid not in allowed:
            hits.append(sid)
    my_regions = {STORE_DIR[s][2] for s in stores}
    for region in {v[2] for v in STORE_DIR.values()} - my_regions:
        if re.search(rf"\b{region}\b", question, re.I):
            hits.append(region)
    for sid, (name, city, _) in STORE_DIR.items():
        if sid not in allowed and re.search(rf"\b{re.escape(name)}\b", question, re.I):
            hits.append(sid)
    return hits


def check_sql(sql, stores):
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise SqlError("empty SQL")
    if ";" in s:
        raise SqlError("only one statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise SqlError("only SELECT statements are allowed")
    bad = sorted({sid for sid in re.findall(r"\bS\d\d\b", s.upper()) if sid not in set(stores)})
    if bad:
        raise ScopeError("SQL names stores outside scope")
    return s


def _authorizer(action, arg1, arg2, dbname, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        table = (arg1 or "").lower()
        if table in VIEWS:  # a base table: only through its scoped view
            return sqlite3.SQLITE_OK if source == VIEWS[table] else sqlite3.SQLITE_DENY
        if table in ("products", "my_sales", "my_stores") or dbname is None:
            return sqlite3.SQLITE_OK  # dbname None: a CTE or subquery column
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY  # writes, ATTACH, PRAGMA, schema changes


def connect(stores):
    """A read-only connection where my_sales / my_stores hold only the user's stores."""
    for s in stores:
        if s not in ALL_STORES:
            raise ScopeError("bad store id in users.json")
    ids = ",".join(f"'{s}'" for s in stores)  # validated ids, not user text
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute(f"CREATE TEMP VIEW my_sales AS SELECT * FROM main.sales WHERE store_id IN ({ids})")
    con.execute(f"CREATE TEMP VIEW my_stores AS SELECT * FROM main.stores WHERE store_id IN ({ids})")
    con.set_authorizer(_authorizer)
    return con


def run(sql, stores, timeout_s=None, row_limit=None):
    """Returns (columns, rows). Raises SqlError or ScopeError."""
    timeout_s = timeout_s or CONFIG["query_timeout_s"]
    row_limit = row_limit or CONFIG["row_limit"]
    s = check_sql(sql, stores)
    con = connect(stores)
    deadline = time.time() + timeout_s
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
    try:
        cur = con.execute(s)
        rows = cur.fetchmany(row_limit)
        cols = [d[0] for d in cur.description or []]
        return cols, [tuple(r) for r in rows]
    except sqlite3.OperationalError as e:
        msg = str(e)
        if "interrupted" in msg:
            raise SqlError(f"query took longer than {timeout_s}s")
        if "not authorized" in msg:
            raise SqlError("not authorized: use only my_sales, my_stores and products")
        raise SqlError(msg[:200])
    except sqlite3.Error as e:
        raise SqlError(str(e)[:200])
    finally:
        con.close()
