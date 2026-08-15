#!/usr/bin/env python3
"""
sample_size.py — Deterministic sample-size calculator + Cosmos intelligence brief.

SurveyMonkey-compatible formula:
  n0 = (z² · p · (1-p)) / e²                    infinite population
  n  = n0 / (1 + (n0-1)/N)                      finite population correction (Cochran)
  where: z = z-score for confidence, e = margin as decimal, p = proportion (0.5 = max variance), N = population

Usage:
  python sample_size.py --population 94000000 --confidence 99 --margin 3
  # → 1849

  python sample_size.py --population 500000 --confidence 95 --margin 5 --p 0.5
  # → 384 (SurveyMonkey Example 1)

  python sample_size.py --subreddit parenting --confidence 95 --margin 5 --html-out ./sample-parenting.html
  python sample_size.py --population 1200 --confidence 95 --margin 5 --topic "sleep training" --html-out ./sample-sleep.html

  # as library:
  from sample_size import calculate, recommend_pull, Z_SCORES

No dependencies beyond stdlib. HTML output is Cosmos (DESIGN-Cosmos.md) single-file.
"""
import argparse, json, math, sys, os, html as htmlmod, re
from pathlib import Path
from datetime import datetime, timezone

Z_SCORES = {
    80: 1.28,
    85: 1.44,
    90: 1.645,
    95: 1.96,
    99: 2.58,
    # allow exact floats too
    99.9: 3.291,
}

# allow string keys like "95%" as well
def fmt_conf(c):
    return f"{int(c)}" if c == int(c) else f"{c}"

def fmt_margin(m):
    return f"{int(m)}" if m == int(m) else f"{m}"

def z_for_confidence(conf) -> float:
    """Return z-score for confidence level (e.g. 95, 99, 90)."""
    try:
        c = float(str(conf).strip().rstrip("%"))
    except:
        raise ValueError(f"bad confidence {conf!r}")
    # exact match first
    if c in Z_SCORES:
        return Z_SCORES[c]
    # nearest standard
    for k in sorted(Z_SCORES):
        if abs(k - c) < 0.01:
            return Z_SCORES[k]
    # interpolate not needed — just require standard levels
    # fallback: compute via normal approximation if scipy available? Keep simple: allow any z directly
    raise ValueError(f"unsupported confidence {c} — choose from {sorted(Z_SCORES.keys())} or pass --z directly")

def sample_size_infinite(z: float, e: float, p: float = 0.5) -> float:
    """Infinite-population n0."""
    if e <= 0 or e >= 1:
        raise ValueError("margin e must be 0 < e < 1 (as decimal, e.g. 0.05 for 5%)")
    if not (0 < p < 1):
        raise ValueError("p must be 0 < p < 1")
    return (z**2 * p * (1 - p)) / (e**2)

def sample_size_finite(N: int, z: float, e: float, p: float = 0.5) -> int:
    """Finite-population corrected n, Cochran. Returns ceiling int."""
    if N is None or N <= 0:
        return math.ceil(sample_size_infinite(z, e, p))
    n0 = sample_size_infinite(z, e, p)
    n = n0 / (1 + (n0 - 1) / N)
    return math.ceil(n)

def calculate(population: int, confidence: float, margin_percent: float, p: float = 0.5, z: float = None):
    """Main entry. margin_percent like 3 means 3%. Returns dict with n, n0, z, e, N, p."""
    e = float(margin_percent) / 100.0
    if z is None:
        z = z_for_confidence(confidence)
    else:
        z = float(z)
    N = int(population) if population is not None else None
    n0 = sample_size_infinite(z, e, p)
    n = sample_size_finite(N, z, e, p) if N else math.ceil(n0)
    return {
        "population": N,
        "confidence": float(confidence),
        "z": round(z, 3),
        "margin_percent": float(margin_percent),
        "margin_decimal": e,
        "p": p,
        "n0_infinite": math.ceil(n0),
        "n": n,
        "formula": "n0=(z²·p·(1-p))/e²; n=n0/(1+(n0-1)/N)",
    }

def recommend_pull(n: int, thin_rate: float = None, concurrency_buffer: float = 0.10, population: int = None) -> dict:
    """
    Practical recommendation: how many redditors to actually attempt to pull.
    Accounts for authors with < min-comments, deleted, bots, fetch failures.
    thin_rate: fraction expected to be thin/deleted. Auto 35% for N<500k (observed r/homeschool), 15% otherwise. Override via arg.
    Returns pull_target and reasoning.
    """
    # Auto thin-rate (Issue 5): small subs have 35-40% thin in recent window
    if thin_rate is None:
        thin_rate = 0.35 if (population is not None and population < 500_000) else 0.15
    pull = math.ceil(n * (1 + thin_rate + concurrency_buffer))
    return {
        "sample_size": n,
        "recommended_pull": pull,
        "buffer": pull - n,
        "buffer_pct": round((pull - n) / n * 100, 1) if n else 0,
        "assumptions": f"thin/deleted ~{thin_rate*100:.0f}% + fetch overhead ~{concurrency_buffer*100:.0f}%",
        "range": f"{n}–{pull}",
        "pilot": max(20, math.ceil(min(n, 50))),
    }

def fetch_subreddit_population(subreddit):
    """Try to fetch subscriber count via Arctic Shift. Returns None if unavailable."""
    import urllib.request, urllib.parse, json as js
    API = "https://arctic-shift.photon-reddit.com"
    try:
        qs = urllib.parse.urlencode({"subreddit": subreddit, "meta-app": "reddit-intel-sample"})
        req = urllib.request.Request(f"{API}/api/subreddits/search?{qs}", headers={"User-Agent": "reddit-intel/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = js.loads(r.read().decode())
            rows = data.get("data", [])
            if rows:
                # Arctic Shift subreddit docs vary — try subscribers, subscriber_count, accounts_active
                row = rows[0]
                for key in ("subscribers", "subscriber_count", "subscribers_count", "accounts_active", "active_user_count"):
                    if key in row and isinstance(row[key], (int, float)) and row[key] > 100:
                        return int(row[key])
                # fallback: try 'subscribers' nested?
                return None
    except Exception as e:
        print(f"[sample] subreddit lookup failed: {e}", file=sys.stderr)
    return None

def estimate_active_population(subreddit, window_days=30):
    """Estimate active population by counting unique authors in recent comments. Rough."""
    try:
        from analyze import discover_authors
        authors = discover_authors(subreddit, target=500)
        # crude: unique authors in sample * scaling factor — not rigorous, just display
        return len(authors) * 6  # placeholder heuristic
    except:
        return None

# ── Cosmos HTML renderer ──

def render_cosmos_html(result: dict, args, population_source: str = "provided") -> str:
    esc = lambda s: htmlmod.escape(str(s), quote=False)
    now = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    N = result["population"]
    N_str = f"{N:,}" if N else "— (infinite)"
    conf = result["confidence"]
    z = result["z"]
    margin = result["margin_percent"]
    conf_s = fmt_conf(conf)
    margin_s = fmt_margin(margin)
    p = result["p"]
    n = result["n"]
    n0 = result["n0_infinite"]
    rec = recommend_pull(n, population=N)
    pull = rec["recommended_pull"]
    pilot = rec["pilot"]
    topic = getattr(args, "topic", None) or getattr(args, "topic_filter", None) or ""
    subreddit = getattr(args, "subreddit", None) or ""
    pop_label = f"r/{subreddit}" if subreddit else "target population"

    # Cosmos tokens
    styles = r"""
:root{--color-linen-canvas:#f7f5f3;--color-ink-black:#0d0d0d;--color-paper-white:#ffffff;--color-stone:#6e6a69;--color-pebble:#9a9796;
 --font-cosmosoracle:'cosmosOracle',Georgia,'Times New Roman',serif;
 --text-caption:14px;--text-body:16px;--text-heading-sm:24px;--text-heading:33px;--text-display:58px;
 --spacing-16:16px;--spacing-24:24px;--spacing-32:32px;--spacing-48:48px;
 --radius-cards:16px;--radius-buttons:16px;--page-max-width:1280px}
*{box-sizing:border-box}html{scroll-behavior:smooth}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
body{margin:0;background:var(--color-linen-canvas);color:var(--color-ink-black);font-family:Georgia,'Times New Roman',serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
.pill-nav{position:sticky;top:12px;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px auto;max-width:var(--page-max-width);background:var(--color-paper-white);border:1px solid rgba(13,13,13,.12);border-radius:9999px;padding:8px 14px;font-size:13px}
.pill-nav .l{display:flex;align-items:center;gap:8px;font-weight:500}
.pill-nav .dot{width:18px;height:18px;display:grid;place-items:center;font-size:10px}
.pill-nav .r{display:flex;align-items:center;gap:14px}
.pill-nav a{text-decoration:none;color:var(--color-stone);font-size:12px}
.btn-pill{appearance:none;border:none;background:var(--color-ink-black);color:var(--color-paper-white);font:500 13px/1 Georgia,serif;padding:10px 16px;border-radius:var(--radius-buttons);cursor:pointer}
.btn-ghost{appearance:none;background:var(--color-paper-white);color:var(--color-ink-black);border:1px solid rgba(13,13,13,.15);font:500 13px/1 Georgia,serif;padding:10px 16px;border-radius:var(--radius-buttons);cursor:pointer}
.mast{max-width:var(--page-max-width);margin:0 auto;padding:18px 16px 8px;text-align:center}
.mast h1{margin:0;font-weight:350;font-size:38px;letter-spacing:-1.5px;line-height:1}
.mast .sub{margin:6px 0 0;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--color-stone)}
.mast .kicker{display:flex;justify-content:center;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)}
.mast .kicker span+span::before{content:"·";margin-right:16px;color:var(--color-pebble)}
.wrap{max-width:var(--page-max-width);margin:0 auto;padding:0 16px}
section{padding:32px 0;border-bottom:1px solid rgba(13,13,13,.08)}
section:last-of-type{border-bottom:none}
.eyebrow{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-stone);margin:0 0 10px;font-weight:500}
h2{margin:0;font-weight:350;font-size:33px;line-height:1.1;letter-spacing:-1.32px;max-width:24ch}
h2 strong{font-weight:500}
h2 em{font-style:normal;background:linear-gradient(transparent 64%, rgba(13,13,13,.08) 64% 88%, transparent 88%)}
.deck{margin:12px 0 0;color:var(--color-stone);font-size:16px;line-height:1.5;max-width:62ch}
.deck b{color:var(--color-ink-black)}
.lede{color:var(--color-stone);font-size:15px;line-height:1.5;margin:0 0 16px;max-width:68ch}
.lede b{color:var(--color-ink-black)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:900px){.grid3{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.grid3{grid-template-columns:1fr}}
.card{background:var(--color-paper-white);border:1px solid rgba(13,13,13,.08);border-radius:var(--radius-cards);padding:16px}
.card-linen{background:var(--color-linen-canvas);border:1px solid rgba(13,13,13,.06)}
.mono{font-family:ui-monospace,monospace;font-size:12px}
.pill{display:inline-block;font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:3px 8px;border:1px solid rgba(13,13,13,.12);background:var(--color-paper-white);white-space:nowrap;border-radius:9999px}
.pill.dark{background:var(--color-ink-black);color:var(--color-paper-white);border-color:var(--color-ink-black)}
.pill.ghost{color:var(--color-stone)}
.kpi{display:grid;place-items:center;text-align:center;padding:18px}
.kpi b{font-size:34px;letter-spacing:-1.5px;line-height:1;font-weight:350}
.kpi span{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone);margin-top:6px}
.kpi p{margin:6px 0 0;font-size:11px;color:var(--color-stone);line-height:1.4}
.table-wrap{background:var(--color-paper-white);border:1px solid rgba(13,13,13,.08);border-radius:var(--radius-cards);overflow:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-stone);font-weight:500;padding:10px 12px;border-bottom:1px solid rgba(13,13,13,.08);white-space:nowrap;background:var(--color-paper-white)}
td{padding:10px 12px;border-bottom:1px solid #f0ece8;vertical-align:middle}
tr:last-child td{border-bottom:none}
.callout{border:1px solid rgba(13,13,13,.08);padding:16px;background:var(--color-paper-white);border-radius:var(--radius-cards)}
.note{margin:10px 0 0;font-size:11px;color:var(--color-stone);line-height:1.5}
.footer{padding:16px;text-align:center;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone);border-top:1px solid rgba(13,13,13,.08)}
.hero{padding:28px 0 24px;display:grid;grid-template-columns:1.3fr .85fr;gap:24px;border-bottom:1px solid rgba(13,13,13,.08)}
@media(max-width:860px){.hero{grid-template-columns:1fr}}
.big-num{font-size:52px;letter-spacing:-2.5px;line-height:1;font-weight:350}
"""
    # recommendation sentence
    # core statement: with 'x' population at 'y' confidence and 'z' margin, we think ... and we recommend abc.
    # Build two variants: statistical + operational
    stat_sentence = f"With <b>{N_str}</b> in {esc(pop_label)} at <b>{conf_s}% confidence</b> and <b>{margin_s}% margin of error</b> (p={p}, z={z}), the finite-population sample is <b>{n:,}</b> (infinite-population n₀={n0:,})."
    # operational recommendation
    topic_clause = f" on <b>{esc(topic)}</b>" if topic else ""
    op_sentence = f"We recommend pulling <b>{pull:,}</b> redditors (≈{rec['buffer_pct']}% buffer) and targeting <b>{n:,}</b> completed dossiers{topic_clause}. Start with a <b>pilot of {pilot}</b> to validate the prompt and thin-rate before scaling."
    # confidence vs margin table
    conf_rows = ""
    for c in [90, 95, 99]:
        r = calculate(N if N else 10_000_000, c, margin, p)
        conf_rows += f"<tr><td><b>{c}%</b> <span style='color:var(--color-stone)'>z={Z_SCORES[c]}</span></td><td class='mono'>{r['n']:,}</td><td class='mono' style='color:var(--color-stone)'>{r['n0_infinite']:,}</td></tr>"
    margin_rows = ""
    for m in [3, 5, 7, 10]:
        r = calculate(N if N else 10_000_000, conf, m, p)
        margin_rows += f"<tr><td><b>±{m}%</b></td><td class='mono'>{r['n']:,}</td><td class='mono' style='color:var(--color-stone)'>{r['n0_infinite']:,}</td></tr>"

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="color-scheme" content="light"/>
<title>Cosmos · Sample Size — {esc(pop_label)} · {conf:.0f}% / ±{margin_s}%</title>
<style>{styles}</style>
</head><body>
<nav class="pill-nav" aria-label="Nav"><div class="l"><span class="dot">◈</span> COSMOS <span style="color:var(--color-pebble);font-weight:400">SAMPLE SIZE</span></div><div class="r"><a href="#recommendation">Recommendation</a><a href="#formula">Formula</a><a href="#sensitivity">Sensitivity</a><button class="btn-pill" onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href)">Share ↓</button></div></nav>
<header class="mast"><h1>COSMOS · SAMPLE SIZE</h1><div class="sub">How many redditors to pull — and how sure you can be</div>
<div class="kicker"><span><b>{N_str}</b> population</span><span><b>{conf_s}%</b> confidence</span><span><b>±{margin_s}%</b> margin</span><span><b>{n:,}</b> required</span></div></header>

<main class="wrap">

<div class="hero">
  <div>
    <p class="eyebrow">Recommendation — {esc(pop_label)}</p>
    <h2>With <em>{N_str}</em> at {conf_s}% confidence, you need <em>{n:,}</em>.</h2>
    <p class="deck">{stat_sentence} We recommend <b>{pull:,}</b> pulls to net {n:,} completions.</p>
    <p class="lede" style="margin-top:10px">{op_sentence}</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <span class="pill dark">n = {n:,}</span>
      <span class="pill">pull target {pull:,}</span>
      <span class="pill ghost">pilot {pilot}</span>
      <span class="pill ghost">p={p} · z={z}</span>
    </div>
  </div>
  <div class="card" style="display:grid;place-items:center;text-align:center">
    <div>
      <div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--color-stone);font-weight:500">Required completes</div>
      <div class="big-num" style="margin-top:6px">{n:,}</div>
      <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone);margin-top:4px">of {N_str} · {conf_s}% / ±{margin_s}%</div>
      <div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:10px;text-align:left">
        <div style="border-top:1px solid rgba(13,13,13,.08);padding-top:10px"><b style="font-size:16px">{pull:,}</b><div style="font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)">Pull target</div></div>
        <div style="border-top:1px solid rgba(13,13,13,.08);padding-top:10px"><b style="font-size:16px">{pilot}</b><div style="font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)">Pilot first</div></div>
      </div>
      <p class="note">Finite-population correction applied. Infinite n₀={n0:,} → corrected n={n:,}.</p>
    </div>
  </div>
</div>

<section id="recommendation">
  <div class="eyebrow">01 — WHAT WE THINK & WHAT WE RECOMMEND</div>
  <div class="grid2" style="align-items:start">
    <div class="card">
      <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">With x at y confidence and z margin, we think…</div>
      <p style="margin:10px 0 0;font-size:14px;line-height:1.6">{stat_sentence} At this sample, any proportion you measure{topic_clause} will lie within ±{margin_s}% of the true {esc(pop_label)} value in {conf_s}% of repeated samples (95% ≈ 1.96σ, 99% ≈ 2.58σ).</p>
      <p style="margin:8px 0 0;font-size:13px;line-height:1.6;color:var(--color-stone)">Sampling fraction: <b style="color:var(--color-ink-black)">{(n/N*100) if N else 0:.2f}%</b> of population. Below ~5%, finite correction barely moves n₀ — above that, it saves meaningful pulls.</p>
      <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap"><span class="pill ghost">N={N_str}</span><span class="pill ghost">n₀={n0:,}</span><span class="pill dark">n={n:,}</span><span class="pill">source: {esc(population_source)}</span></div>
    </div>
    <div class="card card-linen" style="border-left:3px solid var(--color-ink-black)">
      <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">We recommend…</div>
      <p style="margin:8px 0 0;font-size:14px;line-height:1.6"><b>Pull {pull:,} → target {n:,} completions.</b> Buffer covers thin/deleted/bot authors (~15%) + fetch failures. Run a <b>pilot of {pilot}</b> first to measure thin-rate, then scale with <code style="background:#fff;padding:2px 6px;border-radius:6px;border:1px solid rgba(13,13,13,.08)">build_dataset.py --subreddit {esc(subreddit) if subreddit else 'X'} --users {n} --comments-per-user 100 --out ./data/{esc(subreddit) if subreddit else 'dataset'}/</code></p>
      <ul style="margin:10px 0 0;padding:0 0 0 16px;font-size:13px;line-height:1.7">
        <li>Heuristic mode (no LLM) for the pilot — validate pipeline cheap.</li>
        <li>LLM mode (Notion dossiers) for the full sample — {n:,} dossiers.</li>
        <li>Checkpoint via <code>manifest.json</code> — resume-safe.</li>
      </ul>
      {f'<p class="note">Topic filter: <b>{esc(topic)}</b> — random sample among authors who matched the filter, not the whole subreddit. Population for this slice is smaller than r/{esc(subreddit)}.</p>' if topic else ''}
    </div>
  </div>
  <div class="card" style="margin-top:16px">
    <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">How to use this sample</div>
    <div class="grid3" style="margin-top:10px">
      <div><b style="font-size:14px">Random quotes{topic_clause}</b><p style="margin:4px 0 0;font-size:13px;line-height:1.5;color:var(--color-stone)">From the {n:,} sample, draw a stratified random subset and surface verbatim quotes via <code>analyze.py</code> / <code>search_arctic.py --body "{esc(topic) if topic else '...'}"</code></p></div>
      <div><b style="font-size:14px">Synthetic population</b><p style="margin:4px 0 0;font-size:13px;line-height:1.5;color:var(--color-stone)">Feed <code>personas.jsonl</code> (V3.3 rubrics) into your simulator to generate synthetic reactions at scale — same Engine distribution as the real sample.</p></div>
      <div><b style="font-size:14px">Debate / messaging</b><p style="margin:4px 0 0;font-size:13px;line-height:1.5;color:var(--color-stone)">Pick high-leverage personas (e.g. C+ F+ or C- F-) from dossiers to pressure-test copy before shipping.</p></div>
    </div>
  </div>
</section>

<section id="formula">
  <div class="eyebrow">02 — FORMULA <em>· SurveyMonkey-compatible</em></div>
  <div class="grid2">
    <div class="card">
      <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">Cochran with finite correction</div>
      <div class="mono" style="margin-top:8px;background:var(--color-linen-canvas);padding:12px;border-radius:12px;border:1px solid rgba(13,13,13,.06);line-height:1.7">
        n₀ = (z² · p · (1-p)) / e²<br/>
        n &nbsp;= n₀ / (1 + (n₀-1)/N)<br/><br/>
        z = {z} ({conf_s}% confidence)<br/>
        e = {margin/100:.3f} (±{margin_s}%) · p = {p} (conservative)
      </div>
      <p class="note">Same inputs as SurveyMonkey: 94M at 99% / ±3% → 1,849. This implementation matches. p=0.5 is max-variance (safest when you don't know the split). Use p≠0.5 only when you have a prior.</p>
    </div>
    <div class="card">
      <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">z-score table</div>
      <div class="table-wrap" style="margin-top:8px"><table><thead><tr><th>Confidence</th><th>z-score</th></tr></thead><tbody>
        <tr><td>80%</td><td class="mono">1.28</td></tr>
        <tr><td>85%</td><td class="mono">1.44</td></tr>
        <tr><td>90%</td><td class="mono">1.645</td></tr>
        <tr style="background:var(--color-linen-canvas)"><td><b>95%</b></td><td class="mono"><b>1.96</b></td></tr>
        <tr style="background:var(--color-linen-canvas)"><td><b>99%</b></td><td class="mono"><b>2.576</b></td></tr>
      </tbody></table></div>
      <p class="note">Computed with N={N_str}. Change N, confidence, or margin and n recomputes deterministically — no LLM, fully reproducible.</p>
    </div>
  </div>
</section>

<section id="sensitivity">
  <div class="eyebrow">03 — SENSITIVITY <em>· what moves the number</em></div>
  <div class="grid2">
    <div class="card">
      <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">At ±{margin_s}% margin — confidence changes n</div>
      <div class="table-wrap" style="margin-top:8px"><table><thead><tr><th>Confidence</th><th>n (finite)</th><th style="color:var(--color-pebble)">n₀ infinite</th></tr></thead><tbody>{conf_rows}</tbody></table></div>
      <p class="note">99% costs ~1.7× the pulls of 95% at the same margin.</p>
    </div>
    <div class="card">
      <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">At {conf_s}% confidence — margin changes n</div>
      <div class="table-wrap" style="margin-top:8px"><table><thead><tr><th>Margin</th><th>n (finite)</th><th style="color:var(--color-pebble)">n₀ infinite</th></tr></thead><tbody>{margin_rows}</tbody></table></div>
      <p class="note">Halving margin roughly quadruples n — budget accordingly.</p>
    </div>
  </div>
  <div class="card card-linen" style="margin-top:16px">
    <div style="font:500 11px/1 Georgia,serif;letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone)">Prompt-cache note (all three pipelines)</div>
    <p style="margin:8px 0 0;font-size:13px;line-height:1.6">Sample-size itself is deterministic python — no prompt to cache. But the downstream synthesis that <em>uses</em> this n benefits: keep the V3.3 template as a stable <b>system prefix</b> and pass only the per-author corpus as the variable suffix. With prompt caching (OpenAI/Anthropic), the template is cached once and each of the {n:,} dossiers pays only for the corpus + completion.</p>
    <ul style="margin:8px 0 0;padding:0 0 0 16px;font-size:13px;line-height:1.6;color:var(--color-stone)">
      <li><b>Pulse (Monocle):</b> theme/sentiment prompt prefix is stable — cache it across re-runs of the same subreddit window.</li>
      <li><b>Persona (Notion):</b> put the full V3.3 template in <code>system</code> / cached prefix, corpus in <code>user</code> — hit rate ≈ dossiers-1 / dossiers.</li>
      <li><b>Dataset bulk:</b> same as persona × N — use <code>--model gpt-4o-mini</code> and sequential batching to keep cache hot.</li>
    </ul>
  </div>
</section>

<section>
  <div class="eyebrow">04 — NEXT STEPS</div>
  <div class="grid3">
    <div class="card"><b style="font-size:14px">1 · Pilot</b><p style="margin:6px 0 0;font-size:13px;line-height:1.5;color:var(--color-stone)">Pull {pilot} authors, build heuristic dossiers, measure thin-rate and avg cost/dossier.</p><code class="mono" style="display:block;margin-top:8px;background:var(--color-linen-canvas);padding:8px;border-radius:8px">build_dataset.py --subreddit {esc(subreddit) if subreddit else 'X'} --users {pilot} --no-llm --out ./data/{esc(subreddit) if subreddit else 'pilot'}-pilot/</code></div>
    <div class="card"><b style="font-size:14px">2 · Scale to n</b><p style="margin:6px 0 0;font-size:13px;line-height:1.5;color:var(--color-stone)">Re-run with LLM to {n:,} (pull {pull:,}). Resume-safe via manifest.json.</p><code class="mono" style="display:block;margin-top:8px;background:var(--color-linen-canvas);padding:8px;border-radius:8px">build_dataset.py --subreddit {esc(subreddit) if subreddit else 'X'} --users {n} --out ./data/{esc(subreddit) if subreddit else 'dataset'}/</code></div>
    <div class="card" style="background:var(--color-ink-black);color:var(--color-paper-white);border-color:var(--color-ink-black)"><b style="font-size:14px;color:var(--color-paper-white)">3 · Simulate</b><p style="margin:6px 0 0;font-size:13px;line-height:1.5;color:#cbd5ff">Use <code style="background:rgba(255,255,255,.12);padding:2px 6px;border-radius:6px">personas.jsonl</code> to synthesize reactions to posts/products before shipping.</p></div>
  </div>
</section>

</main>
<div class="footer">COSMOS · Sample Size Intelligence · {esc(pop_label)} · N={N_str} · {conf_s}% / ±{margin_s}% · n={n:,} · pull {pull:,} · {now} · Cosmos tokens #f7f5f3 / #0d0d0d / 16px · Single-file HTML — opens offline</div>
</body></html>"""
    return html

def main():
    ap = argparse.ArgumentParser(description="Sample size calculator (SurveyMonkey-compatible) + Cosmos brief")
    ap.add_argument("--population", type=int, default=None, help="population size N (e.g. 94000000)")
    ap.add_argument("--subreddit", type=str, default=None, help="fetch N from r/<subreddit> subscriber count (overrides --population if found)")
    ap.add_argument("--confidence", type=float, default=95, help="confidence level percent (80,85,90,95,99)")
    ap.add_argument("--margin", type=float, default=5, help="margin of error percent (e.g. 3 for +-3pct)")
    ap.add_argument("--p", type=float, default=0.5, help="population proportion (0.5 = conservative max-variance)")
    ap.add_argument("--z", type=float, default=None, help="override z-score directly (skips confidence lookup)")
    ap.add_argument("--topic", type=str, default=None, help="topic label for report context (e.g. 'sleep training')")
    ap.add_argument("--html-out", type=str, default=None, help="write Cosmos HTML report to this path")
    ap.add_argument("--json-out", type=str, default=None, help="write JSON result to this path")
    ap.add_argument("--quiet", action="store_true", help="only print n")
    args = ap.parse_args()

    # resolve population
    population = args.population
    source = "provided"
    if args.subreddit:
        fetched = fetch_subreddit_population(args.subreddit)
        if fetched:
            population = fetched
            source = f"r/{args.subreddit} subscribers via Arctic Shift"
            print(f"[sample] r/{args.subreddit} population ≈ {fetched:,} (subscribers)", file=sys.stderr)
        elif population is None:
            print(f"[sample] could not fetch population for r/{args.subreddit} — pass --population explicitly", file=sys.stderr)
            # still continue if population was provided, else error
            if population is None:
                # try active estimate
                print(f"[sample] tip: search_arctic.py subreddit --name {args.subreddit}", file=sys.stderr)
                sys.exit(2)

    if population is None:
        ap.error("--population or --subreddit (with fetchable count) is required")

    result = calculate(population, args.confidence, args.margin, p=args.p, z=args.z)
    rec = recommend_pull(result["n"], population=result.get("population") or result.get("N"))

    if args.quiet:
        print(result["n"])
    else:
        # human table
        print(f"Population: {result['population']:,}", file=sys.stderr)
        print(f"Confidence: {fmt_conf(result['confidence'])}% (z={result['z']})", file=sys.stderr)
        print(f"Margin: ±{fmt_margin(result['margin_percent'])}%  p={result['p']}", file=sys.stderr)
        print(f"n₀ (infinite): {result['n0_infinite']:,}", file=sys.stderr)
        print(f"n (finite): {result['n']:,}", file=sys.stderr)
        print(f"Recommended pull: {rec['recommended_pull']:,}  (buffer {rec['buffer']:,} / {rec['buffer_pct']}%)  pilot {rec['pilot']}", file=sys.stderr)
        print(f"Formula: {result['formula']}", file=sys.stderr)
        # stdout: just n (for scripting) unless html/json requested
        if not args.html_out and not args.json_out:
            print(result["n"])

    # html report
    if args.html_out:
        html = render_cosmos_html(result, args, population_source=source)
        out = Path(args.html_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"[sample] Cosmos report → {out} ({len(html):,} bytes)", file=sys.stderr)
        if args.quiet:
            print(str(out))
        else:
            print(str(out), file=sys.stderr)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {**result, "recommendation": rec, "population_source": source, "topic": args.topic, "subreddit": args.subreddit}
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[sample] JSON → {out}", file=sys.stderr)

if __name__ == "__main__":
    main()
