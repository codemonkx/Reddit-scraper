"""
Reddit Comment Scraper — Desktop GUI
======================================
A Tkinter-based desktop UI for scraping comments from specific Reddit posts.

Run:
    python gui.py
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import json
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import praw
except ImportError:
    praw = None


# ─────────────────────────────────────────────────────────────────────────────
# Colours & Fonts
# ─────────────────────────────────────────────────────────────────────────────

BG        = "#0f1117"      # main background
BG2       = "#1a1d27"      # card / panel background
BG3       = "#22263a"      # input fields
ACCENT    = "#ff4500"      # Reddit orange
ACCENT2   = "#ff6534"      # lighter orange
TEXT      = "#e8eaf6"      # primary text
TEXT_DIM  = "#8b90a0"      # muted text
SUCCESS   = "#4caf50"
WARNING   = "#ffc107"
ERROR_CLR = "#f44336"
BORDER    = "#2e3250"

FONT_TITLE  = ("Segoe UI", 18, "bold")
FONT_HEAD   = ("Segoe UI", 11, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_BADGE  = ("Segoe UI", 8, "bold")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (same logic as scraper.py)
# ─────────────────────────────────────────────────────────────────────────────

def ts_to_iso(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_human(utc_ts: float) -> str:
    return datetime.fromtimestamp(utc_ts, tz=timezone.utc).strftime("%d %b %Y  %H:%M UTC")


def extract_post_id(url: str) -> str:
    url = url.strip().rstrip("/")
    for pattern in [
        r"reddit\.com/r/[^/]+/comments/([a-z0-9]+)",
        r"redd\.it/([a-z0-9]+)",
        r"reddit\.com/comments/([a-z0-9]+)",
    ]:
        m = re.search(pattern, url, re.I)
        if m:
            return m.group(1)
    if re.match(r"^[a-z0-9]+$", url, re.I):
        return url
    raise ValueError(f"Cannot parse post ID from: {url!r}")


def load_dotenv():
    env_file = Path(__file__).parent / ".env"
    result = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    return result


def comment_to_dict(comment) -> dict:
    return {
        "id":           comment.id,
        "parent_id":    comment.parent_id,
        "depth":        comment.depth,
        "author":       str(comment.author) if comment.author else "[deleted]",
        "score":        comment.score,
        "created_utc":  comment.created_utc,
        "created_human": ts_to_human(comment.created_utc),
        "is_submitter": comment.is_submitter,
        "flair":        comment.author_flair_text or "",
        "permalink":    f"https://www.reddit.com{comment.permalink}",
        "body":         comment.body,
        "replies":      [],
    }


def walk_forest(forest) -> list:
    result = []
    for item in forest:
        if isinstance(item, praw.models.MoreComments):
            continue
        c = comment_to_dict(item)
        c["replies"] = walk_forest(item.replies)
        result.append(c)
    return result


def flatten(comments, flat=None):
    if flat is None:
        flat = []
    for c in comments:
        flat.append({k: v for k, v in c.items() if k != "replies"})
        flatten(c["replies"], flat)
    return flat


# ─────────────────────────────────────────────────────────────────────────────
# Custom Widgets
# ─────────────────────────────────────────────────────────────────────────────

class RoundedEntry(tk.Frame):
    """Entry widget with a custom dark style."""
    def __init__(self, parent, placeholder="", show="", **kw):
        super().__init__(parent, bg=BG3, highlightbackground=BORDER,
                         highlightthickness=1, **kw)
        self._ph = placeholder
        self._showing_ph = False
        self._show = show

        self.entry = tk.Entry(
            self, bg=BG3, fg=TEXT, insertbackground=ACCENT,
            relief="flat", font=FONT_BODY,
            show=show if show else "",
            bd=0,
        )
        self.entry.pack(fill="x", padx=10, pady=8)

        if placeholder:
            self._set_placeholder()
            self.entry.bind("<FocusIn>",  self._on_focus_in)
            self.entry.bind("<FocusOut>", self._on_focus_out)

        self.entry.bind("<Enter>", lambda e: self.config(highlightbackground=ACCENT))
        self.entry.bind("<Leave>", lambda e: self.config(highlightbackground=BORDER))

    def _set_placeholder(self):
        self.entry.config(show="")
        self.entry.insert(0, self._ph)
        self.entry.config(fg=TEXT_DIM)
        self._showing_ph = True

    def _on_focus_in(self, e):
        if self._showing_ph:
            self.entry.delete(0, "end")
            self.entry.config(fg=TEXT, show=self._show)
            self._showing_ph = False

    def _on_focus_out(self, e):
        if not self.entry.get():
            self._set_placeholder()

    def get(self):
        if self._showing_ph:
            return ""
        return self.entry.get()

    def set(self, val):
        self._showing_ph = False
        self.entry.delete(0, "end")
        self.entry.config(fg=TEXT, show=self._show)
        self.entry.insert(0, val)


class FlatButton(tk.Label):
    """Flat clickable button with hover effect."""
    def __init__(self, parent, text, command=None, bg=ACCENT, fg="white",
                 hover_bg=ACCENT2, padx=20, pady=8, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         font=FONT_HEAD, cursor="hand2",
                         padx=padx, pady=pady, **kw)
        self._bg = bg
        self._hover = hover_bg
        self._cmd = command
        self.bind("<Enter>",  lambda e: self.config(bg=self._hover))
        self.bind("<Leave>",  lambda e: self.config(bg=self._bg))
        self.bind("<Button-1>", lambda e: self._cmd() if self._cmd else None)

    def set_state(self, enabled: bool):
        self._enabled = enabled
        if enabled:
            self.config(cursor="hand2", bg=self._bg)
            self.bind("<Button-1>", lambda e: self._cmd() if self._cmd else None)
        else:
            self.config(cursor="", bg=BG3)
            self.unbind("<Button-1>")


class CommentCard(tk.Frame):
    """A single comment displayed as a card with indent."""
    def __init__(self, parent, comment: dict, **kw):
        depth = comment.get("depth", 0)
        indent = depth * 18

        super().__init__(parent, bg=BG2, **kw)

        # Left accent bar (depth-coloured)
        colours = [ACCENT, "#7c4dff", "#00bcd4", "#4caf50", "#ffc107"]
        bar_colour = colours[min(depth, len(colours) - 1)]
        bar = tk.Frame(self, bg=bar_colour, width=3)
        bar.pack(side="left", fill="y", padx=(indent, 0))

        body = tk.Frame(self, bg=BG2)
        body.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        # Header row
        header = tk.Frame(body, bg=BG2)
        header.pack(fill="x")

        author_text = comment["author"]
        if comment.get("is_submitter"):
            author_text += " [OP]"

        tk.Label(header, text=f"u/{author_text}", fg=ACCENT,
                 bg=BG2, font=FONT_HEAD).pack(side="left")

        score = comment.get("score", 0)
        score_colour = SUCCESS if score > 0 else (ERROR_CLR if score < 0 else TEXT_DIM)
        tk.Label(header, text=f"  ▲ {score}", fg=score_colour,
                 bg=BG2, font=FONT_SMALL).pack(side="left", padx=(8, 0))

        tk.Label(header, text=comment.get("created_human", ""),
                 fg=TEXT_DIM, bg=BG2, font=FONT_SMALL).pack(side="right")

        # Body
        body_text = comment.get("body", "").strip()
        if len(body_text) > 400:
            body_text = body_text[:400] + "…"

        tk.Label(body, text=body_text, fg=TEXT, bg=BG2,
                 font=FONT_BODY, wraplength=680, justify="left",
                 anchor="w").pack(fill="x", pady=(6, 0))

        # Flair
        if comment.get("flair"):
            tk.Label(body, text=f"  {comment['flair']}  ",
                     fg=BG, bg=ACCENT2, font=FONT_BADGE,
                     padx=4, pady=2).pack(anchor="w", pady=(4, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reddit Comment Scraper")
        self.geometry("1100x760")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self.resizable(True, True)

        self._scraped_posts = []   # holds result data
        self._scraping = False

        self._build_ui()
        self._load_saved_credentials()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ──
        topbar = tk.Frame(self, bg=BG2, height=60)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="⬛", fg=ACCENT, bg=BG2,
                 font=("Segoe UI", 22)).pack(side="left", padx=(18, 4), pady=10)
        tk.Label(topbar, text="Reddit Comment Scraper",
                 fg=TEXT, bg=BG2, font=FONT_TITLE).pack(side="left", pady=10)
        tk.Label(topbar, text="Paste your post URL → scrape all comments",
                 fg=TEXT_DIM, bg=BG2, font=FONT_SMALL).pack(side="left", padx=18, pady=10)

        # ── Main pane ──
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # Left panel (inputs)
        left = tk.Frame(main, bg=BG2, width=340)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        left.pack_propagate(False)
        self._build_left(left)

        # Right panel (results)
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self._build_right(right)

    def _build_left(self, parent):
        pad = dict(padx=16)

        tk.Label(parent, text="POST URLS", fg=TEXT_DIM, bg=BG2,
                 font=FONT_BADGE).pack(anchor="w", pady=(18, 4), **pad)

        # URL text area
        url_frame = tk.Frame(parent, bg=BG3, highlightbackground=BORDER,
                             highlightthickness=1)
        url_frame.pack(fill="x", **pad)
        self.url_box = tk.Text(url_frame, bg=BG3, fg=TEXT, insertbackground=ACCENT,
                               relief="flat", font=FONT_BODY, height=5, bd=0,
                               wrap="word")
        self.url_box.pack(fill="x", padx=10, pady=8)
        self.url_box.insert("1.0", "Paste one URL per line…")
        self.url_box.config(fg=TEXT_DIM)
        self.url_box.bind("<FocusIn>",  self._url_focus_in)
        self.url_box.bind("<FocusOut>", self._url_focus_out)
        self._url_placeholder = True

        tk.Label(parent, text="One URL per line. Supports any Reddit URL format.",
                 fg=TEXT_DIM, bg=BG2, font=FONT_SMALL,
                 wraplength=290, justify="left").pack(anchor="w", pady=(4, 12), **pad)

        # Separator
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", **pad, pady=4)

        tk.Label(parent, text="API CREDENTIALS", fg=TEXT_DIM, bg=BG2,
                 font=FONT_BADGE).pack(anchor="w", pady=(12, 4), **pad)

        tk.Label(parent, text="Client ID", fg=TEXT, bg=BG2,
                 font=FONT_SMALL).pack(anchor="w", **pad)
        self.client_id_entry = RoundedEntry(parent, placeholder="From reddit.com/prefs/apps")
        self.client_id_entry.pack(fill="x", **pad, pady=(2, 8))

        tk.Label(parent, text="Client Secret", fg=TEXT, bg=BG2,
                 font=FONT_SMALL).pack(anchor="w", **pad)
        self.client_secret_entry = RoundedEntry(parent, placeholder="Client secret", show="•")
        self.client_secret_entry.pack(fill="x", **pad, pady=(2, 8))

        tk.Label(parent,
                 text="Get free credentials at reddit.com/prefs/apps\n"
                      "(create a 'script' app, any redirect URI)",
                 fg=TEXT_DIM, bg=BG2, font=FONT_SMALL,
                 wraplength=290, justify="left").pack(anchor="w", **pad, pady=(0, 12))

        # Separator
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", **pad, pady=4)

        tk.Label(parent, text="OUTPUT", fg=TEXT_DIM, bg=BG2,
                 font=FONT_BADGE).pack(anchor="w", pady=(12, 4), **pad)

        out_row = tk.Frame(parent, bg=BG2)
        out_row.pack(fill="x", **pad, pady=(0, 8))
        tk.Label(out_row, text="Format:", fg=TEXT, bg=BG2,
                 font=FONT_SMALL).pack(side="left")
        self.fmt_var = tk.StringVar(value="both")
        for val, label in [("json", "JSON"), ("csv", "CSV"), ("both", "Both")]:
            tk.Radiobutton(out_row, text=label, variable=self.fmt_var, value=val,
                           bg=BG2, fg=TEXT, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT,
                           font=FONT_SMALL).pack(side="left", padx=6)

        dir_row = tk.Frame(parent, bg=BG2)
        dir_row.pack(fill="x", **pad, pady=(0, 16))
        self.out_dir_var = tk.StringVar(value=str(Path.cwd()))
        tk.Label(dir_row, text="Save to:", fg=TEXT, bg=BG2,
                 font=FONT_SMALL).pack(side="left")
        tk.Label(dir_row, textvariable=self.out_dir_var,
                 fg=ACCENT, bg=BG2, font=FONT_SMALL,
                 cursor="hand2", wraplength=180, justify="left").pack(side="left", padx=6)
        tk.Label(dir_row, text="✏", fg=TEXT_DIM, bg=BG2,
                 cursor="hand2", font=FONT_BODY).pack(side="left")
        dir_row.bind("<Button-1>", lambda e: self._pick_dir())
        for child in dir_row.winfo_children():
            child.bind("<Button-1>", lambda e: self._pick_dir())

        # Scrape button
        self.scrape_btn = FlatButton(parent, text="▶  SCRAPE COMMENTS",
                                     command=self._start_scrape,
                                     bg=ACCENT, hover_bg=ACCENT2)
        self.scrape_btn.pack(fill="x", **pad, pady=(0, 12))

        # Progress bar
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Reddit.Horizontal.TProgressbar",
                        troughcolor=BG3, background=ACCENT,
                        bordercolor=BG3, lightcolor=ACCENT, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(parent, style="Reddit.Horizontal.TProgressbar",
                                        mode="indeterminate")
        self.progress.pack(fill="x", **pad, pady=(0, 4))

        self.status_label = tk.Label(parent, text="Ready", fg=TEXT_DIM,
                                     bg=BG2, font=FONT_SMALL)
        self.status_label.pack(anchor="w", **pad)

    def _build_right(self, parent):
        # Tabs: Comments | Log
        tab_bar = tk.Frame(parent, bg=BG)
        tab_bar.pack(fill="x")

        self.tab_comments_btn = tk.Label(tab_bar, text="💬 Comments",
                                         bg=BG, fg=ACCENT, font=FONT_HEAD,
                                         padx=16, pady=8, cursor="hand2")
        self.tab_comments_btn.pack(side="left")
        self.tab_log_btn = tk.Label(tab_bar, text="📋 Log",
                                    bg=BG, fg=TEXT_DIM, font=FONT_HEAD,
                                    padx=16, pady=8, cursor="hand2")
        self.tab_log_btn.pack(side="left")

        # Download buttons (top-right)
        dl_row = tk.Frame(tab_bar, bg=BG)
        dl_row.pack(side="right", padx=8)
        FlatButton(dl_row, text="⬇ JSON", command=lambda: self._download("json"),
                   bg=BG3, hover_bg=BORDER, fg=TEXT, padx=12, pady=6).pack(side="left", padx=4)
        FlatButton(dl_row, text="⬇ CSV", command=lambda: self._download("csv"),
                   bg=BG3, hover_bg=BORDER, fg=TEXT, padx=12, pady=6).pack(side="left", padx=4)

        # Content area
        self.content_frame = tk.Frame(parent, bg=BG)
        self.content_frame.pack(fill="both", expand=True)

        # Comments pane
        self.comments_outer = tk.Frame(self.content_frame, bg=BG)
        self.comments_outer.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.canvas = tk.Canvas(self.comments_outer, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(self.comments_outer, orient="vertical",
                                 command=self.canvas.yview,
                                 bg=BG3, troughcolor=BG2)
        scrollbar.pack(side="right", fill="y")
        self.canvas.config(yscrollcommand=scrollbar.set)

        self.comments_inner = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.comments_inner, anchor="nw"
        )
        self.comments_inner.bind("<Configure>", self._on_comments_resize)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Empty state
        self.empty_label = tk.Label(self.comments_inner,
                                    text="🔍\n\nPaste a Reddit post URL\nand click Scrape",
                                    fg=TEXT_DIM, bg=BG, font=("Segoe UI", 13),
                                    justify="center")
        self.empty_label.pack(expand=True, pady=80)

        # Log pane
        self.log_outer = tk.Frame(self.content_frame, bg=BG)

        self.log_box = scrolledtext.ScrolledText(
            self.log_outer, bg=BG2, fg=TEXT_DIM, font=FONT_MONO,
            relief="flat", bd=0, state="disabled",
            insertbackground=TEXT,
        )
        self.log_box.pack(fill="both", expand=True, pady=4)

        # Tag colours for log
        self.log_box.tag_config("info",    foreground=TEXT_DIM)
        self.log_box.tag_config("success", foreground=SUCCESS)
        self.log_box.tag_config("error",   foreground=ERROR_CLR)
        self.log_box.tag_config("warn",    foreground=WARNING)
        self.log_box.tag_config("head",    foreground=ACCENT, font=("Consolas", 9, "bold"))

        # Tab switching
        self.tab_comments_btn.bind("<Button-1>", lambda e: self._show_tab("comments"))
        self.tab_log_btn.bind(     "<Button-1>", lambda e: self._show_tab("log"))
        self._current_tab = "comments"

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _show_tab(self, tab: str):
        self._current_tab = tab
        if tab == "comments":
            self.tab_comments_btn.config(fg=ACCENT)
            self.tab_log_btn.config(fg=TEXT_DIM)
            self.log_outer.place_forget()
            self.comments_outer.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.tab_log_btn.config(fg=ACCENT)
            self.tab_comments_btn.config(fg=TEXT_DIM)
            self.comments_outer.place_forget()
            self.log_outer.place(relx=0, rely=0, relwidth=1, relheight=1)

    # ── URL placeholder ───────────────────────────────────────────────────────

    def _url_focus_in(self, e):
        if self._url_placeholder:
            self.url_box.delete("1.0", "end")
            self.url_box.config(fg=TEXT)
            self._url_placeholder = False

    def _url_focus_out(self, e):
        if not self.url_box.get("1.0", "end").strip():
            self.url_box.insert("1.0", "Paste one URL per line…")
            self.url_box.config(fg=TEXT_DIM)
            self._url_placeholder = True

    # ── Misc ──────────────────────────────────────────────────────────────────

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Choose output folder",
                                    initialdir=self.out_dir_var.get())
        if d:
            self.out_dir_var.set(d)

    def _on_comments_resize(self, e):
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_resize(self, e):
        self.canvas.itemconfig(self.canvas_window, width=e.width)

    def _on_mousewheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _load_saved_credentials(self):
        env = load_dotenv()
        if env.get("REDDIT_CLIENT_ID"):
            self.client_id_entry.set(env["REDDIT_CLIENT_ID"])
        if env.get("REDDIT_CLIENT_SECRET"):
            self.client_secret_entry.set(env["REDDIT_CLIENT_SECRET"])

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, msg: str, kind: str = "info"):
        def _do():
            self.log_box.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {msg}\n", kind)
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _do)

    def set_status(self, msg: str, colour: str = TEXT_DIM):
        self.after(0, lambda: self.status_label.config(text=msg, fg=colour))

    # ── Scraping ──────────────────────────────────────────────────────────────

    def _start_scrape(self):
        if self._scraping:
            return

        if praw is None:
            messagebox.showerror("Missing dependency",
                                 "PRAW is not installed.\n\nRun:\n  pip install praw")
            return

        raw_urls = self.url_box.get("1.0", "end").strip()
        if self._url_placeholder or not raw_urls:
            messagebox.showwarning("No URLs", "Please paste at least one Reddit post URL.")
            return

        urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]
        client_id     = self.client_id_entry.get().strip()
        client_secret = self.client_secret_entry.get().strip()

        if not client_id or not client_secret:
            messagebox.showwarning("Missing credentials",
                                   "Please enter your Reddit API Client ID and Client Secret.")
            return

        self._scraping = True
        self.scrape_btn.set_state(False)
        self.scrape_btn.config(text="⏳ Scraping…")
        self.progress.start(12)
        self._scraped_posts = []
        self._clear_comments()
        self._show_tab("log")
        self.log(f"Starting scrape for {len(urls)} URL(s)…", "head")

        thread = threading.Thread(
            target=self._scrape_thread,
            args=(urls, client_id, client_secret),
            daemon=True,
        )
        thread.start()

    def _scrape_thread(self, urls, client_id, client_secret):
        try:
            reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent="script:reddit-comment-scraper-gui:v1.0",
            )
            reddit.read_only = True

            posts_data = []
            for i, url in enumerate(urls, 1):
                self.log(f"[{i}/{len(urls)}] {url}", "head")
                self.set_status(f"Fetching post {i}/{len(urls)}…")
                try:
                    post_id = extract_post_id(url)
                    submission = reddit.submission(id=post_id)

                    self.log(f'  Title  : {submission.title}', "info")
                    self.log(f'  Author : u/{submission.author}  |  r/{submission.subreddit}', "info")
                    self.log(f'  Score  : {submission.score}  |  Comments: {submission.num_comments}', "info")

                    if submission.num_comments == 0:
                        self.log("  (No comments on this post)", "warn")
                        continue

                    self.log("  Expanding all comments… (may take a moment)", "info")
                    self.set_status(f"Expanding comments for post {i}…")
                    submission.comments.replace_more(limit=None)
                    comments = walk_forest(submission.comments)
                    flat = flatten(comments)
                    self.log(f"  ✓ {len(flat)} comments collected.", "success")

                    posts_data.append({
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
                        "comments":     comments,
                        "total_scraped": len(flat),
                    })

                except ValueError as e:
                    self.log(f"  ✗ Bad URL: {e}", "error")
                except Exception as e:
                    self.log(f"  ✗ Error: {e}", "error")

            self._scraped_posts = posts_data

            # Auto-save
            if posts_data:
                self._auto_save()
                self.set_status(
                    f"Done — {sum(p['total_scraped'] for p in posts_data)} comments",
                    SUCCESS,
                )
                self.log(
                    f"\n✓ All done! {len(posts_data)} post(s), "
                    f"{sum(p['total_scraped'] for p in posts_data)} total comments.",
                    "success",
                )
                self.after(0, self._render_comments)
                self.after(0, lambda: self._show_tab("comments"))
            else:
                self.set_status("No data scraped.", WARNING)

        except Exception as e:
            self.log(f"Fatal error: {e}", "error")
            self.set_status(f"Error: {e}", ERROR_CLR)

        finally:
            self.after(0, self._scrape_done)

    def _scrape_done(self):
        self._scraping = False
        self.progress.stop()
        self.scrape_btn.set_state(True)
        self.scrape_btn.config(text="▶  SCRAPE COMMENTS")

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _clear_comments(self):
        for widget in self.comments_inner.winfo_children():
            widget.destroy()

    def _render_comments(self):
        self._clear_comments()

        if not self._scraped_posts:
            tk.Label(self.comments_inner, text="No comments found.",
                     fg=TEXT_DIM, bg=BG, font=FONT_BODY).pack(pady=40)
            return

        for post in self._scraped_posts:
            # Post header
            post_header = tk.Frame(self.comments_inner, bg=BG3)
            post_header.pack(fill="x", padx=4, pady=(8, 2))

            tk.Label(post_header, text=f"  📄 {post['title']}",
                     fg=TEXT, bg=BG3, font=FONT_HEAD,
                     wraplength=700, justify="left", anchor="w").pack(
                         fill="x", padx=12, pady=(10, 2))

            info_row = tk.Frame(post_header, bg=BG3)
            info_row.pack(fill="x", padx=12, pady=(0, 10))
            tk.Label(info_row, text=f"r/{post['subreddit']}", fg=ACCENT,
                     bg=BG3, font=FONT_SMALL).pack(side="left")
            tk.Label(info_row,
                     text=f"  •  u/{post['author']}  •  ▲{post['score']}  •  {post['total_scraped']} comments",
                     fg=TEXT_DIM, bg=BG3, font=FONT_SMALL).pack(side="left")

            # Flat list of all comments
            all_flat = flatten(post["comments"])
            for c in all_flat:
                card = CommentCard(self.comments_inner, c)
                card.pack(fill="x", padx=4, pady=1)

        self.canvas.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    # ── Saving ────────────────────────────────────────────────────────────────

    def _auto_save(self):
        fmt = self.fmt_var.get()
        out_dir = Path(self.out_dir_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)

        if len(self._scraped_posts) == 1:
            p = self._scraped_posts[0]
            base = f"reddit_{p['subreddit']}_{p['id']}"
        else:
            base = f"reddit_{len(self._scraped_posts)}_posts"

        if fmt in ("json", "both"):
            path = out_dir / f"{base}.json"
            path.write_text(
                json.dumps(self._scraped_posts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.log(f"  Saved JSON -> {path}", "success")

        if fmt in ("csv", "both"):
            path = out_dir / f"{base}.csv"
            fieldnames = [
                "post_id", "post_title", "post_subreddit",
                "id", "parent_id", "depth", "author", "score",
                "created_utc", "is_submitter", "flair", "permalink", "body",
            ]
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for post in self._scraped_posts:
                    for row in flatten(post["comments"]):
                        row["post_id"]        = post["id"]
                        row["post_title"]     = post["title"]
                        row["post_subreddit"] = post["subreddit"]
                        writer.writerow(row)
            self.log(f"  Saved CSV  -> {path}", "success")

    def _download(self, fmt: str):
        if not self._scraped_posts:
            messagebox.showinfo("Nothing to save", "Scrape some posts first.")
            return

        if len(self._scraped_posts) == 1:
            p = self._scraped_posts[0]
            default = f"reddit_{p['subreddit']}_{p['id']}.{fmt}"
        else:
            default = f"reddit_{len(self._scraped_posts)}_posts.{fmt}"

        if fmt == "json":
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                initialfile=default,
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if path:
                Path(path).write_text(
                    json.dumps(self._scraped_posts, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                messagebox.showinfo("Saved", f"JSON saved to:\n{path}")
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                initialfile=default,
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            )
            if path:
                fieldnames = [
                    "post_id", "post_title", "post_subreddit",
                    "id", "parent_id", "depth", "author", "score",
                    "created_utc", "is_submitter", "flair", "permalink", "body",
                ]
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for post in self._scraped_posts:
                        for row in flatten(post["comments"]):
                            row["post_id"]        = post["id"]
                            row["post_title"]     = post["title"]
                            row["post_subreddit"] = post["subreddit"]
                            writer.writerow(row)
                messagebox.showinfo("Saved", f"CSV saved to:\n{path}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
