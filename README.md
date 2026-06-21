# GEO Baselines

Auto-updating Generative Engine Optimization baseline dashboards for The Media Copilot and Eight Sleep.

Live site: `https://YOUR-USERNAME.github.io/geo-baselines/`

## What this does

For each brand, runs the same 15 queries against ChatGPT, Perplexity, Gemini, and Claude every Monday morning. Scores each answer for Mention (brand named) and Citation (brand URL in source list). Also extracts the top cited domains and competitor brand names showing up when the brand is absent. Renders dashboards plus a landing page on GitHub Pages, ready to embed via iframe.

Methodology: see *Getting Started with GEO* by Pete Pachal at [mediacopilot.ai](https://mediacopilot.ai).

## Repo structure

```
.
├── index.html              landing page linking to both dashboards
├── dashboard.html          single template, brand from URL hash
├── runner.py               runs queries, writes data files
├── requirements.txt        python deps for the workflow
├── configs/                brand inputs + query sets + competitor lists
│   ├── media-copilot.json
│   └── eight-sleep.json
├── data/                   results, regenerated weekly by the workflow
│   ├── media-copilot.json
│   └── eight-sleep.json
└── .github/workflows/
    └── update.yml          weekly cron (Mondays 9am ET) + manual trigger
```

## How the weekly update works

1. GitHub Actions runs `update.yml` every Monday at 13:00 UTC (9am ET / 6am PT).
2. The workflow installs Python, reads API keys from repo secrets, runs `runner.py`.
3. `runner.py` reads each config in `configs/`, runs all four engines, writes `data/{slug}.json`.
4. The workflow commits the updated data files back to the repo.
5. GitHub Pages rebuilds. The dashboards show the new data on next page load.

You can also trigger a run manually: **Actions → Update GEO baselines → Run workflow**.

## First-time setup

### 1. Add API keys as repo secrets

**Settings → Secrets and variables → Actions** and add four secrets:

- `OPENAI_API_KEY` — from platform.openai.com
- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `GEMINI_API_KEY` — from aistudio.google.com
- `PERPLEXITY_API_KEY` — from perplexity.ai (Settings → API)

Any engine whose key isn't set will be skipped.

### 2. Enable GitHub Pages

**Settings → Pages → Source: Deploy from a branch → main / (root) → Save.**

After 30 to 60 seconds the site is live at `https://YOUR-USERNAME.github.io/geo-baselines/`.

### 3. Trigger the first run

**Actions → Update GEO baselines → Run workflow.** Takes 8–12 minutes. When it finishes, the data files commit and the live site updates.

## Embedding on a website

The landing page is iframe-friendly. Paste this into any HTML page:

```html
<iframe
  src="https://YOUR-USERNAME.github.io/geo-baselines/"
  width="100%"
  height="900"
  style="border:none;"
  loading="lazy"
></iframe>
```

For a brand-specific embed, use the dashboard URL with the hash:

```html
<iframe src="https://YOUR-USERNAME.github.io/geo-baselines/dashboard.html#eight-sleep" ...></iframe>
```

## Adding a new brand

1. Create `configs/{slug}.json` modeled on the existing ones:
   ```json
   {
     "slug": "your-brand",
     "subject": {
       "brand": "Your Brand",
       "url": "yourbrand.com",
       "person": "Founder Name",
       "brand_aliases": ["Your Brand", "YourBrand"],
       "person_aliases": ["Founder Name"],
       "owned_domains": ["yourbrand.com"],
       "competitors": ["Competitor A", "Competitor B"]
     },
     "queries": [
       { "q": "What is Your Brand", "cat": "Branded", "group": "Branded" },
       ...
     ]
   }
   ```
2. Add the brand to `KNOWN_BRANDS` in `dashboard.html` and to the list in `index.html`.
3. Commit. Next Monday's run populates `data/{slug}.json`.

## Cost note

Weekly run cost across two brands and four engines is roughly $0.20 to $0.50 per week depending on which engines bill (Perplexity Sonar is the most expensive per call; Gemini's free tier covers most of its usage; Anthropic and OpenAI are cheap).

## Local test

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export PERPLEXITY_API_KEY=...
python3 runner.py --brand eight-sleep
python3 -m http.server 8000
# open http://localhost:8000/
```

## License

MIT for the code and methodology. Brand names and visibility scores are factual public observations.
