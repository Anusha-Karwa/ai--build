import os
from dotenv import load_dotenv

load_dotenv()

OFFLINE = os.getenv("OFFLINE", "1") == "1"
API_KEY = os.getenv("GEMINI_API_KEY") or None
MODEL = "gemini-2.0-flash"
TEMPERATURE = 0.2         # low: every step must return parseable JSON

QUALIFY_THRESHOLD = 70    # minimum ICP fit to email, on the same 0-100 scale as the score
MAX_ROUNDS = 2            # extra pages the qualifier may read and re-score on
RETRIES = 2               # extra attempts for a transient fetch / model failure
RETRY_BACKOFF = 1.0       # seconds; doubles each attempt
TO_ADDRESS = "growth.lead@example.com"  # case rule: all mail goes to the student's own inbox
