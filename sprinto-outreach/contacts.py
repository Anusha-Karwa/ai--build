import csv
import os

DECISION_TITLES = ("security", "cto", "cio", "ciso", "compliance", "engineering", "founder", "ceo")


def find_contact(domain, path="data/contacts.csv", live=False):
    if live:
        return _hunter_contact(domain)

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["domain"].strip() == domain:
                return {"name": row["name"], "title": row["title"], "email": row["email"]}
    return None


def _hunter_contact(domain):
    """Pick the most senior security/engineering contact from Hunter.io (pip package: pyhunter)."""
    from pyhunter import PyHunter
    key = os.getenv("HUNTER_API_KEY")
    if not key:
        raise RuntimeError("HUNTER_API_KEY is not set in .env")
    data = PyHunter(key).domain_search(domain, limit=10) or {}
    for e in data.get("emails", []):
        title = (e.get("position") or "").lower()
        if any(t in title for t in DECISION_TITLES):
            name = " ".join(filter(None, [e.get("first_name"), e.get("last_name")]))
            return {"name": name or e["value"], "title": e.get("position"), "email": e["value"]}
    return None
