"""
Reddit Comment Scraper (Selenium Engine)
===========================================
Uses headless Chrome browser via Selenium to fetch posts and ALL comments.
Includes interactive expansion loop for 'load more comments' buttons.

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

# Force UTF-8 output encoding for Windows terminal safety
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
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
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
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


def expand_all_comments(driver, log=print):
    """
    Repeatedly scroll and click all 'shreddit-more-comment' / 'view more' buttons
    to fully hydrate every single comment on the post.
    """
    log("Expanding all comment threads ...", "info")

    for iteration in range(1, 10):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        # Find buttons / elements for more comments
        more_elements = driver.find_elements(
            By.CSS_SELECTOR, "shreddit-more-comment, button, faceplate-partial"
        )
        clicked = 0
        for el in more_elements:
            try:
                tag = el.tag_name
                txt = el.text.lower()
                if (
                    tag == "shreddit-more-comment"
                    or "more" in txt
                    or "view" in txt
                    or "reply" in txt
                    or "replies" in txt
                ):
                    driver.execute_script("arguments[0].click();", el)
                    clicked += 1
            except Exception:
                pass

        total_loaded = len(driver.find_elements(By.TAG_NAME, "shreddit-comment"))
        if clicked > 0:
            log(f"  [Pass {iteration}] Clicked {clicked} expand buttons -> {total_loaded} comments", "info")
        else:
            if iteration > 2:
                break


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
        log("Launching headless browser ...", "info")
        driver = create_driver()
        close_driver_on_exit = True

    try:
        log(f"Navigating to post: {url}", "info")
        driver.get(url)
        time.sleep(3)

        final_url = driver.current_url
        log(f"Resolved URL: {final_url}", "info")

        # Hydrate all comments by scrolling & expanding
        expand_all_comments(driver, log=log)

        page_source = driver.page_source
        soup = BeautifulSoup(page_source, "html.parser")

        # Extract Post Title
        post_title_el = (
            soup.find("h1")
            or soup.find("shreddit-title")
            or soup.find("a", class_="title")
        )
        post_title = post_title_el.text.strip() if post_title_el else "Reddit Post"

        subreddit = ""
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

        # Parse all shreddit-comment elements
        raw_comments = soup.find_all("shreddit-comment")

        comments = []
        for i, c in enumerate(raw_comments):
            author = c.get("author", "[deleted]")
            score = c.get("score", "0")
            depth = int(c.get("depth", "0"))
            c_id = c.get("thingid", f"c_{i}")

            body_el = (
                c.find("div", slot="comment")
                or c.find("div", class_="md")
                or c.find("p")
            )
            body = body_el.text.strip() if body_el else ""

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

        log(f"[SUCCESS] Scraped {len(comments)} total comments.", "success")

        return {
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

    finally:
        if close_driver_on_exit and driver:
            driver.quit()


# ---------------------------------------------------------------------------
# Formatters
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
    parser = argparse.ArgumentParser(description="Scrape ALL Reddit comments via Selenium.")
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
