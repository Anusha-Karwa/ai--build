import re

ANTI_THESIS = ["consumer social", "gaming", "creator economy", "nbfc", "lending licence",
               "d2c", "crypto", "web3"]


def anti_thesis(app):
    """Return the anti-thesis term an application hits, or None. Whole-word match on the
    form's sector and model, so e.g. 'd2c' does not fire inside an unrelated word."""
    text = f"{app['sector']} {app['model']}".lower()
    for term in ANTI_THESIS:
        if re.search(rf"\b{re.escape(term)}\b", text):
            return term
    return None
