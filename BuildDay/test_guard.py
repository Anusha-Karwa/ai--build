"""Isolation and safety tests. No model calls, no key needed: python test_guard.py"""
import guard
from assistant import cache_key

ANA = guard.scope("ana")      # S03
MEERA = guard.scope("meera")  # S01-S04


def blocked(sql, stores=ANA):
    try:
        guard.run(sql, stores)
    except (guard.SqlError, guard.ScopeError):
        return True
    return False


# Scoped views return only the user's stores
cols, rows = guard.run("SELECT DISTINCT store_id FROM my_sales", ANA)
assert rows == [("S03",)], rows
cols, rows = guard.run("SELECT store_id FROM my_stores ORDER BY 1", MEERA)
assert [r[0] for r in rows] == ["S01", "S02", "S03", "S04"], rows

# Base tables are blocked, even inside a subquery or a CTE
assert blocked("SELECT COUNT(*) FROM sales")
assert blocked("SELECT COUNT(*) FROM main.sales")
assert blocked("SELECT * FROM stores")
assert blocked("SELECT (SELECT SUM(qty) FROM sales) FROM my_stores")
assert blocked("WITH x AS (SELECT * FROM sales) SELECT COUNT(*) FROM x")
assert blocked("SELECT name FROM sqlite_master")

# CTEs over the views still work
cols, rows = guard.run("WITH x AS (SELECT store_id, qty FROM my_sales) SELECT DISTINCT store_id FROM x", ANA)
assert rows == [("S03",)], rows

# Out-of-scope store literal in SQL is a scope error even though the view would return nothing
assert blocked("SELECT SUM(qty) FROM my_sales WHERE store_id='S07'")

# No writes, no second statement, no pragma or attach
assert blocked("DELETE FROM my_sales")
assert blocked("UPDATE products SET mrp=0")
assert blocked("DROP TABLE products")
assert blocked("SELECT 1; DELETE FROM products")
assert blocked("PRAGMA table_info(sales)")
assert blocked("ATTACH DATABASE 'x.db' AS x")

# Timeout stops a runaway query
assert blocked("SELECT COUNT(*) FROM my_sales a, my_sales b", ANA)

# Row limit
cols, rows = guard.run("SELECT line_id FROM my_sales", ANA)
assert len(rows) == guard.CONFIG["row_limit"], len(rows)

# Question-level scope check
assert guard.out_of_scope("What were S07's net sales?", ANA) == ["S07"]
assert "South" in guard.out_of_scope("Show net sales for the South region", MEERA)
assert guard.out_of_scope("How did Koregaon Park do?", ANA) == []
assert guard.out_of_scope("How did Bandra do?", ANA) == ["S02"]
assert guard.out_of_scope("Which stores are in my region?", MEERA) == []

# Cache key: same words from two users never share an answer
assert cache_key("Net sales last month?", guard.scope("ana")) != cache_key("Net sales last month?", guard.scope("ravi"))
assert cache_key("Net sales last month?", ANA) == cache_key("  net sales LAST month ", ANA)

print("guard tests: all passed")
