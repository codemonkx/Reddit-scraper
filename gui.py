"""
Reddit Comment Scraper — Desktop GUI (Multi-Format Support)
============================================================
Supports HTML (Interactive Reader), Markdown (.md), JSON, and CSV exports.

Run:
    python gui.py
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import json
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper import scrape, create_driver, flatten, save_html, save_markdown, save_json, save_csv


# ─────────────────────────────────────────────────────────────────────────────
# Styling Tokens
# ─────────────────────────────────────────────────────────────────────────────

BG        = "#0f1117"
BG2       = "#1a1d27"
BG3       = "#22263a"
ACCENT    = "#ff4500"
ACCENT2   = "#ff6534"
TEXT      = "#e8eaf6"
TEXT_DIM  = "#8b90a0"
SUCCESS   = "#4caf50"
WARNING   = "#ffc107"
ERROR_CLR = "#f44336"
BORDER    = "#2e3250"

FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_HEAD  = ("Segoe UI", 11, "bold")
FONT_BODY  = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO  = ("Consolas", 9)
FONT_BADGE = ("Segoe UI", 8, "bold")


# ─────────────────────────────────────────────────────────────────────────────
# UI Widgets
# ─────────────────────────────────────────────────────────────────────────────

class FlatButton(tk.Label):
    def __init__(self, parent, text, command=None,
                 bg=ACCENT, fg="white", hover_bg=ACCENT2,
                 padx=16, pady=6, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         font=FONT_HEAD, cursor="hand2",
                         padx=padx, pady=pady, **kw)
        self._bg    = bg
        self._hover = hover_bg
        self._cmd   = command
        self._on    = True
        self.bind("<Enter>",    lambda e: self.config(bg=self._hover) if self._on else None)
        self.bind("<Leave>",    lambda e: self.config(bg=self._bg)    if self._on else None)
        self.bind("<Button-1>", lambda e: self._cmd()                 if self._on and self._cmd else None)

    def set_state(self, enabled: bool):
        self._on = enabled
        self.config(cursor="hand2" if enabled else "", bg=self._bg if enabled else BG3)


class CommentCard(tk.Frame):
    def __init__(self, parent, comment: dict, **kw):
        depth  = int(comment.get("depth", 0))
        indent = depth * 18
        colours = [ACCENT, "#7c4dff", "#00bcd4", "#4caf50", "#ffc107"]
        bar_clr = colours[min(depth, len(colours) - 1)]

        super().__init__(parent, bg=BG2, **kw)

        tk.Frame(self, bg=bar_clr, width=3).pack(side="left", fill="y", padx=(indent, 0))

        body = tk.Frame(self, bg=BG2)
        body.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        hdr = tk.Frame(body, bg=BG2)
        hdr.pack(fill="x")

        author = comment["author"]
        if comment.get("is_submitter"):
            author += " [OP]"
        tk.Label(hdr, text=f"u/{author}", fg=ACCENT,
                 bg=BG2, font=FONT_HEAD).pack(side="left")

        score = comment.get("score", 0)
        try:
            s_val = int(score)
            sc = SUCCESS if s_val > 0 else (ERROR_CLR if s_val < 0 else TEXT_DIM)
        except ValueError:
            sc = TEXT_DIM

        tk.Label(hdr, text=f"  ▲ {score}", fg=sc,
                 bg=BG2, font=FONT_SMALL).pack(side="left", padx=(8, 0))

        text = comment.get("body", "").strip()
        if len(text) > 450:
            text = text[:450] + "…"
        tk.Label(body, text=text, fg=TEXT, bg=BG2, font=FONT_BODY,
                 wraplength=680, justify="left", anchor="w").pack(fill="x", pady=(6, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Main Window App
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reddit Comment Scraper")
        self.geometry("1150x780")
        self.minsize(950, 620)
        self.configure(bg=BG)
        self.resizable(True, True)

        self._posts_data = []
        self._scraping   = False
        self._url_ph     = True

        self._build_ui()

    def _build_ui(self):
        bar = tk.Frame(self, bg=BG2, height=60)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tk.Label(bar, text="🔴", fg=ACCENT, bg=BG2,
                 font=("Segoe UI", 22)).pack(side="left", padx=(18, 4), pady=10)
        tk.Label(bar, text="Reddit Comment Scraper",
                 fg=TEXT, bg=BG2, font=FONT_TITLE).pack(side="left", pady=10)
        tk.Label(bar, text="Scrape and export comments as HTML Reader, Markdown, JSON, or CSV",
                 fg=TEXT_DIM, bg=BG2, font=FONT_SMALL).pack(side="left", padx=18)

        tk.Label(bar, text=" ✓ HTML Reader Enabled ",
                 fg="#0f1117", bg=SUCCESS, font=FONT_BADGE,
                 padx=8, pady=3).pack(side="right", padx=16)

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg=BG2, width=320)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self._build_right(right)

    def _build_left(self, parent):
        pad = dict(padx=16)

        tk.Label(parent, text="POST URL(S)",
                 fg=TEXT_DIM, bg=BG2, font=FONT_BADGE).pack(
                     anchor="w", pady=(18, 4), **pad)

        url_frame = tk.Frame(parent, bg=BG3,
                             highlightbackground=BORDER, highlightthickness=1)
        url_frame.pack(fill="x", **pad)
        self.url_box = tk.Text(url_frame, bg=BG3, fg=TEXT_DIM,
                               insertbackground=ACCENT, relief="flat",
                               font=FONT_BODY, height=6, bd=0, wrap="word")
        self.url_box.pack(fill="x", padx=10, pady=8)
        self.url_box.insert("1.0", "Paste one URL per line…")
        self.url_box.bind("<FocusIn>",  self._url_in)
        self.url_box.bind("<FocusOut>", self._url_out)

        tk.Label(parent,
                 text="Supports any Reddit post URL / share link.",
                 fg=TEXT_DIM, bg=BG2, font=FONT_SMALL,
                 wraplength=270, justify="left").pack(
                     anchor="w", pady=(4, 12), **pad)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", **pad, pady=4)

        tk.Label(parent, text="EXPORT FORMAT", fg=TEXT_DIM, bg=BG2,
                 font=FONT_BADGE).pack(anchor="w", pady=(12, 4), **pad)

        fmt_frame = tk.Frame(parent, bg=BG2)
        fmt_frame.pack(fill="x", **pad, pady=(0, 8))
        self.fmt_var = tk.StringVar(value="all")

        formats = [
            ("html", "🌐 HTML Reader (Recommended)"),
            ("md",   "📝 Markdown (.md)"),
            ("json", "📦 JSON Data"),
            ("csv",  "📊 CSV Table"),
            ("all",  "⚡ All Formats"),
        ]

        for val, lbl in formats:
            tk.Radiobutton(fmt_frame, text=lbl, variable=self.fmt_var, value=val,
                           bg=BG2, fg=TEXT, selectcolor=BG3,
                           activebackground=BG2, activeforeground=TEXT,
                           font=FONT_SMALL, anchor="w").pack(fill="x", pady=2)

        dir_row = tk.Frame(parent, bg=BG2)
        dir_row.pack(fill="x", **pad, pady=(8, 16))
        tk.Label(dir_row, text="Save to:", fg=TEXT, bg=BG2,
                 font=FONT_SMALL).pack(side="left")
        self.out_dir_var = tk.StringVar(value=str(Path.cwd()))
        lbl = tk.Label(dir_row, textvariable=self.out_dir_var,
                       fg=ACCENT, bg=BG2, font=FONT_SMALL,
                       cursor="hand2", wraplength=170, justify="left")
        lbl.pack(side="left", padx=6)
        lbl.bind("<Button-1>", lambda e: self._pick_dir())

        self.scrape_btn = FlatButton(parent, text="▶  SCRAPE COMMENTS",
                                     command=self._start_scrape)
        self.scrape_btn.pack(fill="x", **pad, pady=(12, 10))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("R.Horizontal.TProgressbar",
                        troughcolor=BG3, background=ACCENT,
                        bordercolor=BG3, lightcolor=ACCENT, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(parent, style="R.Horizontal.TProgressbar",
                                        mode="indeterminate")
        self.progress.pack(fill="x", **pad, pady=(0, 4))
        self.status_lbl = tk.Label(parent, text="Ready",
                                   fg=TEXT_DIM, bg=BG2, font=FONT_SMALL)
        self.status_lbl.pack(anchor="w", **pad)

    def _build_right(self, parent):
        tab_bar = tk.Frame(parent, bg=BG)
        tab_bar.pack(fill="x")

        self.tab_c = tk.Label(tab_bar, text="💬 Comments",
                              bg=BG, fg=ACCENT, font=FONT_HEAD,
                              padx=16, pady=8, cursor="hand2")
        self.tab_c.pack(side="left")
        self.tab_l = tk.Label(tab_bar, text="📋 Log",
                              bg=BG, fg=TEXT_DIM, font=FONT_HEAD,
                              padx=16, pady=8, cursor="hand2")
        self.tab_l.pack(side="left")

        dl = tk.Frame(tab_bar, bg=BG)
        dl.pack(side="right", padx=4)
        FlatButton(dl, text="🌐 HTML", command=lambda: self._download("html"), bg=BG3, hover_bg=BORDER, fg=TEXT, padx=10, pady=4).pack(side="left", padx=2)
        FlatButton(dl, text="📝 MD", command=lambda: self._download("md"), bg=BG3, hover_bg=BORDER, fg=TEXT, padx=10, pady=4).pack(side="left", padx=2)
        FlatButton(dl, text="⬇ JSON", command=lambda: self._download("json"), bg=BG3, hover_bg=BORDER, fg=TEXT, padx=10, pady=4).pack(side="left", padx=2)
        FlatButton(dl, text="⬇ CSV", command=lambda: self._download("csv"), bg=BG3, hover_bg=BORDER, fg=TEXT, padx=10, pady=4).pack(side="left", padx=2)

        self.content = tk.Frame(parent, bg=BG)
        self.content.pack(fill="both", expand=True)

        self.comments_outer = tk.Frame(self.content, bg=BG)
        self.comments_outer.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.canvas = tk.Canvas(self.comments_outer, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(self.comments_outer, orient="vertical",
                          command=self.canvas.yview,
                          bg=BG3, troughcolor=BG2)
        sb.pack(side="right", fill="y")
        self.canvas.config(yscrollcommand=sb.set)

        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win  = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.config(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(
                                 int(-1 * (e.delta / 120)), "units"))

        tk.Label(self.inner,
                 text="🔍\n\nPaste a Reddit post URL\nand click Scrape",
                 fg=TEXT_DIM, bg=BG, font=("Segoe UI", 13),
                 justify="center").pack(expand=True, pady=80)

        self.log_outer = tk.Frame(self.content, bg=BG)
        self.log_box   = scrolledtext.ScrolledText(
            self.log_outer, bg=BG2, fg=TEXT_DIM, font=FONT_MONO,
            relief="flat", bd=0, state="disabled", insertbackground=TEXT)
        self.log_box.pack(fill="both", expand=True, pady=4)
        for tag, clr in [("info", TEXT_DIM), ("success", SUCCESS),
                         ("error", ERROR_CLR), ("warn", WARNING),
                         ("head", ACCENT)]:
            self.log_box.tag_config(tag, foreground=clr)

        self.tab_c.bind("<Button-1>", lambda e: self._tab("comments"))
        self.tab_l.bind("<Button-1>", lambda e: self._tab("log"))

    def _tab(self, which):
        if which == "comments":
            self.tab_c.config(fg=ACCENT)
            self.tab_l.config(fg=TEXT_DIM)
            self.log_outer.place_forget()
            self.comments_outer.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.tab_l.config(fg=ACCENT)
            self.tab_c.config(fg=TEXT_DIM)
            self.comments_outer.place_forget()
            self.log_outer.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _url_in(self, e):
        if self._url_ph:
            self.url_box.delete("1.0", "end")
            self.url_box.config(fg=TEXT)
            self._url_ph = False

    def _url_out(self, e):
        if not self.url_box.get("1.0", "end").strip():
            self.url_box.insert("1.0", "Paste one URL per line…")
            self.url_box.config(fg=TEXT_DIM)
            self._url_ph = True

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_dir_var.get())
        if d:
            self.out_dir_var.set(d)

    def log(self, msg, kind="info"):
        def _do():
            self.log_box.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {msg}\n", kind)
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _do)

    def set_status(self, msg, clr=TEXT_DIM):
        self.after(0, lambda: self.status_lbl.config(text=msg, fg=clr))

    def _start_scrape(self):
        if self._scraping:
            return

        raw = self.url_box.get("1.0", "end").strip()
        if self._url_ph or not raw:
            messagebox.showwarning("No URL", "Please paste at least one Reddit post URL.")
            return

        urls = [u.strip() for u in raw.splitlines() if u.strip()]

        self._scraping   = True
        self._posts_data = []
        self.scrape_btn.set_state(False)
        self.scrape_btn.config(text="⏳ Scraping…")
        self.progress.start(12)
        self._clear_comments()
        self._tab("log")
        self.log(f"Starting scrape for {len(urls)} URL(s) …", "head")

        threading.Thread(target=self._thread, args=(urls,), daemon=True).start()

    def _thread(self, urls):
        driver = None
        posts = []
        try:
            self.log("Initializing Chrome browser engine...", "info")
            driver = create_driver()

            for i, url in enumerate(urls, 1):
                self.log(f"\n[{i}/{len(urls)}] {url}", "head")
                self.set_status(f"Scraping {i}/{len(urls)} …")
                try:
                    post = scrape(url, driver=driver, progress_cb=self.log)
                    posts.append(post)
                except Exception as e:
                    self.log(f"  ERROR: {e}", "error")

            self._posts_data = posts

            if posts:
                self._auto_save()
                total_target  = sum(p.get("target_count", 0) for p in posts)
                total_scraped = sum(p["total_scraped"] for p in posts)
                pct = (total_scraped / total_target * 100) if total_target > 0 else 100.0
                self.set_status(f"Done — Scraped {total_scraped} of {total_target} comments ({pct:.1f}%)", SUCCESS)
                self.after(0, self._render_comments)
                self.after(0, lambda: self._tab("comments"))
            else:
                self.set_status("Nothing scraped.", WARNING)

        finally:
            if driver:
                driver.quit()
            self.after(0, self._done)

    def _done(self):
        self._scraping = False
        self.progress.stop()
        self.scrape_btn.set_state(True)
        self.scrape_btn.config(text="▶  SCRAPE COMMENTS")

    def _clear_comments(self):
        for w in self.inner.winfo_children():
            w.destroy()

    def _render_comments(self):
        self._clear_comments()

        if not self._posts_data:
            tk.Label(self.inner, text="No comments found.",
                     fg=TEXT_DIM, bg=BG, font=FONT_BODY).pack(pady=40)
            return

        for post in self._posts_data:
            hdr = tk.Frame(self.inner, bg=BG3)
            hdr.pack(fill="x", padx=4, pady=(8, 2))
            tk.Label(hdr, text=f"  📄 {post['title']}",
                     fg=TEXT, bg=BG3, font=FONT_HEAD,
                     wraplength=700, justify="left", anchor="w").pack(
                         fill="x", padx=12, pady=(10, 2))
            info = tk.Frame(hdr, bg=BG3)
            info.pack(fill="x", padx=12, pady=(0, 10))
            tk.Label(info, text=f"r/{post['subreddit']}", fg=ACCENT,
                     bg=BG3, font=FONT_SMALL).pack(side="left")

            target  = post.get("target_count", 0)
            scraped = post.get("total_scraped", 0)
            pct     = (scraped / target * 100) if target > 0 else 100.0

            summary_txt = f"  •  u/{post['author']}  •  Target: {target} comments  |  Scraped: {scraped} ({pct:.1f}%)"

            tk.Label(info, text=summary_txt,
                     fg=SUCCESS if pct > 70 else WARNING, bg=BG3, font=FONT_SMALL).pack(side="left")

            for c in post["comments"]:
                CommentCard(self.inner, c).pack(fill="x", padx=4, pady=1)

        self.canvas.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def _auto_save(self):
        fmt     = self.fmt_var.get()
        out_dir = Path(self.out_dir_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)
        base = (
            f"reddit_{self._posts_data[0]['subreddit']}_{self._posts_data[0]['id']}"
            if len(self._posts_data) == 1
            else f"reddit_{len(self._posts_data)}_posts"
        )

        if fmt in ("html", "all"):
            save_html(self._posts_data, out_dir / f"{base}.html")
        if fmt in ("md", "all"):
            save_markdown(self._posts_data, out_dir / f"{base}.md")
        if fmt in ("json", "all"):
            save_json(self._posts_data, out_dir / f"{base}.json")
        if fmt in ("csv", "all"):
            save_csv(self._posts_data, out_dir / f"{base}.csv")

    def _download(self, fmt):
        if not self._posts_data:
            messagebox.showinfo("Nothing to save", "Scrape some posts first.")
            return
        base = (
            f"reddit_{self._posts_data[0]['subreddit']}_{self._posts_data[0]['id']}"
            if len(self._posts_data) == 1
            else f"reddit_{len(self._posts_data)}_posts"
        )
        ext  = f".{fmt}"
        path = filedialog.asksaveasfilename(
            defaultextension=ext, initialfile=base + ext,
            filetypes=[(f"{fmt.upper()} files", f"*{ext}"), ("All", "*.*")])
        if not path:
            return

        if fmt == "html":
            save_html(self._posts_data, Path(path))
        elif fmt == "md":
            save_markdown(self._posts_data, Path(path))
        elif fmt == "json":
            save_json(self._posts_data, Path(path))
        elif fmt == "csv":
            save_csv(self._posts_data, Path(path))

        messagebox.showinfo("Saved", f"Saved to:\n{path}")


if __name__ == "__main__":
    App().mainloop()
