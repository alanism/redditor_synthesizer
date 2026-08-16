# Redditor Synthesizer

**Understand any online community by reading what its members actually say.**

This tool takes a Reddit community (like r/parenting or r/stocks), reads thousands
of real comments, and turns them into clear, easy-to-read reports you can open in
any web browser. It answers questions like:

- *What is everyone talking about right now?*
- *Who are the people here, and how do they think?*
- *If we showed them our product idea, what would they say?*

You don't need to be a programmer to read the results — every report is a single
HTML file that opens like a webpage, on any computer, with no internet required.

---

## What it does (in plain English)

| You ask | What it gives you | Think of it as |
|---------|-------------------|----------------|
| **"What's happening in this community?"** | A one-page newspaper: the hot topics, the mood, what changed this week | A community weather report |
| **"Who are the people here?"** | Detailed profiles of the most active members — their style, values, hot buttons, and how they talk | A focus group with 20–400 people |
| **"How big a sample do I need?"** | A simple math answer: how many people to study so your results are trustworthy | A sample-size calculator |
| **"What would they think of my idea?"** | Simulated answers to YOUR survey questions, from the perspective of each community member | A test market before you build anything |

The reports are **simulations**, not real surveys — they're the tool's best guess
at how a community would react, based on what those people have actually written.
Think of them as a well-informed rehearsal before you spend real money on the
real thing.

---

## What you get

Everything the tool produces is a simple file:

- **Reports** — `.html` files. Open them in any browser. That's it.
- **Data** — small `.json` files with the raw numbers, if you want to dig deeper
  or put them in a spreadsheet.

No databases, no servers, no apps to install. Just files.

---

## Quick start

### Step 1: Get the code

```bash
git clone https://github.com/alanism/redditor_synthesizer.git
cd redditor_synthesizer
```

### Step 2: (Recommended) Add an AI key

The tool works fine without this, but the reports get much smarter with an AI
model doing the reading. The easiest option is a DeepSeek key (fast and cheap):

```bash
export DEEPSEEK_API_KEY=your-key-here
```

### Step 3: Run your first community report

Let's look at the stocks community as an example. Pick any subreddit you like —
just swap `stocks` for your community's name.

```bash
# 1. What's happening in r/stocks right now?
python reddit-intel/scripts/pulse.py \
  --subreddit stocks --limit 30 --top 5 \
  --out pulse-stocks.html
# → open pulse-stocks.html — a one-page "newspaper" of the community

# 2. How many people should we study for trustworthy results?
python reddit-intel/scripts/sample_size.py \
  --subreddit stocks --confidence 95 --margin 5 \
  --html-out sample-size-stocks.html
# → open sample-size-stocks.html — it tells you exactly how many to use

# 3. Build profiles of 20 of the most active members
python reddit-intel/scripts/build_dataset.py \
  --subreddit stocks --users 20 --comments-per-user 30 \
  --out dataset-stocks --model deepseek-v4-flash --concurrency 2
# → dataset-stocks/index.html — a gallery of who these people are

# 4. Ask them about your product idea (a simulated survey)
python reddit-intel/scripts/synthetic_survey.py \
  --personas dataset-stocks/personas.jsonl \
  --out survey-stocks --model deepseek-v4-flash --concurrency 2
# → survey-stocks/report.html — how this community would react to your idea
```

That's the whole flow. Four commands, four reports, all openable in a browser.

---

## Asking your own questions (rounds of surveys)

Once you've built a set of community profiles, you can ask them *anything* —
and keep asking. Each new question set is a "round," and it reuses the same
profiles, so it's fast and cheap.

Here's how to test, say, three different ways of describing your product to see
which one people like best:

```bash
# Step A: Write your questions in a simple JSON file (see examples/positioning-instrument.json)
# Step B: Quick test on a small sample first (~2 minutes)
python reddit-intel/scripts/ai_use_survey.py \
  --personas dataset-stocks/personas-20-random.jsonl \
  --instrument examples/positioning-instrument.json \
  --out survey-test-20 --model deepseek-v4-flash --concurrency 3

# Step C: If the small test looks sensible, run the full community (~30 minutes)
python reddit-intel/scripts/ai_use_survey.py \
  --personas dataset-stocks/personas-30.jsonl \
  --instrument examples/positioning-instrument.json \
  --out survey-test-full --model deepseek-v4-flash --concurrency 3
```

**The golden rule for reading the answers:** people's stated opinions are nice,
but what they'd actually *buy* is the truth. Pay most attention to the question
that asks which offer they'd take today, not the one that asks what sounds nice.

---

## Tips for good results

- **Use at least 30 comments per person.** More writing = more accurate profiles.
- **Skip the quiet people.** Community members who've only written a few comments
  don't give reliable profiles — the tool filters these out by default.
- **Test small before you go big.** Always run a 20-person sample before a
  400-person run. It takes two minutes and catches mistakes early.
- **Treat the results as rehearsal, not prophecy.** Simulated answers are a great
  guide, but real customers are the final word.

---

## Under the hood (for the curious)

- No installation needed beyond Python — the scripts use only standard tools.
- Profiles are built from each person's real comments, stored locally on your
  machine. Nothing is uploaded.
- The AI model reads the comments and summarizes the person's style, values, and
  likely reactions. Every claim is grounded in actual quotes.
- Reports are styled like a quality newspaper or a clean magazine — designed to
  be read by people, not parsed by machines.
- The original SvelteKit web app (an archived-Reddit search tool) ships alongside
  these scripts, unchanged. `npm install && npm run dev` launches it if you want
  the visual explorer.

---

## Credits & notes

- This is a fork of [ArthurHeitmann/arctic_shift_ui](https://github.com/ArthurHeitmann/arctic_shift_ui),
  which searches an archived copy of Reddit. We use that archive as the raw
  material for the profiles and reports.
- Archived data; removal requests: https://github.com/ArthurHeitmann/arctic_shift#contact--removal-requests
- Sample reports from real runs live in `examples/`.
