"""Gemini calls: one place for the client, retries and token counts."""
import json
import os
import random
import threading
import time

from google import genai
from google.genai import errors, types

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "config.json")))

_client = None
_lock = threading.Lock()
RETRY_CODES = {429, 500, 503, 504}


def _load_env():
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def client():
    global _client
    with _lock:
        if _client is None:
            _load_env()
            _client = genai.Client()
        return _client


def call(model, system, prompt, schema=None, max_tokens=None):
    """Returns (parsed or text, tokens_in, tokens_out). tokens_out includes thinking tokens (billed as output)."""
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        max_output_tokens=max_tokens or CONFIG["max_output_tokens"],
        thinking_config=types.ThinkingConfig(thinking_level=CONFIG["thinking_level"]),
    )
    if schema is not None:
        cfg.response_mime_type = "application/json"
        cfg.response_schema = schema
    tries = CONFIG["rate_limit_retries"]
    for attempt in range(tries + 1):
        try:
            r = client().models.generate_content(model=model, contents=prompt, config=cfg)
            break
        except errors.APIError as e:
            if getattr(e, "code", None) in RETRY_CODES and attempt < tries:
                time.sleep(2 ** (attempt + 1) + random.random())
                continue
            raise
    u = r.usage_metadata
    tin = u.prompt_token_count or 0
    tout = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    out = r.parsed if schema is not None else (r.text or "")
    return out, tin, tout


def cost_inr(model, tin, tout):
    """Rupees for one call, or None until prices are filled in config.json."""
    p = CONFIG["prices"]
    m = p.get(model) or {}
    if p.get("usd_inr") is None or m.get("input_per_m_usd") is None or m.get("output_per_m_usd") is None:
        return None
    return (tin * m["input_per_m_usd"] + tout * m["output_per_m_usd"]) / 1e6 * p["usd_inr"]
