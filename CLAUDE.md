# JABchem CMS — Project Context for Claude

This file is automatically read by Claude Code when you open this project.
It gives Claude full context on what this project is, what's been built, and what's next.

---

## What this project is

A local Flask-based CMS that manages content for **jabchem.org.uk** — a Scottish SQA revision
website covering Chemistry, Biology, Maths and Physics at National 5, Higher and Advanced Higher.

The CMS lets a non-technical user:
- Add/edit subjects, levels, and past papers via a browser UI
- Upload PDFs which are auto-filed into the correct folder
- Preview the generated site locally before publishing
- Push to GitHub with one click (Cloudflare Pages then auto-deploys)

All content is stored in a single `content/content.json` file. The admin UI reads and writes
that file via a Flask API. A separate `builder/build.py` script renders Jinja2 templates into
a fully static `/site` folder.

---

## Project structure

```
jabchem-cms/
├── admin/
│   ├── app.py                  ← Flask server — run this to start the admin
│   └── templates/
│       └── index.html          ← Full single-page admin UI (vanilla JS + fetch)
├── content/
│   ├── content.json            ← Single source of truth for ALL content
│   └── files/                  ← Uploaded PDFs, organised by subject/level
│       ├── chemistry/{national5,higher,advancedhigher,archive}/
│       ├── biology/...
│       ├── maths/...
│       └── physics/...
├── builder/
│   ├── build.py                ← Static site generator (reads content.json → writes /site)
│   └── templates/
│       ├── base.html           ← Nav, footer, global CSS (Jinja2)
│       ├── home.html           ← Site homepage
│       ├── subject.html        ← Subject landing page e.g. /chemistry/
│       └── level.html          ← Level page with papers table e.g. /chemistry/national5/
├── site/                       ← Generated static HTML — this is what gets deployed
├── requirements.txt
├── .env.example                ← Copy to .env and fill in GitHub token
├── .gitignore
└── README.md
```

---

## How to run

```bash
# 1. Activate virtual environment
source venv/bin/activate      # Mac/Linux
venv\Scripts\activate         # Windows

# 2. Start the admin
cd admin
python app.py
# → Admin UI at http://localhost:5000

# 3. Preview the built site (also available via the UI)
# Click "Preview locally" in the deploy bar → opens http://localhost:5050
```

---

## Key files to know

### `content/content.json`
The entire site lives here. Structure:
```json
{
  "site": { "title", "tagline", "baseUrl", "theme", "nav", "footer" },
  "subjects": [
    {
      "id", "title", "slug", "description", "icon": {"fa": "fa-flask"},
      "colour": "#534AB7",
      "published": true,
      "levels": [
        {
          "id", "title", "slug", "published",
          "papers": [{ "year", "paper", "markingScheme", "questionMap", "published" }],
          "trafficLights": [{ "id", "title", "file", "published" }],
          "archive": [...]
        }
      ],
      "resourceTypes": {
        "pastPapers": true, "markingSchemes": true, "trafficLights": true,
        "questionMaps": true, "dataBooklets": false, "formulaSheets": false,
        "studyNotes": false, "archive": true
      }
    }
  ]
}
```

Maths is special — it has a `paperStructure` key defining Paper 1 + Paper 2:
```json
"paperStructure": {
  "parts": [
    { "id": "paper1", "label": "Paper 1 (Non-calculator)" },
    { "id": "paper2", "label": "Paper 2 (Calculator)" }
  ]
}
```

### `admin/app.py`
Flask app with these main API routes:
- `GET  /api/content` — full content.json
- `PUT  /api/site` — update site-level settings
- `POST /api/subjects` — add a new subject
- `PUT  /api/subjects/<id>` — update subject settings
- `POST /api/subjects/<id>/levels/<id>/papers` — add a paper entry
- `DELETE /api/subjects/<id>/levels/<id>/papers/<year>` — remove a paper
- `POST /api/subjects/<id>/levels/<id>/resources/<type>` — add traffic light / study note etc.
- `POST /api/upload` — upload a PDF file, auto-files it, returns web path
- `POST /api/build` — runs builder/build.py
- `POST /api/preview` — builds site + starts preview server on port 5050
- `GET  /api/preview/status` — is preview running?
- `POST /api/preview/stop` — stop preview server
- `POST /api/publish` — builds + git commits + pushes to GitHub (needs .env)

### `admin/templates/index.html`
Single-page admin UI. All JS is vanilla, no framework. Key functions:
- `boot()` — loads content.json, renders sidebar and home
- `selectSubject(id)` / `selectLevel(id)` — navigation
- `renderResourceContent()` — renders the papers table or resource list for current subject/level
- `savePaper()` — uploads files then POSTs paper data
- `doPreview()` — calls /api/preview, shows build progress, auto-opens tab
- `doPublish()` — calls /api/publish with commit message

### `builder/build.py`
Reads content.json, loops subjects → levels, renders Jinja2 templates, writes to /site/.
Also copies /content/files → /site/files and /admin/static/assets → /site/assets.

---

## Current state (what's done)

- [x] Full content.json schema for Chemistry, Biology, Maths, Physics
- [x] Flask admin with complete API (CRUD for subjects, levels, papers, resources)
- [x] File upload handler — auto-generates canonical paths
- [x] Single-page admin UI with subject/level navigation
- [x] Subject settings modal (rename, icon, colour, resource type toggles)
- [x] Add new subject flow with per-subject resource type config
- [x] Static site builder (Jinja2 → /site HTML)
- [x] Local preview server on port 5050, with build log and status indicator
- [x] GitHub publish route (gitpython, requires .env)
- [x] Base, home, subject, level HTML templates (functional, minimal styling)

---

## What still needs doing (pick up here)

### High priority
- [ ] **Style the public site templates** to match jabchem.org.uk's current design
  - Visit jabchem.org.uk to inspect the current nav, typography, colour scheme
  - Update `builder/templates/base.html` with matching CSS
  - The nav background colour is stored in `content.json → site.theme.navBackground`

- [ ] **Migrate existing content** from jabchem.org.uk into content.json
  - Scrape or manually enter existing past paper links
  - Organise existing PDFs into the /content/files/ folder structure

- [ ] **Test the GitHub publish flow** end-to-end
  - Set up .env with real GITHUB_TOKEN and GITHUB_REPO
  - Verify gitpython push works correctly
  - Connect Cloudflare Pages to the repo

### Medium priority
- [ ] **Drag-to-reorder** subjects in the nav (sidebar and site settings)
- [ ] **Bulk import** — CSV or folder drop to add multiple papers at once
- [ ] **Archive migration** — move papers from current to archive with one click
- [ ] **404 page** — add a custom 404.html template
- [ ] **Image/banner upload** for subject hero images
- [ ] **Search** across papers (client-side JS on the public site)

### Nice to have
- [ ] **Dark mode** for the public site
- [ ] **Print-friendly** CSS for the papers table pages
- [ ] **Sitemap.xml** generation in build.py
- [ ] **robots.txt** generation in build.py
- [ ] **Last updated** timestamp shown on level pages

---

## Design decisions made (don't change without good reason)

- **No database** — content.json is the intentional single source of truth. Simple, portable, version-controlled.
- **No JS framework** in the admin — vanilla JS + fetch keeps it dependency-light and easy to understand.
- **Static output** — the /site folder is pure HTML. No server-side rendering on the live site.
- **Per-subject resource types** — `resourceTypes` flags in each subject control which tabs/fields appear. Adding a new resource type means adding a flag here + a section in level.html.
- **Maths paper structure** — the `paperStructure` key is the extension point for subjects with multi-part papers.
- **Preview on port 5050** — separate from admin on 5000. Daemon thread, killed when admin stops.
- **File paths** follow `/files/{subject}/{level}/{year}_{type}.pdf` — generated automatically, never typed by hand.

---

## Notes on the live site (jabchem.org.uk)

- Hosted on Cloudflare Pages
- Uses Cloudflare for analytics (no cookies)
- Current URL structure: `/chemistry/national5`, `/biology/higher` etc. — matches our slug structure
- The site was on "V2" at time of CMS build — design may have evolved

---

## How to ask Claude for help

Some useful prompts to continue this project:

- *"Style the public site templates to match jabchem.org.uk — here's a screenshot"*
- *"Add a bulk import feature — CSV with columns: subject, level, year, paper_url, ms_url"*
- *"Add a 404.html template and generate it in build.py"*
- *"Add sitemap.xml generation to build.py"*
- *"The GitHub push in app.py isn't working — here's the error"*
- *"Add drag-to-reorder for the subject list in the admin sidebar"*
