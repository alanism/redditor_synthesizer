# Redditor Synthesizer

> Fork of [ArthurHeitmann/arctic_shift_ui](https://github.com/ArthurHeitmann/arctic_shift_ui) (SvelteKit explorer for the [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) Reddit archive at `https://arctic-shift.photon-reddit.com`) with **reddit-intel** — a skill + scripts to turn any `r/<subreddit>` into 3 runnable pipelines on a Hermes agent: **Monocle newspaper → Notion dossiers → Cosmos sample-size → Synthetic survey**.

Upstream overview page: https://github.com/ArthurHeitmann/arctic_shift

## What reddit-intel adds

| Pipeline | Input | Output | Design | Script |
|----------|-------|--------|--------|--------|
| **Pulse (Pipeline A)** | `r/<subreddit>` | Single-file Monocle HTML: 3-5 top posts, themes, sentiment, trends | `docs/DESIGN/DESIGN-Monocle.md` | `reddit-intel/scripts/pulse.py` |
| **Personas (Pipeline B)** | `r/<subreddit>` or `u/<author>` | V3.3 Seven-Signal Engine dossiers (Notion HTML + JSON rubric) | `docs/DESIGN/DESIGN-Notion.md` | `reddit-intel/scripts/persona.py` / `build_dataset.py` |
| **Survey (Pipeline 3)** | `personas.jsonl` + instrument | 12-Q simulated responses + Cosmos report | `docs/DESIGN/DESIGN-Cosmos.md` | `reddit-intel/scripts/synthetic_survey.py` |
| **Sample Size (Pipeline C)** | population or `r/<subreddit>` | Deterministic n + Cosmos brief | `docs/DESIGN/DESIGN-Cosmos.md` | `reddit-intel/scripts/sample_size.py` |

Live demos (r/stocks Q2 Evidence Stack **6.7/7, 100% top-2-box**; r/parenting file-first **6.8/7**) are archived as `examples/`.

## Quick Start — Run 3 pipelines end-to-end

### One-time setup

```bash
# Requires Python 3.9+, no extra pip packages (stdlib only). LLM is optional.
git clone https://github.com/alanism/redditor_synthesizer.git
cd redditor_synthesizer

# Optional: keep the SvelteKit explorer (original app)
npm install
npm run dev   # or: npm run build && npm run preview

# Set a model key so personas + surveys use real LLM instead of heuristics.
# DeepSeek V4 Flash is the recommended default (prompt-cache ~0.1x, quality).
# SKILL.md: the harness loads this automatically via reddit-intel's _load_env_file.
export DEEPSEEK_API_KEY=...        # preferred (direct api.deepseek.com)
# or fallback:
export OPENAI_API_KEY=...
# Write to one of these so Hermes subshells see it without export:
#   ~/.hermes/.env  or  ~/.hermes/profiles/hermozi/.env
```

On a Hermes harness the key lives in `~/.hermes/profiles/hermozi/.env` / `~/.hermes/.env` and `reddit-intel/scripts/analyze.py:_load_env_file()` loads it automatically — no `export` needed per shell. The harness also exposes `--model deepseek-v4-flash` (prompt-cache: system=V3.3 prefix ~2484 chars, user=corpus ~1k variable).

### 3 pipelines — r/stocks example

```bash
# Preflight — fail fast (env + API)
python -c "from reddit_intel.scripts.analyze import _load_env_file; _load_env_file(); import os; k=os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY') or 'MISSING'; print(k[:12]+'…' if k!='MISSING' else 'MISSING')"
python reddit-intel/scripts/analyze.py --subreddit stocks --limit 5
python reddit-intel/scripts/pulse.py --help
python reddit-intel/scripts/sample_size.py --help

# Pipeline A: Pulse newspaper (Monocle, offline single-file HTML) + Cosmos sizing
OUT=~/Documents/Vibe\ Code/reddit-intel-stocks   # or ./demo-stocks
python reddit-intel/scripts/pulse.py \
  --subreddit stocks --limit 30 --top 5 \
  --out "$OUT/pulse-stocks.html"

python reddit-intel/scripts/sample_size.py \
  --subreddit stocks --confidence 95 --margin 5 \
  --html-out "$OUT/Cosmos-r-stocks-95-5-required.html"
# → N=8,418,548 @95%/±5% → n=385, pull 482, pilot 50  (thin-aware: 35% for N<500k, 25% otherwise)
python reddit-intel/scripts/sample_size.py --subreddit stocks --confidence 95 --margin 3 \
  --html-out "$OUT/Cosmos-r-stocks-95-3-tighter.html"

# Pipeline B: 20-dossier dataset (Notion, deepseek-v4-flash)
# 180s shell limit: 20 via deepseek ≈300s at concurrency 2 — use checkpointing (re-run resumes)
# or concurrency 4 / timeout 600 / background=True for one-shot.
python reddit-intel/scripts/build_dataset.py \
  --subreddit stocks --users 20 --comments-per-user 30 \
  --out "$OUT/dataset-pilot-20" --model deepseek-v4-flash --concurrency 2

# Pipeline 3: Decision > Prediction extension interest survey (12 Qs, --instrument)
# Default instrument (no --instrument): UCC Hermes Thrice Great (SOP v6, 11 instruments + M/C/M/F/N)
# Here: Decision > Prediction packet (Decision_Prediction_Product_Packet.md) × Hermes extension
python reddit-intel/scripts/synthetic_survey.py \
  --personas "$OUT/dataset-pilot-20/personas.jsonl" \
  --instrument reddit-intel/instruments/survey-instrument-decision-prediction.json \
  --out "$OUT/survey-simulation" --model deepseek-v4-flash --concurrency 2
# → survey-simulation/report.html (Cosmos), responses.jsonl/csv, aggregates.json

# Or UCC Hermes default (no --instrument):
python reddit-intel/scripts/synthetic_survey.py \
  --personas "$OUT/dataset-pilot-20/personas.jsonl" \
  --out "$OUT/survey-simulation-ucc" --model deepseek-v4-flash --concurrency 2

# Heuristic-only (no LLM, no key) still produces valid HTML/JSON for pipeline testing:
python reddit-intel/scripts/build_dataset.py --subreddit stocks --users 20 --out /tmp/demo --no-llm
python reddit-intel/scripts/synthetic_survey.py --personas /tmp/demo/personas.jsonl --out /tmp/demo/survey --no-llm
```

## Rounds of surveys — iterate positioning/pricing on the same personas

Once you have a dataset (`dataset-*/personas-30.jsonl`), you can run any number
of survey **rounds** against the same personas — no new fetching. Each round is
a new instrument + output dir, checkpointed via `responses.jsonl` (re-running
resumes, skipping completed authors).

```bash
# 1. Short custom instruments (2+ single_choice questions, % per option):
#    use ai_use_survey.py — it accepts ANY N questions via --instrument.
#    (synthetic_survey.py is hardcoded to the 12-Q shape; ai_use_survey is the generic one.)

# Pilot FIRST on a random 20 rich personas (~2 min at c3) — direction gate, not share:
python3 - <<'EOF'
import json, random
rows=[json.loads(l) for l in open("$OUT/dataset-385/personas-30.jsonl")]
rich=[r for r in rows if r.get("big_five") and r.get("engine") and r.get("quotes") and r.get("one_line")]
random.seed(20260816)  # fixed seed = reproducible sample
open("$OUT/dataset-385/personas-20-random.jsonl","w").write(
  "\n".join(json.dumps(r,ensure_ascii=False) for r in random.sample(rich,20)))
EOF

# 2. Run the instrument on the pilot (read DIRECTION; 100% columns are instrument artifacts)
python reddit-intel/scripts/ai_use_survey.py \
  --personas "$OUT/dataset-385/personas-20-random.jsonl" \
  --instrument examples/positioning-instrument.json \
  --out "$OUT/survey-positioning-20" --model deepseek-v4-flash --concurrency 3

# 3. If direction is good, run the full population (~25-35 min for 7-Q at c3):
python reddit-intel/scripts/ai_use_survey.py \
  --personas "$OUT/dataset-385/personas-30.jsonl" \
  --instrument examples/positioning-instrument.json \
  --out "$OUT/survey-positioning-385" --model deepseek-v4-flash --concurrency 3
# → report.html (mono design), aggregates.json (share % per option per Q), responses.jsonl/csv
```

**Reading rule (Hormozi):** don't trust what respondents say they like — watch
which offer they'd buy today (Q6) and which line wins head-to-head (Q1). Q2
reveals the wedge; Q3 tests whether "we handle everything" converts the
undecided block; Q7 identifies the conversion trigger for a fielded pilot.

**Narrative report (optional, per round):** the mono grid is data; for a
stakeholder deliverable, wrap it in a Thompson-style editorial × Monocle-design
single-file HTML with a pilot postscript + Hormozi operator note (see the
reddit-dataset-ops skill reference for the exact recipe). Every number must be
pulled live from `aggregates.json`/`responses.jsonl` — never hardcoded.

**Filter before surveying (Alan's standing preference):** build
`personas-30.jsonl` (`comments >= 30`) and point instruments at it, not the
full `personas.jsonl`. Pilot rows may carry `comments: null` — backfill the
count from the seed pilot jsonl first.

### Open the results (offline, single-file)

- `pulse-*.html` — Monocle newspaper on `#fdfcf3` (Plantin), yellow `#ffc500` ≤1 accent, `1px #d9d9d9` hairlines, `0px` card radius.
- `Cosmos-*.html` — Cosmos brief on `#f7f5f3` linen, `#0d0d0d` ink, `16px` cards. States: *"With X population at Y% / ±Z%, we think … and we recommend pull + pilot."*
- `dataset-pilot-20/dossiers/u_*.html` — Notion dossiers on `#f6f5f4` warm canvas, white `12px` cards, marigold/coral/sky/midnight rotation. Each links to its JSON sidecar (`u_*.json` with `engine`, `big_five`, `quotes`, `persona_stack`).
- `survey-simulation/report.html` — Cosmos report (aggregates + methodology + individual cards → dossiers).

See `examples/` for sample HTMLs from the r/stocks run.

## What works like this harness

- There is no installation step for `reddit-intel` beyond `export DEEPSEEK_API_KEY` (or `~/.hermes/.env`). All 6 scripts are stdlib-only, single-file HTML, offline-openable.
- Hermes harness convention: the active profile's env file is `~/.hermes/profiles/hermozi/.env`; `analyze.py` reads both `~/.hermes/profiles/hermozi/.env` and `~/.hermes/.env` so background/terminal subshells see the key without `export`. On plain machines, `export DEEPSEEK_API_KEY` is enough.
- Recommended model is `deepseek-v4-flash` everywhere (`--model deepseek-v4-flash` default). `analyze.py:try_llm(max_tokens=None)` auto-sets `12000` for deepseek (reasoning) vs `3000` otherwise, with `reasoning_content` fallback — callers should not set `max_tokens` manually.
- End-to-end the harness uses 4 profile runs (homeschool, parenting, stocks): same commands, different `--subreddit` / `--instrument`.

## Hermes Skill — install like a harness agent

On a [Hermes](https://github.com/hermes) agent the same SKILL.md is loadable as a skill:

```bash
# Clone this repo next to your hermes skills, or copy reddit-intel/ into:
#   ~/.hermes/skills/research/reddit-intel/   (harness global)
#   ~/.hermes/profiles/hermozi/skills/research/reddit-intel/
cp -r reddit-intel ~/.hermes/skills/research/reddit-intel
# The agent can now `skill_view(name='reddit-intel')` and call the scripts.
```

Contract is in `reddit-intel/SKILL.md` v1.1.0 (328 lines) — pipelines, data flow, prompt-caching (system=V3.3/instrument prefix), thin-rate (`recommend_pull(population=)` 35%/25%), 180s checkpointing, design tokens, verification checklists.

## Related

- **Upstream explorer:** [ArthurHeitmann/arctic_shift_ui](https://github.com/ArthurHeitmann/arctic_shift_ui) / [arctic_shift](https://github.com/ArthurHeitmann/arctic_shift) — the SvelteKit search UI and API (`https://arctic-shift.photon-reddit.com`, `limit 1–100`, `after = last.created_utc * 1000`, polite `1 req/sec`).
- **Design systems:** `docs/DESIGN/DESIGN-Monocle.md`, `DESIGN-Notion.md`, `DESIGN-Cosmos.md` + `reddit-intel/references/`.
- **Template:** V3.3 Seven-Signal Engine (`reddit-intel/references/template-v33.md`) + `UNIVERSAL … V3.3` upstream.
- **Instruments:** `reddit-intel/instruments/survey-instrument-decision-prediction.json` (12 Qs, Decision_Prediction_Product_Packet grounded); default UCC Hermes instrument embedded in `synthetic_survey.py` (`SURVEY_INSTRUMENT`).
- **Demos:** `examples/pulse-stocks.html`, `examples/Cosmos-*.html`, `examples/sample-dataset/`, `examples/sample-survey/report.html`.

## Upstream `arctic_shift_ui` notes (kept intact)

The original SvelteKit app is in `src/` unchanged. `npm run dev` / `npm run build` still work as upstream documents. `reddit-intel/` sits alongside it — no shared state except the Arctic Shift API base `https://arctic-shift.photon-reddit.com`.

## Removal

Archived data; removal requests as documented upstream: https://github.com/ArthurHeitmann/arctic_shift#contact--removal-requests

---

## Develop / Build (SvelteKit)

```bash
npm install
npm run dev         # with --open to open in browser
npm run build       # production build to ./build
npm run preview
```
