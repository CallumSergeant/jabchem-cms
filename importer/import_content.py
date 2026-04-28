#!/usr/bin/env python3
"""
jabchem.org.uk content importer
================================
Reads importer/scraped.json, maps sections into content.json,
copies PDFs into content/files/ with clean canonical names,
and writes the updated content.json.

Usage (from project root):
    python importer/import_content.py
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT       = Path(__file__).parent.parent
SCRAPE     = Path(__file__).parent / "scraped.json"
SRC_FILES  = Path(__file__).parent / "files"
DEST_FILES = ROOT / "content" / "files"
CONTENT    = ROOT / "content" / "content.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(text: str, maxlen: int = 30) -> str:
    s = re.sub(r'[^a-z0-9]+', '_', text.lower().strip()).strip('_')
    return s[:maxlen]


def copy_file(local_path: str, dest_dir: Path, new_name: str) -> str | None:
    """Copy a file from importer/files/ to content/files/ and return the web path."""
    src = SRC_FILES / local_path
    if not src.exists():
        print(f"    [missing] {local_path}")
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / new_name
    shutil.copy2(src, dest)
    return "/" + str(dest.relative_to(ROOT / "content")).replace("\\", "/")


def resolve_year(link: dict) -> str:
    """
    Return a 4-digit year string for a link.
    Falls back to inferring from a 2-digit prefix in the filename
    (e.g. '19AHmsch.pdf' → '2019') when the scraper couldn't extract one.
    """
    year = link.get('year')
    if year:
        return str(year)
    fname = Path(link.get('local_path') or link['url']).name
    # 2-digit year prefix: e.g. '19AHmsch.pdf', '09AHmsch.pdf'
    m = re.match(r'^(\d{2})[A-Za-z]', fname)
    if m:
        yy = int(m.group(1))
        return str(2000 + yy if yy <= 30 else 1900 + yy)
    return 'unknown'


def extract_unit_num(filename: str) -> str | None:
    """Extract a unit number like '1.1' or '3' from a filename."""
    m = re.search(r'(\d+\.\d+)', filename)
    if m:
        return m.group(1)
    m = re.search(r'[Uu]nit\s*(\d+)', filename)
    if m:
        return m.group(1)
    return None


def sort_unit_key(unit: str) -> list:
    """Sort key for unit numbers like '1.1', '2.3', '10'."""
    try:
        return [int(x) for x in unit.split('.')]
    except (ValueError, AttributeError):
        return [999]


# ── Section builders ──────────────────────────────────────────────────────────

def build_past_papers_section(heading: str, links: list, subject: str, level: str, section_id: str) -> dict:
    """Group links by year into paper entries, handling 2-digit year prefixes."""
    dest_dir    = DEST_FILES / subject / level / section_id
    has_jabchem = any(l['type'] == 'jabchemMarkingScheme' for l in links)

    # Group by resolved year — first link of each type per year wins
    by_year: dict[str, dict] = {}
    for link in links:
        year = resolve_year(link)
        by_year.setdefault(year, {})
        t = link['type']
        if t in ('paper', 'markingScheme', 'jabchemMarkingScheme') and t not in by_year[year]:
            by_year[year][t] = link

    def cp(link, suffix):
        if not link or not link.get('local_path'):
            return None
        return copy_file(link['local_path'], dest_dir, f"{year}_{suffix}.pdf")

    papers = []
    for year in sorted(by_year, key=lambda y: int(y) if y.isdigit() else 0, reverse=True):
        group = by_year[year]
        papers.append({
            "year":                 int(year) if year.isdigit() else year,
            "paper":                cp(group.get('paper'),                'paper'),
            "markingScheme":        cp(group.get('markingScheme'),        'ms'),
            "jabchemMarkingScheme": cp(group.get('jabchemMarkingScheme'), 'jabchem_ms'),
            "published":            True,
        })

    return {
        "id":                   section_id,
        "title":                heading,
        "resourceType":         "pastPapers",
        "jabchemMarkingScheme": has_jabchem,
        "papers":               papers,
    }


def build_items_section(heading: str, links: list, resource_type: str,
                        subject: str, level: str, section_id: str) -> dict:
    """Build an items section (trafficLights, studyNotes, questionMaps, dataBooklets)."""
    dest_dir = DEST_FILES / subject / level / section_id
    items = []
    for i, link in enumerate(links):
        if not link.get('local_path'):
            continue
        fname    = Path(link['local_path']).name
        web_path = copy_file(link['local_path'], dest_dir, fname)
        title    = link.get('text') or Path(fname).stem
        items.append({
            "id":        f"item_{i + 1}",
            "title":     title,
            "file":      web_path,
            "published": True,
        })
    return {
        "id":           section_id,
        "title":        heading,
        "resourceType": resource_type,
        "items":        items,
    }


def build_custom_table_section(heading: str, links: list,
                               subject: str, level: str, section_id: str) -> dict:
    """Build a custom table section for miscellaneous file collections."""
    dest_dir = DEST_FILES / subject / level / section_id
    rows = []
    for i, link in enumerate(links):
        if not link.get('local_path'):
            continue
        fname    = Path(link['local_path']).name
        web_path = copy_file(link['local_path'], dest_dir, fname)
        title    = link.get('text') or Path(fname).stem
        rows.append({
            "id":        f"row_{i + 1}",
            "published": True,
            "title":     title,
            "file":      {"label": title, "file": web_path},
        })
    return {
        "id":           section_id,
        "title":        heading,
        "resourceType": "customTable",
        "description":  "",
        "footnote":     "",
        "columns": [
            {"id": "title", "label": "Title", "type": "text"},
            {"id": "file",  "label": "File",  "type": "file"},
        ],
        "rows": rows,
    }


def build_notes_exercises_table(heading: str, links: list,
                                subject: str, level: str, section_id: str) -> dict:
    """
    Build a paired Notes + Exercises custom table.
    Links alternate between studyNotes and 'other' (exercises), grouped by unit number
    extracted from the filename (e.g. '1.1', '2.3').
    """
    dest_dir = DEST_FILES / subject / level / section_id

    # Group by unit number
    units: dict[str, dict] = {}
    for link in links:
        fname = Path(link.get('local_path') or link['url']).name
        unit  = extract_unit_num(fname) or 'misc'
        units.setdefault(unit, {'notes': [], 'exercises': []})
        if link['type'] == 'studyNotes':
            units[unit]['notes'].append(link)
        else:
            units[unit]['exercises'].append(link)

    rows = []
    row_num = 1
    for unit in sorted(units, key=sort_unit_key):
        group     = units[unit]
        notes     = group['notes']
        exercises = group['exercises']
        max_rows  = max(len(notes), len(exercises), 1)

        for j in range(max_rows):
            note_link = notes[j] if j < len(notes) else None
            ex_link   = exercises[j] if j < len(exercises) else None

            def cp_link(link, dest):
                if not link or not link.get('local_path'):
                    return None
                fname = Path(link['local_path']).name
                return copy_file(link['local_path'], dest, fname)

            rows.append({
                "id":        f"row_{row_num}",
                "published": True,
                "number":    unit,
                "notes":     {"label": "", "file": cp_link(note_link, dest_dir)},
                "exercises": {"label": "", "file": cp_link(ex_link,   dest_dir)},
            })
            row_num += 1

    return {
        "id":           section_id,
        "title":        heading,
        "resourceType": "customTable",
        "description":  "",
        "footnote":     "",
        "columns": [
            {"id": "number",    "label": "#",          "type": "text"},
            {"id": "notes",     "label": "Notes",      "type": "file"},
            {"id": "exercises", "label": "Exercises",  "type": "file"},
        ],
        "rows": rows,
    }


# ── Type routing ──────────────────────────────────────────────────────────────

PAPER_TYPES   = {'paper', 'markingScheme', 'jabchemMarkingScheme'}
ITEM_TYPE_MAP = {
    'trafficLights': 'trafficLights',
    'studyNotes':    'studyNotes',
    'questionMaps':  'questionMaps',
    'dataBooklet':   'dataBooklets',
}


def dominant_resource_type(links: list) -> str:
    types = {l['type'] for l in links}
    if types & PAPER_TYPES:
        return 'pastPapers'
    for t, rt in ITEM_TYPE_MAP.items():
        if t in types:
            return rt
    return 'other'


def is_notes_exercises_section(links: list) -> bool:
    """Detect alternating studyNotes + other (exercises) pattern."""
    types = [l['type'] for l in links]
    has_notes     = any(t == 'studyNotes' for t in types)
    has_exercises = any(t == 'other'      for t in types)
    return has_notes and has_exercises


def build_section(heading: str, links: list, subject: str, level: str) -> dict | None:
    if not links:
        return None
    section_id = slugify(heading, maxlen=60)
    res_type   = dominant_resource_type(links)

    if res_type == 'pastPapers':
        return build_past_papers_section(heading, links, subject, level, section_id)
    elif res_type in ('studyNotes', 'other') and is_notes_exercises_section(links):
        return build_notes_exercises_table(heading, links, subject, level, section_id)
    elif res_type == 'other':
        return build_custom_table_section(heading, links, subject, level, section_id)
    else:
        return build_items_section(heading, links, res_type, subject, level, section_id)


# ── Human Biology split ───────────────────────────────────────────────────────

def is_humanbio(link: dict) -> bool:
    return '/humanbiology/' in link['url']


def split_humanbio(sections: list) -> tuple[list, list]:
    """Split biology/higher sections into (biology-only, human-biology-only)."""
    bio, hbio = [], []
    for sec in sections:
        bio_links  = [l for l in sec['links'] if not is_humanbio(l)]
        hbio_links = [l for l in sec['links'] if is_humanbio(l)]
        if bio_links:
            bio.append({**sec, 'links': bio_links})
        if hbio_links:
            hbio.append({**sec, 'links': hbio_links})
    return bio, hbio


# ── Page processor ────────────────────────────────────────────────────────────

def process_sections(scraped_sections: list, subject: str, level: str) -> list:
    out = []
    for sec in scraped_sections:
        built = build_section(sec['heading'], sec['links'], subject, level)
        if built:
            out.append(built)
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    scraped = json.loads(SCRAPE.read_text(encoding='utf-8'))
    content = json.loads(CONTENT.read_text(encoding='utf-8'))

    # Remove any previously imported humanbiology subject so re-runs are safe
    content['subjects'] = [s for s in content['subjects'] if s['id'] != 'humanbiology']
    nav_order = content['site']['nav']['subjectOrder']
    content['site']['nav']['subjectOrder'] = [s for s in nav_order if s != 'humanbiology']

    # Clear all existing sections so re-running doesn't double-up
    for s in content['subjects']:
        s.pop('paperStructure', None)   # maths papers are single combined PDFs
        for lv in s['levels']:
            lv['sections'] = []

    subj_map = {s['id']: s for s in content['subjects']}
    humanbio_sections = []

    for page in scraped:
        subject = page['subject']
        level   = page['level']

        if subject not in subj_map:
            print(f"\n[skip] Unknown subject: {subject}")
            continue

        subj_obj  = subj_map[subject]
        level_map = {lv['id']: lv for lv in subj_obj['levels']}

        if level not in level_map:
            print(f"\n[skip] Unknown level: {subject}/{level}")
            continue

        print(f"\n→ {subject} / {level}")

        # Split Human Biology out of biology/higher
        if subject == 'biology' and level == 'higher':
            bio_secs, hbio_secs = split_humanbio(page['sections'])
            sections            = process_sections(bio_secs,  'biology',     level)
            humanbio_sections   = process_sections(hbio_secs, 'humanbiology', level)
        else:
            sections = process_sections(page['sections'], subject, level)

        level_map[level]['sections'] = sections

        for sec in sections:
            count = len(sec.get('papers') or sec.get('items') or sec.get('rows') or [])
            print(f"  [{sec['title']}] {sec['resourceType']} — {count} entries")

    # Add Human Biology subject
    if humanbio_sections:
        humanbio = {
            "id":           "humanbiology",
            "title":        "Human Biology",
            "shortTitle":   "Human Bio",
            "slug":         "humanbiology",
            "description":  "Past papers and revision materials for SQA Human Biology at Higher.",
            "homeHeroText": "Human Biology revision made easy",
            "published":    True,
            "icon":         {"fa": "fa-dna", "emoji": ""},
            "colour":       "#0E9E8E",
            "levels": [
                {
                    "id":          "higher",
                    "title":       "Higher",
                    "shortTitle":  "Higher",
                    "slug":        "higher",
                    "published":   True,
                    "description": "Higher Human Biology past papers and revision resources.",
                    "sections":    humanbio_sections,
                }
            ],
        }
        content['subjects'].append(humanbio)
        content['site']['nav']['subjectOrder'].append('humanbiology')
        print(f"\n→ humanbiology / higher — {len(humanbio_sections)} sections created")

    CONTENT.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n✅ content.json updated")

    total = sum(
        len(sec.get('papers') or sec.get('items') or sec.get('rows') or [])
        for s  in content['subjects']
        for lv in s['levels']
        for sec in lv.get('sections', [])
    )
    print(f"   {total} total entries across all sections")


if __name__ == "__main__":
    main()
