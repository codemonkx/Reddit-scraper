"""
Reddit Comment Scraper (Selenium Multi-Sort Engine)
=====================================================
Scrapes ALL comments from Reddit posts by cycling through all sort modes
(top, new, old, controversial) and expanding all comment threads.

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


def expand_page_comments(driver):
    """
    Scroll and click 'load more comments' / 'view replies' buttons on current page.
    """
    for iteration in range(1, 7):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.2)

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

        if clicked == 0 and iteration > 2:
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
        base_clean_url = final_url.split("?")[0].rstrip("/")

        post_id_m = re.search(r"/comments/([a-z0-9]+)", base_clean_url)
        post_id = post_id_m.group(1) if post_id_m else "post"

        subreddit = ""
        sub_m = re.search(r"r/([a-zA-Z0-9_]+)", base_clean_url)
        if sub_m:
            subreddit = sub_m.group(1)

        # Get initial metadata
        soup_init = BeautifulSoup(driver.page_source, "html.parser")
        post_title_el = (
            soup_init.find("h1")
            or soup_init.find("shreddit-title")
            or soup_init.find("a", class_="title")
        )
        post_title = post_title_el.text.strip() if post_title_el else "Reddit Post"

        post_author = "[deleted]"
        post_meta_el = soup_init.find("shreddit-post")
        if post_meta_el and post_meta_el.get("author"):
            post_author = post_meta_el.get("author")

        log(f'Post Title : "{post_title}"', "head")
        log(f'Subreddit  : r/{subreddit} | ID: {post_id}', "info")

        # Multi-sort scraping to collect 100% of comments across sort filters
        sort_modes = ["top", "new", "old", "controversial"]
        unique_comments_dict = {}

        for sort_mode in sort_modes:
            sort_url = f"{base_clean_url}/?sort={sort_mode}"
            log(f"Fetching comments (sort={sort_mode}) ...", "info")
            driver.get(sort_url)
            time.sleep(2.5)

            expand_page_comments(driver)

            soup = BeautifulSoup(driver.page_source, "html.parser")
            raw_comments = soup.find_all("shreddit-comment")

            new_count = 0
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

                # Key by author + body content to uniquely identify comment
                dedup_key = f"{c_id}:{author}:{body[:60]}"
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
                        "replies":       []
                    }
                    new_count += 1

            log(f"  Sort '{sort_mode}': {len(raw_comments)} comments on page (+{new_count} new unique)", "info")

        all_comments = list(unique_comments_dict.values())
        log(f"[SUCCESS] Total unique comments collected: {len(all_comments)}", "success")

        return {
            "id":            post_id,
            "title":         post_title,
            "author":        post_author,
            "subreddit":     subreddit,
            "score":         0,
            "upvote_ratio":  None,
            "num_comments":  len(all_comments),
            "created_utc":   "",
            "url":           base_clean_url,
            "permalink":     base_clean_url,
            "selftext":      "",
            "flair":         "",
            "comments":      all_comments,
            "total_scraped": len(all_comments),
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
    parser = argparse.ArgumentParser(description="Scrape ALL Reddit comments via Multi-Sort Selenium.")
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
