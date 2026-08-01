# Reddit Comment Scraper

A desktop GUI tool to scrape all comments from specific Reddit posts.

## Features
- Paste one or more Reddit post URLs
- Scrapes ALL comments including nested replies
- Export as JSON and/or CSV
- Clean dark-themed desktop UI (no browser needed)

## Requirements
```
pip install praw
```

## Setup
1. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Create a **script** type app (redirect URI: `http://localhost:8080`)
3. Copy your `client_id` and `client_secret`

## Run
```
python gui.py
```

## Files
- `gui.py` — Desktop UI (run this)
- `scraper.py` — Core scraping logic (CLI version)
- `.env.example` — Credentials template
