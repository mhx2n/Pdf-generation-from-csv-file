"""
QuizPDF Telegram Bot
====================
Owner-controlled Telegram bot that converts a quiz CSV into a beautifully
formatted, 2-column, Bengali-ready, LaTeX-aware PDF — fully customizable
via inline buttons (logo, header, footer, watermark, theme color, etc.).

Designed to deploy on Render (free tier) using the included Dockerfile.

Single file. Polling mode. SQLite-backed settings + per-user logo storage.

ENV VARS REQUIRED
-----------------
BOT_TOKEN   : Telegram bot token from @BotFather
OWNER_ID    : Your numeric Telegram user id (the only super-admin)

Optional:
DATA_DIR    : Defaults to ./data
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass, field
from html import escape as h
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from telegram import (  # noqa: E402
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.constants import ChatAction, ParseMode  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from weasyprint import CSS, HTML  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or "0")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
FONTS_DIR = Path(__file__).parent / "fonts"
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logos").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "watermarks").mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "bot.db"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("quizpdfbot")

if not BOT_TOKEN or not OWNER_ID:
    log.error("BOT_TOKEN and OWNER_ID env vars are required.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with closing(db()) as con, con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_csv (
                user_id INTEGER PRIMARY KEY,
                csv_text TEXT NOT NULL,
                filename TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS edit_state (
                user_id INTEGER PRIMARY KEY,
                field TEXT NOT NULL
            );
            """
        )


# ---------------------------------------------------------------------------
# Per-user settings model
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "title": "Quiz Paper",
    "subtitle": "সাধারণ",
    "set_name": "A",
    "total_marks": "",        # auto-fill from row count if blank
    "time_minutes": "15",
    "footer_text": "আমাদের টেলিগ্রাম চ্যানেল",
    "footer_link": "https://t.me/",
    "watermark_text": "",
    "watermark_enabled": False,
    "logo_enabled": True,
    "columns": 2,             # 1 or 2
    "show_explanation": True,
    "show_answer": True,
    "theme": "blue",          # blue | green | red | purple | orange | slate
    "language_label": "বাংলা",
    "page_size": "A4",        # A4 | Letter
}

THEMES = {
    "blue":   {"primary": "#1f4fa5", "soft": "#eef3fb", "border": "#bcd0ec"},
    "green":  {"primary": "#1f7a4d", "soft": "#ecf7f0", "border": "#bce0c9"},
    "red":    {"primary": "#a52323", "soft": "#fbeeee", "border": "#ecbcbc"},
    "purple": {"primary": "#5a2a9a", "soft": "#f1ecfb", "border": "#d4c2ec"},
    "orange": {"primary": "#b86412", "soft": "#fbf2e8", "border": "#ecd2bc"},
    "slate":  {"primary": "#334155", "soft": "#eef2f7", "border": "#c2cad8"},
}


def get_settings(user_id: int) -> dict[str, Any]:
    with closing(db()) as con:
        row = con.execute(
            "SELECT data FROM settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    s = dict(DEFAULT_SETTINGS)
    if row:
        try:
            s.update(json.loads(row["data"]))
        except Exception:
            pass
    return s


def save_settings(user_id: int, s: dict[str, Any]) -> None:
    with closing(db()) as con, con:
        con.execute(
            "INSERT INTO settings (user_id, data) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
            (user_id, json.dumps(s, ensure_ascii=False)),
        )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


def is_allowed(uid: int) -> bool:
    if is_owner(uid):
        return True
    with closing(db()) as con:
        return (
            con.execute(
                "SELECT 1 FROM allowed_users WHERE user_id = ?", (uid,)
            ).fetchone()
            is not None
        )


def add_allowed(uid: int, username: str | None) -> None:
    with closing(db()) as con, con:
        con.execute(
            "INSERT OR REPLACE INTO allowed_users (user_id, username) VALUES (?, ?)",
            (uid, username),
        )


def remove_allowed(uid: int) -> None:
    with closing(db()) as con, con:
        con.execute("DELETE FROM allowed_users WHERE user_id = ?", (uid,))


def list_allowed() -> list[sqlite3.Row]:
    with closing(db()) as con:
        return con.execute(
            "SELECT user_id, username, added_at FROM allowed_users ORDER BY added_at"
        ).fetchall()


# ---------------------------------------------------------------------------
# Pending CSV / edit state
# ---------------------------------------------------------------------------
def set_pending_csv(user_id: int, text: str, filename: str) -> None:
    with closing(db()) as con, con:
        con.execute(
            "INSERT OR REPLACE INTO pending_csv (user_id, csv_text, filename) "
            "VALUES (?, ?, ?)",
            (user_id, text, filename),
        )


def get_pending_csv(user_id: int) -> tuple[str, str] | None:
    with closing(db()) as con:
        row = con.execute(
            "SELECT csv_text, filename FROM pending_csv WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return (row["csv_text"], row["filename"]) if row else None


def clear_pending_csv(user_id: int) -> None:
    with closing(db()) as con, con:
        con.execute("DELETE FROM pending_csv WHERE user_id = ?", (user_id,))


def set_edit_field(user_id: int, field: str | None) -> None:
    with closing(db()) as con, con:
        if field is None:
            con.execute("DELETE FROM edit_state WHERE user_id = ?", (user_id,))
        else:
            con.execute(
                "INSERT OR REPLACE INTO edit_state (user_id, field) VALUES (?, ?)",
                (user_id, field),
            )


def get_edit_field(user_id: int) -> str | None:
    with closing(db()) as con:
        row = con.execute(
            "SELECT field FROM edit_state WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["field"] if row else None


def logo_path(user_id: int) -> Path:
    return DATA_DIR / "logos" / f"{user_id}.png"


# ---------------------------------------------------------------------------
# CSV → questions
# ---------------------------------------------------------------------------
@dataclass
class Question:
    number: int
    text: str
    options: list[str] = field(default_factory=list)
    answer_index: int | None = None  # 0-based
    explanation: str = ""


def parse_csv(text: str) -> list[Question]:
    # Strip BOM
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    questions: list[Question] = []
    for i, row in enumerate(reader, start=1):
        # Tolerant header lookup
        rk = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        qtext = rk.get("questions") or rk.get("question") or ""
        if not qtext:
            continue
        opts = []
        for n in range(1, 6):
            v = rk.get(f"option{n}", "")
            if v:
                opts.append(v)
        ans_raw = rk.get("answer", "")
        ans_idx: int | None = None
        if ans_raw:
            try:
                a = int(ans_raw)
                if 1 <= a <= len(opts):
                    ans_idx = a - 1
            except ValueError:
                # try matching by text
                for j, o in enumerate(opts):
                    if o.strip() == ans_raw.strip():
                        ans_idx = j
                        break
        questions.append(
            Question(
                number=len(questions) + 1,
                text=qtext,
                options=opts,
                answer_index=ans_idx,
                explanation=rk.get("explanation", ""),
            )
        )
    return questions


# ---------------------------------------------------------------------------
# LaTeX (math) inline rendering
# ---------------------------------------------------------------------------
_MATH_PATTERN = re.compile(r"\$([^$]+?)\$")
_DOUBLE_MATH = re.compile(r"\$\$([^$]+?)\$\$")


def _render_math(expr: str, fontsize: int = 14) -> str:
    """Render a LaTeX math expression to a base64 PNG data URI."""
    try:
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.patch.set_alpha(0)
        text = fig.text(0, 0, f"${expr}$", fontsize=fontsize, color="black")
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            bbox_inches="tight",
            pad_inches=0.05,
            transparent=True,
            dpi=180,
        )
        plt.close(fig)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return (
            f'<img class="math" src="data:image/png;base64,{b64}" alt="math" />'
        )
    except Exception as e:
        log.warning("math render failed for %r: %s", expr, e)
        return f"<code>{h(expr)}</code>"


def render_text(text: str) -> str:
    """Escape text, render $...$ math, preserve line breaks."""
    if not text:
        return ""
    # Protect math first by tokenizing
    tokens: list[tuple[str, str]] = []  # (type, value); type: 'text' or 'math'
    pos = 0
    # Combine $$...$$ and $...$ with $$ taking precedence
    pattern = re.compile(r"\$\$([^$]+?)\$\$|\$([^$\n]+?)\$")
    for m in pattern.finditer(text):
        if m.start() > pos:
            tokens.append(("text", text[pos : m.start()]))
        expr = m.group(1) or m.group(2)
        tokens.append(("math", expr))
        pos = m.end()
    if pos < len(text):
        tokens.append(("text", text[pos:]))

    parts: list[str] = []
    for kind, val in tokens:
        if kind == "math":
            parts.append(_render_math(val))
        else:
            esc = h(val)
            esc = esc.replace("\n", "<br/>")
            parts.append(esc)
    return "".join(parts)


# ---------------------------------------------------------------------------
# HTML / CSS template (mirrors the sample PDF layout)
# ---------------------------------------------------------------------------
BENGALI_DIGITS = "০১২৩৪৫৬৭৮৯"
OPTION_LABELS = ["ক", "খ", "গ", "ঘ", "ঙ"]


def to_bn_num(n: int | str) -> str:
    s = str(n)
    return "".join(BENGALI_DIGITS[int(c)] if c.isdigit() else c for c in s)


def build_html(
    questions: list[Question],
    settings: dict[str, Any],
    logo_data_uri: str | None,
) -> str:
    theme = THEMES.get(settings.get("theme", "blue"), THEMES["blue"])
    primary = theme["primary"]
    soft = theme["soft"]
    border = theme["border"]
    columns = int(settings.get("columns", 2) or 2)
    column_count_css = max(1, min(columns, 2))

    total_marks = settings.get("total_marks") or str(len(questions))
    title = settings.get("title", "Quiz")
    subtitle = settings.get("subtitle", "")
    set_name = settings.get("set_name", "A")
    time_minutes = settings.get("time_minutes", "")
    footer_text = settings.get("footer_text", "")
    footer_link = settings.get("footer_link", "")
    show_ans = bool(settings.get("show_answer", True))
    show_exp = bool(settings.get("show_explanation", True))
    watermark_text = (
        settings.get("watermark_text", "") if settings.get("watermark_enabled") else ""
    )

    logo_html = ""
    if logo_data_uri and settings.get("logo_enabled", True):
        logo_html = f'<img class="logo" src="{logo_data_uri}" alt="logo"/>'

    # Build question blocks
    q_blocks: list[str] = []
    for q in questions:
        opts_html_parts = []
        # 2x2 grid of options
        for idx, opt in enumerate(q.options):
            label = OPTION_LABELS[idx] if idx < len(OPTION_LABELS) else str(idx + 1)
            opts_html_parts.append(
                f'<div class="opt"><span class="opt-label">{label})</span> '
                f'<span class="opt-text">{render_text(opt)}</span></div>'
            )
        opts_html = (
            f'<div class="opts cols-{2 if len(q.options) > 1 else 1}">'
            + "".join(opts_html_parts)
            + "</div>"
        )

        ans_block = ""
        if show_ans and q.answer_index is not None:
            ans_label = (
                OPTION_LABELS[q.answer_index]
                if q.answer_index < len(OPTION_LABELS)
                else str(q.answer_index + 1)
            )
            ans_text = (
                q.options[q.answer_index] if q.answer_index < len(q.options) else ""
            )
            inner = (
                f'<div class="ans-line"><span class="ans-tag">সঠিক উত্তর:</span> '
                f"{ans_label}) {render_text(ans_text)}</div>"
            )
            if show_exp and q.explanation:
                inner += (
                    f'<div class="exp-line"><span class="exp-tag">ব্যাখ্যা:</span> '
                    f"{render_text(q.explanation)}</div>"
                )
            ans_block = f'<div class="answer-box">{inner}</div>'

        q_blocks.append(
            f"""
            <article class="q">
              <div class="q-head">
                <span class="q-num">{to_bn_num(q.number)}.</span>
                <span class="q-text">{render_text(q.text)}</span>
              </div>
              {opts_html}
              {ans_block}
            </article>
            """
        )

    questions_html = "\n".join(q_blocks)

    watermark_html = ""
    if watermark_text:
        watermark_html = f'<div class="watermark"><span>{h(watermark_text)}</span></div>'

    footer_link_html = ""
    if footer_text:
        if footer_link:
            footer_link_html = (
                f'<a href="{h(footer_link)}">➤ {h(footer_text)}</a>'
            )
        else:
            footer_link_html = f"➤ {h(footer_text)}"

    fonts_css = f"""
    @font-face {{
      font-family: 'NotoBn';
      src: url('file://{FONTS_DIR / "NotoSansBengali-Regular.ttf"}') format('truetype');
      font-weight: 100 900; font-style: normal;
    }}
    @font-face {{
      font-family: 'NotoSans';
      src: url('file://{FONTS_DIR / "NotoSans-Regular.ttf"}') format('truetype');
      font-weight: 100 900; font-style: normal;
    }}
    """

    page_size = settings.get("page_size", "A4")

    css = f"""
    {fonts_css}
    @page {{
      size: {page_size};
      margin: 14mm 12mm 16mm 12mm;
      @top-left {{
        content: "{h(title)}";
        font-family: 'NotoBn','NotoSans',sans-serif;
        font-size: 9pt; color: {primary}; padding-top: 4mm;
      }}
      @top-right {{
        content: "সেট: {h(set_name)}";
        font-family: 'NotoBn','NotoSans',sans-serif;
        font-size: 9pt; color: {primary}; padding-top: 4mm;
      }}
      @bottom-center {{
        content: "{footer_text and ('➤ ' + footer_text) or ''}";
        font-family: 'NotoBn','NotoSans',sans-serif;
        font-size: 9pt; color: {primary};
      }}
      @bottom-right {{
        content: "পৃষ্ঠা " counter(page) " / " counter(pages);
        font-family: 'NotoBn','NotoSans',sans-serif;
        font-size: 8.5pt; color: #666;
      }}
    }}
    @page :first {{
      @top-left {{ content: ""; }}
      @top-right {{ content: ""; }}
    }}
    html, body {{
      font-family: 'NotoBn','NotoSans',sans-serif;
      color: #1a2233;
      font-size: 9.7pt;
      line-height: 1.45;
      margin: 0; padding: 0;
    }}
    a {{ color: {primary}; text-decoration: none; }}
    .header {{
      text-align: center;
      margin-bottom: 6mm;
      position: relative;
    }}
    .logo {{
      max-height: 13mm; max-width: 28mm; display: inline-block;
      margin-bottom: 2mm;
    }}
    .title {{
      font-size: 22pt; color: {primary}; font-weight: 700;
      margin: 0; letter-spacing: 0.3pt;
    }}
    .subtitle {{
      font-size: 11pt; color: #5a6478; margin-top: 1mm;
    }}
    .info-bar {{
      display: flex; justify-content: space-between; align-items: center;
      border-top: 1px solid {primary};
      border-bottom: 1px solid {primary};
      padding: 2mm 1mm; margin-bottom: 5mm;
      font-size: 10pt; color: #1a2233;
    }}
    .info-bar .cell {{ flex: 1; text-align: center; }}
    .info-bar .cell.left {{ text-align: left; }}
    .info-bar .cell.right {{ text-align: right; }}
    .info-bar b {{ color: {primary}; }}

    .questions {{
      column-count: {column_count_css};
      column-gap: 7mm;
      column-rule: 1px solid #e3e7ef;
    }}
    .q {{
      break-inside: avoid;
      page-break-inside: avoid;
      margin-bottom: 4mm;
    }}
    .q-head {{
      display: block; font-weight: 600; margin-bottom: 1.5mm;
    }}
    .q-num {{
      color: {primary}; font-weight: 700; margin-right: 1mm;
    }}
    .opts {{
      display: grid; grid-template-columns: 1fr 1fr;
      gap: 0.5mm 4mm; margin-left: 4mm;
      margin-bottom: 2mm;
    }}
    .opts.cols-1 {{ grid-template-columns: 1fr; }}
    .opt {{ font-size: 9.5pt; }}
    .opt-label {{ color: #444; font-weight: 600; margin-right: 1mm; }}
    .answer-box {{
      background: {soft}; border: 1px solid {border};
      border-radius: 3pt; padding: 2mm 2.5mm; margin-top: 1mm;
      font-size: 9.2pt;
    }}
    .ans-tag {{ color: {primary}; font-weight: 700; }}
    .ans-line {{ font-weight: 600; }}
    .exp-tag {{ color: {primary}; font-weight: 700; margin-right: 1mm; }}
    .exp-line {{ margin-top: 1mm; color: #2a3346; font-weight: 400; }}

    img.math {{
      display: inline-block;
      vertical-align: -2pt;
      max-height: 14pt;
    }}

    .watermark {{
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      pointer-events: none;
      z-index: 0;
    }}
    .watermark span {{
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%) rotate(-30deg);
      font-size: 80pt; color: rgba(0,0,0,0.06);
      font-weight: 800; white-space: nowrap;
    }}
    """

    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{h(title)}</title>
<style>{css}</style></head>
<body>
{watermark_html}
<header class="header">
  {logo_html}
  <h1 class="title">{h(title)}</h1>
  <div class="subtitle">{h(subtitle)}</div>
</header>
<div class="info-bar">
  <div class="cell left"><b>পূর্ণমান:</b> {to_bn_num(total_marks)}</div>
  <div class="cell"><b>সেট:</b> {h(set_name)}</div>
  <div class="cell right"><b>সময়:</b> {to_bn_num(time_minutes)} মিনিট</div>
</div>
<section class="questions">
{questions_html}
</section>
</body></html>
"""
    return html_doc


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------
def generate_pdf(
    user_id: int,
    questions: list[Question],
    settings: dict[str, Any],
) -> bytes:
    logo_data_uri = None
    lp = logo_path(user_id)
    if lp.exists():
        b64 = base64.b64encode(lp.read_bytes()).decode("ascii")
        logo_data_uri = f"data:image/png;base64,{b64}"
    html_text = build_html(questions, settings, logo_data_uri)
    pdf_bytes = HTML(string=html_text, base_url=str(Path(".").resolve())).write_pdf()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Telegram UI helpers
# ---------------------------------------------------------------------------
def main_menu_kb(s: dict[str, Any]) -> InlineKeyboardMarkup:
    def tog(v: bool) -> str:
        return "✅" if v else "⬜️"

    rows = [
        [
            InlineKeyboardButton("📝 Title", callback_data="edit:title"),
            InlineKeyboardButton("📌 Subtitle", callback_data="edit:subtitle"),
        ],
        [
            InlineKeyboardButton("🔤 Set", callback_data="edit:set_name"),
            InlineKeyboardButton("💯 Total Marks", callback_data="edit:total_marks"),
            InlineKeyboardButton("⏱ Time", callback_data="edit:time_minutes"),
        ],
        [
            InlineKeyboardButton("🔗 Footer Text", callback_data="edit:footer_text"),
            InlineKeyboardButton("🌐 Footer Link", callback_data="edit:footer_link"),
        ],
        [
            InlineKeyboardButton(
                f"{tog(s['watermark_enabled'])} Watermark",
                callback_data="toggle:watermark_enabled",
            ),
            InlineKeyboardButton("✏️ WM Text", callback_data="edit:watermark_text"),
        ],
        [
            InlineKeyboardButton(
                f"{tog(s['logo_enabled'])} Logo", callback_data="toggle:logo_enabled"
            ),
            InlineKeyboardButton(
                f"{tog(s['show_answer'])} Answer", callback_data="toggle:show_answer"
            ),
            InlineKeyboardButton(
                f"{tog(s['show_explanation'])} Explain",
                callback_data="toggle:show_explanation",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📐 Columns: {s['columns']}", callback_data="cycle:columns"
            ),
            InlineKeyboardButton(
                f"📄 Page: {s['page_size']}", callback_data="cycle:page_size"
            ),
        ],
        [InlineKeyboardButton(f"🎨 Theme: {s['theme']}", callback_data="theme:menu")],
        [
            InlineKeyboardButton("👀 Preview Settings", callback_data="preview"),
            InlineKeyboardButton("♻️ Reset", callback_data="reset"),
        ],
        [InlineKeyboardButton("✅ Generate PDF", callback_data="generate")],
    ]
    return InlineKeyboardMarkup(rows)


def theme_menu_kb() -> InlineKeyboardMarkup:
    keys = list(THEMES.keys())
    rows = []
    for i in range(0, len(keys), 3):
        rows.append(
            [
                InlineKeyboardButton(
                    f"🎨 {k.capitalize()}", callback_data=f"theme:set:{k}"
                )
                for k in keys[i : i + 3]
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:main")])
    return InlineKeyboardMarkup(rows)


def settings_summary(s: dict[str, Any]) -> str:
    return (
        "<b>Current Settings</b>\n"
        f"• Title: <code>{h(s['title'])}</code>\n"
        f"• Subtitle: <code>{h(s['subtitle'])}</code>\n"
        f"• Set: <code>{h(s['set_name'])}</code>  |  "
        f"Marks: <code>{h(str(s['total_marks']) or 'auto')}</code>  |  "
        f"Time: <code>{h(str(s['time_minutes']))}</code> min\n"
        f"• Footer: <code>{h(s['footer_text'])}</code>\n"
        f"• Link: <code>{h(s['footer_link'])}</code>\n"
        f"• Watermark: <code>{h(s['watermark_text']) or '—'}</code> "
        f"({'on' if s['watermark_enabled'] else 'off'})\n"
        f"• Logo: {'on' if s['logo_enabled'] else 'off'}  |  "
        f"Answer: {'on' if s['show_answer'] else 'off'}  |  "
        f"Explanation: {'on' if s['show_explanation'] else 'off'}\n"
        f"• Columns: <code>{s['columns']}</code>  |  "
        f"Page: <code>{s['page_size']}</code>  |  "
        f"Theme: <code>{s['theme']}</code>"
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
GUARD_MSG = "⛔️ এই বট শুধু অনুমোদিত ব্যবহারকারীদের জন্য।"


async def guard(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    if not is_allowed(uid):
        if update.message:
            await update.message.reply_text(GUARD_MSG)
        elif update.callback_query:
            await update.callback_query.answer(GUARD_MSG, show_alert=True)
        return False
    return True


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    role = "👑 Owner" if is_owner(uid) else "✅ Allowed user"
    await update.message.reply_text(
        f"<b>QuizPDF Bot</b>\n{role}\n\n"
        "১. একটি লোগো (PNG/JPG) পাঠাও — অটো সেভ হবে\n"
        "২. <code>.csv</code> ফাইল পাঠাও\n"
        "৩. বাটন দিয়ে কাস্টমাইজ করো\n"
        "৪. ✅ <b>Generate PDF</b> প্রেস করো\n\n"
        "Commands: /settings /preview /reset /help"
        + ("\n\n👑 Owner: /allow /revoke /users" if is_owner(uid) else ""),
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await update.message.reply_text(
        "<b>CSV Format</b>\n"
        "<code>questions,option1,option2,option3,option4,option5,answer,explanation,type,section</code>\n"
        "• <b>answer</b>: 1..N (option index)\n"
        "• গণিত: <code>$x^2 + y^2 = r^2$</code> এভাবে LaTeX লিখো\n"
        "• ব্যাখ্যায় newline দিতে পারো\n\n"
        "যেকোনো সময় /settings দিলে অপশন দেখাবে।",
        parse_mode=ParseMode.HTML,
    )


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    s = get_settings(uid)
    await update.message.reply_text(
        settings_summary(s),
        reply_markup=main_menu_kb(s),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    s = get_settings(uid)
    await update.message.reply_text(
        settings_summary(s),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    save_settings(uid, dict(DEFAULT_SETTINGS))
    await update.message.reply_text("♻️ Settings reset to defaults.")


async def cmd_allow(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_owner(uid):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /allow <user_id> [@username]")
        return
    try:
        target = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Invalid id.")
        return
    uname = ctx.args[1] if len(ctx.args) > 1 else None
    add_allowed(target, uname)
    await update.message.reply_text(f"✅ Allowed user {target}.")


async def cmd_revoke(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /revoke <user_id>")
        return
    try:
        target = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Invalid id.")
        return
    remove_allowed(target)
    await update.message.reply_text(f"🗑 Revoked {target}.")


async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        return
    rows = list_allowed()
    if not rows:
        await update.message.reply_text("No allowed users yet (only owner).")
        return
    msg = "<b>Allowed users</b>\n" + "\n".join(
        f"• <code>{r['user_id']}</code> {h(r['username'] or '')}" for r in rows
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your id: <code>{update.effective_user.id}</code>",
                                    parse_mode=ParseMode.HTML)


# --- Document / photo handling ---------------------------------------------
async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    doc = update.message.document
    fname = (doc.file_name or "").lower()
    if fname.endswith(".csv") or (doc.mime_type or "").startswith("text/"):
        f = await doc.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(out=bio)
        try:
            text = bio.getvalue().decode("utf-8-sig")
        except UnicodeDecodeError:
            text = bio.getvalue().decode("utf-8", errors="replace")
        # Validate
        qs = parse_csv(text)
        if not qs:
            await update.message.reply_text(
                "❌ CSV-তে কোনো প্রশ্ন পাওয়া যায়নি। হেডার ঠিক আছে?"
            )
            return
        set_pending_csv(uid, text, doc.file_name or "quiz.csv")
        s = get_settings(uid)
        await update.message.reply_text(
            f"✅ {len(qs)} টি প্রশ্ন পাওয়া গেছে। নিচে সেটিংস কাস্টমাইজ করো:\n\n"
            + settings_summary(s),
            reply_markup=main_menu_kb(s),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return
    # Image as logo
    if (doc.mime_type or "").startswith("image/"):
        await _save_logo_from_file(update, ctx, doc)
        return
    await update.message.reply_text("শুধু .csv বা ছবি (লোগো) পাঠাও।")


async def _save_logo_from_file(update: Update, ctx, doc) -> None:
    uid = update.effective_user.id
    f = await doc.get_file()
    bio = io.BytesIO()
    await f.download_to_memory(out=bio)
    logo_path(uid).write_bytes(bio.getvalue())
    await update.message.reply_text("🖼 লোগো সেভ হয়েছে। পরবর্তী PDF-এ অটো বসে যাবে।")


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    photo = update.message.photo[-1]
    f = await photo.get_file()
    bio = io.BytesIO()
    await f.download_to_memory(out=bio)
    logo_path(uid).write_bytes(bio.getvalue())
    await update.message.reply_text("🖼 লোগো সেভ হয়েছে। পরবর্তী PDF-এ অটো বসে যাবে।")


# --- Inline editing ---------------------------------------------------------
EDITABLE_FIELDS = {
    "title": "Title (PDF এর বড় টাইটেল)",
    "subtitle": "Subtitle",
    "set_name": "Set name (e.g. A, B)",
    "total_marks": "Total marks (blank = প্রশ্ন সংখ্যা)",
    "time_minutes": "Time in minutes",
    "footer_text": "Footer text",
    "footer_link": "Footer link (https://...)",
    "watermark_text": "Watermark text",
}


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    uid = update.effective_user.id
    field = get_edit_field(uid)
    if not field:
        return  # ignore stray text
    text = (update.message.text or "").strip()
    s = get_settings(uid)
    s[field] = text
    save_settings(uid, s)
    set_edit_field(uid, None)
    await update.message.reply_text(
        f"✅ <b>{h(field)}</b> আপডেট হয়েছে।\n\n" + settings_summary(s),
        reply_markup=main_menu_kb(s),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# --- Callback queries -------------------------------------------------------
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""
    s = get_settings(uid)

    if data.startswith("edit:"):
        field = data.split(":", 1)[1]
        if field not in EDITABLE_FIELDS:
            return
        set_edit_field(uid, field)
        prompt = EDITABLE_FIELDS[field]
        cur = s.get(field, "")
        await q.message.reply_text(
            f"✏️ নতুন মান পাঠাও — <b>{h(prompt)}</b>\n"
            f"বর্তমান: <code>{h(str(cur)) or '—'}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("toggle:"):
        field = data.split(":", 1)[1]
        s[field] = not bool(s.get(field, False))
        save_settings(uid, s)
        await _refresh_menu(q, s)
        return

    if data.startswith("cycle:"):
        field = data.split(":", 1)[1]
        if field == "columns":
            s["columns"] = 1 if int(s.get("columns", 2)) == 2 else 2
        elif field == "page_size":
            s["page_size"] = "Letter" if s.get("page_size") == "A4" else "A4"
        save_settings(uid, s)
        await _refresh_menu(q, s)
        return

    if data == "theme:menu":
        await q.edit_message_reply_markup(reply_markup=theme_menu_kb())
        return
    if data.startswith("theme:set:"):
        theme = data.split(":", 2)[2]
        if theme in THEMES:
            s["theme"] = theme
            save_settings(uid, s)
        await _refresh_menu(q, s)
        return
    if data == "back:main":
        await _refresh_menu(q, s)
        return

    if data == "preview":
        await q.message.reply_text(
            settings_summary(s),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if data == "reset":
        save_settings(uid, dict(DEFAULT_SETTINGS))
        s = get_settings(uid)
        await _refresh_menu(q, s)
        await q.message.reply_text("♻️ Reset complete.")
        return

    if data == "generate":
        await _generate_and_send(q, ctx, uid)
        return


async def _refresh_menu(q, s: dict[str, Any]) -> None:
    try:
        await q.edit_message_text(
            settings_summary(s),
            reply_markup=main_menu_kb(s),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        await q.message.reply_text(
            settings_summary(s),
            reply_markup=main_menu_kb(s),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def _generate_and_send(q, ctx, uid: int) -> None:
    pending = get_pending_csv(uid)
    if not pending:
        await q.message.reply_text("⚠️ আগে একটি .csv ফাইল পাঠাও।")
        return
    csv_text, fname = pending
    s = get_settings(uid)
    questions = parse_csv(csv_text)
    if not questions:
        await q.message.reply_text("❌ CSV পার্স করা যায়নি।")
        return
    await ctx.bot.send_chat_action(q.message.chat_id, ChatAction.UPLOAD_DOCUMENT)
    try:
        # Run the (CPU-bound) PDF render in a thread so the bot stays responsive
        pdf_bytes = await asyncio.to_thread(generate_pdf, uid, questions, s)
    except Exception as e:
        log.exception("PDF generation failed")
        await q.message.reply_text(f"❌ PDF তৈরি ব্যর্থ: <code>{h(str(e))}</code>",
                                   parse_mode=ParseMode.HTML)
        return
    out_name = (Path(fname).stem or "quiz") + ".pdf"
    bio = io.BytesIO(pdf_bytes)
    bio.name = out_name
    await ctx.bot.send_document(
        q.message.chat_id,
        document=InputFile(bio, filename=out_name),
        caption=f"✅ <b>{h(s['title'])}</b> — {len(questions)} questions",
        parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))

    log.info("Bot starting (owner=%s)…", OWNER_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
