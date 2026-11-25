"""Dhruva triage tools exposed over MCP (stdio).

Run:   .venv\\Scripts\\python.exe mcp_server.py
Test:  .venv\\Scripts\\python.exe ..\\S4\\call_tool.py mcp_server.py
Needs Python 3.10+ and: pip install "mcp>=2"
"""
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # find loader.py whatever folder the host starts us from

import loader  # noqa: E402
from mcp.server import MCPServer  # noqa: E402

# stdout is the MCP channel: never print(). Logs go to stderr.
log = logging.getLogger("dhruva-mcp")
mcp = MCPServer("dhruva-triage")

CSV_PATH = HERE / "data" / "applications.csv"


def _err(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


@mcp.tool()
def get_application(app_id: str) -> dict:
    """Fetch one startup application (fields and deck text) by id, e.g. 'A03'. Use this first, before any assessment. Read only.

    On success returns ok true, the application fields, its deck text, and
    missing_fields: the fields that are blank. Treat those as unknown; never guess them.

    Failures (do not retry any of them):
    NOT_FOUND: no application with that id. Ask once for a valid id, then escalate.
    BAD_INPUT: the id is empty.
    DATA_ERROR: the applications file is missing or malformed. Report it to the user.
    """
    app_id = (app_id or "").strip().upper()
    log.info("get_application %s", app_id)
    if not app_id:
        return _err("BAD_INPUT", "app_id is empty; expected something like 'A03'")

    try:
        apps = loader.load(CSV_PATH)
    except FileNotFoundError:
        return _err("DATA_ERROR", f"applications file not found at {CSV_PATH}")
    except ValueError as e:  # loader raises this for missing columns
        return _err("DATA_ERROR", str(e))

    for app in apps:
        if app["id"].upper() == app_id:
            missing = [k for k in loader.FIELDS if k != "id" and not app[k]]
            return {"ok": True, **app, "missing_fields": missing}
    return _err("NOT_FOUND", f"no application with id {app_id}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run(transport="stdio")
