#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║   Bengali MCQ Quiz PDF Generator — Telegram Bot              ║
║   Single File · Render Ready · Professional · Error-Free     ║
╚══════════════════════════════════════════════════════════════╝

Required packages (pip install):
  python-telegram-bot==20.7
  reportlab==4.1.0
  matplotlib==3.8.2
  Pillow==10.2.0
  requests==2.31.0

Environment Variables (set in Render):
  BOT_TOKEN   — Your Telegram Bot Token
  OWNER_ID    — Your Telegram User ID (integer)
"""

import asyncio
import csv
import io
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("QuizBot")

# ── Third-party imports ────────────────────────────────────────────────────────
try:
    from telegram import (
        Update, InlineKeyboardButton, InlineKeyboardMarkup,
        ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile,
    )
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, CallbackQueryHandler,
        ConversationHandler, ContextTypes, filters,
    )
    from telegram.constants import ParseMode
except ImportError:
    logger.error("python-telegram-bot not installed. Run: pip install python-telegram-bot==20.7")
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.mathtext as mathtext
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    logger.warning("matplotlib not found — math rendering disabled")

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate,
        Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus.flowables import Flowable
    from reportlab.pdfgen import canvas as pdfcanvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    logger.error("reportlab not installed. Run: pip install reportlab")
    sys.exit(1)

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("Pillow not found — logo handling limited")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION & PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

DATA_DIR = Path("bot_data")
DATA_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"
LOGO_DIR = DATA_DIR / "logos"
LOGO_DIR.mkdir(exist_ok=True)
FONT_DIR = DATA_DIR / "fonts"
FONT_DIR.mkdir(exist_ok=True)
MATH_CACHE_DIR = DATA_DIR / "math_cache"
MATH_CACHE_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID  = int(os.environ.get("OWNER_ID", "0"))

# ── Color Themes ───────────────────────────────────────────────────────────────
THEMES = {
    "🔵 নীল (ক্লাসিক)": {
        "name": "blue",
        "color_header_bg":     "#1a5276",
        "color_header_text":   "#ffffff",
        "color_answer_bg":     "#eaf4fb",
        "color_answer_border": "#2980b9",
        "color_question_num":  "#1a5276",
        "color_correct_opt":   "#1a5276",
        "color_separator":     "#cccccc",
    },
    "🟢 সবুজ (প্রকৃতি)": {
        "name": "green",
        "color_header_bg":     "#1e8449",
        "color_header_text":   "#ffffff",
        "color_answer_bg":     "#eafaf1",
        "color_answer_border": "#27ae60",
        "color_question_num":  "#1e8449",
        "color_correct_opt":   "#1e8449",
        "color_separator":     "#abebc6",
    },
    "🔴 লাল (শক্তি)": {
        "name": "red",
        "color_header_bg":     "#922b21",
        "color_header_text":   "#ffffff",
        "color_answer_bg":     "#fdedec",
        "color_answer_border": "#e74c3c",
        "color_question_num":  "#922b21",
        "color_correct_opt":   "#922b21",
        "color_separator":     "#f5b7b1",
    },
    "🟣 বেগুনি (প্রিমিয়াম)": {
        "name": "purple",
        "color_header_bg":     "#6c3483",
        "color_header_text":   "#ffffff",
        "color_answer_bg":     "#f5eef8",
        "color_answer_border": "#8e44ad",
        "color_question_num":  "#6c3483",
        "color_correct_opt":   "#6c3483",
        "color_separator":     "#d7bde2",
    },
    "⚫ কালো (ডার্ক)": {
        "name": "dark",
        "color_header_bg":     "#1c1c1c",
        "color_header_text":   "#f0f0f0",
        "color_answer_bg":     "#f2f2f2",
        "color_answer_border": "#555555",
        "color_question_num":  "#222222",
        "color_correct_opt":   "#222222",
        "color_separator":     "#bbbbbb",
    },
    "🟠 কমলা (উদ্যম)": {
        "name": "orange",
        "color_header_bg":     "#d35400",
        "color_header_text":   "#ffffff",
        "color_answer_bg":     "#fef9e7",
        "color_answer_border": "#f39c12",
        "color_question_num":  "#d35400",
        "color_correct_opt":   "#d35400",
        "color_separator":     "#fad7a0",
    },
}

DEFAULT_SETTINGS = {
    "exam_title":         "পরীক্ষার নাম",
    "exam_subtitle":      "বিষয়: সাধারণ জ্ঞান",
    "total_marks":        "৪৫",
    "set_label":          "সেট: ক",
    "time_label":         "সময়: ৪৫ মিনিট",
    "header_channel_name": "আমাদের চ্যানেল",
    "header_channel_link": "https://t.me/yourchannel",
    "footer_left":        "আমাদের চ্যানেল",
    "watermark_text":     "",
    "watermark_opacity":  0.08,
    "columns":            2,
    "show_explanation":   True,
    "show_answer_inline": True,
    "theme":              "🔵 নীল (ক্লাসিক)",
    "logo_path":          None,
}

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = {**DEFAULT_SETTINGS, **data}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(cfg: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ══════════════════════════════════════════════════════════════════════════════
# FONT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

FONT_URLS = {
    "NotoSansBengali-Regular.ttf": (
        "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/"
        "NotoSansBengali/NotoSansBengali-Regular.ttf"
    ),
    "NotoSansBengali-Bold.ttf": (
        "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/"
        "NotoSansBengali/NotoSansBengali-Bold.ttf"
    ),
}

SYSTEM_FONT_PATHS = [
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/noto",
    "/usr/local/share/fonts",
    "/System/Library/Fonts",
]

def find_font(name: str) -> str | None:
    local = FONT_DIR / name
    if local.exists():
        return str(local)
    for d in SYSTEM_FONT_PATHS:
        p = Path(d) / name
        if p.exists():
            return str(p)
    return None

def download_font(name: str) -> str | None:
    dest = FONT_DIR / name
    if dest.exists():
        return str(dest)
    url = FONT_URLS.get(name)
    if not url:
        return None
    logger.info(f"Downloading font: {name}")
    try:
        urllib.request.urlretrieve(url, dest)
        logger.info(f"Font downloaded: {dest}")
        return str(dest)
    except Exception as e:
        logger.error(f"Font download failed: {e}")
        return None

def ensure_fonts() -> tuple[str, str]:
    reg_name = "NotoSansBengali-Regular.ttf"
    bld_name = "NotoSansBengali-Bold.ttf"
    reg = find_font(reg_name) or download_font(reg_name)
    bld = find_font(bld_name) or download_font(bld_name)
    if not reg or not bld:
        raise RuntimeError("Bengali fonts not available")
    return reg, bld

_fonts_registered = False

def register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    reg, bld = ensure_fonts()
    pdfmetrics.registerFont(TTFont("BengaliRegular", reg))
    pdfmetrics.registerFont(TTFont("BengaliBold", bld))
    pdfmetrics.registerFontFamily("Bengali", normal="BengaliRegular", bold="BengaliBold")
    _fonts_registered = True
    logger.info("Fonts registered successfully")

# ══════════════════════════════════════════════════════════════════════════════
# LATEX / MATH RENDERER
# ══════════════════════════════════════════════════════════════════════════════

MATH_PATTERN = re.compile(
    r"""
    \$\$(.+?)\$\$           |   # $$...$$
    \$([^$\n]+?)\$          |   # $...$
    \\begin\{[^}]+\}.*?\\end\{[^}]+\}   # \begin{env}...\end{env}
    """,
    re.VERBOSE | re.DOTALL,
)

# LaTeX symbols to unicode mapping for simple cases
LATEX_UNICODE = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\zeta": "ζ", r"\eta": "η", r"\theta": "θ",
    r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ", r"\mu": "μ",
    r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\rho": "ρ",
    r"\sigma": "σ", r"\tau": "τ", r"\upsilon": "υ", r"\phi": "φ",
    r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    r"\Alpha": "Α", r"\Beta": "Β", r"\Gamma": "Γ", r"\Delta": "Δ",
    r"\Theta": "Θ", r"\Lambda": "Λ", r"\Pi": "Π", r"\Sigma": "Σ",
    r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
    r"\infty": "∞", r"\pm": "±", r"\times": "×", r"\div": "÷",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
    r"\cdot": "·", r"\ldots": "…", r"\int": "∫", r"\sum": "∑",
    r"\prod": "∏", r"\sqrt": "√", r"\partial": "∂", r"\nabla": "∇",
    r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\Leftrightarrow": "⇔", r"\in": "∈", r"\notin": "∉",
    r"\subset": "⊂", r"\supset": "⊃", r"\cup": "∪", r"\cap": "∩",
    r"\circ": "∘", r"\bullet": "•", r"\therefore": "∴",
    r"\because": "∵", r"\forall": "∀", r"\exists": "∃",
    r"\log": "log", r"\ln": "ln", r"\sin": "sin", r"\cos": "cos",
    r"\tan": "tan", r"\cot": "cot", r"\sec": "sec", r"\csc": "csc",
    r"\lim": "lim", r"\max": "max", r"\min": "min",
}


def latex_to_unicode(text: str) -> str:
    """Convert simple LaTeX expressions to unicode for plain text rendering."""
    for cmd, uni in LATEX_UNICODE.items():
        text = text.replace(cmd, uni)

    # \frac{a}{b} → (a/b)
    def frac_replace(m):
        return f"({m.group(1)}/{m.group(2)})"
    text = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", frac_replace, text)

    # x^{abc} → x^(abc)
    text = re.sub(r"\^\\{([^}]*)\\}", r"^(\1)", text)
    text = re.sub(r"\^\{([^}]*)\}", r"^(\1)", text)

    # x_{abc} → x_(abc)
    text = re.sub(r"_\{([^}]*)\}", r"_(\1)", text)

    # \sqrt{x} → √x
    text = re.sub(r"\\sqrt\{([^}]*)\}", r"√(\1)", text)

    # Remove remaining \commands{}
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)

    # Clean up braces
    text = text.replace("{", "").replace("}", "")
    return text.strip()


def render_math_to_image(latex_expr: str, font_size: float = 14) -> bytes | None:
    """Render a LaTeX math expression to a PNG image using matplotlib mathtext."""
    if not HAS_MATPLOTLIB:
        return None

    cache_key = re.sub(r"[^a-zA-Z0-9]", "_", latex_expr[:40])
    cache_path = MATH_CACHE_DIR / f"{cache_key}_{font_size}.png"
    if cache_path.exists():
        return cache_path.read_bytes()

    try:
        # Ensure it's wrapped in $ $ for mathtext
        expr = latex_expr.strip()
        if not expr.startswith("$"):
            expr = f"${expr}$"

        fig = Figure(figsize=(0.01, 0.01))
        canvas = FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()

        text_obj = ax.text(
            0.5, 0.5, expr,
            ha="center", va="center",
            fontsize=font_size,
            color="black",
            transform=ax.transAxes,
        )

        # Get bounding box to size figure properly
        canvas.draw()
        renderer = canvas.get_renderer()
        bbox = text_obj.get_window_extent(renderer=renderer)
        w_px = max(int(bbox.width) + 20, 30)
        h_px = max(int(bbox.height) + 10, 20)

        dpi = 150
        fig2 = Figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi, facecolor="white")
        canvas2 = FigureCanvasAgg(fig2)
        ax2 = fig2.add_axes([0, 0, 1, 1])
        ax2.set_facecolor("white")
        ax2.set_axis_off()
        ax2.text(0.5, 0.5, expr, ha="center", va="center",
                 fontsize=font_size, color="black", transform=ax2.transAxes)

        buf = BytesIO()
        canvas2.draw()
        fig2.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                     facecolor="white", pad_inches=0.05)
        plt.close("all")

        img_bytes = buf.getvalue()
        cache_path.write_bytes(img_bytes)
        return img_bytes
    except Exception as e:
        logger.debug(f"Math render error for '{latex_expr[:30]}': {e}")
        return None


def has_latex(text: str) -> bool:
    """Check if text contains LaTeX math or special LaTeX commands."""
    patterns = [
        r"\$[^$]+\$",
        r"\\frac\{", r"\\sqrt\{", r"\\int\b", r"\\sum\b", r"\\prod\b",
        r"\\begin\{", r"\\alpha", r"\\beta", r"\\gamma", r"\\delta",
        r"\\theta", r"\\pi\b", r"\\sigma", r"\\omega",
        r"\\sin\b", r"\\cos\b", r"\\tan\b", r"\\log\b", r"\\ln\b",
        r"\\lim\b", r"\\infty", r"\\partial", r"\\nabla",
        r"\\[a-zA-Z]+\{",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return False


def clean_text_for_pdf(text: str) -> str:
    """Clean and prepare text for PDF rendering — convert LaTeX to readable form."""
    if not text:
        return ""

    # Extract math from $...$ blocks and convert
    def replace_inline_math(m):
        inner = m.group(1) or m.group(2) or ""
        return latex_to_unicode(inner)

    text = re.sub(r"\$\$(.+?)\$\$", replace_inline_math, text, flags=re.DOTALL)
    text = re.sub(r"\$([^$\n]+?)\$", replace_inline_math, text)

    # Convert remaining LaTeX
    if has_latex(text):
        text = latex_to_unicode(text)

    return text.strip()


def html_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

# ══════════════════════════════════════════════════════════════════════════════
# CSV LOADER
# ══════════════════════════════════════════════════════════════════════════════

def load_csv_from_bytes(data: bytes) -> list[dict]:
    """Load questions from CSV bytes."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    questions = []
    for row in reader:
        opts = []
        for k in ["option1", "option2", "option3", "option4", "option5"]:
            v = (row.get(k) or "").strip()
            if v:
                opts.append(v)
        if not opts:
            continue
        try:
            ans_idx = int(row.get("answer", "1") or "1") - 1
        except ValueError:
            ans_idx = 0
        ans_idx = max(0, min(ans_idx, len(opts) - 1))

        questions.append({
            "question":    (row.get("questions") or row.get("question") or "").strip(),
            "options":     opts,
            "answer_idx":  ans_idx,
            "explanation": (row.get("explanation") or "").strip(),
            "section":     (row.get("section") or "").strip(),
            "qtype":       (row.get("type") or "").strip(),
        })
    return questions

# ══════════════════════════════════════════════════════════════════════════════
# PDF GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def hex_to_color(hex_str: str):
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return colors.Color(r, g, b)


OPTION_LABELS = ["ক)", "খ)", "গ)", "ঘ)", "ঙ)"]


class MathImageFlowable(Flowable):
    """A flowable that renders a math expression as an inline image."""
    def __init__(self, img_bytes: bytes, width_pt: float, height_pt: float):
        super().__init__()
        self.img_bytes = img_bytes
        self.width = width_pt
        self.height = height_pt

    def draw(self):
        img = PILImage.open(BytesIO(self.img_bytes))
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp.name)
        tmp.close()
        self.canv.drawImage(tmp.name, 0, 0, width=self.width, height=self.height)
        os.unlink(tmp.name)


def make_styles(cfg: dict) -> dict:
    theme_name = cfg.get("theme", "🔵 নীল (ক্লাসিক)")
    theme = THEMES.get(theme_name, THEMES["🔵 নীল (ক্লাসিক)"])

    clr_q_num   = hex_to_color(theme["color_question_num"])
    clr_cor_opt = hex_to_color(theme["color_correct_opt"])

    return {
        "q_num": ParagraphStyle(
            "q_num", fontName="BengaliBold", fontSize=10,
            textColor=clr_q_num, leading=14, spaceAfter=1,
        ),
        "q_text": ParagraphStyle(
            "q_text", fontName="BengaliRegular", fontSize=9.5,
            leading=16, spaceAfter=3, textColor=colors.black,
        ),
        "option": ParagraphStyle(
            "option", fontName="BengaliRegular", fontSize=9,
            leading=14, leftIndent=6, textColor=colors.HexColor("#333333"),
        ),
        "correct_label": ParagraphStyle(
            "correct_label", fontName="BengaliBold", fontSize=9,
            textColor=clr_cor_opt, leading=13,
        ),
        "explanation": ParagraphStyle(
            "explanation", fontName="BengaliRegular", fontSize=8.5,
            leading=13, textColor=colors.HexColor("#444444"),
        ),
        "header_title": ParagraphStyle(
            "header_title", fontName="BengaliBold", fontSize=16,
            textColor=hex_to_color(theme["color_header_text"]),
            alignment=TA_CENTER, leading=22,
        ),
        "header_sub": ParagraphStyle(
            "header_sub", fontName="BengaliRegular", fontSize=10,
            textColor=hex_to_color(theme["color_header_text"]),
            alignment=TA_CENTER, leading=15,
        ),
        "meta": ParagraphStyle(
            "meta", fontName="BengaliRegular", fontSize=9.5,
            textColor=colors.black, leading=13,
        ),
        "meta_bold": ParagraphStyle(
            "meta_bold", fontName="BengaliBold", fontSize=9.5,
            textColor=colors.black, leading=13,
        ),
        "section_header": ParagraphStyle(
            "section_header", fontName="BengaliBold", fontSize=10,
            textColor=colors.white, leading=14, alignment=TA_CENTER,
        ),
        "_theme": theme,
    }


def draw_watermark(c, doc, cfg: dict):
    wm = cfg.get("watermark_text", "").strip()
    if not wm:
        return
    c.saveState()
    c.setFont("BengaliBold", 55)
    opacity = float(cfg.get("watermark_opacity", 0.08))
    c.setFillColorRGB(0.5, 0.5, 0.5, alpha=opacity)
    c.translate(A4[0] / 2, A4[1] / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, wm)
    c.restoreState()


def make_page_canvas_fn(cfg: dict):
    def _draw(c, doc):
        c.saveState()
        w, h = A4
        M = 15 * mm
        draw_watermark(c, doc, cfg)

        footer_y = 8 * mm
        c.setFont("BengaliRegular", 8)
        c.setFillColor(colors.HexColor("#666666"))

        c.drawString(M, footer_y, cfg.get("footer_left", ""))
        c.drawCentredString(w / 2, footer_y, f"— {doc.page} —")

        sep_color = cfg.get("_theme_sep", "#cccccc")
        c.setStrokeColor(colors.HexColor(sep_color))
        c.setLineWidth(0.4)
        c.line(M, footer_y + 4.5 * mm, w - M, footer_y + 4.5 * mm)
        c.restoreState()
    return _draw


def build_header(styles: dict, cfg: dict, usable_w: float) -> list:
    theme = styles["_theme"]
    clr_bg = hex_to_color(theme["color_header_bg"])

    elems = []

    # Logo row
    logo_path = cfg.get("logo_path")
    logo_row = None
    if logo_path and Path(logo_path).exists():
        try:
            lw = float(cfg.get("logo_width_mm", 25)) * mm
            lh = float(cfg.get("logo_height_mm", 18)) * mm
            logo_img = RLImage(logo_path, width=lw, height=lh)
            title_p  = Paragraph(html_escape(cfg["exam_title"]),   styles["header_title"])
            sub_p    = Paragraph(html_escape(cfg["exam_subtitle"]), styles["header_sub"])
            text_col = Table([[title_p], [sub_p]], colWidths=[usable_w - lw - 8])
            text_col.setStyle(TableStyle([
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))
            logo_row = Table([[logo_img, text_col]], colWidths=[lw + 8, usable_w - lw - 8])
            logo_row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND",    (0, 0), (-1, -1), clr_bg),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ]))
        except Exception as e:
            logger.warning(f"Logo render error: {e}")
            logo_row = None

    if logo_row is None:
        title_p = Paragraph(html_escape(cfg["exam_title"]),   styles["header_title"])
        sub_p   = Paragraph(html_escape(cfg["exam_subtitle"]), styles["header_sub"])
        logo_row = Table([[title_p], [sub_p]], colWidths=[usable_w])
        logo_row.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), clr_bg),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ]))

    elems.append(logo_row)
    elems.append(Spacer(1, 4))

    # Channel row
    channel = cfg.get("header_channel_name", "")
    if channel:
        link = cfg.get("header_channel_link", "")
        if link:
            ch_txt = f'<a href="{html_escape(link)}" color="#2980b9">{html_escape(channel)}</a>'
        else:
            ch_txt = html_escape(channel)
        ch_style = ParagraphStyle(
            "ch", fontName="BengaliRegular", fontSize=8.5,
            textColor=colors.HexColor("#555555"), alignment=TA_CENTER, leading=12,
        )
        ch_p = Paragraph(ch_txt, ch_style)
        ch_table = Table([[ch_p]], colWidths=[usable_w])
        ch_table.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2),
                                      ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        elems.append(ch_table)
        elems.append(Spacer(1, 3))

    # Meta row: marks | set | time
    meta_l = Paragraph(f"<b>পূর্ণমান:</b> {html_escape(cfg['total_marks'])}", styles["meta"])
    meta_m = Paragraph(html_escape(cfg["set_label"]),  styles["meta_bold"])
    meta_r = Paragraph(html_escape(cfg["time_label"]), styles["meta"])
    meta_t = Table([[meta_l, meta_m, meta_r]], colWidths=[usable_w / 3] * 3)
    meta_t.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (0, 0), "LEFT"),
        ("ALIGN",         (1, 0), (1, 0), "CENTER"),
        ("ALIGN",         (2, 0), (2, 0), "RIGHT"),
        ("FONTNAME",      (0, 0), (-1, -1), "BengaliRegular"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX",           (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("LINEAFTER",     (0, 0), (1, 0),   0.4, colors.HexColor("#cccccc")),
    ]))
    elems.append(meta_t)
    elems.append(Spacer(1, 8))
    return elems


def build_question_block(q_num: int, q: dict, styles: dict, cfg: dict,
                         col_width_pt: float) -> "Table":
    theme = styles["_theme"]
    clr_ans_bg  = hex_to_color(theme["color_answer_bg"])
    clr_ans_bdr = hex_to_color(theme["color_answer_border"])

    rows = []

    # Question text
    q_raw  = clean_text_for_pdf(q["question"])
    q_safe = html_escape(q_raw)
    q_para = Paragraph(f"<b>{q_num}.</b> {q_safe}", styles["q_text"])
    rows.append([q_para])

    # Options
    opts = [clean_text_for_pdf(o) for o in q["options"]]
    opt_pairs = []
    for i in range(0, len(opts), 2):
        left_txt  = html_escape(f"{OPTION_LABELS[i]} {opts[i]}")
        right_txt = html_escape(f"{OPTION_LABELS[i+1]} {opts[i+1]}") if i + 1 < len(opts) else ""
        opt_pairs.append([
            Paragraph(left_txt,  styles["option"]),
            Paragraph(right_txt, styles["option"]),
        ])
    if opt_pairs:
        opt_tbl = Table(opt_pairs, colWidths=["50%", "50%"])
        opt_tbl.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ]))
        rows.append([opt_tbl])

    # Answer + Explanation box
    if cfg.get("show_answer_inline", True):
        correct_raw = opts[q["answer_idx"]] if q["answer_idx"] < len(opts) else "?"
        correct_lbl = OPTION_LABELS[q["answer_idx"]] if q["answer_idx"] < len(OPTION_LABELS) else ""
        ans_content = [
            Paragraph(
                f"<b>সঠিক উত্তর:</b> {correct_lbl} {html_escape(correct_raw)}",
                styles["correct_label"],
            )
        ]
        if cfg.get("show_explanation", True) and q.get("explanation"):
            exp_raw   = clean_text_for_pdf(q["explanation"])
            exp_short = exp_raw[:200] + ("..." if len(exp_raw) > 200 else "")
            ans_content.append(
                Paragraph(f"<b>ব্যাখ্যা:</b> {html_escape(exp_short)}", styles["explanation"])
            )

        ans_tbl = Table([[ans_content]], colWidths=["100%"])
        ans_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), clr_ans_bg),
            ("BOX",           (0, 0), (-1, -1), 0.8, clr_ans_bdr),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]))
        rows.append([ans_tbl])

    outer = Table(rows, colWidths=["100%"])
    outer.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return outer


def generate_pdf(questions: list[dict], cfg: dict, output_path: str) -> str:
    """Generate PDF from questions list and settings. Returns output path."""
    register_fonts()

    theme_name = cfg.get("theme", "🔵 নীল (ক্লাসিক)")
    theme = THEMES.get(theme_name, THEMES["🔵 নীল (ক্লাসিক)"])
    cfg["_theme_sep"] = theme["color_separator"]

    width_pt, height_pt = A4
    M        = 15 * mm
    usable_w = width_pt - 2 * M
    gap      = 6 * mm

    cols = int(cfg.get("columns", 2))
    col_w = (usable_w - gap) / 2 if cols == 2 else usable_w

    footer_h = 15 * mm
    top_m    = 12 * mm
    bottom_m = footer_h + 5 * mm
    frame_h  = height_pt - top_m - bottom_m

    if cols == 2:
        frames = [
            Frame(M,             bottom_m, col_w, frame_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="col1"),
            Frame(M + col_w + gap, bottom_m, col_w, frame_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="col2"),
        ]
    else:
        frames = [
            Frame(M, bottom_m, usable_w, frame_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="main"),
        ]

    page_fn = make_page_canvas_fn(cfg)
    doc = BaseDocTemplate(
        output_path, pagesize=A4,
        leftMargin=M, rightMargin=M,
        topMargin=top_m, bottomMargin=bottom_m,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=frames, onPage=page_fn)])

    styles = make_styles(cfg)

    story = []
    story.extend(build_header(styles, cfg, usable_w))

    prev_section = None
    for i, q in enumerate(questions, 1):
        # Section header
        sect = q.get("section", "").strip()
        if sect and sect != prev_section:
            prev_section = sect
            theme_c = hex_to_color(theme["color_header_bg"])
            s_tbl = Table(
                [[Paragraph(html_escape(sect), styles["section_header"])]],
                colWidths=["100%"],
            )
            s_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), theme_c),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            story.append(s_tbl)
            story.append(Spacer(1, 4))

        block = build_question_block(i, q, styles, cfg, col_w)
        story.append(block)
        story.append(Spacer(1, 3))

        if i % 2 == 0:
            story.append(HRFlowable(
                width="100%", thickness=0.3,
                color=colors.HexColor(theme["color_separator"]),
                spaceAfter=2, spaceBefore=2,
            ))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc.build(story)
    return output_path

# ══════════════════════════════════════════════════════════════════════════════
# BOT CONVERSATION STATES
# ══════════════════════════════════════════════════════════════════════════════

(
    STATE_MAIN,
    STATE_WAIT_CSV,
    STATE_WAIT_LOGO,
    STATE_SETTINGS,
    STATE_SET_TITLE,
    STATE_SET_SUBTITLE,
    STATE_SET_MARKS,
    STATE_SET_SET,
    STATE_SET_TIME,
    STATE_SET_CHANNEL,
    STATE_SET_CHANNEL_LINK,
    STATE_SET_WATERMARK,
    STATE_THEME,
    STATE_COLUMNS,
    STATE_CONFIRM_PDF,
    STATE_FOOTER_LEFT,
) = range(16)

# ══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════════

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 CSV আপলোড", callback_data="upload_csv"),
         InlineKeyboardButton("🖼 লোগো আপলোড", callback_data="upload_logo")],
        [InlineKeyboardButton("⚙️ পরীক্ষার তথ্য", callback_data="settings"),
         InlineKeyboardButton("🎨 কালার থিম", callback_data="theme")],
        [InlineKeyboardButton("📋 বর্তমান সেটিংস", callback_data="show_settings"),
         InlineKeyboardButton("📄 PDF তৈরি করুন", callback_data="gen_pdf")],
        [InlineKeyboardButton("🔲 কলাম পরিবর্তন", callback_data="columns"),
         InlineKeyboardButton("👁 ব্যাখ্যা টগল", callback_data="toggle_expl")],
    ])

def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 পরীক্ষার শিরোনাম", callback_data="set_title"),
         InlineKeyboardButton("📌 বিষয়/সাবটাইটেল", callback_data="set_subtitle")],
        [InlineKeyboardButton("🔢 পূর্ণমান", callback_data="set_marks"),
         InlineKeyboardButton("🗂 সেট লেবেল", callback_data="set_set")],
        [InlineKeyboardButton("⏱ সময়", callback_data="set_time"),
         InlineKeyboardButton("💧 ওয়াটারমার্ক", callback_data="set_watermark")],
        [InlineKeyboardButton("📢 চ্যানেল নাম", callback_data="set_channel"),
         InlineKeyboardButton("🔗 চ্যানেল লিংক", callback_data="set_channel_link")],
        [InlineKeyboardButton("📌 ফুটার টেক্সট", callback_data="set_footer"),
         InlineKeyboardButton("◀️ ফিরে যান", callback_data="back_main")],
    ])

def kb_themes() -> InlineKeyboardMarkup:
    rows = []
    theme_list = list(THEMES.keys())
    for i in range(0, len(theme_list), 2):
        row = [InlineKeyboardButton(theme_list[i], callback_data=f"theme_{i}")]
        if i + 1 < len(theme_list):
            row.append(InlineKeyboardButton(theme_list[i + 1], callback_data=f"theme_{i+1}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ ফিরে যান", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_confirm_pdf(has_csv: bool) -> InlineKeyboardMarkup:
    if has_csv:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ PDF তৈরি করুন", callback_data="do_gen_pdf"),
             InlineKeyboardButton("❌ বাতিল", callback_data="back_main")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 CSV আপলোড করুন", callback_data="upload_csv"),
         InlineKeyboardButton("◀️ ফিরে যান", callback_data="back_main")],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ ফিরে যান", callback_data="back_main")]])

def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ বাতিল", callback_data="back_main")]])

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def owner_only(func):
    """Decorator to restrict access to owner only."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = (update.effective_user or update.callback_query.from_user).id
        if OWNER_ID and user_id != OWNER_ID:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text("⛔ শুধুমাত্র বটের মালিক এটি ব্যবহার করতে পারবেন।")
            return STATE_MAIN
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


def settings_summary(cfg: dict) -> str:
    theme_name = cfg.get("theme", "🔵 নীল (ক্লাসিক)")
    logo = "✅ আছে" if (cfg.get("logo_path") and Path(str(cfg["logo_path"])).exists()) else "❌ নেই"
    expl = "✅ দেখাবে" if cfg.get("show_explanation") else "❌ দেখাবে না"
    cols = cfg.get("columns", 2)
    wm   = cfg.get("watermark_text") or "নেই"
    return (
        f"📋 <b>বর্তমান সেটিংস</b>\n\n"
        f"📝 শিরোনাম: <code>{cfg.get('exam_title','')}</code>\n"
        f"📌 বিষয়: <code>{cfg.get('exam_subtitle','')}</code>\n"
        f"🔢 পূর্ণমান: <code>{cfg.get('total_marks','')}</code>\n"
        f"🗂 সেট: <code>{cfg.get('set_label','')}</code>\n"
        f"⏱ সময়: <code>{cfg.get('time_label','')}</code>\n"
        f"📢 চ্যানেল: <code>{cfg.get('header_channel_name','')}</code>\n"
        f"🔗 লিংক: <code>{cfg.get('header_channel_link','')}</code>\n"
        f"📌 ফুটার: <code>{cfg.get('footer_left','')}</code>\n"
        f"💧 ওয়াটারমার্ক: <code>{wm}</code>\n"
        f"🎨 থিম: {theme_name}\n"
        f"🔲 কলাম: {cols}\n"
        f"👁 ব্যাখ্যা: {expl}\n"
        f"🖼 লোগো: {logo}\n"
    )


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         text: str = None):
    cfg  = context.user_data.get("cfg", load_settings())
    csv_data = context.user_data.get("csv_data")
    csv_info = f"📊 CSV: ✅ {context.user_data.get('csv_filename','লোড হয়েছে')}" \
        if csv_data else "📊 CSV: ❌ আপলোড হয়নি"

    if text is None:
        text = (
            "🎓 <b>MCQ Quiz PDF Generator Bot</b>\n\n"
            f"{csv_info}\n\n"
            "নিচের মেনু থেকে আপনার কাজ বেছে নিন:"
        )

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.HTML, reply_markup=kb_main()
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=kb_main()
            )
    else:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb_main()
        )

# ══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "cfg" not in context.user_data:
        context.user_data["cfg"] = load_settings()
    await send_main_menu(update, context)
    return STATE_MAIN


@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>সাহায্য</b>\n\n"
        "/start — মূল মেনু\n"
        "/help  — সাহায্য\n"
        "/reset — সেটিংস রিসেট\n\n"
        "1️⃣ CSV আপলোড করুন\n"
        "2️⃣ সেটিংস ঠিক করুন\n"
        "3️⃣ PDF তৈরি করুন\n\n"
        "CSV কলাম: questions, option1-5, answer, explanation, type, section"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    return STATE_MAIN


@owner_only
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cfg"] = dict(DEFAULT_SETTINGS)
    save_settings(context.user_data["cfg"])
    await update.message.reply_text(
        "✅ সেটিংস রিসেট হয়েছে।", reply_markup=kb_main()
    )
    return STATE_MAIN

# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLERS — Main Menu
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if "cfg" not in context.user_data:
        context.user_data["cfg"] = load_settings()
    cfg = context.user_data["cfg"]

    # ── Main navigation ────────────────────────────────────────────────────────
    if data == "back_main":
        await send_main_menu(update, context)
        return STATE_MAIN

    if data == "upload_csv":
        await query.edit_message_text(
            "📤 <b>CSV ফাইল আপলোড করুন</b>\n\n"
            "আপনার MCQ প্রশ্নের CSV ফাইলটি এখানে পাঠান।\n\n"
            "প্রয়োজনীয় কলাম:\n"
            "<code>questions, option1, option2, option3, option4, answer, explanation</code>\n\n"
            "বাতিল করতে /start টাইপ করুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_CSV

    if data == "upload_logo":
        logo_status = ""
        if cfg.get("logo_path") and Path(str(cfg["logo_path"])).exists():
            logo_status = "✅ বর্তমানে একটি লোগো সেট আছে। নতুন পাঠালে পুরানোটি পরিবর্তন হবে।\n\n"
        await query.edit_message_text(
            f"🖼 <b>লোগো আপলোড করুন</b>\n\n"
            f"{logo_status}"
            "একটি PNG বা JPG ইমেজ পাঠান।\n"
            "লোগো PDF-এর হেডারে স্বয়ংক্রিয়ভাবে যোগ হবে।\n\n"
            "বাতিল করতে /start টাইপ করুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_LOGO

    if data == "settings":
        await query.edit_message_text(
            "⚙️ <b>পরীক্ষার তথ্য সম্পাদনা</b>\n\nকোনটি পরিবর্তন করতে চান?",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_settings(),
        )
        return STATE_SETTINGS

    if data == "theme":
        current = cfg.get("theme", "🔵 নীল (ক্লাসিক)")
        await query.edit_message_text(
            f"🎨 <b>কালার থিম বেছে নিন</b>\n\nবর্তমান: {current}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_themes(),
        )
        return STATE_THEME

    if data == "show_settings":
        await query.edit_message_text(
            settings_summary(cfg),
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back(),
        )
        return STATE_MAIN

    if data == "columns":
        current = int(cfg.get("columns", 2))
        cfg["columns"] = 1 if current == 2 else 2
        save_settings(cfg)
        await query.edit_message_text(
            f"✅ কলাম পরিবর্তন হয়েছে: <b>{cfg['columns']} কলাম</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back(),
        )
        return STATE_MAIN

    if data == "toggle_expl":
        cfg["show_explanation"] = not cfg.get("show_explanation", True)
        save_settings(cfg)
        status = "✅ দেখাবে" if cfg["show_explanation"] else "❌ দেখাবে না"
        await query.edit_message_text(
            f"✅ ব্যাখ্যা: <b>{status}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back(),
        )
        return STATE_MAIN

    if data == "gen_pdf":
        csv_data = context.user_data.get("csv_data")
        has_csv  = bool(csv_data)
        q_count  = len(context.user_data.get("questions", [])) if has_csv else 0

        text = (
            f"📄 <b>PDF তৈরি করার আগে নিশ্চিত করুন</b>\n\n"
            + settings_summary(cfg) +
            f"\n📊 মোট প্রশ্ন: <b>{q_count}</b>\n\n"
        )
        if not has_csv:
            text += "⚠️ CSV ফাইল আপলোড হয়নি। আগে CSV আপলোড করুন।"
        else:
            text += "সব ঠিক থাকলে <b>PDF তৈরি করুন</b> চাপুন।"

        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_confirm_pdf(has_csv),
        )
        return STATE_CONFIRM_PDF

    # ── Settings sub-items ─────────────────────────────────────────────────────
    settings_map = {
        "set_title":        (STATE_SET_TITLE,        "📝 নতুন পরীক্ষার শিরোনাম লিখুন:\n\nউদাহরণ: রসায়ন প্রথম পত্র"),
        "set_subtitle":     (STATE_SET_SUBTITLE,     "📌 নতুন বিষয়/সাবটাইটেল লিখুন:\n\nউদাহরণ: মৌলের পর্যায়বৃত্ত ধর্ম"),
        "set_marks":        (STATE_SET_MARKS,        "🔢 পূর্ণমান লিখুন:\n\nউদাহরণ: ৪৫ অথবা 45"),
        "set_set":          (STATE_SET_SET,          "🗂 সেট লেবেল লিখুন:\n\nউদাহরণ: সেট: ক"),
        "set_time":         (STATE_SET_TIME,         "⏱ সময় লিখুন:\n\nউদাহরণ: সময়: ৪৫ মিনিট"),
        "set_channel":      (STATE_SET_CHANNEL,      "📢 চ্যানেলের নাম লিখুন:"),
        "set_channel_link": (STATE_SET_CHANNEL_LINK, "🔗 চ্যানেলের লিংক লিখুন:\n\nউদাহরণ: https://t.me/mychannel"),
        "set_watermark":    (STATE_SET_WATERMARK,    "💧 ওয়াটারমার্ক টেক্সট লিখুন:\n(খালি রাখলে ওয়াটারমার্ক থাকবে না)"),
        "set_footer":       (STATE_FOOTER_LEFT,      "📌 ফুটার বাম দিকের টেক্সট লিখুন:"),
    }
    if data in settings_map:
        next_state, prompt = settings_map[data]
        await query.edit_message_text(
            f"✏️ <b>{prompt}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel(),
        )
        return next_state

    # ── Theme selection ────────────────────────────────────────────────────────
    if data.startswith("theme_"):
        idx = int(data.split("_")[1])
        theme_keys = list(THEMES.keys())
        if 0 <= idx < len(theme_keys):
            cfg["theme"] = theme_keys[idx]
            save_settings(cfg)
            await query.edit_message_text(
                f"✅ থিম পরিবর্তন হয়েছে: <b>{cfg['theme']}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_back(),
            )
        return STATE_MAIN

    # ── PDF Generation ─────────────────────────────────────────────────────────
    if data == "do_gen_pdf":
        questions = context.user_data.get("questions", [])
        if not questions:
            await query.edit_message_text(
                "❌ কোনো প্রশ্ন পাওয়া যায়নি। আগে CSV আপলোড করুন।",
                reply_markup=kb_back(),
            )
            return STATE_MAIN

        await query.edit_message_text(
            "⏳ PDF তৈরি হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।"
        )

        try:
            out_path = str(DATA_DIR / "output.pdf")
            await asyncio.get_event_loop().run_in_executor(
                None, generate_pdf, questions, cfg, out_path
            )

            with open(out_path, "rb") as f:
                filename = f"{cfg.get('exam_title','Quiz').replace(' ','_')}_MCQ.pdf"
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=InputFile(f, filename=filename),
                    caption=(
                        f"✅ <b>PDF তৈরি সম্পন্ন!</b>\n\n"
                        f"📝 {cfg.get('exam_title','')}\n"
                        f"📊 মোট প্রশ্ন: {len(questions)}\n"
                        f"🎨 থিম: {cfg.get('theme','')}"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            await send_main_menu(update, context,
                                 text="✅ PDF পাঠানো হয়েছে। আর কিছু করতে চান?")
        except Exception as e:
            logger.error(f"PDF generation error: {traceback.format_exc()}")
            await query.message.reply_text(
                f"❌ PDF তৈরিতে সমস্যা হয়েছে:\n<code>{html_escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_back(),
            )
        return STATE_MAIN

    return STATE_MAIN

# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLERS — text input for settings
# ══════════════════════════════════════════════════════════════════════════════

async def _save_field(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      field: str, label: str) -> int:
    cfg = context.user_data.setdefault("cfg", load_settings())
    cfg[field] = update.message.text.strip()
    save_settings(cfg)
    await update.message.reply_text(
        f"✅ {label} আপডেট হয়েছে: <b>{html_escape(cfg[field])}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_settings(),
    )
    return STATE_SETTINGS


@owner_only
async def recv_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "exam_title", "পরীক্ষার শিরোনাম")

@owner_only
async def recv_subtitle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "exam_subtitle", "বিষয়/সাবটাইটেল")

@owner_only
async def recv_marks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "total_marks", "পূর্ণমান")

@owner_only
async def recv_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "set_label", "সেট লেবেল")

@owner_only
async def recv_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "time_label", "সময়")

@owner_only
async def recv_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = context.user_data.setdefault("cfg", load_settings())
    val = update.message.text.strip()
    cfg["header_channel_name"] = val
    cfg["footer_left"] = val
    save_settings(cfg)
    await update.message.reply_text(
        f"✅ চ্যানেল নাম আপডেট হয়েছে: <b>{html_escape(val)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_settings(),
    )
    return STATE_SETTINGS

@owner_only
async def recv_channel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "header_channel_link", "চ্যানেল লিংক")

@owner_only
async def recv_watermark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "watermark_text", "ওয়াটারমার্ক")

@owner_only
async def recv_footer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_field(update, context, "footer_left", "ফুটার টেক্সট")

# ══════════════════════════════════════════════════════════════════════════════
# FILE HANDLERS — CSV and Logo
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def recv_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text(
            "❌ অনুগ্রহ করে একটি CSV ফাইল পাঠান।",
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_CSV

    if not doc.file_name.lower().endswith(".csv"):
        await update.message.reply_text(
            "❌ শুধুমাত্র .csv ফাইল গ্রহণযোগ্য।",
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_CSV

    msg = await update.message.reply_text("⏳ CSV পড়া হচ্ছে...")

    try:
        file = await doc.get_file()
        buf  = BytesIO()
        await file.download_to_memory(buf)
        csv_bytes = buf.getvalue()

        questions = load_csv_from_bytes(csv_bytes)
        if not questions:
            await msg.edit_text("❌ CSV ফাইলে কোনো প্রশ্ন পাওয়া যায়নি। ফরম্যাট চেক করুন।")
            return STATE_WAIT_CSV

        context.user_data["csv_data"]     = csv_bytes
        context.user_data["questions"]    = questions
        context.user_data["csv_filename"] = doc.file_name

        await msg.edit_text(
            f"✅ <b>CSV লোড সম্পন্ন!</b>\n\n"
            f"📊 মোট প্রশ্ন: <b>{len(questions)}</b>\n"
            f"📄 ফাইল: {html_escape(doc.file_name)}\n\n"
            "এখন PDF তৈরি করতে মূল মেনু থেকে 📄 PDF তৈরি করুন চাপুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(),
        )
        return STATE_MAIN

    except Exception as e:
        logger.error(f"CSV load error: {traceback.format_exc()}")
        await msg.edit_text(
            f"❌ CSV পড়তে সমস্যা:\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_CSV


@owner_only
async def recv_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo
    doc   = update.message.document

    if not photo and not doc:
        await update.message.reply_text(
            "❌ একটি ছবি বা PNG/JPG ফাইল পাঠান।",
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_LOGO

    msg = await update.message.reply_text("⏳ লোগো সংরক্ষণ হচ্ছে...")

    try:
        if photo:
            file_obj = await photo[-1].get_file()
            ext      = ".jpg"
        else:
            if not (doc.file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
                await msg.edit_text("❌ শুধুমাত্র PNG/JPG/JPEG/WEBP ফাইল গ্রহণযোগ্য।")
                return STATE_WAIT_LOGO
            file_obj = await doc.get_file()
            ext = Path(doc.file_name).suffix.lower()

        logo_path = LOGO_DIR / f"logo{ext}"
        await file_obj.download_to_drive(str(logo_path))

        # Convert to PNG for reliability
        if HAS_PIL:
            try:
                img = PILImage.open(str(logo_path)).convert("RGBA")
                png_path = LOGO_DIR / "logo.png"
                img.save(str(png_path), "PNG")
                logo_path = png_path
            except Exception:
                pass

        cfg = context.user_data.setdefault("cfg", load_settings())
        cfg["logo_path"] = str(logo_path)
        save_settings(cfg)

        await msg.edit_text(
            "✅ <b>লোগো সংরক্ষিত হয়েছে!</b>\n\n"
            "পরবর্তী PDF-এ স্বয়ংক্রিয়ভাবে হেডারে যোগ হবে।\n"
            "নতুন লোগো আপলোড করলে পুরানোটি পরিবর্তন হয়ে যাবে।",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(),
        )
        return STATE_MAIN

    except Exception as e:
        logger.error(f"Logo save error: {traceback.format_exc()}")
        await msg.edit_text(
            f"❌ লোগো সংরক্ষণে সমস্যা:\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel(),
        )
        return STATE_WAIT_LOGO

# ══════════════════════════════════════════════════════════════════════════════
# FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

@owner_only
async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ /start দিয়ে মূল মেনু খুলুন।",
        reply_markup=kb_main(),
    )
    return STATE_MAIN


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ একটি অপ্রত্যাশিত সমস্যা হয়েছে। /start দিয়ে আবার চেষ্টা করুন।"
        )

# ══════════════════════════════════════════════════════════════════════════════
# APPLICATION SETUP
# ══════════════════════════════════════════════════════════════════════════════

def build_app() -> Application:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")
    if not OWNER_ID:
        logger.warning("OWNER_ID is not set — no access restriction!")

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            STATE_MAIN: [
                CallbackQueryHandler(cb_handler),
                CommandHandler("help", cmd_help),
                CommandHandler("reset", cmd_reset),
                MessageHandler(filters.Document.ALL, recv_csv),
                MessageHandler(filters.PHOTO, recv_logo),
            ],
            STATE_WAIT_CSV: [
                MessageHandler(filters.Document.ALL, recv_csv),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_WAIT_LOGO: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, recv_logo),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SETTINGS: [
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_title),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_SUBTITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_subtitle),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_MARKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_marks),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_SET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_set),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_time),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_channel),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_CHANNEL_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_channel_link),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_SET_WATERMARK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_watermark),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_FOOTER_LEFT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_footer),
                CallbackQueryHandler(cb_handler),
            ],
            STATE_THEME: [
                CallbackQueryHandler(cb_handler),
            ],
            STATE_CONFIRM_PDF: [
                CallbackQueryHandler(cb_handler),
            ],
            STATE_COLUMNS: [
                CallbackQueryHandler(cb_handler),
            ],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CommandHandler("help",  cmd_help),
            CommandHandler("reset", cmd_reset),
            MessageHandler(filters.ALL, fallback),
        ],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_error_handler(error_handler)
    return app


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK HTTP SERVER (required for Render Web Service)
# ══════════════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK - Quiz PDF Bot is running!")

    def log_message(self, format, *args):
        pass  # Silence access logs


def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health check server started on port {port}")
    server.serve_forever()


def main():
    logger.info("═" * 60)
    logger.info("  Bengali MCQ Quiz PDF Generator Bot  ")
    logger.info("═" * 60)

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Exiting.")
        sys.exit(1)

    logger.info(f"Owner ID : {OWNER_ID or 'Not set (open access)'}")
    logger.info(f"Data Dir : {DATA_DIR.resolve()}")

    # Start health check HTTP server in background thread (Render requires this)
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Pre-download fonts
    logger.info("Checking fonts...")
    try:
        reg, bld = ensure_fonts()
        logger.info(f"Regular: {reg}")
        logger.info(f"Bold   : {bld}")
        register_fonts()
        logger.info("Fonts OK ✓")
    except Exception as e:
        logger.error(f"Font setup failed: {e}")
        logger.error("PDF generation may fail. Install NotoSansBengali fonts.")

    app = build_app()
    logger.info("Bot starting — polling mode...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
