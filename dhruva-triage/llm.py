import json
from pathlib import Path
import config

_CANNED = Path(__file__).parent / "fixtures" / "llm_responses.json"

VERDICTS = "match | partial | no-match | insufficient-data"


def build_prompt(app):
    form = {k: v for k, v in app.items() if k != "deck"}
    return (
        "You triage inbound applications for Dhruva Capital against six thesis criteria: "
        f"{', '.join(config.CRITERIA)}.\n"
        f"For each criterion give a verdict ({VERDICTS}) and a citation quoting the form or deck. "
        "If neither the form nor the deck establishes it, use insufficient-data, citation null, "
        "and say why. Do not guess.\n"
        'Reply with JSON only: {"criteria": {"<criterion>": {"verdict": ..., "citation": ..., "why": ...}}}\n\n'
        f"FORM: {json.dumps(form)}\nDECK: {app['deck']}"
    )


def assess(app_id, prompt):
    """Return the model's per-criterion verdicts and token counts for one application."""
    if config.OFFLINE:
        return json.loads(_CANNED.read_text(encoding="utf-8"))[app_id]

    from google import genai
    client = genai.Client(api_key=config.API_KEY)
    resp = client.models.generate_content(
        model=config.MODEL, contents=prompt,
        config={"temperature": config.TEMPERATURE, "response_mime_type": "application/json"})
    reply = json.loads(resp.text)
    usage = resp.usage_metadata
    reply["tokens_in"] = usage.prompt_token_count or 0
    reply["tokens_out"] = usage.candidates_token_count or 0
    return reply
