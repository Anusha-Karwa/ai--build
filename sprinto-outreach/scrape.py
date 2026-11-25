import time
from html.parser import HTMLParser
from pathlib import Path
import requests
import config

PAGES = Path(__file__).parent / "fixtures" / "pages"


def fetch(domain, path="home"):
    """Return cleaned page text for a domain (home or about page), or "" if unavailable."""
    if config.OFFLINE:
        page = PAGES / f"{domain}_{path}.txt"
        return page.read_text(encoding="utf-8") if page.exists() else ""
    url = f"https://{domain}/" + ("" if path == "home" else path)
    for attempt in range(config.RETRIES + 1):
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "sprinto-outreach/1.0"})
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")   # transient: retry
            if resp.status_code >= 400:
                return ""                                             # 404 etc.: page doesn't exist
            return clean(resp.text)
        except requests.RequestException as e:
            if attempt == config.RETRIES:
                print(f"  fetch failed {url} after {attempt + 1} tries: {e}")
                return ""
            time.sleep(config.RETRY_BACKOFF * 2 ** attempt)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def clean(html):
    p = _Text()
    p.feed(html)
    text = "".join(p.parts)
    lines = [" ".join(l.split()) for l in text.splitlines()]
    lines = [l for l in lines if len(l.split()) >= 8]
    seen, out = set(), []
    for l in lines:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return "\n".join(out)[:8000]
