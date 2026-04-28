#!/usr/bin/env python3
"""
jabchem.org.uk scraper
======================
Fetches every level page from the sitemap, extracts all PDF links (grouped by
the section heading they appear under), downloads the PDFs, and writes
scraped.json — a structured report used by the next import step.

Usage:
    pip install requests beautifulsoup4
    python importer/scrape.py

Output:
    importer/scraped.json      — structured PDF inventory
    importer/files/…           — downloaded PDFs, mirroring the site's paths
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL   = "https://jabchem.org.uk"
OUT_DIR    = Path(__file__).parent / "files"       # downloaded PDFs land here
REPORT     = Path(__file__).parent / "scraped.json"
DELAY      = 1.2   # seconds between requests — be polite

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://jabchem.org.uk/",
}

# Pages to scrape — level pages only (skip home + subject landing pages)
LEVEL_PAGES = [
    "/chemistry/national5/",
    "/chemistry/higher/",
    "/chemistry/advancedhigher/",
    "/chemistry/additional/",
    "/chemistry/archive/",
    "/biology/national5/",
    "/biology/higher/",
    "/biology/advancedhigher/",
    "/biology/archive/",
    "/maths/national5/",
    "/maths/higher/",
    "/maths/advancedhigher/",
    "/maths/archive/",
    "/physics/national5/",
    "/physics/higher/",
    "/physics/advancedhigher/",
    "/physics/archive/",
]

# ── PDF type detection ────────────────────────────────────────────────────────

def detect_type(url: str, anchor_text: str) -> str:
    """
    Guess the resource type from filename / link text.
    Returns one of: paper, markingScheme, jabchemMarkingScheme,
                    trafficLights, questionMaps, studyNotes, dataBooklet, other
    """
    combined = (url + " " + anchor_text).lower()
    fname    = unquote(urlparse(url).path.split("/")[-1]).lower()

    if any(k in combined for k in ("jabchem msch", "jabchemmsch", "jabchem marking", "jabchemmch")):
        return "jabchemMarkingScheme"
    if any(k in combined for k in ("traffic light", "trafficlight", "self eval", "selfeval")):
        return "trafficLights"
    if any(k in combined for k in ("question map", "questionmap", "question bank", "questionbank")):
        return "questionMaps"
    if any(k in combined for k in ("study note", "studynote", "revision note", "notes")):
        return "studyNotes"
    if any(k in combined for k in ("data booklet", "databooklet", "data book")):
        return "dataBooklet"
    if any(k in combined for k in ("msch", "marking scheme", "markingscheme", "mark scheme")):
        return "markingScheme"
    if any(k in combined for k in ("sqa pp", "sqapp", "past paper", "pastpaper")):
        return "paper"
    # Fall back to filename pattern — e.g. "2024_paper.pdf", "2024_ms.pdf"
    if re.search(r'\d{4}.*pp', fname):
        return "paper"
    if re.search(r'\d{4}.*m(sc?h?|ark)', fname):
        return "markingScheme"
    return "other"


def extract_year(url: str, anchor_text: str) -> str | None:
    """Try to extract a 4-digit year from the URL or link text."""
    for source in (anchor_text, unquote(urlparse(url).path)):
        m = re.search(r'(20\d{2}|19\d{2})', source)
        if m:
            return m.group(1)
    return None


# ── HTML parsing ─────────────────────────────────────────────────────────────

def parse_sections(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Walk the page and group PDF links under the nearest heading above them.
    Returns a list of:
        { "heading": str, "links": [{ "url", "text", "type", "year" }] }
    """
    sections: list[dict] = []
    current_heading = "General"
    current_links: list[dict] = []

    # Collect all relevant elements in document order
    for el in soup.find_all(["h1", "h2", "h3", "h4", "a"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            text = el.get_text(strip=True)
            if text:
                # Save what we've collected under the previous heading
                if current_links:
                    sections.append({"heading": current_heading, "links": current_links})
                    current_links = []
                current_heading = text

        elif el.name == "a":
            href = el.get("href", "")
            if not href.lower().endswith(".pdf"):
                continue
            abs_url = urljoin(page_url, href)
            text    = el.get_text(strip=True)
            current_links.append({
                "url":  abs_url,
                "text": text,
                "type": detect_type(abs_url, text),
                "year": extract_year(abs_url, text),
            })

    # Flush last section
    if current_links:
        sections.append({"heading": current_heading, "links": current_links})

    return sections


# ── Downloader ────────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)

def download_pdf(url: str) -> Path | None:
    """Download a PDF and save it mirroring the URL path under OUT_DIR."""
    path_part = unquote(urlparse(url).path).lstrip("/")
    dest      = OUT_DIR / path_part
    if dest.exists():
        print(f"    [skip] {dest.name} (already downloaded)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(url, timeout=30, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        size_kb = dest.stat().st_size // 1024
        print(f"    [ok]   {dest.name} ({size_kb} KB)")
        time.sleep(0.3)
        return dest
    except Exception as e:
        print(f"    [err]  {url}  →  {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape_page(path: str) -> dict:
    url = BASE_URL + path
    print(f"\n→ {url}")
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  FETCH ERROR: {e}")
        return {"url": url, "error": str(e), "sections": []}

    soup     = BeautifulSoup(r.text, "html.parser")
    sections = parse_sections(soup, url)

    total_pdfs = sum(len(s["links"]) for s in sections)
    print(f"  Found {len(sections)} section(s), {total_pdfs} PDF link(s)")
    for sec in sections:
        print(f"  [{sec['heading']}] — {len(sec['links'])} PDF(s)")

    # Download everything
    for sec in sections:
        for link in sec["links"]:
            local = download_pdf(link["url"])
            link["local_path"] = str(local.relative_to(OUT_DIR)) if local else None

    # Parse subject/level from path  e.g. /chemistry/higher/
    parts   = [p for p in path.strip("/").split("/") if p]
    subject = parts[0] if len(parts) > 0 else "unknown"
    level   = parts[1] if len(parts) > 1 else "unknown"

    return {
        "url":      url,
        "subject":  subject,
        "level":    level,
        "sections": sections,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for path in LEVEL_PAGES:
        result = scrape_page(path)
        results.append(result)
        time.sleep(DELAY)

    REPORT.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n✅ Done. Report written to {REPORT}")

    total_links = sum(
        len(s["links"])
        for r in results
        for s in r.get("sections", [])
    )
    errors = sum(1 for r in results for s in r.get("sections", []) for l in s["links"] if l.get("local_path") is None)
    print(f"   {total_links} PDFs found, {errors} failed to download")


if __name__ == "__main__":
    main()
