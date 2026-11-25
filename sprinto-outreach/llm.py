import json
import re
import time
from pathlib import Path
import config

_CANNED = Path(__file__).parent / "fixtures" / "llm_responses.json"


def _parse(text):
    """Parse a JSON reply, tolerating a ```json fenced block."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


def ask(step, domain, prompt):
    """Return the model's JSON reply as a dict."""
    if config.OFFLINE:
        canned = json.loads(_CANNED.read_text(encoding="utf-8"))
        try:
            return canned[step][domain]
        except KeyError:
            raise KeyError(f"no canned reply for step={step!r} domain={domain!r} in {_CANNED.name}")

    if not config.API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env (or set OFFLINE=1)")
    from google import genai
    client = genai.Client(api_key=config.API_KEY)
    for attempt in range(config.RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model=config.MODEL,
                contents=prompt,
                config={"temperature": config.TEMPERATURE, "response_mime_type": "application/json"},
            )
            return _parse(resp.text)
        except Exception as e:      # bad JSON, rate limit, server error
            if attempt == config.RETRIES:
                raise RuntimeError(f"{step} failed for {domain} after {attempt + 1} tries: {e}") from e
            time.sleep(config.RETRY_BACKOFF * 2 ** attempt)
