# Redditor Synthesizer — Product Documentation & Playbook

**Version:** 1.0 · **Status:** Production-ready v1
**One-liner:** Turn any online community into a research panel — read what its members actually wrote, understand who they are, and ask them anything.

---

## Part 1 — The Problem

Product teams, marketers, and researchers share the same expensive bottleneck: **finding out what a group of people actually thinks.**

The classic options all hurt:

| Traditional method | Cost | Speed | The flaw |
|---|---|---|---|
| Survey panels | $2,000–$10,000+ | 2–6 weeks | People answer *what they think you want to hear* |
| Focus groups | $5,000–$15,000+ | 3–8 weeks | 8 people ≠ a market; groupthink contaminates |
| Social listening dashboards | $1,000–$30,000/yr | Realtime volume | Tells you *what* is discussed — never *who* is discussing or *how they think* |
| "Just talk to customers" | Free | Fast | Anecdotes, not evidence; survivorship bias |

Meanwhile, **the people you want to understand are already writing their unfiltered opinions** — every day, in public, on Reddit. Not what they'd say in a survey (guarded, polite, aspirational), but how they actually talk: their complaints, their values, their trade-offs, their vocabulary, their hot buttons.

**The problem isn't that the data doesn't exist. It's that nobody has a way to turn raw public writing into a usable, statistical research panel.**

---

## Part 2 — The Solution

**Redditor Synthesizer reads a community's public archive, builds detailed profiles of its most active members, and then lets you run surveys on that population as a simulation — fast, cheap, and grounded in real evidence.**

Four capabilities, one data backbone:

| # | Capability | What you get | Think of it as |
|---|---|---|---|
| 1 | **Pulse** | A one-page "newspaper" of the community: hot topics, mood, what changed this week | Community weather report |
| 2 | **Sample Size** | A deterministic answer: *how many people do I need to study for trustworthy results?* | Statistician on demand |
| 3 | **Personas** | Detailed profiles of 20–400+ community members — their communication style, values, Big Five traits, evidence anchors | A focus group you can keep |
| 4 | **Synthetic Surveys** | Simulated answers to *your* survey questions, from each persona's perspective | A test market before you build |

All four run on the same local files. Everything is a single HTML report you open in a browser — no database, no dashboard, no vendor lock-in.

---

## Part 3 — Value Proposition

### For the price of a coffee, get what used to cost a research firm

| Dimension | Traditional | Redditor Synthesizer |
|---|---|---|
| **Speed** | Weeks | **Hours** (pulse in minutes, full study in a day) |
| **Cost** | $2,000–$30,000 | **~$1–$20 of AI tokens** (free heuristic mode without a key) |
| **Scale** | 8–50 respondents | **385-person simulated panel** (±5% at 95% confidence) |
| **Grounding** | Self-reported intentions | **Real public writing** — every profile anchored in actual quotes |
| **Reusability** | Survey ends, panel disappears | **Personas persist** — run unlimited survey rounds on the same population |
| **Privacy** | Respondent data held by vendors | **Public archive + local processing** — no new data collected, nothing uploaded |
| **Honesty** | Numbers look clean | **Built-in warnings** — simulations labeled, heuristics flagged, confidence stated |

### The 30-second pitch

> "Tell me what a community is talking about, who the people are, and what they'd say about your idea — in hours, for pocket change, with the receipts to prove it."

---

## Part 4 — Core Concepts

Understanding five ideas unlocks the whole tool:

**1. The Archive (raw material).** Redditor Synthesizer reads the Arctic Shift archive — a public, searchable copy of Reddit history. No scraping, no API keys, no ToS risk. The archive is the raw ore.

**2. The Persona (the unit of research).** Each persona is a synthesized profile of one real community member, built from ~30 of their actual comments: their communication engine (directness, warmth, evidence-use), Big Five personality, signature phrases, and worldview. Every claim is grounded in quotes — it's a *evidence-anchored profile*, not a vibe.

**3. The Corpus (your panel).** A corpus is 20–400+ personas from one community. Built once, reusable forever. This is the asset.

**4. The Instrument (your questions).** Any survey question set: 2 questions or 12, Likert scales, NPS, single-choice, open text. Written in a simple JSON file.

**5. The Simulation (the answer).** Each persona "answers" your instrument as themselves — drawing on their engine, values, and quotes. The aggregate is a simulated distribution with honest margins and explicit "not fielded" labeling.

---

## Part 5 — Use Cases

### A. Product validation before you build
You have an idea. Instead of asking your friends, ask 385 simulated members of the target community what they think — and **why**. The open-text answers tell you the objections before you spend a dollar.

### B. Positioning & messaging testing
Three ways to describe your product? Run a head-to-head survey (like our positioning instrument): which line wins, which value pillar matters, which offer they'd buy today. **The golden rule: people's stated preferences are nice, but what they'd actually buy is the truth.**

### C. Market & demand sensing
What is a community complaining about? What do they wish existed? Pulse gives you the demand signals; personas tell you who feels them most.

### D. Investor & stakeholder evidence
Walk in with a report that says: *"n=385 simulated parents, NPS −52.6 against the status quo, 90% prefer a fast diagnosis offer, and here are their exact words."* That's a credibility asset.

### E. Community intelligence for growth
Launching into a subreddit? Know its culture first: the themes, the tone, the intent (advice-seeking vs venting vs safety), the people who shape it.

### F. Academic / research rehearsal
Test hypotheses and instruments on a synthetic population before fielding a real study — cheap pilot, calibrated expectations.

---

## Part 6 — The Four Pipelines (Instruction Manual)

### Pipeline 1: Pulse — what's happening (minutes)

```bash
python reddit-intel/scripts/pulse.py \
  --subreddit stocks --limit 30 --top 5 \
  --out pulse-stocks.html
```

Opens as a one-page intelligence brief: top posts, themes (frequency vs engagement), sentiment, intent, and "what changed this week." **Use it when you need orientation fast.**

### Pipeline 2: Sample Size — how many people (seconds)

```bash
python reddit-intel/scripts/sample_size.py \
  --subreddit stocks --confidence 95 --margin 5 \
  --html-out sample-size-stocks.html
```

A deterministic calculator with a plain-English brief: *"With N population at 95% / ±5%, we think X and we recommend pull + pilot."* **Use it before every study to size the panel.**

### Pipeline 3: Personas — who the people are (hours)

```bash
python reddit-intel/scripts/build_dataset.py \
  --subreddit stocks --users 20 --comments-per-user 30 \
  --out dataset-stocks --model deepseek-v4-flash --concurrency 2
```

Builds N persona dossiers + a control-panel index + `personas.jsonl` (the reusable corpus). **Use it once per community; the corpus is your asset.**

### Pipeline 4: Synthetic Survey — what they'd say (30 min to 2.5 hrs)

```bash
python reddit-intel/scripts/synthetic_survey.py \
  --personas dataset-stocks/personas.jsonl \
  --out survey-stocks --model deepseek-v4-flash --concurrency 2
```

Simulates your instrument on every persona, checkpointed (resume-safe), outputs a report + aggregates. **Use it every time you have a new question.**

### Bonus: Rounds of surveys — keep asking

Once a corpus exists, run unlimited instruments against it (positioning, pricing, feature preference) via `ai_use_survey.py` — no new fetching, each round ~30 min. **This is where the tool compounds: one corpus, infinite questions.**

---

## Part 7 — The Playbook (step by step)

### Level 1: Community orientation (30 minutes)

1. Run **Pulse** on your target subreddit → read the themes & mood.
2. Run **Sample Size** → know the N you'd need.
3. Read the methodology note. Done.

**Goal:** know what the community cares about before you say a word.

### Level 2: First research panel (half a day)

1. **Pulse** the subreddit.
2. **Build personas** — start with 20 (`--users 20`) as a pilot.
3. Write a simple 2–5 question instrument.
4. **Pilot the survey** on a random 20 rich personas first (~2 min).
   - *Why:* catches instrument design flaws for ~5% of full-run cost.
   - *Warning:* if a pilot column hits 100%, that's instrument artifact, not market truth.
5. If direction looks sensible, scale: build 385 personas, run the full survey.

**Goal:** a credible first read with margins you can quote.

### Level 3: Full study with narrative report (1–2 days)

1. Build the full corpus (385 = ±5% @ 95% for large communities).
2. Run your core instrument (12-Q usefulness, positioning, pricing...).
3. Read the aggregates: which pillar wins, which offer converts, what's the NPS.
4. Wrap it in a narrative report (editorial voice + design system) for stakeholders.
5. Pair with the Hormozi reading: **the offer they'd buy today beats what they say they like.**

**Goal:** a decision-grade deliverable with receipts.

### Level 4: Iterative product intelligence (ongoing)

1. Keep the corpus. Each new question = a new round (30 min).
2. Track signals across rounds: did repositioning move the NPS? Which blocker faded?
3. When the product ships, field a small real survey to calibrate the simulation.

**Goal:** research that compounds instead of restarting.

---

## Part 8 — Reading Results Without Fooling Yourself

These rules are baked into the workflow for a reason — we've been burned by each:

1. **Synthetic ≠ fielded.** Simulated answers are a well-informed rehearsal, not real customers. The report says so; you should too.
2. **Direction over spread at pilot scale.** A 20-person pilot tells you *which way* the wind blows. Only quote percentages at full n.
3. **100% columns are red flags, not wins.** When every persona picks the same option, the question design is too kind — it dissolved the top fear. Force trade-offs if spread matters.
4. **"Why" matters more than "what".** The one-line justifications are where the actual insight lives.
5. **Watch the buy-today question, not the like-it question.** Stated preference is cheap; revealed intent is the signal.
6. **Check the heuristic count.** If the AI key is missing, you get lexicon-based guesses, not synthesis. Verify `heuristic_count: 0` before quoting.

---

## Part 9 — Honest Limitations

- **Reddit is not the whole market.** The tool studies one community; generalize only with care.
- **Language ≈ attitude > behavior.** What people say they'd do is not what they do. The tool models the former.
- **Guardrails of the base models apply.** You can't hand the personas to a generic AI chat and ask for segmentation (NotebookLM refuses; see learnings). The survey pipeline does the synthesis with full control instead.
- **Archive coverage varies.** Very new or very small subreddits may have thin data; the sample-size pipeline accounts for this automatically.

---

## Part 10 — Proof: What We've Learned From Real Runs

| Study | What we ran | What it told us |
|---|---|---|
| r/parenting (2026-08) | 385 personas, 12-Q UCC Hermes survey | File-first ownership is the wedge (6.01/7, 81% top-2-box); setup friction is the killer (87% blocker); NPS −52.6 → the market wants a free 20-min test drive, not a platform pitch |
| r/parenting positioning pilot (2026-08) | 7-Q instrument, n=20 | "The 20-Minute Answer" beats "Family Fortress" and "Concierge" 90/5/0; proof (65%) matters more than speed (30%) — the direction became the go-to-market |
| r/stocks (earlier) | 20 personas, evidence-stack survey | Evidence framing scored 6.7/7, 100% top-2-box — a strong signal for a data-first product |
| r/parenting AI-use (2026-08) | 2-Q survey, n=383 | 90% of parents already use AI themselves; 86.5% are conditional about kids' AI — the self/kid gap is the product opening |

Each run produced a shareable HTML report + the raw data behind it. Nothing is hidden in a database.

---

## Part 11 — Getting Started (60 seconds)

```bash
# 1. Get the code
git clone https://github.com/alanism/redditor_synthesizer.git
cd redditor_synthesizer

# 2. (Recommended) add an AI key — makes reports much smarter
export DEEPSEEK_API_KEY=your-key-here

# 3. Run your first community report (swap "stocks" for any subreddit)
python reddit-intel/scripts/pulse.py --subreddit stocks --limit 30 --top 5 --out pulse.html

# 4. Open pulse.html in any browser. That's it.
```

Requirements: Python 3.9+ (no extra packages). Reports are single-file HTML — open offline, share freely.

---

## Part 12 — Roadmap Ideas

- **Multi-community notebooks:** query several subreddits' corpora together (cross-community QA).
- **Fielded calibration kit:** a guided path to run a small real survey and measure simulation-vs-reality drift.
- **Templates library:** drop-in instruments (positioning, pricing, NPS, feature-preference) for common jobs.
- **Scheduled intelligence:** cron-driven weekly pulses for communities you watch.

---

*Redditor Synthesizer — read what they wrote, know who they are, ask them anything.*
