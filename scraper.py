"""
Reddit Comment Scraper (Selenium Driver)
===========================================
Uses headless Chrome browser via Selenium to fetch posts and comments.
Bypasses all Reddit bot/API blocks without needing client IDs or API keys.

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

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Driver initialization
# ---------------------------------------------------------------------------

def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--blink-settings=imagesEnabled=false")  # fast load
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    
    # Suppress chrome logging
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


# ---------------------------------------------------------------------------
# Helpers & Parsing
# ---------------------------------------------------------------------------

def ts_to_iso(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_human(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%d %b %Y %H:%M UTC")


def flatten(comments: list, flat: list = None) -> list:
    if flat is None:
        flat = []
    for c in comments:
        flat.append({k: v for k, v in c.items() if k != "replies"})
        if c.get("replies"):
            flatten(c["replies"], flat)
    return flat


def scrape(url: str, driver=None, progress_cb=None) -> dict:
    """
    Scrape comments from a Reddit URL using Selenium.
    """
    def log(msg, kind="info"):
        if progress_cb:
            progress_cb(msg, kind)
        else:
            print(msg)

    close_driver_on_exit = False
    if driver is None:
        log("Launching headless browser …", "info")
        driver = create_driver()
        close_driver_on_exit = True

    try:
        log(f"Navigating to post: {url}", "info")
        driver.get(url)
        time.sleep(3)

        final_url = driver.current_url
        log(f"Resolved URL: {final_url}", "info")

        # Scroll to load dynamically rendered comments
        log("Loading comments forest …", "info")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for scroll in range(4):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        page_source = driver.page_source
        soup = BeautifulSoup(page_source, "html.parser")

        # Extract Post Metadata
        post_title_el = (
            soup.find("h1")
            or soup.find("shreddit-title")
            or soup.find("a", class_="title")
        )
        post_title = post_title_el.text.strip() if post_title_el else "Reddit Post"

        # Try extract subreddit & author from shreddit components or HTML meta
        subreddit = ""
        sub_meta = soup.find("meta", property="og:title")
        sub_m = re.search(r"r/([a-zA-Z0-9_]+)", final_url)
        if sub_m:
            subreddit = sub_m.group(1)

        post_id_m = re.search(r"/comments/([a-z0-9]+)", final_url)
        post_id = post_id_m.group(1) if post_id_m else "post"

        post_author = "[deleted]"
        post_meta_el = soup.find("shreddit-post")
        if post_meta_el and post_meta_el.get("author"):
            post_author = post_meta_el.get("author")

        log(f'Post Title : "{post_title}"', "head")
        log(f'Subreddit  : r/{subreddit} | ID: {post_id}', "info")

        # Parse shreddit-comment elements
        raw_comments = soup.find_all("shreddit-comment")
        log(f"Found {len(raw_comments)} comments on page.", "info")

        comments = []
        for i, c in enumerate(raw_comments):
            author = c.get("author", "[deleted]")
            score = c.get("score", "0")
            depth = int(c.get("depth", "0"))
            c_id = c.get("thingid", f"c_{i}")

            # Extract text body
            body_el = (
                c.find("div", slot="comment")
                or c.find("div", class_="md")
                or c.find("p")
            )
            body = body_el.text.strip() if body_el else ""

            # Skip empty deleted/bot placeholders if body is empty
            if not body and author == "[deleted]":
                continue

            comments.append({
                "id":            c_id,
                "parent_id":     "",
                "depth":         depth,
                "author":        author,
                "score":         score,
                "created_utc":   "",
                "created_human": "",
                "is_submitter":  False,
                "flair":         "",
                "permalink":     final_url,
                "body":          body,
                "replies":       []
            })

        log(f"✓ Scraped {len(comments)} total comments.", "success")

        post_data = {
            "id":            post_id,
            "title":         post_title,
            "author":        post_author,
            "subreddit":     subreddit,
            "score":         0,
            "upvote_ratio":  None,
            "num_comments":  len(comments),
            "created_utc":   "",
            "url":           final_url,
            "permalink":     final_url,
            "selftext":      "",
            "flair":         "",
            "comments":      comments,
            "total_scraped": len(comments),
        }

        return post_data

    finally:
        if close_driver_on_exit and driver:
            driver.quit()


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------

def save_json(posts_data: list, path: Path):
    path.write_text(json.dumps(posts_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON saved -> {path}")


def save_csv(posts_data: list, path: Path):
    fieldnames = [
        "post_id", "post_title", "post_subreddit",
        "id", "parent_id", "depth", "author", "score",
        "created_utc", "is_submitter", "flair", "permalink", "body",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for post in posts_data:
            for row in flatten(post["comments"]):
                row["post_id"]        = post["id"]
                row["post_title"]     = post["title"]
                row["post_subreddit"] = post["subreddit"]
                writer.writerow(row)
    print(f"CSV  saved -> {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape Reddit comments via Selenium.")
    parser.add_argument("urls", nargs="+", metavar="URL", help="One or more Reddit post URLs")
    parser.add_argument("--output", "-o", choices=["json", "csv", "both"], default="both")
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

    if args.output in ("json", "both"):
        save_json(posts, out_dir / f"{base}.json")
    if args.output in ("csv", "both"):
        save_csv(posts, out_dir / f"{base}.csv")

    total = sum(p["total_scraped"] for p in posts)
    print(f"\nDone! {len(posts)} post(s) | {total} total comments.")


if __name__ == "__main__":
    main()
