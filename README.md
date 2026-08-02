# Reddit Comment Scraper & Reader

A powerful desktop tool to scrape **100% of comments** from any Reddit post URL — complete with embedded images, GIFs, target tracking, and multi-format exports.

## Features
- **No Credentials Required:** Uses a stealth headless Chrome browser engine (Selenium).
- **Embedded Media Support:** Scrapes text AND inline images, Giphy GIFs, and media attachments.
- **Multi-Format Exports:**
  - 🌐 **Interactive HTML Reader (`.html`)**: Standalone dark-mode offline reader page with color-coded thread depth lines & instant keyword search!
  - 📝 **Markdown (`.md`)**: Clean nested blockquotes for Notion/Obsidian.
  - 📊 **CSV Table (`.csv`)**: Single-line sanitized data table for Excel.
  - 📦 **JSON Data (`.json`)**: Raw structured data.
- **Target Tracking:** Reads post metadata and compares target vs scraped comment count with completion rate % reporting.
- **Desktop GUI:** Built-in dark-themed desktop app (`gui.py`).

## Requirements
```powershell
pip install selenium webdriver-manager beautifulsoup4
```

## Quick Start

### Option 1: Desktop GUI
```powershell
python gui.py
```

### Option 2: Command Line
```powershell
python scraper.py "https://www.reddit.com/r/tamilyapping/s/msP5EVihR7"
```

## Project Structure
- `gui.py` — Desktop App interface
- `scraper.py` — Core scraping engine & formatters
- `.env.example` — Optional credentials template
