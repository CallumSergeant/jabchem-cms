# JABchem CMS

A simple local admin app that manages content via `content.json` and generates a fully static website.

## Folder structure

```
jabchem-cms/
├── admin/
│   ├── app.py              ← Flask admin app (run this)
│   └── templates/
│       └── index.html      ← Admin UI
├── content/
│   ├── content.json        ← All site content (subjects, papers, settings)
│   └── files/              ← All uploaded PDFs
│       ├── chemistry/
│       ├── biology/
│       ├── maths/
│       └── physics/
├── builder/
│   ├── build.py            ← Static site generator
│   └── templates/          ← Jinja2 HTML templates
│       ├── base.html
│       ├── home.html
│       ├── subject.html
│       └── level.html
├── site/                   ← Generated static HTML (pushed to GitHub)
├── requirements.txt
├── .env.example
└── .gitignore
```

## First-time setup

### 1. Install Python dependencies

```bash
cd jabchem-cms
python -m venv venv

# Mac / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure GitHub publishing

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `GITHUB_TOKEN` — create one at github.com → Settings → Developer settings → Personal access tokens → Generate new token (classic). Tick the `repo` scope.
- `GITHUB_REPO` — your GitHub username and repo name, e.g. `jabchem/jabchem-site`

### 3. Set up GitHub and Cloudflare Pages (once only)

1. Create a new repository on GitHub
2. Push this project to it:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOURUSERNAME/YOURREPO.git
   git push -u origin main
   ```
3. Go to Cloudflare Pages → Create a project → Connect to Git → select your repo
4. Set build output directory to: `site`
5. Leave build command blank (we build locally)

After this, every time you click "Publish to site" in the admin, it pushes to GitHub and Cloudflare deploys automatically.

## Running the admin

Every time you want to manage content:

```bash
# Mac / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate

cd admin
python app.py
```

Then open **http://localhost:5000** in your browser.

## Day-to-day workflow

1. Open terminal → run `python admin/app.py`
2. Open browser → `http://localhost:5000`
3. Select subject and level
4. Add papers, upload PDFs
5. Click **Publish to site** → live in ~30 seconds

## Adding a new subject

1. Click **+ Add new subject** in the sidebar
2. Fill in name, icon (from fontawesome.com), colour, levels, resource types
3. Click **Create subject**
4. Add papers as normal
5. Publish

## Manual build (without publishing)

If you just want to preview the generated site locally:

```bash
python builder/build.py
```

Then open `site/index.html` in your browser.

## Customising the site design

Edit the Jinja2 templates in `builder/templates/`:
- `base.html` — nav, footer, global CSS
- `home.html` — site homepage
- `subject.html` — subject landing page (e.g. /chemistry/)
- `level.html` — level page with papers table (e.g. /chemistry/national5/)

Nav colours and fonts are controlled by `content.json` → `site.theme`.
