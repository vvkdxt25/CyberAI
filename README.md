# Wire: AI and cybersecurity news

A static site. A Python script collects headlines into `news.json`, a GitHub
Action re-runs it every 3 hours, and `index.html` displays the result.
No API keys, no servers, no cost.

## Deploy with GitHub Pages

1. Push this folder to a GitHub repository on the `main` or `master` branch.
2. In the repository, open **Settings > Pages** and set the source to
   **GitHub Actions**.
3. The **Deploy to GitHub Pages** workflow publishes the site on each push.
   You can also run it manually from the **Actions** tab.
4. In **Settings > Actions > General > Workflow permissions**, allow
   **Read and write permissions** so the **Update news** workflow can commit
   refreshed headlines. Run **Update news** once manually to fetch the first
   batch; it then runs every three hours.

## Run locally

    pip install -r requirements.txt
    python scripts/fetch_news.py
    python -m http.server 8000     # open http://localhost:8000

(Open it through a server; `fetch()` does not work from a file:// URL.)

## Customize

- Add or remove sources at the top of `scripts/fetch_news.py` (`RSS`, `HN_QUERIES`).
- Change the refresh interval in `.github/workflows/update-news.yml` (`cron`).
- Rename the site and change colors in `index.html`.

Only headlines, a short teaser and a link back are shown. Keep it that way
and credit the source, which is already displayed on each story.
