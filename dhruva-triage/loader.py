import csv
from pathlib import Path

ROOT = Path(__file__).parent
FIELDS = ["id", "name", "stage", "sector", "hq", "founders", "model", "round_size_cr"]


def load(path="data/applications.csv"):
    apps = []
    # utf-8-sig: tolerate a BOM from Excel exports; explicit so Windows doesn't fall back to cp1252.
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            absent = [k for k in FIELDS if k not in row]
            if absent:
                raise ValueError(f"{path}: missing column(s) {absent}")
            deck = ROOT / "decks" / (row["id"] + ".txt")
            apps.append({**{k: row[k] for k in FIELDS},
                         "deck": deck.read_text(encoding="utf-8") if deck.exists() else ""})
    return apps
