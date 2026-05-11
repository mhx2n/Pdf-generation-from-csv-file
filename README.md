# QuizPDF Telegram Bot

Single-file Python Telegram bot that turns a quiz `.csv` into a beautiful,
2-column, Bengali-ready PDF (LaTeX `$...$` supported, logo, header, footer,
watermark, color theme) — fully customizable via inline buttons.

## Features

- 🇧🇩 **Bengali rendering** via Pango/HarfBuzz (WeasyPrint) — no broken যুক্তাক্ষর
- 🧮 **LaTeX inline math**: write `$x^2+y^2=r^2$` anywhere in question/option/explanation
- 🎨 **6 color themes** (blue/green/red/purple/orange/slate)
- 🖼 **Owner logo upload** — send a PNG/JPG; auto-replaced on next upload
- 🧷 Editable: title, subtitle, set name, total marks, time, footer text/link,
  watermark text, columns (1/2), page size (A4/Letter), toggles for logo /
  watermark / answer / explanation
- 🔒 **Owner-only by default**; owner can `/allow <user_id>` to grant access
- 💾 SQLite-backed per-user settings; logos persist across PDFs
- 🐳 Render-ready Docker image (free tier compatible)

## Deploy on Render (free)

1. Push this folder to a GitHub repo.
2. On Render → **New → Blueprint** → select the repo. Render auto-detects
   `render.yaml`.
3. Add the two secrets when asked:
   - `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `OWNER_ID` — your numeric Telegram id (use `/myid` after first launch
     to discover, or [@userinfobot](https://t.me/userinfobot))
4. Deploy. The bot runs as a background worker (no public port needed).

> **Note:** the free Render disk (1 GB) keeps your settings, logos, and
> allow-list across deploys.

## Usage

1. `/start` — verify access
2. Send a logo image (optional) — auto-saved
3. Send a `.csv` quiz file
4. Tap inline buttons to customize everything live
5. Tap **✅ Generate PDF**

### CSV format

```
questions,option1,option2,option3,option4,option5,answer,explanation,type,section
"প্রশ্ন এখানে","ক অপশন","খ অপশন","গ অপশন","ঘ অপশন",,2,"ব্যাখ্যা",1,1
```

- `answer` = 1..N (option index)
- Math: wrap in `$...$` (e.g. `$\frac{a}{b}$`)

### Owner commands

- `/allow <user_id>` — grant access
- `/revoke <user_id>` — remove access
- `/users` — list allowed users
- `/myid` — show your Telegram id

## Local run

```bash
export BOT_TOKEN=...
export OWNER_ID=123456789
docker build -t quizpdfbot . && docker run --rm -e BOT_TOKEN -e OWNER_ID quizpdfbot
```
