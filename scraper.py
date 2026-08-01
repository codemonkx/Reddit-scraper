"""
Reddit Comment Scraper — Specific Posts
=========================================
Scrapes ALL comments from one or more Reddit posts you specify.

SETUP (one-time):
  1. Go to: https://www.reddit.com/prefs/apps
  2. Click "create another app" -> choose "script"
  3. Name it anything, redirect URI: http://localhost:8080
  4. Copy client_id and client_secret into .env (see .env.example)

Usage:
    # Single post
    python scraper.py https://www.reddit.com/r/sub/comments/abc123/

    # Multiple posts at once
    python scraper.py https://reddit.com/r/sub/comments/abc123/ https://reddit.com/r/sub/comments/xyz456/

    # CSV only, save to custom folder
    python scraper.py <url> --output csv --out-dir ./results
"""

import praw
import json
import csv
import re
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def load_dotenv():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts_to_iso(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_post_id(url: str) -> str:
    """Extract post ID from any Reddit URL format."""
    url = url.strip().rstrip("/")

    m = re.search(r"reddit\.com/r/[^/]+/comments/([a-z0-9]+)", url, re.I)
    if m:
        return m.group(1)

    m = re.search(r"redd\.it/([a-z0-9]+)", url, re.I)
    if m:
        return m.group(1)

    m = re.search(r"reddit\.com/comments/([a-z0-9]+)", url, re.I)
    if m:
        return m.group(1)

    # Bare post ID
    if re.match(r"^[a-z0-9]+$", url, re.I):
        return url

    raise ValueError(f"Cannot parse a post ID from: {url!r}")


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------

def comment_to_dict(comment) -> dict:
    author = str(comment.author) if comment.author else "[deleted]"
    return {
        "id":           comment.id,
        "parent_id":    comment.parent_id,
        "depth":        comment.depth,
        "author":       author,
        "score":        comment.score,
        "created_utc":  ts_to_iso(comment.created_utc),
        "is_submitter": comment.is_submitter,
        "flair":        comment.author_flair_text or "",
        "permalink":    f"https://www.reddit.com{comment.permalink}",
        "body":         comment.body,
        "replies":      [],
    }


def walk_forest(comment_forest) -> list:
    result = []
    for item in comment_forest:
        if isinstance(item, praw.models.MoreComments):
            continue
        c = comment_to_dict(item)
        c["replies"] = walk_forest(item.replies)
        result.append(c)
    return result


def flatten(comments: list, flat: list = None) -> list:
    if flat is None:
        flat = []
    for c in comments:
        flat.append({k: v for k, v in c.items() if k != "replies"})
        flatten(c["replies"], flat)
    return flat


# ---------------------------------------------------------------------------
# Scrape
# ---------------------------------------------------------------------------

def scrape_post(reddit, url: str) -> dict:
    """Fetch all comments for a single post URL."""
    post_id = extract_post_id(url)
    submission = reddit.submission(id=post_id)

    post_meta = {
        "id":           submission.id,
        "title":        submission.title,
        "author":       str(submission.author) if submission.author else "[deleted]",
        "subreddit":    str(submission.subreddit),
        "score":        submission.score,
        "upvote_ratio": submission.upvote_ratio,
        "num_comments": submission.num_comments,
        "created_utc":  ts_to_iso(submission.created_utc),
        "url":          submission.url,
        "permalink":    f"https://www.reddit.com{submission.permalink}",
        "selftext":     submission.selftext,
        "flair":        submission.link_flair_text or "",
    }

    print(f'\n  Post   : "{submission.title}"')
    print(f'  By     : u/{post_meta["author"]}  |  r/{post_meta["subreddit"]}')
    print(f'  Score  : {post_meta["score"]}  |  Comments: {post_meta["num_comments"]}')

    if submission.num_comments == 0:
        print("  (no comments)")
        return {**post_meta, "comments": [], "total_scraped": 0}

    print("  Expanding all comments ...", end=" ", flush=True)
    submission.comments.replace_more(limit=None)
    comments = walk_forest(submission.comments)
    total = len(flatten(comments))
    print(f"{total} comments collected.")

    return {**post_meta, "comments": comments, "total_scraped": total}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_json(posts_data: list, path: Path):
    path.write_text(json.dumps(posts_data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(p["total_scraped"] for p in posts_data)
    print(f"JSON -> {path}  ({len(posts_data)} post(s), {total} total comments)")


def save_csv(posts_data: list, path: Path):
    fieldnames = [
        "post_id", "post_title", "post_subreddit",
        "id", "parent_id", "depth", "author", "score",
        "created_utc", "is_submitter", "flair", "permalink", "body",
    ]
    total = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for post in posts_data:
            for row in flatten(post["comments"]):
                row["post_id"]        = post["id"]
                row["post_title"]     = post["title"]
                row["post_subreddit"] = post["subreddit"]
                writer.writerow(row)
                total += 1
    print(f"CSV  -> {path}  ({total} rows)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        description="Scrape ALL comments from specific Reddit post(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "urls",
        nargs="+",
        metavar="URL",
        help="One or more Reddit post URLs",
    )
    p.add_argument(
        "--output", "-o",
        choices=["json", "csv", "both"],
        default="both",
        help="Output format (default: both)",
    )
    p.add_argument(
        "--out-dir", "-d",
        default=".",
        help="Output directory (default: current folder)",
    )
    p.add_argument("--client-id",     default=None)
    p.add_argument("--client-secret", default=None)
    p.add_argument("--username",      default=None, help="Your Reddit username (optional)")
    p.add_argument("--password",      default=None, help="Your Reddit password (optional)")
    return p


def main():
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    client_id     = args.client_id     or os.environ.get("REDDIT_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("REDDIT_CLIENT_SECRET")
    username      = args.username      or os.environ.get("REDDIT_USERNAME", "")
    password      = args.password      or os.environ.get("REDDIT_PASSWORD", "")

    if not client_id or not client_secret:
        print(
            "\nERROR: Missing REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET.\n"
            "\nQuick setup:\n"
            "  1. https://www.reddit.com/prefs/apps  ->  create a 'script' app\n"
            "  2. Copy client_id and client_secret into .env\n",
            file=sys.stderr,
        )
        sys.exit(1)

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        user_agent="script:reddit-comment-scraper:v1.0 (personal tool)",
    )
    reddit.read_only = not (username and password)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    posts_data = []
    for i, url in enumerate(args.urls, 1):
        print(f"\n[{i}/{len(args.urls)}] {url}")
        try:
            post_data = scrape_post(reddit, url)
            posts_data.append(post_data)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)

    if not posts_data:
        print("No data scraped.")
        return

    # Output filename: single post → use post id; multiple → combined file
    if len(posts_data) == 1:
        p = posts_data[0]
        base_name = f"reddit_{p['subreddit']}_{p['id']}"
    else:
        base_name = f"reddit_posts_{len(posts_data)}_posts"

    print()
    if args.output in ("json", "both"):
        save_json(posts_data, out_dir / f"{base_name}.json")
    if args.output in ("csv", "both"):
        save_csv(posts_data, out_dir / f"{base_name}.csv")

    total = sum(p["total_scraped"] for p in posts_data)
    print(f"\nDone! {len(posts_data)} post(s) | {total} total comments scraped.")


if __name__ == "__main__":
    main()
