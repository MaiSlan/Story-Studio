# Story Studio

A small app you run yourself that writes graded-reader stories for language learners and turns them into PDFs.
You give it a topic; it writes the story line by line in three languages:

| Track | Bold line (read aloud) | Grey line | Small italic line |
|---|---|---|---|
| **Pinyin** (Mandarin learners) | pinyin with tone marks | simplified hanzi | English |
| **Français** (French learners) | French | simplified hanzi | English |

Lengths: **short ≈ 50 lines**, **medium ≈ 130** (100 to 150), **long ≈ 200** (150+), or any custom number.
One *line* is one numbered triple, so a 50-line story is 50 + 50 + 50 sentences.

```
frontend/   the website: plain HTML/CSS/JavaScript, no build step          -> deploy on Vercel
backend/    the API: Python (FastAPI), writing pipeline, checker, PDFs     -> run locally, or on Modal / Render
```

---

## 1. Run everything on your computer (5 minutes)

You need Python 3.10 or newer ([python.org](https://www.python.org/downloads/)).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then put at least one key in .env (see section 3)
python run.py
```

Your browser opens at <http://127.0.0.1:8000>. When `frontend/` sits next to `backend/`, the same process serves the
website, so there is nothing else to start. With no key at all you can already try everything with the
**Demo (offline)** AI, which writes nonsense stories but exercises the whole app, the checker and the PDF.

---

## 2. Put it online for free: Vercel (website) + Modal (API)

```
 your browser ──► Vercel  (frontend/, static files, free)
        │
        └──────► Modal    (backend/, one small container + a disk for your stories, free monthly credits)
                    │
                    └──► the AI service you chose (Gemini, Groq, Claude API, ...)
```

Do it in this order, because each step gives you an address the next one needs.

**A. Website on Vercel**
1. vercel.com → *Add New… → Project* → import this GitHub repository.
2. **Root Directory: `frontend`**. Framework preset *Other*. Leave build command and output directory empty. Deploy.
3. Note the address, e.g. `https://story-studio-xyz.vercel.app`.

**B. API on Modal**
1. Create an account at modal.com (the free Starter plan includes monthly credits and asks for no card at the time of writing).
2. In a terminal, from this repository:
   ```bash
   pip install modal
   modal setup
   modal secret create story-studio \
     GEMINI_API_KEY=... GROQ_API_KEY=... \
     APP_PASSWORD=pick-a-long-password \
     ALLOWED_ORIGINS=https://story-studio-xyz.vercel.app
   cd backend
   modal deploy modal_app.py
   ```
   Leave out any key you do not have. `ALLOWED_ORIGINS` is the Vercel address from step A (no trailing slash).
3. Modal prints the API address, e.g. `https://yourname--story-studio-web.modal.run`.

**C. Connect them**
Edit `frontend/config.js`, set `window.STORY_STUDIO_API = "https://yourname--story-studio-web.modal.run";`, commit and
push. Vercel redeploys by itself. Open your Vercel address from any device, enter the password once (it is remembered on
that device), done.

How it behaves: stories are saved on a Modal Volume, so they survive restarts and redeploys (the two sample stories are
copied in the first time). After about 15 idle minutes the container sleeps and the first visit takes a few seconds to
wake it; the page shows a "waking up" banner. The API runs as a single container on purpose: a story is written by a
background job that the browser polls, so every request has to reach the same process.

**Other hosts.** `backend/Dockerfile` runs the API anywhere that runs containers (Render, Railway, Fly.io, a VPS). Set the
same variables (`APP_PASSWORD`, `ALLOWED_ORIGINS`, keys) and mount a persistent disk at `/data`. Caveats: Render's free web
service sleeps after 15 minutes (about a minute to wake) and has **no persistent disk**, so stories vanish on every
restart unless you download them; that is why Modal is the recommended free option here.
Running the API on Vercel itself is not a good fit: its functions are stateless and short-lived, which does not suit
background jobs plus files on disk.

**Always set `APP_PASSWORD` online.** Anyone who finds the address could otherwise spend your AI credit.

---

## 3. Choosing the AI

Copy `backend/.env.example` to `backend/.env` (locally) or put the same names in the Modal secret (online).
Open **Connections** in the app and press *Test connection* after any change.

| Option | Cost | Notes |
|---|---|---|
| **Google Gemini** (`GEMINI_API_KEY`) | free tier | Key at aistudio.google.com. The most capable free choice I know of for this task. On the free tier Google may use your prompts to improve its products, and daily limits apply. |
| **Groq** (`GROQ_API_KEY`) | free tier | Very fast. The default small Llama is weak at pinyin; type `openai/gpt-oss-120b` in the *Model* box for better stories. Its free limits are low (tokens per minute and per day), so expect pauses and a few stories per day. |
| **Claude API** (`ANTHROPIC_API_KEY`) | pay per use | Key from console.anthropic.com. **A claude.ai Pro/Max subscription does not include API access**; the API is a separate account. Roughly 10 to 20 US cents for a 130-line story at the Sonnet 5.5 price in Anthropic's docs ($2 / $10 per million tokens): an estimate, and each story page shows the real token count. |
| **Ollama** | free | Models on your own computer (`ollama pull qwen2.5:14b`). More pinyin mistakes; the checker flags them. Local only. |
| OpenAI, xAI, OpenRouter | pay per use | Listed too; any service speaking the "OpenAI chat" protocol can be added in six lines in `backend/app/config.py`. |
| **Claude via your Claude app login** | uses your plan | See below. Local only. |

The built-in checker marks every line whose pinyin does not match its hanzi, so you can compare models on your own
stories: the error count is shown at the top of each one.

### Using your Claude account instead of an API key (local only)

On your own computer you can pick **"Claude via your Claude app login"**. The app then runs Anthropic's own
Claude Code program (`claude -p ...`) for each request, using the plan you are signed in with. Setup: install Claude Code,
run `claude` once and sign in, then start the app with `python run.py`.

Limits you should know about:
* It counts against your plan's usage limits and is slower than the API.
* It works only when the backend runs on **localhost**. The app refuses it on a server on purpose: Anthropic's terms for
  Claude Code do not allow other products or hosted services to sign users in with, or route requests through, claude.ai
  subscriptions. Running Claude Code yourself, on your own computer, signed in as yourself, is the supported use.
* The app never sees or stores your login. It only starts the `claude` program and reads its answer.

---

## 4. Use it

1. **New story**: choose Pinyin or Français, type a topic (or press *Suggest ideas*), choose length and level,
   press *Write the story*. A progress bar shows each part being written.
2. The story opens in a reading view that looks like the PDF. Click any line to edit it.
   Lines whose pinyin does not match the hanzi are marked in red with a one-click *Rebuild pinyin from hanzi*.
3. **Preview PDF** / **Download PDF** / data as JSON (under *More*). Stories are saved as one JSON file each in
   `backend/data/stories/` (locally) or on the Modal volume (online).

Also available from a terminal: `cd backend && python -m app.cli --help` (generate, ideas, pdf, check, list).

## 5. How it works

```
topic ──► outline (title, characters with fixed spellings, N beats)
              │
              ▼  for each beat (about 25 lines):
          write lines ──► check ──► retry with precise feedback if bad (max 3 tries)
              │
              ▼
        auto-repair what is still wrong ──► save JSON ──► PDF on demand
```

* **Why chunks?** A 200-line trilingual story is too long to write well in one go. Each part sees the outline, the
  character spellings and the last lines written, so the story stays coherent and names stay identical.
* **The checker** (`backend/app/pinyin_tools.py`) compares pinyin with hanzi syllable by syllable using the `pypinyin`
  dictionary: missing or extra syllables, wrong tones, tone numbers, inconsistent name spelling, traditional characters.
  It understands the textbook changes (不 → bú, 一 → yí/yì, erhua, neutral tones). Lines with real errors are retried;
  if they stay wrong, the pinyin is rebuilt from the hanzi. Tone *warnings* are shown for you to judge.
* **Fonts**: `backend/fonts/` contains DejaVu Sans and a Noto Sans SC subset (all common hanzi) so PDFs look the same
  everywhere. Licences are in `backend/fonts/LICENSES/`.

```
frontend/index.html, app.js, style.css     the website            frontend/config.js   where the API lives
backend/run.py                              start locally          backend/modal_app.py deploy on Modal
backend/app/api.py                          web endpoints          backend/app/generator.py  the pipeline
backend/app/validate.py, pinyin_tools.py    checks                 backend/app/pdf.py   PDF layout
backend/app/config.py                       providers, settings    backend/app/providers/  Claude, Gemini/Groq/..., login, demo
backend/style/                              THE WRITING RULES, plain text you edit
backend/data/stories/                       two hand-written samples
backend/tests/                              cd backend && python -m pytest
```

## 6. Make it yours

The writing rules are plain text files in `backend/style/`. Edit them and the next story follows them:

* `common.md`: general rules for every story.
* `pinyin_track.md`, `french_track.md`: exact formatting rules for each track.
* `voices.md`: the voices (ancient tale, storyteller, chronicle, fairy tale, faithful retelling).
* `source_modes.md`: how to treat myths, history, licensed worlds (lore only, no invented character dialogue)
  and book adaptations (own words, never copy passages).
* `interests.md`: what *Suggest ideas* leans toward.

Level descriptions are in `backend/app/tracks.py`. To add a new track (say Spanish for Chinese learners), add an entry
there, a `style/<track>_track.md` file and a line in `app/pdf.py` if the layout differs.
After editing the style files online, redeploy (`modal deploy modal_app.py`) so the backend picks them up.

## 7. Good to know

* The tests (`cd backend && python -m pytest`, also run by GitHub Actions) cover the checker, the pipeline, the web API,
  the password and CORS rules, the storage hooks, and the Claude, Gemini/OpenAI-style and Claude-login clients against
  fake servers and a fake `claude` program. **Not yet exercised against the live services**: Modal, Vercel, Gemini, Groq
  and the real Claude Code login. The first real run is *Connections → Test connection*. Model names change often; edit
  them in the form or in `.env`.
* Claude models in the current SDK take no `temperature` setting; the other providers do (0.8 is used).
* A passing check means "pinyin matches hanzi", not "the story is good". Read the story.
