"""
build.py — JABchem static site generator
Reads content/content.json and renders HTML pages into /site
"""

import json
import shutil
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def build_search_index(subjects):
    """Return a flat list of search records covering subjects, levels and papers."""
    records = []
    for subj in subjects:
        records.append({
            'type': 'subject',
            'subject': subj['title'],
            'subjectSlug': subj['slug'],
            'icon': subj['icon']['fa'],
            'colour': subj['colour'],
            'url': f"/{subj['slug']}/",
        })
        for level in subj.get('levels', []):
            if not level.get('published', True):
                continue
            records.append({
                'type': 'level',
                'subject': subj['title'],
                'subjectSlug': subj['slug'],
                'icon': subj['icon']['fa'],
                'colour': subj['colour'],
                'level': level['title'],
                'levelSlug': level['slug'],
                'resourceCount': sum(len(s.get('papers', [])) + len(s.get('items', [])) + len(s.get('rows', [])) for s in level.get('sections', [])),
                'url': f"/{subj['slug']}/{level['slug']}/",
            })
            # Collect papers from all sections, preserving section title
            all_level_papers = []
            for sec in level.get('sections', []):
                for p in sec.get('papers', []):
                    all_level_papers.append((p, sec.get('title', '')))

            for paper, sec_title in all_level_papers:
                if not paper.get('published', True):
                    continue
                base = {
                    'type': 'paper',
                    'subject': subj['title'],
                    'subjectSlug': subj['slug'],
                    'icon': subj['icon']['fa'],
                    'colour': subj['colour'],
                    'level': level['title'],
                    'levelSlug': level['slug'],
                    'year': paper['year'],
                    'sectionTitle': sec_title,
                }
                # Multi-part papers (e.g. Maths Paper 1 / Paper 2)
                if 'paperStructure' in subj:
                    for part in subj['paperStructure']['parts']:
                        if paper.get(part['id']):
                            records.append({**base, 'fileLabel': part['label'], 'url': paper[part['id']]})
                else:
                    if paper.get('paper'):
                        records.append({**base, 'fileLabel': 'Past Paper', 'url': paper['paper']})
                # Marking schemes (same for all subjects)
                if paper.get('jabchemMarkingScheme'):
                    records.append({**base, 'fileLabel': 'JABchem Marking Scheme', 'url': paper['jabchemMarkingScheme']})
                if paper.get('markingScheme'):
                    records.append({**base, 'fileLabel': 'SQA Marking Scheme', 'url': paper['markingScheme']})

            # Section records — anchor links into the level page
            for sec in level.get('sections', []):
                if not sec.get('id'):
                    continue
                records.append({
                    'type': 'section',
                    'subject': subj['title'],
                    'subjectSlug': subj['slug'],
                    'icon': subj['icon']['fa'],
                    'colour': subj['colour'],
                    'level': level['title'],
                    'levelSlug': level['slug'],
                    'title': sec['title'],
                    'resourceType': sec.get('resourceType', ''),
                    'url': f"/{subj['slug']}/{level['slug']}/#{sec['id']}",
                })

            # Collect resource items from sections (traffic lights, study notes, etc.)
            resource_labels = {
                'trafficLights': 'Traffic light',
                'studyNotes': 'Study note',
                'dataBooklets': 'Data booklet',
                'formulaSheets': 'Formula sheet',
                'questionMaps': 'Question map',
            }
            for sec in level.get('sections', []):
                rt_key = sec.get('resourceType', '')
                if rt_key not in resource_labels:
                    continue
                rt_label = resource_labels[rt_key]
                for item in sec.get('items', []):
                    if not item.get('published', True) or not item.get('file'):
                        continue
                    records.append({
                        'type': 'resource',
                        'resourceType': rt_key,
                        'resourceLabel': rt_label,
                        'subject': subj['title'],
                        'subjectSlug': subj['slug'],
                        'icon': subj['icon']['fa'],
                        'colour': subj['colour'],
                        'level': level['title'],
                        'levelSlug': level['slug'],
                        'title': item['title'],
                        'url': item['file'],
                    })
    return records

BASE_DIR      = Path(__file__).parent.parent
CONTENT_FILE  = BASE_DIR / 'content' / 'content.json'
FILES_DIR     = BASE_DIR / 'content' / 'files'
SITE_DIR      = BASE_DIR / 'site'
TEMPLATES_DIR = Path(__file__).parent / 'templates'


def load_content():
    with open(CONTENT_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def setup_jinja():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    return env


def write_page(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    print(f"  ✓ {path.relative_to(SITE_DIR)}")


def count_pdfs(path):
    """Count PDF files recursively under a given directory."""
    p = Path(path)
    return len(list(p.rglob('*.pdf'))) if p.exists() else 0


def build():
    print("\nBuilding JABchem static site...\n")

    # Clean and recreate site dir
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)

    content = load_content()
    env = setup_jinja()
    site = content['site']

    published_subjects = [s for s in content['subjects'] if s.get('published', True)]
    # Respect nav order
    order = site['nav'].get('subjectOrder', [])
    ordered = [s for sid in order for s in published_subjects if s['id'] == sid]
    leftover = [s for s in published_subjects if s['id'] not in order]
    subjects = ordered + leftover

    # ── Pre-compute PDF counts from disk ───────────────────────────────────
    total_pdfs = count_pdfs(FILES_DIR)

    # Per-subject and per-level counts keyed by slug
    subject_pdfs = {}
    level_pdfs   = {}
    for subj in subjects:
        subj_dir = FILES_DIR / subj['slug']
        subject_pdfs[subj['slug']] = count_pdfs(subj_dir)
        for level in subj.get('levels', []):
            level_dir = subj_dir / level['slug']
            level_pdfs[f"{subj['slug']}/{level['slug']}"] = count_pdfs(level_dir)

    # ── Home page ──────────────────────────────────────────────────────────
    tmpl = env.get_template('home.html')
    html = tmpl.render(site=site, subjects=subjects,
                       total_pdfs=total_pdfs, subject_pdfs=subject_pdfs,
                       current_path='/')
    write_page(SITE_DIR / 'index.html', html)

    # ── Subject and level pages ────────────────────────────────────────────
    for subj in subjects:
        # Subject home page
        tmpl = env.get_template('subject.html')
        html = tmpl.render(site=site, subjects=subjects, subject=subj,
                           subject_pdfs=subject_pdfs, level_pdfs=level_pdfs,
                           current_path=f'/{subj["slug"]}/')
        write_page(SITE_DIR / subj['slug'] / 'index.html', html)

        for level in subj.get('levels', []):
            if not level.get('published', True):
                continue
            tmpl = env.get_template('level.html')
            html = tmpl.render(
                site=site, subjects=subjects,
                subject=subj, level=level,
                current_path=f'/{subj["slug"]}/{level["slug"]}/'
            )
            write_page(SITE_DIR / subj['slug'] / level['slug'] / 'index.html', html)

    # ── Privacy page ──────────────────────────────────────────────────────────
    if site.get('privacy'):
        tmpl = env.get_template('privacy.html')
        html = tmpl.render(site=site, subjects=subjects, current_path='/privacy/')
        write_page(SITE_DIR / 'privacy' / 'index.html', html)

    # ── 404 page ───────────────────────────────────────────────────────────────
    tmpl = env.get_template('404.html')
    html = tmpl.render(site=site, subjects=subjects, current_path='/404')
    write_page(SITE_DIR / '404.html', html)

    # ── Copy files ─────────────────────────────────────────────────────────
    if FILES_DIR.exists():
        dest = SITE_DIR / 'files'
        shutil.copytree(FILES_DIR, dest)
        print(f"  ✓ files/ copied")

    # ── Copy assets ────────────────────────────────────────────────────────
    assets_src = BASE_DIR / 'admin' / 'static' / 'assets'
    if assets_src.exists():
        shutil.copytree(assets_src, SITE_DIR / 'assets')
        print(f"  ✓ assets/ copied")

    # ── Search index ───────────────────────────────────────────────────────────
    index = build_search_index(subjects)
    (SITE_DIR / 'search-index.json').write_text(
        json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8'
    )
    print(f"  ✓ search-index.json ({len(index)} records)")

    # ── Sitemap ────────────────────────────────────────────────────────────────
    base_url = site.get('baseUrl', '').rstrip('/')
    urls = ['/']
    for subj in subjects:
        urls.append(f'/{subj["slug"]}/')
        for level in subj.get('levels', []):
            if level.get('published', True):
                urls.append(f'/{subj["slug"]}/{level["slug"]}/')
    if site.get('privacy'):
        urls.append('/privacy/')
    sitemap_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap_lines.append(f'  <url><loc>{base_url}{u}</loc></url>')
    sitemap_lines.append('</urlset>')
    (SITE_DIR / 'sitemap.xml').write_text('\n'.join(sitemap_lines), encoding='utf-8')
    print(f"  ✓ sitemap.xml ({len(urls)} URLs)")

    print(f"\n✅ Build complete → {SITE_DIR}\n")
    return True


if __name__ == '__main__':
    try:
        build()
    except Exception as e:
        print(f"\n❌ Build failed: {e}\n", file=sys.stderr)
        sys.exit(1)
