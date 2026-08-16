---
name: reddit-intel
description: "Use when analyzing Reddit subreddits or redditors: pulse reports, persona synthesis, or synthetic datasets."
version: 1.5.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Reddit, Intelligence, Persona, Synthesis, Monocle, Notion, Arctic-Shift, OSINT]
    related_skills: [arctic-shift, reference-to-site]
---

# Reddit Intel — Subreddit Pulse + Persona Synthesis Engine

Three intelligence products on one data backbone (Arctic Shift API). Strictly token-faithful rendering: Monocle for the newspaper, Notion for the dossier.

## Overview

| Product | Design System | Input | Output | Use |
|---------|--------------|-------|--------|-----|
| **Pulse** | `DESIGN-Monocle.md` (tokens only; report never says Monocle) | `r/<subreddit>` + window | Single-file Intelligence Brief HTML: generated title, executive briefing, activity timeline, what changed, theme landscape (volume vs engagement + heatmap), representative posts, sentiment + intent, keywords + methodology | What is happening, what is changing, and what evidence supports it (30-sec brief) |
| **Persona** | `DESIGN-Notion.md` | `u/<author>` or `r/<sub>` sample | Single-file dossier HTML populated from V3.3 Engine Template | Debate prep or high-fidelity digital twin |
| **Collective Profile** | `DESIGN-Notion.md` | Multi-year raw comments + annual dossiers | Complete HTML + Markdown + JSON + exact-evidence audit | Stable traits, longitudinal shifts, and complete V3.3 population |
| **Dataset** | Control Panel (HERMES tokens; Vega-Lite JSON) | `r/<sub>` + N users | Folder with N dossiers + `index.html` (archetypes + Vega-Lite + expandable previews + Copy JSON, local-first) + `personas.jsonl` (enriched: Big Five/quotes/arguments) | Cohort-level simulation control panel |
| **Sample Size** | `DESIGN-Cosmos.md` | `N` + confidence + margin (+ optional `r/<sub>` + topic) | Deterministic `n` + Cosmos intelligence brief HTML | Decide how many redditors to pull — with x at y confidence and z margin, we think ... and we recommend abc. |
| **Synthetic Survey** | `DESIGN-Cosmos.md` (report) | `personas.jsonl` + 12-Q instrument (SOP v6 grounded) | Simulated responses: `responses.jsonl/csv`, `report.html` with aggregates + Cosmos methodology box | Test positioning/messaging on a synthetic population before fielding |

All four share the same fetch layer (`arctic-shift` API at `https://arctic-shift.photon-reddit.com`) and the same local cache at `.hermes/cache/reddit-intel/`.

## When to Use

- User says "pulse on r/X" / "what's happening in r/X" / "subreddit report" -> **Pulse**
- User says "analyze u/X" / "who is this redditor" / "debate prep for u/X" / "synthesize this user" -> **Persona** (single)
- User says "use all comments" / "complete profile" / "populate the full V3.3 template" / asks how one user changed over years -> **Collective Profile**: hierarchical annual synthesis + balanced raw excerpts + exact evidence audit; follow `references/collective-profile.md`
- User says "build a dataset for r/X" / "sample of r/parenting" / "simulate reactions from r/vietnam" -> **Dataset** (bulk persona)
- User says "trends in r/X" / "sentiment of r/X" -> **Pulse** with trend block

Don't use for:
- Live Reddit API actions (posting, voting, moderating) — this is archive intelligence only
- Non-Reddit persona synthesis (use the V4 template directly)

## Template Selection — V4 Thinking vs V4 Flash

One Seven-Signal system, two templates. Pick by target, not by preference.

| Dimension | **V4 Thinking** | **V4 Flash** |
|---|---|---|
| Target | Single redditor (`u/X`) | Cohort / segment (`r/X` sample, 20–100 profiles) |
| Goal | Deep dossier, digital twin, debate prep, longitudinal arc | Synthetic data, simulated survey/review, group + segment prediction |
| Corpus | Full multi-year, 100+ comments | 15–30+ comments/profile (30 preferred, 15–20 thin-flag, <15 drop) |
| Output | Full essay dossier + 18-section JSON | One compact JSON microcard + one segment rollup |
| Tokens/profile | ~10–15k in, ~4–8k out | ~3–6k in, ~350–550 out (card) + ~80–200 (answer) |
| Speed | Slow, one at a time | High-throughput batch |
| Prompt cache | System = full template (stable) | Pass 1: system = codebook+schema; Pass 2: system = codebook+instrument |
| IQ-LP | Optional, quarantined band | OFF by default, never aggregated |
| Escalation | — | Single decision-critical profiles escalate to Thinking |

Routing: `persona.py --author X` (single) → **V4 Thinking**. `build_dataset.py` + `synthetic_survey.py` (bulk) → **V4 Flash**. `--template v33` retains the legacy V3.3 prompt. Templates: `templates/AlanDarkArts-v4-thinking.md`, `templates/AlanDarkArts-v4-flash.md`; adversarial review: `references/adversarial-review-v4-flash.md`.

## Quick Reference

```bash
# -- Preflight: fail fast before any LLM batch (env + API) --
python -c "from analyze import _load_env_file; _load_env_file(); import os; k=os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY') or 'MISSING'; print(k[:12]+'…' if k!='MISSING' else 'MISSING — export DEEPSEEK_API_KEY or OPENAI_API_KEY')"
python ~/.hermes/skills/research/reddit-intel/scripts/analyze.py --subreddit parenting --limit 5
curl -s "https://arctic-shift.photon-reddit.com/api/comments/search?author=spez&limit=3" | python3 -m json.tool

# -- Pulse: newspaper for a subreddit (Monocle) --
python ~/.hermes/skills/research/reddit-intel/scripts/pulse.py --subreddit parenting --window 7d --out ./pulse-parenting.html
python ~/.hermes/skills/research/reddit-intel/scripts/pulse.py --subreddit vietnam --limit 25 --top 5 --out ./pulse-vietnam.html
# -- Pulse now generates a human title (no HERMES). Structure: Briefing → Activity → What changed → Themes → Posts → Sentiment+Intent → Keywords+Method

# -- Persona: single redditor dossier (Notion) -- recommended: deepseek-v4-flash (prompt-cache + quality)
python ~/.hermes/skills/research/reddit-intel/scripts/persona.py --author spez --limit 100 --model deepseek-v4-flash --out ./dossier-spez.html
python ~/.hermes/skills/research/reddit-intel/scripts/persona.py --author someuser --limit 500 --model deepseek-v4-flash --out ./dossier-someuser.html

# -- Dataset: bulk synthetic population -- deepseek-v4-flash recommended; checkpoints via manifest.json
python ~/.hermes/skills/research/reddit-intel/scripts/build_dataset.py --subreddit parenting --users 20 --comments-per-user 30 --out ./data/parenting/ --model deepseek-v4-flash --concurrency 2
python ~/.hermes/skills/research/reddit-intel/scripts/build_dataset.py --subreddit vietnam --users 100 --comments-per-user 100 --out ./data/vietnam/ --model deepseek-v4-flash --concurrency 2
# reindex only (no fetch): python ~/.hermes/skills/research/reddit-intel/scripts/build_dataset.py --subreddit parenting --out ./data/parenting/ --reindex-only  # backfills Big Five/quotes/arguments from dossiers

# -- Sample Size: deterministic + Cosmos brief -- thin-rate aware (35% for N<500k, 25% otherwise)
python ~/.hermes/skills/research/reddit-intel/scripts/sample_size.py --population 94000000 --confidence 99 --margin 3  # -> 1849
python ~/.hermes/skills/research/reddit-intel/scripts/sample_size.py --subreddit parenting --confidence 95 --margin 5 --html-out ./sample-parenting.html
python ~/.hermes/skills/research/reddit-intel/scripts/sample_size.py --population 1200 --confidence 95 --margin 5 --topic "sleep training" --html-out ./sample-sleep.html

# -- Synthetic Survey (Pipeline 3): simulate a 12-Q instrument on a dossier population --
python ~/.hermes/skills/research/reddit-intel/scripts/synthetic_survey.py --personas ./data/parenting/personas.jsonl --out ./data/parenting/survey-simulation --model deepseek-v4-flash --concurrency 2
# or with a custom instrument:
python ~/.hermes/skills/research/reddit-intel/scripts/synthetic_survey.py --personas ./data/vietnam/personas.jsonl --instrument ./my-instrument.json --out ./data/vietnam/survey --model deepseek-v4-flash
```

## Architecture — How the Two Products Fit

```
                    ┌─────────────────────────┐
                    │  Arctic Shift API       │
                    │  photon-reddit.com      │
                    └────────────┬────────────┘
                                 │  fetch + paginate + cache
                    ┌────────────▼────────────┐
                    │  Intelligence Layer      │
                    │  ┌───────────────────┐  │
                    │  │ Pulse: themes,    │  │  keyword clustering + LLM synthesis
                    │  │ sentiment, trends │  │  score/velocity + sentiment scoring
                    │  │ top 3-5 posts     │  │  engagement ranking
                    │  ├───────────────────┤  │
                    │  │ Persona: V3.3     │  │  LLM fills all 8 sections + Engine
                    │  │ Engine + 7 layers │  │  evidence-anchored scoring
                    │  └───────────────────┘  │
                    └────────────┬────────────┘
                                 │  render (strict DESIGN.md tokens)
              ┌──────────────────┼──────────────────┐
              ▼                  │                   ▼
   ┌───────────────────┐  ┌──────▼──────┐  ┌─────────────────┐
   │ Intelligence Brief│  │  Notion     │  │ Dataset Folder  │
   │ pulse-*.html      │  │ dossier-*.html │ │ index.html (Control Panel)   │
   │ cream #fdfcf3     │  │ paper #f6f5f4│  │ dossiers/*.html (Notion)│
   │ Plantin serif     │  │ NotionInter │  │ manifest.json   │
   │ yellow #ffc500    │  │ accent cards│  │ personas.jsonl  │
   └───────────────────┘  └─────────────┘  └─────────────────┘
```

### Data Flow per Product

**Pulse (7 sections — Intelligence Brief, never says Monocle):**
1. Fetch posts `GET /api/posts/search?subreddit=X&limit=25-30&sort=desc` (+ `after` window; if limit>=40 fetch 60 for baseline split).
2. Rank top 3-5 by `score*0.6 + num_comments*0.9 + (score+comments)*0.1` composite, extract title/selftext/permalink, tag intent via `classify_intent`.
3. Synthesize themes (phrase-aware cluster: `extract_phrases` bigrams + `ARTIFACT_TOKENS` filtered), sentiment per theme, intent breakdown, timeline/heatmap/quadrant, collection_meta + confidence_assessment.
4. LLM enrichment (if key): generate human title (`_is_weak_label` + mega-cluster guard; neutral fallback `A Quiet Week in r/X` if sparse), polish theme labels, produce 3-sentence briefing, refine sentiment. Never use the word Monocle.
5. Render single-file HTML with Monocle tokens (sections: Briefing → Activity → What changed → Themes → Posts → Sentiment+Intent → Keywords+Method). Done when: HTML opens offline, branded `HERMES INTELLIGENCE`, title human and evidence-grounded, confidence limitation visible.

**Persona (4 steps):**
1. Fetch comments `GET /api/comments/search?author=X&limit=N` (paginate if N>100, cap at 100 per call).
2. Optionally fetch posts by same author for cross-check.
3. LLM synthesis: feed concatenated corpus (truncate to ~30k chars) into V3.3 template prompt — fills Engine axes (C/F/A1/A2/P 0-5), Big Five, style, quotes, argument flow, problem-solving, humor, response strategies + JSON rubric.
4. Render single-file HTML with Notion tokens. Done when: HTML opens offline, every V3.3 section populated with evidence anchors (real quotes), Engine signature shown, JSON rubric included.

**Dataset (bulk Persona):**
1. Discover users: `GET /api/comments/search?subreddit=X&limit=100&sort=desc` -> unique authors (repeat paginating until N uniques). Filter removed/deleted/bots.
2. For each author: fetch up to `--comments-per-user` comments (skip authors with <20 comments).
3. Queue LLM synthesis (concurrency capped, rate-limited, checkpointed to `manifest.json`).
4. Write `dossiers/u_<author>.html` (Notion) + `personas.jsonl` (one JSON rubric per line) + `index.html` (Monocle directory) + `manifest.json` (progress).

> **V4 Flash batch note.** Dataset + survey are the V4 Flash lane. Microcards carry a `segment` label (dominant PRISM × Proof pole) so the rollup can report per-segment. IQ-LP is OFF at batch scale (never aggregated). Thin authors (15–20 comments) get a `thin` flag + downgraded confidence — they are **not** auto-escalated to Thinking; only decision-critical profiles escalate. See `references/adversarial-review-v4-flash.md`.

## Fetch Layer — Arctic Shift Details

Base: `https://arctic-shift.photon-reddit.com` — no API key.

| Endpoint | Params | Notes |
|----------|--------|-------|
| `GET /api/posts/search` | `subreddit`, `author`, `limit` (1-100), `sort` (asc/desc), `after`/`before` (ISO or ms), `title`/`selftext` (FTS, needs subreddit or author) | Posts for pulse ranking |
| `GET /api/comments/search` | `subreddit`, `author`, `limit`, `sort`, `after`/`before`, `body` (FTS, needs subreddit/author/link_id), `link_id` | Comments for persona corpus |
| `GET /api/posts/ids?ids=t3_...` | `ids` comma-separated | Hydrate specific posts |
| `GET /api/comments/ids?ids=t1_...` | `ids` | Hydrate specific comments |
| `GET /api/utils/min?subreddit=X` | `subreddit` or `author` | Earliest archived date |

Common gotchas (from `arctic-shift` skill):
- `limit` caps at 100 — paginate with `after = last_item.created_utc` (seconds).
- FTS (`title`/`selftext`/`body`) silently ignored without companion field (`subreddit` or `author`).
- API expects `after`/`before` as ms or ISO; stored `created_utc` is seconds.
- No auth header needed; add `meta-app=reddit-intel` to identify.

## Intelligence Layer — What Gets Synthesized

### Pulse: Subreddit Themes / Sentiment / Intent / Trends

| Signal | How | Output in Brief |
|--------|-----|-----------------|
| **Themes** | Phrase-aware bigram extraction + contraction-aware tokenize (ARTIFACT_TOKENS: don/him/like/old removed) -> seed clusters by distinct keywords interleaved with phrase unigrams. Weak labels filtered via `_is_weak_label` + mega-cluster guard (>60% of sample treated as corpus, not theme). LLM refines labels when key present. | Theme cards: eyebrow = label, pills = freq + median engagement + sentiment, separate frequency vs engagement |
| **Sentiment** | Per-theme lexicon (SENT_POS/NEG) + aggregate bar; overall mood badge. LLM sentiment replaces when key present. Kept separate from engagement. | Sentiment strip (yellow/black/gray bar) + per-theme pill |
| **Intent** | Rule-based `classify_intent` (6 buckets: advice-seeking, reassurance, venting, personal story, product recommendation, safety concern) + neutral fallback. | Intent bar (stacked colors) + pill legend + per-post pill |
| **Trends / What changed** | Prior 7d vs current 7d split (fetch 60 when limit>=40). Also timeline (posts/day), theme×day heatmap, volume vs engagement quadrant, engagement histogram. | Timeline bars + heatmap table + quadrant plot + "What changed" card (new/faded themes) |
| **Top posts** | Rank by `score*0.6 + num_comments*0.9 + (score+comments)*0.1` composite -> top 3-5 with excerpt, permalink, intent tag | Lead card (warm left border) + secondary stack |

No LLM required for ranking/themes/intent/timeline; LLM required for human title + briefing + polished theme labels. Falls back to neutral title (`A Quiet Week in r/X` / `What r/X Is Asking This Week`) and heuristic labels with weak-label guard if no key.

### Persona: V3.3 Engine Template (all 8 sections)

The Notion dossier must populate every section from `UNIVERSAL COMMUNICATION-STYLE SYNTHESIS TEMPLATE (V3.3)`:

0. **Engine Layer** — C / F / A1 / A2 / P scores (0-5), polarity, signature (e.g. `C+ F+ A1~ A2+ P~`), execution envelope, failure modes, evidence anchors.
1. **Core Communication & Personality** — Big Five (linguistically inferred), Enneagram, IQ band, PRISM leanings, reflective vs reactive, thinking style, pace.
2. **Signature Speaking & Writing Style** — verbs, adjectives, transitions, sentence structure, rhetorical devices, delivery features.
3. **Example Quotes & Contextual Snippets** — 4-6 real quotes with source/trigger/signal.
4. **Structure of Arguments & Logical Flow** — hook, development, closure.
5. **Problem-Solving & Cognitive Approach** — pattern recognition vs deduction vs intuition+data, archetypal process.
6. **Humor, Drama & Emotional Nuance** — humor type, timing, range, destabilization points.
7. **Response Strategies & Closing Techniques** — challenge handling, reframing, closure, aftertaste.

Plus appendices: Seven-Signal table, usage protocol, and JSON rubric (`persona_stack` + `engine_metrics`).

Each score must have an **evidence anchor** — a short real phrase from the corpus, not a citation.

## Rendering — Strict DESIGN.md Compliance

### Monocle Pulse (`pulse.py` -> `DESIGN-Monocle.md`) — Tokens only, report says `HERMES INTELLIGENCE`

- **Naming:** report title + masthead + footer never say HERMES; internal design name stays in `DESIGN-Monocle.md` / code / docs only. Generated title is human, grounded in themes (e.g. `Parenting Pulse: Sleep, Potty Woes, Childcare & Hard Questions`), with neutral fallbacks (`A Quiet Week in r/X` / `What r/X Is Asking This Week`) when sparse/inconclusive and a `_is_weak_label` + mega-cluster (>60% of sample) guard so heuristic titles like `Kids, Anyone & Est` never render. Weak evidence must not be overstated.
- **Structure (7 sections):** Briefing (30-sec bullets + confidence dot) → Activity (timeline + engagement histogram) → What changed (7d vs prior 7d baseline) → Themes (freq vs engagement separated + quadrant + heatmap) → Posts (lead + stack, intent-tagged) → Sentiment+Intent → Keywords+Methodology. Covers: what's discussed, what changed, which themes matter, what evidence supports it, how confident.
- **Canvas / Type / Rules / Grid / Single-file:** as before. **Verify:** open HTML offline -> masthead `HERMES INTELLIGENCE · r/<sub>` (no HERMES) -> title human/specific, not generic -> yellow <=3 places, 1px hairlines, timeline + heatmap + quadrant render, confidence + methodology visible, no `don`/`him`/`like` in themes/keywords.

### Notion Dossier (`persona.py` -> `DESIGN-Notion.md`)

Must match the Cost Forecast Notion example (`example html/hermes-cost-forecast-notion.html`):

- **Canvas:** `#f6f5f4` paper warmth, not white. `--color-paper-warmth`.
- **Cards:** `#ffffff` with `1px solid rgba(0,0,0,0.08)` + `12px` radius. No shadows except optional nav.
- **Accent rotation:** `#ffb110` marigold, `#f64932` coral, `#62aef0` sky, `#02093a` midnight — rotate for section cards.
- **Type:** NotionInter for all UI/headings (negative tracking at display sizes), Lyon Text only for 18px pull-quotes.
- **Single-file:** inline CSS, inline accent cards, no external deps.

Verify: open HTML offline -> warm canvas visible vs white cards -> `12px` card radius -> accent cards rotate (not all same color) -> pills are `9999px`.

## Pipeline C -- Sample Size (Deterministic + Cosmos)

`scripts/sample_size.py` -- pure python, SurveyMonkey-compatible (z table matches SurveyMonkey calculator). Formula: `n0=(z^2*p*(1-p))/e^2` -> `n=n0/(1+(n0-1)/N)` (Cochran). Levels: 80% 1.28, 85% 1.44, 90% 1.645, 95% 1.96, 99% 2.58. Validated: 94M at 99%/+-3% -> 1849; 500k at 95%/+-5% -> 384; N=300 at 80%/+-10% -> 37. Inputs: `--population N` or `--subreddit r/name`, `--confidence`, `--margin`, `--p 0.5`, `--topic`. Outputs stdout n, Cosmos HTML (--html-out), JSON (--json-out). Brief states: with x at y confidence and z margin, we think ... and we recommend pull + pilot. Includes sensitivity tables and next-step commands. Feed n into build_dataset.py --users n (pull recommended_pull to net n).

## Storage & Caching

```
~/.hermes/cache/reddit-intel/
  pulse/
    r_parenting_7d.json      # raw API snapshot
  personas/
    u_spez_100.json          # raw comments
  datasets/
    parenting/
      manifest.json          # { subreddit, target_users, completed, failed, started_at }
      personas.jsonl         # one JSON rubric per line (append as each completes)
      dossiers/
        u_<author>.html      # Notion dossier per user
      index.html             # Monocle directory (user gallery + aggregate stats)
```

Cache TTL: 24h for pulse snapshots, 7d for persona corpora. Scripts respect `--no-cache` to force refetch.

For survey outputs (Pipeline 3):
```
./data/<subreddit>/survey-simulation/
  survey-instrument.json   # 12-Q instrument (SOP v6 grounded)
  responses.jsonl          # one JSON per author (Q1..Q12 + why + _rubric)
  responses.csv            # flat pivot for Sheets
  report.html              # Cosmos report (aggregates + methodology + cards)
  aggregates.json          # likerts/nps/journeys/top3/heuristic_count/n
```

For user-requested dataset folders (e.g. `./data/parenting/`):
```
./data/<subreddit>/
  index.html
  manifest.json
  personas.jsonl
  dossiers/u_<author>.html
  raw/u_<author>.json        # optional --keep-raw
```

## Prompt Caching -- Optimize for All Three Pipelines

Sample-size itself is deterministic (no LLM). Persona/dataset/survey synthesis is where caching wins:

- Recommended provider: `deepseek-v4-flash` via `DEEPSEEK_API_KEY` (direct api.deepseek.com) -- prompt-cache price advantage (approx 0.1x on cached tokens) + quality. Falls back to OPENROUTER then OPENAI.
- Stable template as cached prefix: put the **full template** in system (cached), corpus in user (variable). V3.3 prompt ≈ 2484 chars. V4 templates are larger (Flash ≈ 5k tokens, Thinking ≈ 13k tokens) so the split matters more. V4 Flash uses a **two-pass** structure — Pass 1 (microcard): system = codebook + card schema, user = corpus; Pass 2 (stimulus): system = codebook + instrument, user = the already-built microcard. Microcards are built once and reused across instruments. Survey: instrument (≈ 2048 tokens) in system, persona summary (≈ 1k variable) in user. First call misses, rest hit.
- Observed: r/homeschool 20 dossiers via deepseek-v4-flash -- 2nd call cache hit 2432/2433, subsequent miss 9 hit 2432 (99.6% on prefix). Survey: cache hit 1920/2033 then 1664/2054 (approx 85-94% on prefix).
- Reasoning budget: deepseek reasoning models burn approx 2000-3000 reasoning tokens before JSON. analyze.py try_llm auto-sets max_tokens=12000 for deepseek models (vs 3000 for others) and falls back to reasoning_content if content empty. Callers should NOT set max_tokens manually.
- Env: _load_env_file reads both profiles/hermozi/.env and .hermes/.env so terminal subshells see keys without export.
- Keep template byte-identical -- even whitespace busts cache. Run sequentially (concurrency 2 keeps KV warm without interleaving misses).

## Cost & Rate Guidance

- Arctic Shift: free, no key, but be polite — 1 req/sec, `limit=100` max, paginate.
- Timeouts: hermes terminal shell limit is 180s. A 20-dossier batch via deepseek (approx 25-35s per dossier, reasoning-heavy) takes approx 300s at concurrency 2 -- exceeds limit. Use checkpoint-resume (re-run same command, skips completed authors via manifest.json/responses.jsonl) or concurrency 4 or background with timeout 600.
- LLM synthesis: deepseek-v4-flash recommended (prompt-cache approx 0.1x on prefix). Approx 8-15k input tokens + approx 4k output per dossier (+ approx 2-3k reasoning). Batch 1200 users = approx 15-20M tokens. At cached pricing, prefix reuse saves approx 7-10M tokens at N=385. Use gpt-4o-mini for survey-only runs if wall time matters (10s/call vs 30s) -- keep deepseek for dossier synthesis where reasoning depth helps V3.3.
- Estimate cost before running: N * 12k * price_per_1k, subtract cached prefix (approx 2.4k * (N-1) * discount). Cosmos brief can show this dollar value via sample_size.py.
- Recommend: pilot with N=20 before scaling to N=1200 or N=385 (required at 95%/+-5% for large subs). Checkpoint via manifest.json (dataset) and responses.jsonl (survey) -- re-running resumes idempotently.

## Scripts

| Script | Purpose | Key flags |
|--------|---------|-----------|
| `scripts/pulse.py` | Fetch + synthesize + render Monocle newspaper | `--subreddit`, `--window` (7d/30d), `--limit`, `--top` (3-5), `--out` |
| `scripts/persona.py` | Fetch corpus + LLM synthesize + render Notion dossier | `--author`, `--limit` (100/500), `--model deepseek-v4-flash`, `--out`, `--no-cache` |
| `scripts/build_dataset.py` | Discover users + bulk persona + Monocle index (checkpoint: `manifest.json`, skip-on-resume) | `--subreddit`, `--users` (N), `--comments-per-user`, `--out`, `--concurrency 2`, `--model deepseek-v4-flash` |
| `scripts/synthetic_survey.py` | Simulate a 12-Q instrument (SOP v6 grounded) on a dossier population | `--personas personas.jsonl`, `--out`, `--instrument` (optional custom JSON), `--model deepseek-v4-flash`, `--concurrency 2` |
| `scripts/analyze.py` | Shared intelligence helpers + centrally-managed LLM (try_llm, prompt-cache, env) | Imported by pulse/persona/build_dataset/synthetic_survey, also CLI for debugging |
| `scripts/sample_size.py` | Sample-size calc + Cosmos brief (deterministic, thin-rate aware) | `--population` or `--subreddit`, `--confidence`, `--margin`, `--topic`, `--html-out` (Cosmos) |

All scripts:
- Write single-file HTML (offline-openable, no build step).
- Print progress to stderr, final path to stdout.
- Exit non-zero on fetch failure with actionable message.

## Verification Checklist

Pulse:
- [ ] HTML opens offline, `HERMES INTELLIGENCE · r/<sub>` (never HERMES), human title (not `Kids, Anyone & Est`), `INTELLIGENCE BRIEF` badge on `#fdfcf3`
- [ ] 7 sections: Briefing (30-sec bullets) → Activity (timeline + histogram) → What changed (7d baseline) → Themes (freq vs engagement) → Posts (intent-tagged) → Sentiment+Intent → Keywords+Method
- [ ] No `don`/`him`/`like`/`old` in themes/keywords (contraction + ARTIFACT_TOKENS filtered); bigrams like `potty training` appear as phrases
- [ ] Timeline + heatmap + quadrant render; collection window, sample size, removed count, methodology + confidence limitations visible; confidence dot matches `confidence_assessment`

Persona:
- [ ] HTML opens offline on `#f6f5f4` with white `12px` cards
- [ ] All 8 V3.3 sections populated (Engine scores + 7 layers)
- [ ] Engine signature (e.g. `C+ F~ A1+ A2~ P+`) shown with 0-5 scores
- [ ] 4-6 real quotes with source/trigger/signal
- [ ] Evidence anchors are short real phrases from corpus
- [ ] JSON rubric (`persona_stack` + `engine_metrics`) included in appendix

Dataset:
- [ ] `manifest.json` tracks total/completed/failed + thin rate, resumes on re-run
- [ ] `personas.jsonl` has one valid JSON per completed user
- [ ] `index.html` (Monocle) lists all users with aggregate Engine distribution
- [ ] No author with <20 comments included without explicit `--include-thin`

Synthetic Survey (Pipeline 3):\n- [ ] `survey-instrument.json` defines all Qs instrument-driven (no hard-coded Journey B); `responses.jsonl` has Q1..Q12 + why; `responses.csv` pivot-ready\n- [ ] `report.html` (HERMES, not MONOCLE) shows 8 sections: 01 Executive summary → 02 Methodology + warning → 03 Audience composition → 04 Concept evaluation → 05 Segment comparison (+ value ranking/funnel/barrier) → 06 Individual cards → 07 Calibration (4 prediction types + scorecard) → 08 Final 8 + Appendix; synthetic warning banner present\n- [ ] Instrument-agnostic: same template renders `r/stocks` Decision>Prediction and `r/parenting` UCC correctly; heuristic fallback shows HERMES banner, heuristic_count, and instrument-aware choices
- [ ] Checkpoint: re-running same `synthetic_survey.py` command skips completed authors via existing `responses.jsonl` (idempotent 6→13→19→20)

## Common Pitfalls

1. **FTS silently ignored** — `title`/`selftext`/`body` filters do nothing without `subreddit` or `author`. Always set one.
2. **Limit >100** — API errors. Paginate with `after = last.created_utc`.
3. **Cache poisoning** — stale 7d persona corpus hides recent style shifts. Use `--no-cache` for debate prep.
4. **Yellow sprawl (Monocle)** — using `#ffc500` outside CTA/trend/sentiment bar breaks the "one color, one button" rule. Keep everything else monochrome.
5. **White canvas (Notion)** — `#ffffff` page background instead of `#f6f5f4` makes it look like generic SaaS. Warm canvas is the signature.
6. **Bulk without pilot** — starting 1200-user run without a 20-user pilot wastes tokens if prompt needs tuning. Always pilot.
7. **Thin authors** — users with <20 comments produce hallucinated dossiers. Filter by default.
8. **Thin-rate underestimated (small subs)** — r/homeschool recent window: 35-40% thin (<20 comments). `recommend_pull` auto-uses 35% for N<500k, 25% otherwise (override via --thin-rate). Log thin rate per subreddit in `manifest.json`.
9. **Heuristic pollution** — `survey-simulation-heuristic/` aggregates look plausible but are not LLM signal. Reports now show HEURISTIC banner when `heuristic_count>0`; don't quote heuristic numbers.
10. **180s shell timeout** — 20 deepseek dossiers take ~300s at concurrency 2. Re-run same command to resume (idempotent), or use concurrency 4 / timeout 600.
11. **Timestamp confusion** — `created_utc` is seconds; `after`/`before` params accept ms or ISO. Convert with `*1000` when paginating via `after`.
12. **`source ~/.hermes/.env` breaks on macOS** — `AGENT_BROWSER_EXECUTABLE_PATH` contains an unquoted path with spaces (`/Applications/Google Chrome.app/...`). Shell `source` fails with `Chrome.app/...: No such file`. Always use `analyze.py:_load_env_file()` (line-by-line, no word-splitting) — same fix handles split-root imports (`~/.hermes/skills/` vs `~/.hermes/profiles/hermozi/skills/`).
13. **`timeout` missing on stock macOS** — `timeout 2400 python …` → `timeout: command not found` (needs `coreutils`/`gtimeout`). Drop `timeout` from wrappers; `build_dataset.py` + `synthetic_survey.py` are checkpoint-resume (`manifest.json` / `responses.jsonl` skip-on-resume) so re-running is idempotent. Also never use shell `nohup`/`&` inside `terminal(background=true)`.
14. **Which pilot to expand** — `dataset-pilot-20/` is enriched (`big_five`+`quotes`+`arguments` present) and is the correct seed for `dataset-385/`; `dataset-pilot-20-deepseek/` is thin (`engine` only) — do not seed from it. Copy `manifest.json` + `personas.jsonl` + `dossiers/u_*.html/json`, then set `target_users=385` before re-running.
15. **Artifact staleness after template revisions** — when pulse/dataset/survey templates revise, every `*.html` on disk must be re-audited case-insensitively (see `references/artifact-lifecycle.md`). Don't confuse `dataset-pilot-20-deepseek/` (thin, needs `--reindex-only`) with the canonical `dataset-pilot-20/` (enriched).
16. **Reasoning response without final JSON** — preserve the raw response as analyst notes, then run a constrained formatting pass with a larger output budget and balanced-brace parsing. Do not discard completed reasoning or pretend a partial response is structured output.
17. **Scalar rendered as a character list** — validate/coerce model field types before rendering (`str` → one-item list). Programmatic JSON validity does not catch this; visual QA and DOM list-count checks do. See `references/collective-profile.md`.

## Related

- Data source: `arctic-shift` skill (`~/.hermes/skills/research/arctic-shift/SKILL.md`) + `https://arctic-shift.photon-reddit.com`
- Design systems: `Design-md collection/DESIGN-Monocle.md`, `DESIGN-Notion.md` + `example html/hermes-cost-forecast-*.html`
- Templates: `templates/AlanDarkArts-v4-thinking.md` (individual/deep) · `templates/AlanDarkArts-v4-flash.md` (batch/compact) · legacy `UNIVERSAL COMMUNICATION-STYLE SYNTHESIS TEMPLATE (V3.3 — Seven-Signal Integrated).txt`
- References in this skill: `references/api.md`, `references/template-v33.md`, `references/mono-notion-tokens.md`, `references/pulse-analyze.md`, `references/dataset-control-panel.md`, `references/survey-agnostic.md`, `references/artifact-lifecycle.md`, `references/longitudinal-alanism.md`, `references/collective-profile.md`, `references/macos-env-quirks-2026-08-16.md`, `references/adversarial-review-v4-flash.md`
- Templates in this skill: `templates/pulse-monocle.html`, `templates/persona-notion.html`

## Artifact lifecycle (2026-08-16)

When templates revise (pulse 1.2→1.4), existing `*.html` artifacts go stale. Audit case-insensitively (`HERMES`/`MONOCLE`, `EXECUTIVE BRIEFING` lower) across `dataset-*/index.html`, `pulse*.html`, `survey-simulation*/report.html`, plus `repo/examples/`. Fix: `--reindex-only --no-archetype-llm` reindexes legacy dataset indexes (18k→140k); `render_report(..., meta)` re-renders legacy surveys without LLM; `MONOCLE→HERMES` + archived warning covers persistent 422 (homeschool 2026-08-16). Details: `references/artifact-lifecycle.md`. Hygiene: `dataset-pilot-20/` (enriched) is canonical seed, not `dataset-pilot-20-deepseek/` (thin).

## Longitudinal — single-author 10-year (2026-08-16)

`u/alanism` 2016–2026, 460 comments (12×month-bucketed `author=alanism&after=&before=`; 422 months skipped → 20/22/18 thin 2016–18, 50/year 2019–26 evenly-spaced). For deep history don't paginate by cursor — it stalls after ~200 — bucket by month/year. Per-year V3.3 LLM synthesis (prompt-cache `deepseek-v4-flash`, 37–102s each, checkpoint-resume on `dossiers/*.json`). `index.html` (68k) is HERMES longitudinal: Vega-Lite engine + Big Five lines plus inline SVG fallback, leanings verbatim, 11 year cards, 11 dossiers. Details: `references/longitudinal-alanism.md` + `/tmp/alanism_timeline.py`. Pitfall: `after=lo before=hi` (not swapped); `Path.home()` for `Documents Vibe Code` spaces inside `terminal(background=true)`.
