"""
Reddit Comment Scraper (Multi-Format & Media Engine)
=====================================================
Extracts text AND embedded media (Images, GIFs, Links) from all comments.

Exports:
  1. Interactive HTML Document (.html) — Renders embedded images and animated GIFs inline!
  2. Formatted Markdown (.md)          — Embedded media links (![image](url))
  3. Structured JSON (.json)           — Includes media_urls list
  4. CSV Table (.csv)                  — Clean single-line CSV rows (sanitized newlines)

Usage:
    python scraper.py "https://www.reddit.com/r/tamilyapping/s/msP5EVihR7"
"""

import os
import sys
import json
import csv
import re
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Stealth Driver Initialization
# ---------------------------------------------------------------------------

def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )
    return driver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts_to_iso(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_human(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%d %b %Y %H:%M UTC")


def flatten(comments: list, flat: list = None) -> list:
    if flat is None:
        flat = []
    for c in comments:
        row = {k: v for k, v in c.items() if k != "replies"}
        if isinstance(row.get("media_urls"), list):
            row["media_urls"] = " | ".join(row["media_urls"])
        flat.append(row)
        if c.get("replies"):
            flatten(c["replies"], flat)
    return flat


def expand_page_comments(driver):
    prev_dom_count = 0
    for pass_num in range(1, 8):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.2)

        click_count = driver.execute_script("""
            let clicked = 0;
            let selectors = [
                'shreddit-more-comment',
                'faceplate-partial',
                'button[aria-label*="comment"]',
                'button[aria-label*="reply"]',
                'button[aria-label*="replies"]',
                'button[aria-label*="more"]'
            ];
            
            document.querySelectorAll(selectors.join(',')).forEach(el => {
                try {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    clicked++;
                } catch(e) {}
            });
            return clicked;
        """)

        time.sleep(1.2)
        current_dom_count = driver.execute_script("return document.querySelectorAll('shreddit-comment').length;")

        if current_dom_count == prev_dom_count and pass_num > 2 and click_count == 0:
            break
        prev_dom_count = current_dom_count


def scrape(url: str, driver=None, progress_cb=None) -> dict:
    def log(msg, kind="info"):
        if progress_cb:
            progress_cb(msg, kind)
        else:
            try:
                print(msg)
            except UnicodeEncodeError:
                print(msg.encode("ascii", errors="replace").decode("ascii"))

    close_driver_on_exit = False
    if driver is None:
        log("Launching stealth browser ...", "info")
        driver = create_driver()
        close_driver_on_exit = True

    try:
        log(f"Navigating to post: {url}", "info")
        driver.get(url)
        time.sleep(3.5)

        final_url = driver.current_url
        base_clean_url = final_url.split("?")[0].rstrip("/")

        post_id_m = re.search(r"/comments/([a-z0-9]+)", base_clean_url)
        post_id = post_id_m.group(1) if post_id_m else "post"

        subreddit = ""
        sub_m = re.search(r"r/([a-zA-Z0-9_]+)", base_clean_url)
        if sub_m:
            subreddit = sub_m.group(1)

        soup_init = BeautifulSoup(driver.page_source, "html.parser")
        post_title_el = (
            soup_init.find("h1")
            or soup_init.find("shreddit-title")
            or soup_init.find("a", class_="title")
        )
        post_title = post_title_el.text.strip() if post_title_el else "Reddit Post"

        if "Prove your humanity" in post_title or "captcha" in driver.page_source.lower():
            log("Warning: Captcha detected, retrying page load...", "warn")
            time.sleep(2)
            driver.get(base_clean_url)
            time.sleep(3.5)
            soup_init = BeautifulSoup(driver.page_source, "html.parser")

        target_count = 0
        post_el = soup_init.find("shreddit-post")
        if post_el and post_el.get("comment-count"):
            try:
                target_count = int(post_el.get("comment-count"))
            except ValueError:
                pass

        post_author = "[deleted]"
        if post_el and post_el.get("author"):
            post_author = post_el.get("author")

        log("==================================================", "head")
        log(f'Post Title : "{post_title}"', "head")
        log(f'Subreddit  : r/{subreddit} | ID: {post_id}', "info")
        log(f'TARGET COMMENTS ON POST: {target_count}', "head")
        log("==================================================", "head")

        sort_modes = ["confidence", "top", "new", "old", "controversial"]
        unique_comments_dict = {}

        for sort_mode in sort_modes:
            sort_url = f"{base_clean_url}/?sort={sort_mode}"
            log(f"Scraping sort view [{sort_mode}] ...", "info")
            driver.get(sort_url)
            time.sleep(2.5)

            expand_page_comments(driver)

            raw_comments = driver.execute_script("""
                let list = [];
                document.querySelectorAll('shreddit-comment').forEach(c => {
                    let id = c.getAttribute('thingid') || c.getAttribute('id') || Math.random().toString();
                    let author = c.getAttribute('author') || '[deleted]';
                    let score = c.getAttribute('score') || '0';
                    let depth = parseInt(c.getAttribute('depth') || '0');
                    let bodyEl = c.querySelector('div[slot="comment"]') || c;
                    let body = bodyEl ? (bodyEl.innerText ? bodyEl.innerText.trim() : '') : '';

                    let mediaUrls = [];
                    bodyEl.querySelectorAll('img, a, faceplate-img, source').forEach(el => {
                        let src = el.getAttribute('src') || el.getAttribute('href') || el.getAttribute('srcset') || '';
                        if (src) {
                            if (!src.includes('avatar') && !src.includes('favicon') && !src.includes('styles/')) {
                                if (src.includes('preview.redd.it') || src.includes('i.redd.it') || src.includes('giphy') || src.includes('.gif') || src.includes('.png') || src.includes('.jpg') || src.includes('.jpeg') || src.includes('external-preview')) {
                                    if (!mediaUrls.includes(src)) {
                                        mediaUrls.push(src);
                                    }
                                }
                            }
                        }
                    });

                    list.push({id, author, score, depth, body, mediaUrls});
                });
                return list;
            """)

            new_count = 0
            for c in raw_comments:
                author = c.get("author", "[deleted]")
                score = c.get("score", "0")
                depth = c.get("depth", 0)
                c_id = c.get("id", "")
                body = c.get("body", "").strip()
                media_urls = c.get("mediaUrls", [])

                if not body and not media_urls and author == "[deleted]":
                    continue

                dedup_key = f"{author}:{body[:50]}:{','.join(media_urls[:2])}"
                if dedup_key not in unique_comments_dict:
                    unique_comments_dict[dedup_key] = {
                        "id":            c_id,
                        "parent_id":     "",
                        "depth":         depth,
                        "author":        author,
                        "score":         score,
                        "created_utc":   "",
                        "created_human": "",
                        "is_submitter":  False,
                        "flair":         "",
                        "permalink":     base_clean_url,
                        "body":          body,
                        "media_urls":    media_urls,
                        "replies":       []
                    }
                    new_count += 1

            scraped_so_far = len(unique_comments_dict)
            log(f"  [{sort_mode}] +{new_count} new unique comments -> Total so far: {scraped_so_far} / {target_count}", "info")

            if target_count > 0 and scraped_so_far >= target_count:
                log("✓ Reached 100% of target comment count!", "success")
                break

        all_comments = list(unique_comments_dict.values())
        scraped_total = len(all_comments)

        completion_pct = (scraped_total / target_count * 100) if target_count > 0 else 100.0

        log("==================================================", "head")
        log("SCRAPE COMPARISON SUMMARY:", "head")
        log(f"  Target Comments Count : {target_count}", "info")
        log(f"  Scraped Unique Comments: {scraped_total}", "success")
        log(f"  Completion Rate        : {completion_pct:.1f}%", "success")
        log("==================================================", "head")

        return {
            "id":            post_id,
            "title":         post_title,
            "author":        post_author,
            "subreddit":     subreddit,
            "score":         0,
            "upvote_ratio":  None,
            "target_count":  target_count,
            "num_comments":  scraped_total,
            "created_utc":   "",
            "url":           base_clean_url,
            "permalink":     base_clean_url,
            "selftext":      "",
            "flair":         "",
            "comments":      all_comments,
            "total_scraped": scraped_total,
        }

    finally:
        if close_driver_on_exit and driver:
            driver.quit()


# ---------------------------------------------------------------------------
# Formatters: HTML, Markdown, JSON, CSV
# ---------------------------------------------------------------------------

def save_json(posts_data: list, path: Path):
    path.write_text(json.dumps(posts_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON     saved -> {path}")


def save_csv(posts_data: list, path: Path):
    """
    Saves clean, single-line CSV rows where body newlines are sanitized into space or \\n.
    """
    fieldnames = [
        "post_id", "post_title", "post_subreddit",
        "id", "parent_id", "depth", "author", "score",
        "created_utc", "is_submitter", "flair", "permalink", "body", "media_urls"
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for post in posts_data:
            for row in flatten(post["comments"]):
                row["post_id"]        = post["id"]
                row["post_title"]     = post["title"]
                row["post_subreddit"] = post["subreddit"]
                # Sanitize body newlines for clean CSV reading
                if isinstance(row.get("body"), str):
                    row["body"] = row["body"].replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                writer.writerow(row)
    print(f"CSV      saved -> {path}")


def save_markdown(posts_data: list, path: Path):
    lines = []
    for post in posts_data:
        target = post.get("target_count", 0)
        scraped = post.get("total_scraped", 0)
        pct = (scraped / target * 100) if target > 0 else 100.0

        lines.append(f"# {post['title']}")
        lines.append(f"**Subreddit:** r/{post['subreddit']} | **Author:** u/{post['author']} | **Comments:** {scraped} / {target} ({pct:.1f}%)\n")
        lines.append(f"**Original Link:** [{post['permalink']}]({post['permalink']})\n")
        lines.append("---\n")

        for c in post["comments"]:
            depth = int(c.get("depth", 0))
            indent = "  " * depth
            author = c["author"]
            score = c.get("score", "0")
            body = c.get("body", "").replace("\n", f"\n{indent}> ")
            media = c.get("media_urls", [])

            lines.append(f"{indent}* **u/{author}** (▲ {score}):")
            if body:
                lines.append(f"{indent}> {body}")
            for m_url in media:
                lines.append(f"{indent}> ![comment media]({m_url})")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown saved -> {path}")


def save_html(posts_data: list, path: Path):
    """
    Generates an interactive HTML reader document that displays embedded images and animated GIFs!
    """
    posts_json = json.dumps(posts_data, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reddit Comments Reader</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0b0e14;
      --card-bg: #151922;
      --card-border: #232936;
      --accent: #ff4500;
      --text: #e2e8f0;
      --text-dim: #8a94a6;
      --success: #22c55e;
      --badge-bg: #1e2638;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 24px 16px;
      max-width: 1000px;
      margin: 0 auto;
    }}
    header {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }}
    .badge {{
      display: inline-block;
      background: var(--badge-bg);
      color: var(--accent);
      font-weight: 600;
      font-size: 0.8rem;
      padding: 4px 10px;
      border-radius: 6px;
      margin-bottom: 12px;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 700; color: #fff; margin-bottom: 12px; }}
    .meta {{ font-size: 0.9rem; color: var(--text-dim); display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }}
    .search-box {{
      width: 100%;
      padding: 12px 16px;
      background: #0f121a;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      color: var(--text);
      font-size: 0.95rem;
      outline: none;
      transition: border-color 0.2s;
    }}
    .search-box:focus {{ border-color: var(--accent); }}
    
    .comment-tree {{ display: flex; flex-direction: column; gap: 8px; }}
    
    .comment-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 14px 18px;
      position: relative;
    }}
    
    .comment-header {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; margin-bottom: 8px; }}
    .author {{ font-weight: 600; color: var(--accent); }}
    .score {{ color: var(--success); font-weight: 600; }}
    
    .comment-body {{ font-size: 0.95rem; color: var(--text); white-space: pre-wrap; word-break: break-word; }}
    
    .media-container {{
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .media-container img {{
      max-width: 100%;
      max-height: 400px;
      border-radius: 8px;
      border: 1px solid var(--card-border);
      object-fit: contain;
    }}

    .depth-0 {{ margin-left: 0px; border-left: 3px solid #ff4500; }}
    .depth-1 {{ margin-left: 20px; border-left: 3px solid #a855f7; }}
    .depth-2 {{ margin-left: 40px; border-left: 3px solid #06b6d4; }}
    .depth-3 {{ margin-left: 60px; border-left: 3px solid #22c55e; }}
    .depth-4 {{ margin-left: 80px; border-left: 3px solid #eab308; }}
    .depth-5 {{ margin-left: 100px; border-left: 3px solid #ec4899; }}

    footer {{ text-align: center; margin-top: 40px; font-size: 0.85rem; color: var(--text-dim); }}
  </style>
</head>
<body>

  <div id="app"></div>

  <script>
    const data = {posts_json};

    function renderApp() {{
      const app = document.getElementById("app");
      let html = "";

      data.forEach(post => {{
        const target = post.target_count || 0;
        const scraped = post.total_scraped || 0;
        const pct = target > 0 ? ((scraped / target) * 100).toFixed(1) : "100";

        html += `
          <header>
            <div class="badge">r/${{post.subreddit}}</div>
            <h1>${{escapeHtml(post.title)}}</h1>
            <div class="meta">
              <span>👤 u/${{post.author}}</span>
              <span>💬 Scraped: <strong>${{scraped}}</strong> of <strong>${{target}}</strong> comments (${{pct}}%)</span>
              <span>🔗 <a href="${{post.permalink}}" target="_blank" style="color:var(--accent)">Original Post</a></span>
            </div>
            <input type="text" class="search-box" id="search-${{post.id}}" placeholder="🔍 Filter comments by keyword, author, or media..." onkeyup="filterComments('${{post.id}}')">
          </header>

          <div class="comment-tree" id="comments-${{post.id}}">
        `;

        post.comments.forEach((c, idx) => {{
          const depth = Math.min(parseInt(c.depth || 0), 5);
          const mediaList = c.media_urls || [];
          
          let mediaHtml = "";
          if (mediaList.length > 0) {{
            mediaHtml += `<div class="media-container">`;
            mediaList.forEach(mUrl => {{
              mediaHtml += `<img src="${{escapeHtml(mUrl)}}" alt="Comment GIF/Image" loading="lazy">`;
            }});
            mediaHtml += `</div>`;
          }}

          html += `
            <div class="comment-card depth-${{depth}}" data-author="${{escapeHtml(c.author).toLowerCase()}}" data-body="${{escapeHtml(c.body).toLowerCase()}}">
              <div class="comment-header">
                <span class="author">u/${{escapeHtml(c.author)}}</span>
                <span class="score">▲ ${{c.score}}</span>
              </div>
              ${{c.body ? `<div class="comment-body">${{escapeHtml(c.body)}}</div>` : ''}}
              ${{mediaHtml}}
            </div>
          `;
        }});

        html += `</div>`;
      }});

      html += `<footer>Exported with Reddit Scraper • ${{new Date().toLocaleDateString()}}</footer>`;
      app.innerHTML = html;
    }}

    function filterComments(postId) {{
      const input = document.getElementById('search-' + postId).value.toLowerCase();
      const cards = document.querySelectorAll('#comments-' + postId + ' .comment-card');
      cards.forEach(card => {{
        const author = card.getAttribute('data-author');
        const body = card.getAttribute('data-body');
        if (author.includes(input) || body.includes(input)) {{
          card.style.display = 'block';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}

    function escapeHtml(str) {{
      if (!str) return '';
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }}

    renderApp();
  </script>
</body>
</html>
"""
    path.write_text(html_content, encoding="utf-8")
    print(f"HTML     saved -> {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape ALL Reddit comments & embedded media (GIFs/Images).")
    parser.add_argument("urls", nargs="+", metavar="URL", help="One or more Reddit post URLs")
    parser.add_argument("--output", "-o", choices=["html", "md", "json", "csv", "all"], default="all")
    parser.add_argument("--out-dir", "-d", default=".")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    driver = create_driver()
    posts = []

    try:
        for i, url in enumerate(args.urls, 1):
            print(f"\n[{i}/{len(args.urls)}] Processing {url}")
            try:
                post = scrape(url, driver=driver)
                posts.append(post)
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
    finally:
        driver.quit()

    if not posts:
        print("No data scraped.")
        return

    base = (
        f"reddit_{posts[0]['subreddit']}_{posts[0]['id']}"
        if len(posts) == 1
        else f"reddit_{len(posts)}_posts"
    )

    fmt = args.output
    if fmt in ("html", "all"):
        save_html(posts, out_dir / f"{base}.html")
    if fmt in ("md", "all"):
        save_markdown(posts, out_dir / f"{base}.md")
    if fmt in ("json", "all"):
        save_json(posts, out_dir / f"{base}.json")
    if fmt in ("csv", "all"):
        save_csv(posts, out_dir / f"{base}.csv")

    total = sum(p["total_scraped"] for p in posts)
    print(f"\nDone! {len(posts)} post(s) | {total} total comments exported.")


if __name__ == "__main__":
    main()
