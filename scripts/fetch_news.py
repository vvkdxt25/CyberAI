#!/usr/bin/env python3
"""Fetch AI and cybersecurity headlines from free RSS feeds and public APIs
and write them to news.json (no API keys needed).

Run locally:   pip install -r requirements.txt && python scripts/fetch_news.py
"""
import calendar
import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import feedparser
import requests

OUT = Path(__file__).resolve().parent.parent / "news.json"
UA = "Mozilla/5.0 (compatible; WireNewsBot/1.0)"
TIMEOUT = 20
MAX_PER_SOURCE = 8      # keeps one noisy source from dominating
MAX_PER_SECTION = 10    # items shown per section
SNIPPET_CHARS = 180     # short teaser only; the link goes to the original

# ---- Edit these lists to add or remove sources -------------------------------
RSS = {
    "ai": [
        ("OpenAI", "https://openai.com/news/rss.xml"),
        ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
        ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
        ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ],
    "cyber": [
        ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        ("Dark Reading", "https://www.darkreading.com/rss.xml"),
        ("SecurityWeek", "https://feeds.feedburner.com/securityweek"),
        ("Schneier on Security", "https://www.schneier.com/feed/atom/"),
    ],
}
ARXIV = {  # research papers (kept small, they are noisy)
    "ai": ("arXiv cs.AI", "http://export.arxiv.org/api/query?search_query=cat:cs.AI"
                          "&sortBy=submittedDate&sortOrder=descending&max_results=5"),
}
HN_QUERIES = {
    "ai": ["LLM", "OpenAI", "Anthropic", "Gemini", "AI agents"],
    "cyber": ["vulnerability", "ransomware", "zero-day", "CVE", "data breach"],
}
HN_MIN_POINTS = 30
HN_DAYS = 3
HN_MAX = 5  # Hacker News items per section, so it doesn't crowd out the news sites
# A Hacker News title must match one of these words to be shown in that section.
HN_RELEVANT = {
    "ai": r"\b(ai|a\.i\.|llms?|gpt|openai|anthropic|claude|gemini|deepseek|mistral|llama|agents?|agentic|"
          r"machine learning|neural|transformers?|chatbots?|copilot|diffusion|inference)\b",
    "cyber": r"\b(security|cyber\w*|vulnerabilit\w+|ransomware|malware|zero-?days?|0-?days?|cves?|breach\w*|"
             r"exploit\w*|hack\w*|phishing|botnet|backdoor|spyware|infostealer|encryption|attack\w*)\b",
}
CISA_KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
# ------------------------------------------------------------------------------


def log(msg):
    print(msg, file=sys.stderr)


def get(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(text, limit=SNIPPET_CHARS):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def norm_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))


def parse_feed(source, content):
    feed = feedparser.parse(content)
    items = []
    for e in feed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        link = e.get("link")
        title = clean(e.get("title"), 200)
        if not (t and link and title):
            continue
        items.append({
            "title": title,
            "url": link,
            "source": source,
            "date": iso(calendar.timegm(t)),
            "summary": clean(e.get("summary", "")),
        })
    items.sort(key=lambda i: i["date"], reverse=True)
    return items[:MAX_PER_SOURCE]


def fetch_rss(section):
    out = []
    for name, url in RSS[section]:
        try:
            out += parse_feed(name, get(url).content)
        except Exception as ex:
            log(f"[skip] {name}: {ex}")
    return out


def fetch_arxiv(section):
    if section not in ARXIV:
        return []
    name, url = ARXIV[section]
    try:
        return parse_feed(name, get(url).content)
    except Exception as ex:
        log(f"[skip] {name}: {ex}")
        return []


def fetch_hn(section):
    since = int(time.time()) - HN_DAYS * 86400
    items = []
    for q in HN_QUERIES[section]:
        url = (f"https://hn.algolia.com/api/v1/search_by_date?query={quote(q)}&tags=story"
               f"&numericFilters=points>{HN_MIN_POINTS},created_at_i>{since}&hitsPerPage=10")
        try:
            for h in get(url).json().get("hits", []):
                if not h.get("title") or not re.search(HN_RELEVANT[section], h["title"], re.I):
                    continue
                items.append({
                    "title": clean(h["title"], 200),
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "source": "Hacker News",
                    "date": iso(h["created_at_i"]),
                    "summary": f"{h.get('points', 0)} points, {h.get('num_comments', 0)} comments on Hacker News",
                })
        except Exception as ex:
            log(f"[skip] HN '{q}': {ex}")
    items.sort(key=lambda i: i["date"], reverse=True)
    return merge(items)[:HN_MAX]


def fetch_kev():
    try:
        vulns = get(CISA_KEV).json().get("vulnerabilities", [])
    except Exception as ex:
        log(f"[skip] CISA KEV: {ex}")
        return []
    vulns.sort(key=lambda v: v.get("dateAdded", ""), reverse=True)
    items = []
    for v in vulns[:MAX_PER_SOURCE]:
        cve = v["cveID"]
        ransomware = " Known to be used in ransomware campaigns." if v.get("knownRansomwareCampaignUse") == "Known" else ""
        items.append({
            "title": f"{cve}: {v.get('vendorProject', '')} {v.get('product', '')} actively exploited".replace("  ", " "),
            "url": f"https://nvd.nist.gov/vuln/detail/{cve}",
            "source": "CISA KEV",
            "date": f"{v['dateAdded']}T00:00:00Z",
            "summary": clean(v.get("shortDescription", "")) + ransomware,
        })
    return items


def merge(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda i: i["date"], reverse=True):
        key = norm_url(it["url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:MAX_PER_SECTION]


def main():
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text())
        except Exception:
            pass

    result = {"updated": iso(time.time())}
    for section in ("ai", "cyber"):
        items = fetch_rss(section) + fetch_arxiv(section) + fetch_hn(section)
        if section == "cyber":
            items += fetch_kev()
        items = merge(items)
        if not items:  # every source failed: keep the last good data
            log(f"[warn] no items for {section}, keeping previous data")
            items = previous.get(section, [])
        result[section] = items
        log(f"{section}: {len(items)} items")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
