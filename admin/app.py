import os
import json
import shutil
import subprocess
import socket
import sys
import tempfile
import threading
import base64
import math
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import fitz  # PyMuPDF

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent
CONTENT_FILE = BASE_DIR / 'content' / 'content.json'
FILES_DIR    = BASE_DIR / 'content' / 'files'
SITE_DIR     = BASE_DIR / 'site'
BUILDER      = BASE_DIR / 'builder' / 'build.py'

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'svg', 'zip'}

# Live-site repo path (separate GitHub Pages repo)
LIVE_REPO_DIR = Path(os.getenv('LIVE_REPO_PATH', str(BASE_DIR / 'live-site')))

_content_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────
def _default_content():
    return {
        "site": {
            "title": "JABchem", "tagline": "", "baseUrl": "",
            "theme": {"navBackground": "#1a1a2e"},
            "nav": {"subjectOrder": []},
            "footer": {"text": ""}
        },
        "subjects": []
    }

def read_content():
    with _content_lock:
        if not CONTENT_FILE.exists():
            CONTENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONTENT_FILE, 'w', encoding='utf-8') as f:
                json.dump(_default_content(), f, indent=2, ensure_ascii=False)
        with open(CONTENT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

def write_content(data):
    with _content_lock:
        tmp = CONTENT_FILE.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(CONTENT_FILE)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def find_subject(content, subject_id):
    for s in content['subjects']:
        if s['id'] == subject_id:
            return s
    return None

def find_level(subject, level_id):
    for lv in subject.get('levels', []):
        if lv['id'] == level_id:
            return lv
    return None

def find_section(level, section_id):
    for s in level.get('sections', []):
        if s['id'] == section_id:
            return s
    return None

def build_file_path(subject_id, level_id, year, file_type, is_archive=False):
    """Generate a canonical file path for a given resource."""
    base = f"files/{subject_id}/{level_id}"
    if is_archive:
        base += "/archive"
    name = f"{year}_{file_type}.pdf"
    return f"/{base}/{name}"

def build_resource_path(subject_id, level_id, resource_type, filename):
    """Generate a path for non-paper resources like traffic lights."""
    safe = secure_filename(filename)
    return f"/files/{subject_id}/{level_id}/{resource_type}/{safe}"


# ── Admin UI ─────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── Content API ──────────────────────────────────────────────────────────────
@app.route('/api/content', methods=['GET'])
def get_content():
    return jsonify(read_content())

@app.route('/api/site', methods=['PUT'])
def update_site():
    content = read_content()
    content['site'].update(request.json)
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects', methods=['GET'])
def get_subjects():
    content = read_content()
    return jsonify(content['subjects'])

@app.route('/api/subjects', methods=['POST'])
def add_subject():
    content = read_content()
    new_subject = request.json

    # Check slug is unique
    existing_slugs = [s['slug'] for s in content['subjects']]
    if new_subject['slug'] in existing_slugs:
        return jsonify({'error': 'A subject with this URL slug already exists'}), 400

    # Build default level structure — each level starts with an empty Past Papers section
    default_levels = []
    for level_id in new_subject.get('levelIds', ['national5', 'higher', 'advancedhigher']):
        level_titles = {
            'national5': ('National 5', 'N5'),
            'higher': ('Higher', 'Higher'),
            'advancedhigher': ('Advanced Higher', 'AH')
        }
        title, short = level_titles.get(level_id, (level_id.title(), level_id[:3].upper()))
        lv = {
            'id': level_id, 'title': title, 'shortTitle': short,
            'slug': level_id, 'published': True,
            'description': f"{title} {new_subject['title']} past papers and revision resources.",
            'sections': [
                {
                    'id': 'past_papers',
                    'title': 'Past Papers',
                    'resourceType': 'pastPapers',
                    'jabchemMarkingScheme': True,
                    'papers': []
                }
            ]
        }
        default_levels.append(lv)

    new_subject['levels'] = default_levels
    new_subject.pop('resourceTypes', None)  # no longer used

    # Create file directories
    for level_id in new_subject.get('levelIds', ['national5', 'higher', 'advancedhigher']):
        p = FILES_DIR / new_subject['slug'] / level_id
        p.mkdir(parents=True, exist_ok=True)
        (p / 'archive').mkdir(exist_ok=True)

    content['subjects'].append(new_subject)

    # Ensure subject order includes the new subject
    if new_subject['id'] not in content['site']['nav']['subjectOrder']:
        content['site']['nav']['subjectOrder'].append(new_subject['id'])

    write_content(content)
    return jsonify({'status': 'ok', 'subject': new_subject})

@app.route('/api/subjects/<subject_id>', methods=['PUT'])
def update_subject(subject_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404
    updates = request.json
    subject.update(updates)
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>', methods=['DELETE'])
def delete_subject(subject_id):
    content = read_content()
    content['subjects'] = [s for s in content['subjects'] if s['id'] != subject_id]
    if subject_id in content['site']['nav']['subjectOrder']:
        content['site']['nav']['subjectOrder'].remove(subject_id)
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels', methods=['POST'])
def add_level(subject_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404
    data = request.json
    title = data.get('title', '').strip()
    short_title = data.get('shortTitle', '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400
    import re
    level_id = re.sub(r'[^a-z0-9]', '', title.lower().replace(' ', ''))
    if not level_id:
        level_id = 'level_' + str(len(subject.get('levels', [])))
    # Ensure unique id
    existing_ids = [l['id'] for l in subject.get('levels', [])]
    base_id = level_id
    i = 2
    while level_id in existing_ids:
        level_id = base_id + str(i)
        i += 1
    new_level = {
        'id': level_id,
        'title': title,
        'shortTitle': short_title or title[:6],
        'slug': level_id,
        'published': True,
        'description': f"{title} {subject['title']} past papers and revision resources.",
        'sections': [
            {
                'id': 'past_papers',
                'title': 'Past Papers',
                'resourceType': 'pastPapers',
                'jabchemMarkingScheme': True,
                'papers': []
            }
        ]
    }
    subject.setdefault('levels', []).append(new_level)
    # Create file directories
    p = FILES_DIR / subject['slug'] / level_id
    p.mkdir(parents=True, exist_ok=True)
    (p / 'archive').mkdir(exist_ok=True)
    write_content(content)
    return jsonify({'status': 'ok', 'level': new_level})

@app.route('/api/subjects/<subject_id>/levels/<level_id>', methods=['PUT'])
def update_level(subject_id, level_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404
    level = find_level(subject, level_id)
    if not level:
        return jsonify({'error': 'Level not found'}), 404
    level.update(request.json)
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>', methods=['DELETE'])
def delete_level(subject_id, level_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404
    subject['levels'] = [l for l in subject.get('levels', []) if l['id'] != level_id]
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/reorder', methods=['PUT'])
def reorder_levels(subject_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404
    order = request.json.get('order', [])
    levels_by_id = {l['id']: l for l in subject.get('levels', [])}
    subject['levels'] = [levels_by_id[lid] for lid in order if lid in levels_by_id]
    write_content(content)
    return jsonify({'status': 'ok'})


# ── Sections API ─────────────────────────────────────────────────────────────
@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections', methods=['POST'])
def add_section(subject_id, level_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    if not level:
        return jsonify({'error': 'Not found'}), 404
    data = request.json
    title = data.get('title', 'New section')
    resource_type = data.get('resourceType', 'pastPapers')
    import re
    section_id = re.sub(r'[^a-z0-9_]', '', title.lower().replace(' ', '_'))[:30]
    new_section = {'id': section_id, 'title': title, 'resourceType': resource_type}
    if resource_type in ('pastPapers', 'archive'):
        new_section['jabchemMarkingScheme'] = data.get('jabchemMarkingScheme', True)
        new_section['papers'] = []
    elif resource_type == 'customTable':
        new_section['description'] = ''
        new_section['footnote'] = ''
        new_section['columns'] = []
        new_section['rows'] = []
    else:
        new_section['items'] = []
    level.setdefault('sections', []).append(new_section)
    write_content(content)
    return jsonify({'status': 'ok', 'section': new_section})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>', methods=['PUT'])
def update_section(subject_id, level_id, section_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    if not level:
        return jsonify({'error': 'Not found'}), 404
    section = find_section(level, section_id)
    if not section:
        return jsonify({'error': 'Section not found'}), 404
    data = request.json
    for field in ('title', 'jabchemMarkingScheme', 'resourceType', 'description', 'footnote', 'columns', 'rows', 'relationshipBooklet'):
        if field in data:
            section[field] = data[field]
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>', methods=['DELETE'])
def delete_section(subject_id, level_id, section_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    if not level:
        return jsonify({'error': 'Not found'}), 404
    level['sections'] = [s for s in level.get('sections', []) if s['id'] != section_id]
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/reorder', methods=['PUT'])
def reorder_sections(subject_id, level_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    if not level:
        return jsonify({'error': 'Not found'}), 404
    order = request.json.get('order', [])
    sections_by_id = {s['id']: s for s in level.get('sections', [])}
    level['sections'] = [sections_by_id[sid] for sid in order if sid in sections_by_id]
    write_content(content)
    return jsonify({'status': 'ok'})


# ── Papers API ───────────────────────────────────────────────────────────────
@app.route('/api/subjects/<subject_id>/levels/<level_id>/papers', methods=['POST'])
def add_paper(subject_id, level_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    if not subject:
        return jsonify({'error': 'Subject not found'}), 404
    level = find_level(subject, level_id)
    if not level:
        return jsonify({'error': 'Level not found'}), 404

    paper_data = request.json
    year = paper_data.get('year')
    section_id = paper_data.get('section_id')

    if not section_id:
        return jsonify({'error': 'section_id is required'}), 400

    section = find_section(level, section_id)
    if not section:
        return jsonify({'error': 'Section not found'}), 404

    label = (paper_data.get('label') or '').strip()

    new_paper = {
        'year': year,
        'paper': paper_data.get('paper', None),
        'jabchemMarkingScheme': paper_data.get('jabchemMarkingScheme', None),
        'markingScheme': paper_data.get('markingScheme', None),
        'published': True
    }
    if label:
        new_paper['label'] = label

    # Handle multi-part paper subjects (e.g. Maths)
    if 'paperStructure' in subject:
        for part in subject['paperStructure']['parts']:
            new_paper[part['id']] = paper_data.get(part['id'], None)
        new_paper.pop('paper', None)

    target = section.setdefault('papers', [])
    existing_keys = [(p['year'], p.get('label', '') or '') for p in target]
    if (year, label) in existing_keys:
        suffix = f' ({label})' if label else ''
        return jsonify({'error': f'A paper for {year}{suffix} already exists in this section'}), 400

    target.append(new_paper)
    target.sort(key=lambda p: p['year'], reverse=True)

    write_content(content)
    return jsonify({'status': 'ok', 'paper': new_paper})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/papers/<int:year>', methods=['PUT'])
def update_paper(subject_id, level_id, year):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    if not level:
        return jsonify({'error': 'Not found'}), 404
    all_papers = []
    for s in level.get('sections', []):
        all_papers += s.get('papers', [])
    for paper in all_papers:
        if paper['year'] == year:
            paper.update(request.json)
            break
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/papers/<int:year>', methods=['DELETE'])
def delete_paper(subject_id, level_id, year):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    if not level:
        return jsonify({'error': 'Not found'}), 404
    for section in level.get('sections', []):
        section['papers'] = [p for p in section.get('papers', []) if p['year'] != year]
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/papers/<int:year>', methods=['DELETE'])
def delete_paper_in_section(subject_id, level_id, section_id, year):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    label = request.args.get('label', None)
    if label is not None:
        section['papers'] = [p for p in section.get('papers', [])
                             if not (p['year'] == year and (p.get('label', '') or '') == label)]
    else:
        section['papers'] = [p for p in section.get('papers', []) if p['year'] != year]
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/papers/<int:year>', methods=['PUT'])
def update_paper_in_section(subject_id, level_id, section_id, year):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    label = request.args.get('label', None)
    data = request.json
    for paper in section.get('papers', []):
        if paper['year'] == year and (label is None or (paper.get('label', '') or '') == label):
            paper.update(data)
            if 'label' in data and not data['label']:
                paper.pop('label', None)
            break
    write_content(content)
    return jsonify({'status': 'ok'})


# ── Section items API (traffic lights, study notes etc) ─────────────────────
@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/items', methods=['POST'])
def add_section_item(subject_id, level_id, section_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    data = request.json
    items = section.setdefault('items', [])
    item = {
        'id': data.get('id', f"item_{len(items)+1}"),
        'title': data.get('title', 'Untitled'),
        'file': data.get('file', None),
        'published': True
    }
    if data.get('level'):
        item['level'] = data['level']
    if data.get('relationshipBooklet'):
        item['relationshipBooklet'] = data['relationshipBooklet']
    items.append(item)
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/items/<item_id>', methods=['PUT'])
def update_section_item(subject_id, level_id, section_id, item_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    data = request.json
    for item in section.get('items', []):
        if item['id'] == item_id:
            for field in ('title', 'file', 'published', 'level', 'relationshipBooklet'):
                if field in data:
                    if data[field] is None:
                        item.pop(field, None)
                    else:
                        item[field] = data[field]
            break
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/items/<item_id>', methods=['DELETE'])
def delete_section_item(subject_id, level_id, section_id, item_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    section['items'] = [r for r in section.get('items', []) if r['id'] != item_id]
    write_content(content)
    return jsonify({'status': 'ok'})


# ── Custom table rows API ────────────────────────────────────────────────────
@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/rows', methods=['POST'])
def add_table_row(subject_id, level_id, section_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    import time
    data = request.json
    row_id = 'row_' + str(int(time.time() * 1000) % 10000000)
    row = {'id': row_id, 'published': True}
    if 'number' in data:
        row['number'] = data['number']
    for col in section.get('columns', []):
        if col['id'] in data:
            row[col['id']] = data[col['id']]
    section.setdefault('rows', []).append(row)
    write_content(content)
    return jsonify({'status': 'ok', 'row': row})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/rows/<row_id>', methods=['PUT'])
def update_table_row(subject_id, level_id, section_id, row_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    data = request.json
    for row in section.get('rows', []):
        if row['id'] == row_id:
            row.update(data)
            break
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/rows/<row_id>', methods=['DELETE'])
def delete_table_row(subject_id, level_id, section_id, row_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    section['rows'] = [r for r in section.get('rows', []) if r['id'] != row_id]
    write_content(content)
    return jsonify({'status': 'ok'})

@app.route('/api/subjects/<subject_id>/levels/<level_id>/sections/<section_id>/rows/reorder', methods=['PUT'])
def reorder_table_rows(subject_id, level_id, section_id):
    content = read_content()
    subject = find_subject(content, subject_id)
    level = find_level(subject, level_id) if subject else None
    section = find_section(level, section_id) if level else None
    if not section:
        return jsonify({'error': 'Not found'}), 404
    order = request.json.get('order', [])
    rows_by_id = {r['id']: r for r in section.get('rows', [])}
    section['rows'] = [rows_by_id[rid] for rid in order if rid in rows_by_id]
    write_content(content)
    return jsonify({'status': 'ok'})


# ── File Upload ───────────────────────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    subject_id   = request.form.get('subject_id', '')
    level_id     = request.form.get('level_id', '')
    section_id   = request.form.get('section_id', '')
    file_type    = request.form.get('file_type', 'misc')   # paper / ms / qmap / tl / notes / data
    year         = request.form.get('year', '')
    is_archive   = request.form.get('is_archive', 'false') == 'true'
    custom_name  = request.form.get('custom_name', '')

    # Build filename
    if year:
        filename = f"{year}_{file_type}.pdf"
    elif custom_name:
        filename = secure_filename(custom_name)
        if not filename.endswith('.pdf'):
            filename += '.pdf'
    else:
        filename = secure_filename(file.filename)

    # Build destination directory — section_id gives each section its own folder,
    # preventing year collisions across sections in the same level
    dest_dir = FILES_DIR / subject_id / level_id
    if section_id:
        dest_dir = dest_dir / section_id
    elif is_archive:
        dest_dir = dest_dir / 'archive'
    elif file_type in ('trafficLights', 'studyNotes', 'dataBooklets', 'formulaSheets', 'questionMaps'):
        dest_dir = dest_dir / file_type

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    file.save(dest_path)

    # Return the web-root-relative path
    web_path = '/' + str(dest_path.relative_to(FILES_DIR.parent)).replace('\\', '/')
    return jsonify({'status': 'ok', 'path': web_path, 'filename': filename})


# ── Fetch PDF from URL ───────────────────────────────────────────────────────
@app.route('/api/fetch-url', methods=['POST'])
def fetch_from_url():
    import urllib.request
    data = request.json
    url        = data.get('url', '').strip()
    subject_id = data.get('subject_id', '')
    level_id   = data.get('level_id', '')
    section_id = data.get('section_id', '')
    file_type  = data.get('file_type', 'misc')
    year       = data.get('year', '')
    is_archive = data.get('is_archive', False)

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    # Build filename (same logic as upload)
    if year:
        filename = f"{year}_{file_type}.pdf"
    else:
        url_path = url.split('?')[0]
        raw_name = url_path.split('/')[-1]
        filename = secure_filename(raw_name) or 'resource.pdf'
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'

    # Build destination directory
    dest_dir = FILES_DIR / subject_id / level_id
    if section_id:
        dest_dir = dest_dir / section_id
    elif is_archive:
        dest_dir = dest_dir / 'archive'
    elif file_type in ('trafficLights', 'studyNotes', 'dataBooklets', 'formulaSheets', 'questionMaps'):
        dest_dir = dest_dir / file_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest_path.write_bytes(resp.read())
    except Exception as e:
        return jsonify({'error': f'Could not fetch URL: {e}'}), 400

    web_path = '/' + str(dest_path.relative_to(FILES_DIR.parent)).replace('\\', '/')
    return jsonify({'status': 'ok', 'path': web_path, 'filename': filename})


# ── Serve uploaded files (dev only) ─────────────────────────────────────────
@app.route('/files/<path:filepath>')
def serve_file(filepath):
    return send_from_directory(FILES_DIR, filepath)


# ── Build ─────────────────────────────────────────────────────────────────────
@app.route('/api/build', methods=['POST'])
def build_site():
    try:
        result = subprocess.run(
            [sys.executable, str(BUILDER)],
            capture_output=True, text=True, cwd=str(BASE_DIR)
        )
        if result.returncode != 0:
            return jsonify({'status': 'error', 'message': result.stderr}), 500
        return jsonify({'status': 'ok', 'output': result.stdout})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Preview server ───────────────────────────────────────────────────────────
PREVIEW_PORT   = 5050
PREVIEW_SCRIPT = Path(__file__).parent / 'preview_server.py'
_PREVIEW_PID_FILE  = Path(tempfile.gettempdir()) / 'jabchem_preview.pid'
_PREVIEW_PORT_FILE = Path(tempfile.gettempdir()) / 'jabchem_preview.port'


def _get_local_ip():
    """Return the machine's LAN IP, falling back to localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        return 'localhost'


def _preview_url(port):
    """Return the URL for the preview server.
    Respects PREVIEW_DOMAIN env var so a reverse-proxy domain works in production.
    """
    domain = os.getenv('PREVIEW_DOMAIN', '')
    if domain:
        return f'https://{domain}'
    return f'http://{_get_local_ip()}:{port}'


def _find_free_port(start=5050):
    """Find an available port starting from `start`."""
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start


def _stop_preview():
    """Kill the running preview subprocess if one exists."""
    if _PREVIEW_PID_FILE.exists():
        try:
            pid = int(_PREVIEW_PID_FILE.read_text().strip())
            os.kill(pid, 9)
        except (ProcessLookupError, ValueError, OSError):
            pass
        try:
            _PREVIEW_PID_FILE.unlink()
            _PREVIEW_PORT_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def _preview_port():
    """Return the port of the running preview server, or None."""
    if not _PREVIEW_PID_FILE.exists():
        return None
    try:
        pid = int(_PREVIEW_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Raises if process is dead
        if _PREVIEW_PORT_FILE.exists():
            return int(_PREVIEW_PORT_FILE.read_text().strip())
    except (ProcessLookupError, ValueError, OSError):
        pass
    return None


@app.route('/api/preview', methods=['POST'])
def preview_site():
    """Build the site then start (or restart) a local preview server."""
    # 1. Build
    result = subprocess.run(
        [sys.executable, str(BUILDER)],
        capture_output=True, text=True, cwd=str(BASE_DIR)
    )
    if result.returncode != 0:
        return jsonify({'status': 'error', 'message': 'Build failed:\n' + result.stderr}), 500

    # 2. Kill any existing preview process
    _stop_preview()

    # 3. Start a fresh preview subprocess on a free port
    port = _find_free_port(PREVIEW_PORT)
    proc = subprocess.Popen(
        [sys.executable, str(PREVIEW_SCRIPT), str(SITE_DIR), str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    _PREVIEW_PID_FILE.write_text(str(proc.pid))
    _PREVIEW_PORT_FILE.write_text(str(port))

    return jsonify({
        'status': 'ok',
        'port': port,
        'url': _preview_url(port),
        'pages': result.stdout.strip()
    })


@app.route('/api/preview/status', methods=['GET'])
def preview_status():
    """Return whether a preview server is running and on which port."""
    port = _preview_port()
    if port:
        return jsonify({'running': True, 'port': port, 'url': _preview_url(port)})
    return jsonify({'running': False})


@app.route('/api/preview/stop', methods=['POST'])
def stop_preview():
    _stop_preview()
    return jsonify({'status': 'ok'})


# ── Publish to GitHub Pages (live repo) ──────────────────────────────────────
@app.route('/api/publish', methods=['POST'])
def publish():
    import git

    token         = os.getenv('GITHUB_TOKEN', '')
    live_repo_id  = os.getenv('LIVE_GITHUB_REPO', '')   # e.g. username/jabchem-live
    live_branch   = os.getenv('LIVE_GITHUB_BRANCH', 'main')
    git_name      = os.getenv('GIT_USER_NAME', 'JABchem CMS')
    git_email     = os.getenv('GIT_USER_EMAIL', 'cms@jabchem.org.uk')

    if not token or not live_repo_id:
        return jsonify({'error': 'GITHUB_TOKEN and LIVE_GITHUB_REPO must be set in .env'}), 400

    message = request.json.get('message', f'Content update {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    remote_url = f'https://{token}@github.com/{live_repo_id}.git'

    try:
        # 1. Build
        build_result = subprocess.run(
            [sys.executable, str(BUILDER)],
            capture_output=True, text=True, cwd=str(BASE_DIR)
        )
        if build_result.returncode != 0:
            return jsonify({'status': 'error', 'message': 'Build failed: ' + build_result.stderr}), 500

        # 2. Ensure the live repo is cloned locally
        LIVE_REPO_DIR.mkdir(parents=True, exist_ok=True)
        if not (LIVE_REPO_DIR / '.git').exists():
            git.Repo.clone_from(remote_url, str(LIVE_REPO_DIR), branch=live_branch)

        live_repo = git.Repo(str(LIVE_REPO_DIR))
        live_repo.remotes.origin.set_url(remote_url)

        # Configure committer identity
        with live_repo.config_writer() as cw:
            cw.set_value('user', 'name', git_name)
            cw.set_value('user', 'email', git_email)

        # Sync to remote HEAD — fetch then hard reset so local always matches
        # remote before we wipe and re-copy.  Using reset --hard rather than pull
        # avoids merge conflicts when the local repo has diverged (e.g. from a
        # partial previous run).
        live_repo.remotes.origin.fetch()
        live_repo.git.reset('--hard', f'origin/{live_branch}')

        # 3. Preserve files that must survive a wipe (CNAME, GitHub Actions workflows)
        cname_file = LIVE_REPO_DIR / 'CNAME'
        cname = cname_file.read_text() if cname_file.exists() else None

        github_dir = LIVE_REPO_DIR / '.github'
        github_backup = None
        if github_dir.exists():
            github_backup = Path(tempfile.mkdtemp()) / '.github'
            shutil.copytree(github_dir, github_backup)

        # 4. Clear the live repo contents (leave .git intact)
        for item in LIVE_REPO_DIR.iterdir():
            if item.name == '.git':
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # 5. Copy built site/ into live repo
        for item in SITE_DIR.iterdir():
            dest = LIVE_REPO_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # Restore preserved files
        if cname is not None:
            cname_file.write_text(cname)
        if github_backup is not None:
            shutil.copytree(github_backup, github_dir)

        # 6. Commit if there are changes
        live_repo.git.add(A=True)
        porcelain = live_repo.git.status('--porcelain')
        if porcelain.strip():
            live_repo.index.commit(message)

        # 7. Push if local HEAD is ahead of remote.
        #    This also catches the case where a previous commit was made locally
        #    but the push failed, leaving the remote behind.
        try:
            ahead = int(live_repo.git.rev_list('--count', f'origin/{live_branch}..HEAD'))
        except Exception:
            # If the ref comparison fails, push unconditionally so we don't silently skip
            ahead = 1

        if ahead > 0:
            live_repo.remotes.origin.push(f'HEAD:{live_branch}')
            verb = 'Published' if porcelain.strip() else 'Pushed pending commits'
            return jsonify({'status': 'ok', 'message': f'{verb} to GitHub Pages successfully'})
        else:
            try:
                git_log = live_repo.git.log('--oneline', '-5')
            except Exception:
                git_log = '(unavailable)'
            return jsonify({
                'status': 'ok',
                'message': 'Nothing to publish — site is already up to date',
                'debug': {
                    'porcelain': porcelain,
                    'ahead': ahead,
                    'git_log': git_log,
                    'live_repo_dir': str(LIVE_REPO_DIR),
                    'site_dir': str(SITE_DIR),
                }
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Stats ─────────────────────────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    pdf_count = len(list(FILES_DIR.rglob('*.pdf')))
    return jsonify({'pdfCount': pdf_count})


# ── Subject nav order ─────────────────────────────────────────────────────────
@app.route('/api/nav-order', methods=['PUT'])
def update_nav_order():
    content = read_content()
    content['site']['nav']['subjectOrder'] = request.json.get('order', [])
    write_content(content)
    return jsonify({'status': 'ok'})


# ── PDF Editor ────────────────────────────────────────────────────────────────

def _resolve_pdf_path(rel_path):
    """Resolve a relative PDF path to an absolute path inside FILES_DIR."""
    # Strip leading /files/ prefix if present
    rel = rel_path.lstrip('/')
    if rel.startswith('files/'):
        rel = rel[len('files/'):]
    p = (FILES_DIR / rel).resolve()
    # Safety: must stay inside FILES_DIR
    if not str(p).startswith(str(FILES_DIR.resolve())):
        return None
    return p


def _is_blank_page(page):
    """Return True if the page has no text and no images."""
    return page.get_text().strip() == '' and len(page.get_images()) == 0


@app.route('/api/pdf/thumbnails', methods=['GET'])
def pdf_thumbnails():
    rel_path = request.args.get('path', '')
    if not rel_path:
        return jsonify({'error': 'path required'}), 400

    p = _resolve_pdf_path(rel_path)
    if not p or not p.exists():
        return jsonify({'error': 'File not found'}), 404

    try:
        doc = fitz.open(str(p))
        pages = []
        mat = fitz.Matrix(0.3, 0.3)  # ~30% scale for thumbnails
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat)
            thumb = 'data:image/jpeg;base64,' + base64.b64encode(
                pix.tobytes('jpeg', jpg_quality=70)
            ).decode()
            pages.append({
                'index': i,
                'thumb': thumb,
                'isBlank': _is_blank_page(page),
            })
        doc.close()
        return jsonify({'pages': pages, 'count': len(pages)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf/list', methods=['GET'])
def pdf_list():
    """Return all PDFs in FILES_DIR grouped by subject/level."""
    if not FILES_DIR.exists():
        return jsonify([])
    groups = {}
    for pdf in sorted(FILES_DIR.rglob('*.pdf')):
        rel = pdf.relative_to(FILES_DIR)
        parts = rel.parts
        group = '/'.join(parts[:-1]) if len(parts) > 1 else ''
        groups.setdefault(group, []).append({
            'path': str(rel),
            'name': pdf.name,
            'url': '/files/' + str(rel),
        })
    result = [{'group': g, 'files': files} for g, files in sorted(groups.items())]
    return jsonify(result)


@app.route('/api/pdf/save', methods=['POST'])
def pdf_save():
    """
    Build a PDF from specified pages of one or more source files and save.
    Body: { output: "rel/path.pdf", sources: [{ path, pages: [0,1,2] }] }
    """
    data = request.json or {}
    output_rel = data.get('output', '').lstrip('/')
    if output_rel.startswith('files/'):
        output_rel = output_rel[len('files/'):]
    sources = data.get('sources', [])

    if not output_rel or not sources:
        return jsonify({'error': 'output and sources required'}), 400

    output_path = (FILES_DIR / output_rel).resolve()
    if not str(output_path).startswith(str(FILES_DIR.resolve())):
        return jsonify({'error': 'Invalid output path'}), 400

    try:
        result_doc = fitz.open()
        for src in sources:
            src_path = _resolve_pdf_path(src.get('path', ''))
            if not src_path or not src_path.exists():
                return jsonify({'error': f'Source not found: {src.get("path")}'}), 404
            page_indices = src.get('pages', [])
            if not page_indices:
                continue
            src_doc = fitz.open(str(src_path))
            for idx in page_indices:
                if 0 <= idx < len(src_doc):
                    result_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
            src_doc.close()

        if len(result_doc) == 0:
            return jsonify({'error': 'No pages selected'}), 400

        output_path.parent.mkdir(parents=True, exist_ok=True)
        page_count = len(result_doc)
        result_doc.save(str(output_path), garbage=4, deflate=True)
        result_doc.close()
        return jsonify({'status': 'ok', 'pages': page_count, 'path': '/files/' + output_rel})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf/page', methods=['GET'])
def pdf_page_render():
    """Render a single page at full resolution for annotation."""
    rel_path = request.args.get('path', '')
    page_num  = int(request.args.get('page', 0))
    scale     = min(max(float(request.args.get('scale', 1.5)), 0.5), 3.0)

    p = _resolve_pdf_path(rel_path)
    if not p or not p.exists():
        return jsonify({'error': 'File not found'}), 404

    try:
        doc = fitz.open(str(p))
        page_count = len(doc)
        if page_num >= page_count:
            doc.close()
            return jsonify({'error': 'Page out of range'}), 400

        page = doc[page_num]
        mat  = fitz.Matrix(scale, scale)
        pix  = page.get_pixmap(matrix=mat)
        img  = 'data:image/jpeg;base64,' + base64.b64encode(
            pix.tobytes('jpeg', jpg_quality=92)
        ).decode()
        w, h = pix.width, pix.height
        doc.close()
        return jsonify({'image': img, 'width': w, 'height': h,
                        'pageCount': page_count, 'scale': scale})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf/watermark', methods=['POST'])
def pdf_watermark():
    """Stamp text watermark across every page of a PDF."""
    data       = request.json or {}
    path_rel   = data.get('path', '')
    text       = (data.get('text') or '').strip()
    colour_hex = (data.get('colour') or '#cc0000').lstrip('#')
    opacity    = max(0.05, min(1.0, float(data.get('opacity', 0.25))))
    font_size  = max(10,  min(200, int(data.get('fontSize', 60))))
    angle      = int(data.get('angle', 45))

    if not text:
        return jsonify({'error': 'text is required'}), 400

    p = _resolve_pdf_path(path_rel)
    if not p or not p.exists():
        return jsonify({'error': 'File not found'}), 404

    try:
        r = int(colour_hex[0:2], 16) / 255
        g = int(colour_hex[2:4], 16) / 255
        b = int(colour_hex[4:6], 16) / 255
    except (ValueError, IndexError):
        r, g, b = 0.8, 0.0, 0.0

    try:
        doc = fitz.open(str(p))
        cos_a = math.cos(math.radians(angle))
        sin_a = math.sin(math.radians(angle))
        rot   = fitz.Matrix(cos_a, sin_a, -sin_a, cos_a, 0, 0)

        for page in doc:
            rect  = page.rect
            pivot = fitz.Point(rect.width / 2, rect.height / 2)
            page.insert_text(
                pivot, text,
                fontsize=font_size,
                color=(r, g, b),
                fill_opacity=opacity,
                morph=(pivot, rot),
                overlay=True,
            )

        pdf_bytes = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        p.write_bytes(pdf_bytes)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/pdf/annotate', methods=['POST'])
def pdf_annotate():
    """
    Burn shape/text/redact annotations into specific pages of a PDF.
    Body: { path, scale, pages: { "0": [annots], "1": [annots] } }
    Each annot: { type:'rect'|'arrow'|'text'|'redact', colour, thickness,
                  x1,y1,x2,y2  OR  x,y,text,fontSize }
    Coordinates are in rendered-image pixels; divide by scale for PDF points.
    """
    data     = request.json or {}
    path_rel = data.get('path', '')
    scale    = float(data.get('scale', 1.5))
    pages    = data.get('pages', {})

    p = _resolve_pdf_path(path_rel)
    if not p or not p.exists():
        return jsonify({'error': 'File not found'}), 404
    if not pages:
        return jsonify({'error': 'No annotations provided'}), 400

    def hex_to_rgb(h):
        h = (h or '#ff0000').lstrip('#')
        return (int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255)

    try:
        doc = fitz.open(str(p))

        for page_str, annots in pages.items():
            page_num = int(page_str)
            if page_num >= len(doc):
                continue
            page    = doc[page_num]
            redacts = []

            for ann in annots:
                t         = ann.get('type')
                colour    = hex_to_rgb(ann.get('colour', '#ff0000'))
                thickness = max(1, int(ann.get('thickness', 2)))

                if t == 'rect':
                    r = fitz.Rect(ann['x1']/scale, ann['y1']/scale,
                                  ann['x2']/scale, ann['y2']/scale)
                    page.draw_rect(r, color=colour, width=thickness)

                elif t == 'arrow':
                    p1 = fitz.Point(ann['x1']/scale, ann['y1']/scale)
                    p2 = fitz.Point(ann['x2']/scale, ann['y2']/scale)
                    page.draw_line(p1, p2, color=colour, width=thickness)
                    # Arrowhead
                    dx = p2.x - p1.x
                    dy = p2.y - p1.y
                    length = math.sqrt(dx*dx + dy*dy)
                    if length > 0:
                        dx /= length; dy /= length
                        head = 8
                        ang  = 0.45
                        for sign in (1, -1):
                            tip = fitz.Point(
                                p2.x - head*(dx*math.cos(ang) + sign*dy*math.sin(ang)),
                                p2.y - head*(dy*math.cos(ang) - sign*dx*math.sin(ang))
                            )
                            page.draw_line(p2, tip, color=colour, width=thickness)

                elif t == 'text':
                    page.insert_text(
                        fitz.Point(ann['x']/scale, ann['y']/scale),
                        ann.get('text', ''),
                        fontsize=max(6, int(ann.get('fontSize', 12))),
                        color=colour,
                        overlay=True,
                    )

                elif t == 'redact':
                    r = fitz.Rect(ann['x1']/scale, ann['y1']/scale,
                                  ann['x2']/scale, ann['y2']/scale)
                    page.add_redact_annot(r, fill=(0, 0, 0))
                    redacts.append(r)

            if redacts:
                page.apply_redactions()

        pdf_bytes = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        p.write_bytes(pdf_bytes)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _autostart_preview():
    """Start the demo preview server automatically on CMS launch."""
    import time
    time.sleep(1)  # Let Flask bind its port first
    if _preview_port() is not None:
        return
    _stop_preview()
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    port = _find_free_port(PREVIEW_PORT)
    proc = subprocess.Popen(
        [sys.executable, str(PREVIEW_SCRIPT), str(SITE_DIR), str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    _PREVIEW_PID_FILE.write_text(str(proc.pid))
    _PREVIEW_PORT_FILE.write_text(str(port))

threading.Thread(target=_autostart_preview, daemon=True).start()


if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print("\n  JABchem Admin\n  Running at: http://localhost:5000\n")
    app.run(debug=debug, port=5000, host="0.0.0.0")
