#!/usr/bin/env python3
"""AI-use survey on r/parenting personas — 2 questions, 5 options each, mono report.

Simulates how each persona (from dataset-385/personas-30.jsonl + dossier sidecars)
would answer:
  Q1 — Parents using AI themselves
  Q2 — Their kids using AI
Returns % per option per question, plus cross-tab, segment split, voice cards,
and a DESIGN-mono.md single-file report.

Usage:
  python ai_use_survey.py \
    --personas "<dataset>/dataset-385/personas-30.jsonl" \
    --out "<dataset>/survey-ai-use" \
    --model deepseek-v4-flash --concurrency 3 [--limit N for smoke tests]
Resume-safe: skips authors already in responses.jsonl.
"""
import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import try_llm, _load_env_file
from synthetic_survey import persona_summary_for_survey, _derive_segments  # noqa: E402

# ── Instrument — 2 questions, 5 options each ────────────────────────────────
INSTRUMENT = {
    "title": "Parents on AI — using it themselves, and letting their kids use it",
    "intro": (
        "Simulated survey on r/parenting's active commenters. Q1 asks how parents feel "
        "about using AI themselves (planning, organizing, research, work, household admin). "
        "Q2 asks how they feel about their kids using AI (homework, learning, creativity, play). "
        "Each question has 5 response options; results are % share of simulated respondents. "
        "Responses are simulated from each redditor's V4-Flash dossier (engine, Big Five, "
        "quotes, arguments) — language/attitude signal, not fielded population estimates."
    ),
    "questions": [
        {
            "id": "Q1",
            "type": "single_choice",
            "prompt": "How do you feel about using AI yourself, as a parent — for planning, organizing, research, work, or household admin? Pick the one closest to your stance.",
            "options": [
                "I already use it regularly and find it genuinely helpful",
                "I use it occasionally for specific tasks",
                "I'm open to it but haven't really used it yet",
                "I'm skeptical — I don't trust it enough",
                "I avoid it — it's not for me",
            ],
        },
        {
            "id": "Q2",
            "type": "single_choice",
            "prompt": "How do you feel about your kids using AI — for homework, learning, creativity, or play?",
            "options": [
                "Great — it's a tool they need to learn to use well",
                "Mostly fine, with supervision and limits",
                "Mixed — depends on age, purpose, and guardrails",
                "Worried — risks outweigh benefits right now",
                "Against it — kids shouldn't use AI",
            ],
        },
    ],
}

SYSTEM_PROMPT = """You are a survey simulator. Given a Reddit persona's communication style and worldview (engine, Big Five, anchors), simulate how THEY would answer the 2-question survey in SURVEY INSTRUMENT.

Rules:
- Stay in character. Use the persona's directness, warmth, skepticism, and vocabulary.
- single_choice: return exactly one option string verbatim from that question's options — no paraphrasing, no editing.
- Every answer needs a one-line "why" (≤120 chars) grounded in the persona's evidence (engine scores, anchors, quotes, Big Five).
- Return ONLY a single JSON object — no prose outside JSON.

SURVEY INSTRUMENT:
{instrument_json}

Return shape:
{{
  "Q1": {{"choice": "…verbatim option…", "why": "…≤120 chars…"}},
  "Q2": {{"choice": "…verbatim option…", "why": "…≤120 chars…"}}
}}"""

SYNTHETIC_WARNING = (
    "Synthetic responses are simulations generated from Reddit comment dossiers — not "
    "population estimates and not fielded survey data. Use for hypothesis generation, "
    "messaging tests, and segment discovery. Language ≈ attitude > behavior."
)


def simulate_one(rubric: dict, model: str) -> dict:
    system = SYSTEM_PROMPT.format(instrument_json=json.dumps(INSTRUMENT, ensure_ascii=False, indent=2))
    user = persona_summary_for_survey(rubric) + "\n\nTASK: Simulate this persona's answers to Q1 and Q2. Return ONLY the JSON object."
    raw = try_llm(user, model=model, system_prompt=system)
    if not raw:
        return {"_error": "llm returned empty"}
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"_error": f"no JSON in raw: {raw[:300]}", "_raw": raw[:1500]}
    try:
        parsed = json.loads(m.group(0))
    except Exception as e:
        return {"_error": f"JSON parse failed: {e}", "_raw": raw[:1500]}
    # validate verbatim options
    by_id = {q["id"]: q for q in INSTRUMENT["questions"]}
    for q in INSTRUMENT["questions"]:
        qid = q["id"]
        v = parsed.get(qid)
        if isinstance(v, dict) and v.get("choice"):
            if v["choice"] not in q["options"]:
                # tolerate small whitespace/quote differences; flag if materially off
                norm = re.sub(r"\s+", " ", v["choice"]).strip().strip("“”\"'")
                if norm not in [re.sub(r"\s+", " ", o).strip().strip("“”\"'") for o in q["options"]]:
                    parsed[qid]["_warn"] = f"choice not verbatim: {v['choice'][:80]}"
        else:
            parsed[qid] = {"_warn": "missing choice", "choice": q["options"][0], "why": "fallback"}
    return parsed


def heuristic_simulate(rubric: dict) -> dict:
    """Deterministic fallback (no LLM): seed by author, skew by engine C (curiosity) / P."""
    import random
    random.seed(abs(hash(rubric.get("author", ""))) % 100000)
    eng = rubric.get("engine") or {}
    C = eng.get("C", 3) or 3
    P = eng.get("P", 3) or 3
    # Q1: higher C -> more likely "already use" / "occasional"; higher P -> more cautious
    def pick(qid):
        opts = [q["options"] for q in INSTRUMENT["questions"] if q["id"] == qid][0]
        if qid == "Q1":
            idx = max(0, min(4, 2 - int((C - 3)) + random.randint(-1, 1)))
        else:
            idx = max(0, min(4, 2 - int((C - 3)) + int((P - 3) * 0.5) + random.randint(-1, 1)))
        return opts[idx]
    return {
        "Q1": {"choice": pick("Q1"), "why": "heuristic fallback (no LLM key)"},
        "Q2": {"choice": pick("Q2"), "why": "heuristic fallback (no LLM key)"},
    }


def aggregate(responses: list) -> dict:
    by_id = {q["id"]: q for q in INSTRUMENT["questions"]}
    agg = {"n": len(responses), "questions": {}, "cross": {}}
    for q in INSTRUMENT["questions"]:
        qid = q["id"]
        opts = q["options"]
        c = Counter()
        for r in responses:
            v = (r.get(qid) or {}).get("choice")
            if v:
                c[v] += 1
        # normalize any non-verbatim choice into closest option
        dist = {o: 0 for o in opts}
        for k, v in c.items():
            if k in dist:
                dist[k] = v
            else:
                best = min(opts, key=lambda o: abs(len(o) - len(k)))
                dist[best] += v
        total = sum(dist.values()) or 1
        agg["questions"][qid] = {
            "prompt": q["prompt"],
            "dist": dist,
            "pct": {o: round(dist[o] / total * 100, 1) for o in opts},
            "top": max(opts, key=lambda o: dist[o]),
            "top_pct": round(max(dist.values()) / total * 100, 1),
        }
    # cross-tab Q1 x Q2 counts
    q1_opts = [q["options"] for q in INSTRUMENT["questions"] if q["id"] == "Q1"][0]
    q2_opts = [q["options"] for q in INSTRUMENT["questions"] if q["id"] == "Q2"][0]
    cross = {a: {b: 0 for b in q2_opts} for a in q1_opts}
    for r in responses:
        a = (r.get("Q1") or {}).get("choice")
        b = (r.get("Q2") or {}).get("choice")
        if a and b:
            cross[a][b] += 1
    agg["cross"] = cross
    # heuristic count
    agg["heuristic_count"] = sum(1 for r in responses if r.get("_fallback") or (r.get("Q1") or {}).get("why", "").startswith("heuristic"))
    return agg


# ── Mono report (DESIGN-mono.md: white gallery grid, 2px #292929, 0 radius) ──
def esc(s):
    import html as _h
    return _h.escape(str(s or ""), quote=False)


def render_report(subreddit: str, population: int, responses: list, agg: dict, meta: dict = None) -> str:
    meta = meta or {}
    now = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    run_id = meta.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    n = agg["n"]
    model = meta.get("model", "deepseek-v4-flash")
    INK, PAPER, CARBON = "#292929", "#ffffff", "#000000"

    def margin_for(n_, N, z=1.96, p=0.5):
        if n_ >= N or n_ <= 0:
            return 0
        fpc = (N - n_) / (N - 1) if N > 1 else 1
        return z * math.sqrt(p * (1 - p) / n_ * fpc) * 100

    margin = margin_for(n, population)

    def label(txt):
        return f'<div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;line-height:1.34;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">{esc(txt)}</div>'

    def head(txt):
        return f'<div style="font-family:var(--font-nh);font-weight:300;font-size:32px;line-height:1.25;letter-spacing:-0.02em;color:{INK}">{esc(txt)}</div>'

    def bar(pct):
        pct = max(0, min(100, float(pct)))
        return (
            f'<div style="height:8px;background:{PAPER};border:1px solid {INK}">'
            f'<div style="width:{pct}%;height:100%;background:{INK}"></div></div>'
        )

    def cell(inner, pad="20px"):
        return f'<div style="background:{PAPER};border:2px solid {INK};border-radius:0;padding:{pad}">{inner}</div>'

    # distribution block for one question
    def dist_block(qid):
        q = agg["questions"][qid]
        prompt = next((qq["prompt"] for qq in INSTRUMENT["questions"] if qq["id"] == qid), "")
        rows = ""
        ranked = sorted(q["dist"].items(), key=lambda kv: kv[1], reverse=True)
        for i, (opt, cnt) in enumerate(ranked):
            pct = q["pct"][opt]
            is_top = i == 0
            inner = (
                f'<div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline">'
                f'<div style="font-family:var(--font-nh);font-weight:400;font-size:16px;line-height:1.34;letter-spacing:-0.02em;color:{INK}">{esc(opt)}</div>'
                f'<div style="display:flex;gap:12px;align-items:baseline;flex-shrink:0">'
                f'<div style="font-family:var(--font-nh);font-weight:100;font-size:40px;line-height:1;letter-spacing:-0.02em;color:{INK}">{pct:.1f}%</div>'
                f'<div style="font-family:var(--font-s-condensed);font-weight:300;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">n={cnt}</div>'
                f'</div></div>'
                f'<div style="margin-top:10px">{bar(pct)}</div>'
            )
            if is_top:
                # dark inverse cell for the modal answer
                rows += (
                    f'<div style="background:{INK};border:2px solid {INK};border-radius:0;padding:20px;margin-bottom:12px">'
                    f'<div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline">'
                    f'<div style="font-family:var(--font-nh);font-weight:300;font-size:18px;line-height:1.5;color:{PAPER}">{esc(opt)} <span style="font-family:var(--font-s-condensed);font-size:12px;letter-spacing:0.1em;text-transform:uppercase">— modal</span></div>'
                    f'<div style="display:flex;gap:12px;align-items:baseline;flex-shrink:0">'
                    f'<div style="font-family:var(--font-nh);font-weight:100;font-size:43px;line-height:1;letter-spacing:-0.02em;color:{PAPER}">{pct:.1f}%</div>'
                    f'<div style="font-family:var(--font-s-condensed);font-weight:300;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{PAPER}">n={cnt}</div>'
                    f'</div></div>'
                    f'<div style="margin-top:10px;height:8px;background:{PAPER}"><div style="width:{pct}%;height:100%;background:{PAPER};border-right:1px solid {INK}"></div></div>'
                    f'</div>'
                )
            else:
                rows += f'<div style="margin-bottom:12px">{cell(inner)}</div>'
        return (
            f'<div style="padding:43px 45px 20px">'
            f'{label("Question " + qid)}'
            f'<div style="margin-top:8px;max-width:70ch">{head(prompt)}</div>'
            f'<div style="margin-top:20px">{rows}</div>'
            f'</div>'
        )

    # cross-tab grid
    q1_opts = [q["options"] for q in INSTRUMENT["questions"] if q["id"] == "Q1"][0]
    q2_opts = [q["options"] for q in INSTRUMENT["questions"] if q["id"] == "Q2"][0]
    cross_rows = ""
    # header row
    cross_rows += '<div style="display:grid;grid-template-columns:2.4fr repeat(5,1fr);gap:0">'
    cross_rows += f'<div style="border:2px solid {INK};border-right:0;padding:8px;font-family:var(--font-s-condensed);font-size:12px;letter-spacing:0.1em;text-transform:uppercase">Q1 ↓ / Q2 →</div>'
    for b in q2_opts:
        cross_rows += f'<div style="border:2px solid {INK};padding:8px;font-family:var(--font-s-condensed);font-size:11px;letter-spacing:0.1em;text-transform:uppercase;text-align:center">{esc(b[:18])}</div>'
    cross_rows += "</div>"
    for a in q1_opts:
        cross_rows += '<div style="display:grid;grid-template-columns:2.4fr repeat(5,1fr);gap:0">'
        cross_rows += f'<div style="border:2px solid {INK};border-top:0;border-right:0;padding:8px;font-family:var(--font-nh);font-weight:400;font-size:12px;line-height:1.34;color:{INK}">{esc(a[:42])}</div>'
        for b in q2_opts:
            v = agg["cross"].get(a, {}).get(b, 0)
            total = n or 1
            pct = round(v / total * 100, 1)
            strong = v > 0 and pct >= 10
            bg = INK if strong else PAPER
            fg = PAPER if strong else INK
            cross_rows += f'<div style="border:2px solid {INK};border-top:0;background:{bg};color:{fg};padding:8px;text-align:center;font-family:var(--font-nh);font-weight:400;font-size:13px">{v}<div style="font-family:var(--font-s-condensed);font-size:10px;letter-spacing:0.1em;text-transform:uppercase">{pct}%</div></div>'
        cross_rows += "</div>"

    # segments
    segments = _derive_segments(responses)
    seg_rows = ""
    for name, bucket in sorted(segments.items(), key=lambda kv: len(kv[1]), reverse=True):
        bn = len(bucket)
        top_choices = []
        for q in INSTRUMENT["questions"]:
            bq = Counter((r.get(q["id"]) or {}).get("choice") for r in bucket)
            t = bq.most_common(1)[0][0] if bq else "—"
            top_choices.append(f'<div style="font-family:var(--font-nh);font-weight:400;font-size:13px;line-height:1.4;color:{INK}">{esc(q["id"])}: {esc(t[:60])}</div>')
        cols = "2fr " + " ".join(["2fr"] * len(INSTRUMENT["questions"]))
        seg_rows += (
            f'<div style="display:grid;grid-template-columns:1.3fr .7fr {cols};gap:12px;padding:12px 0;border-bottom:1px solid {INK}">'
            f'<div style="font-family:var(--font-nh);font-weight:300;font-size:16px;color:{INK}">{esc(name)}</div>'
            f'<div style="font-family:var(--font-s-condensed);font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">n={bn}</div>'
            + "".join(top_choices) +
            f'</div>'
        )

    # voice cards — representative why per option per question
    def voice_cards(qid):
        q = next(qq for qq in INSTRUMENT["questions"] if qq["id"] == qid)
        cards = ""
        for opt in q["options"]:
            matches = [r for r in responses if (r.get(qid) or {}).get("choice") == opt]
            if not matches:
                continue
            sel = matches[:2]
            inner = f'<div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{INK};border-bottom:1px solid {INK};padding-bottom:8px">{esc(opt[:60])}</div>'
            for r in sel:
                why = (r.get(qid) or {}).get("why", "")
                inner += (
                    f'<div style="margin-top:10px;font-family:var(--font-nh);font-weight:300;font-size:14px;line-height:1.5;color:{INK}">“{esc(why)}”</div>'
                    f'<div style="margin-top:4px;font-family:var(--font-s-condensed);font-weight:300;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">u/{esc(r.get("_author","?"))}</div>'
                )
            cards += f'<div style="margin-bottom:12px">{cell(inner)}</div>'
        return cards

    # methodology five layers
    layers = [
        ("Comments collected", f"Arctic Shift archive, r/{esc(subreddit)}, {n} Redditors, ~{n*30} comments (limit 30/author)"),
        ("Profiles inferred", "V4-Flash dossier per author (Engine C/F/A1/A2/P, Big Five, quotes, arguments, one_line); inferred independently per author"),
        ("Synthetic responses generated", f"one simulated completion per persona via {esc(model)} — 2 single-choice questions, verbatim options + one-line why"),
        ("Metrics calculated", "share % per option per question, cross-tab Q1×Q2, Engine C/F segment splits"),
        ("Real-world evidence", "none in this pilot — calibration requires fielded interviews/surveys/conversions"),
    ]
    layer_html = "".join(
        f'<div style="display:grid;grid-template-columns:1.2fr 3fr;gap:12px;padding:10px 0;border-bottom:1px solid {INK}">'
        f'<div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">{esc(t)}</div>'
        f'<div style="font-family:var(--font-nh);font-weight:400;font-size:13px;line-height:1.5;color:{INK}">{esc(d)}</div></div>'
        for t, d in layers
    )

    # final takeaways — generic across instrument questions
    finals = [("Strongest signals (simulated)", " · ".join(f"{qid} modal: “{agg['questions'][qid]['top'][:50]}” at {agg['questions'][qid]['top_pct']:.1f}%" for qid in list(agg["questions"].keys())[:3]))]
    finals.append(("Biggest uncertainty", f"n={n} → ±{margin:.1f}% at 95%; synthetic — language ≈ attitude > behavior"))
    qids_all = list(agg["questions"].keys())
    if len(qids_all) >= 2:
        q_a, q_b = qids_all[0], qids_all[1]
        finals.append(("Top tension", f"{agg['questions'][q_a]['top'][:40]} vs {agg['questions'][q_b]['top'][:40]} — the positioning trade-off to resolve"))
    finals.append(("Riskiest assumption", "that simulated stance transfers to real adoption (setup, trust, cost) without fielded validation"))
    finals.append(("Recommended real test", "field the same options on 20-50 real parents; check modal options + willingness to pay"))
    finals.append(("Cannot establish", "prevalence, willingness to pay, or behavior — only simulated language/attitude distributions"))
    finals_html = "".join(
        f'<div style="padding:12px 0;border-bottom:1px solid {INK}">'
        f'<div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">{esc(t)}</div>'
        f'<div style="margin-top:6px;font-family:var(--font-nh);font-weight:300;font-size:16px;line-height:1.45;color:{INK}">{esc(d)}</div></div>'
        for t, d in finals
    )

    # cross-tab section — only for instruments with >=2 questions (Q1 × Q2)
    has_q1 = any(q["id"] == "Q1" for q in INSTRUMENT["questions"])
    has_q2 = any(q["id"] == "Q2" for q in INSTRUMENT["questions"])
    if has_q1 and has_q2:
        cross_section = f'<div style="padding:43px 45px 20px;border-bottom:2px solid {INK}">' \
            f'{label("Cross-tab — Q1 × Q2, counts + share")}' \
            f'<div style="margin-top:16px;overflow-x:auto">{cross_rows}</div>' \
            f'<div style="margin-top:10px;font-family:var(--font-s-condensed);font-weight:300;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:{INK}">dark cells = ≥10% of respondents · row = Q1 · column = Q2</div></div>'
    else:
        cross_section = ""

    # render each question in instrument order (generated blocks)
    q_blocks = "".join(
        f'<div style="border-bottom:2px solid {INK}">{dist_block(q["id"])}</div>'
        for q in INSTRUMENT["questions"]
    )

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="color-scheme" content="light"/>
<title>Parents on AI · r/{esc(subreddit)} · simulated n={n}</title>
<style>
:root {{
  --color-ink:{INK}; --color-paper:{PAPER}; --color-carbon:{CARBON};
  --font-nh:'NH',Inter,'Helvetica Neue',Arial,ui-sans-serif,system-ui,sans-serif;
  --font-s-condensed:'S-Condensed','Roboto Condensed','Barlow Condensed',ui-sans-serif,system-ui,sans-serif;
  --text-caption:12px; --text-body:16px; --text-body-lg:18px; --text-subheading:25px;
  --text-heading-sm:32px; --text-heading:40px; --text-display:43px;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:{PAPER};color:{INK};font-family:var(--font-nh);-webkit-font-smoothing:antialiased}}
a{{color:{INK}}}
</style></head><body>
<!-- masthead -->
<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 45px;border-bottom:2px solid {INK}">
  <div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.2em;text-transform:uppercase">HERMES · SIMULATED SURVEY · r/{esc(subreddit)}</div>
  <div style="font-family:var(--font-s-condensed);font-weight:300;font-size:12px;letter-spacing:0.1em;text-transform:uppercase">n={n} simulated · {len(INSTRUMENT["questions"])} questions</div>
</div>
<!-- synthetic warning -->
<div style="padding:12px 45px;border-bottom:2px solid {INK};background:{INK};color:{PAPER};font-family:var(--font-s-condensed);font-weight:300;font-size:12px;letter-spacing:0.1em;text-transform:uppercase">⚠ {esc(SYNTHETIC_WARNING)}</div>
<!-- hero -->
<div style="padding:43px 45px;border-bottom:2px solid {INK}">
  <div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.1em;text-transform:uppercase">r/{esc(subreddit)} · N≈{population:,} · run {esc(run_id)} · model {esc(model)}</div>
  <h1 style="margin:12px 0 0;font-family:var(--font-nh);font-weight:300;font-size:43px;line-height:1.34;letter-spacing:-0.02em;color:{INK}">{esc(INSTRUMENT["title"])}</h1>
  <p style="max-width:75ch;margin:16px 0 0;font-family:var(--font-nh);font-weight:400;font-size:16px;line-height:1.5;letter-spacing:-0.02em;color:{INK}">{esc(INSTRUMENT['intro'])}</p>
</div>
<!-- questions -->
{q_blocks}
{cross_section}
<!-- segments -->
<div style="padding:43px 45px 20px;border-bottom:2px solid {INK}">
  {label("Segment split — Engine C/F cohorts")}
  <div style="margin-top:16px">{seg_rows or '<div style="font-family:var(--font-nh);font-weight:400;font-size:14px">Insufficient n for stable segments.</div>'}</div>
</div>
<!-- voice -->
<div style="padding:43px 45px 20px;border-bottom:2px solid {INK}">
  {label("Voice — representative simulated whys, Q1 (parents using AI)")}
  <div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px">{voice_cards("Q1")}</div>
</div>
<div style="padding:43px 45px 20px;border-bottom:2px solid {INK}">
  {label("Voice — representative simulated whys, Q2 (kids using AI)")}
  <div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px">{voice_cards("Q2")}</div>
</div>
<!-- methodology -->
<div style="padding:43px 45px 20px;border-bottom:2px solid {INK}">
  {label("Methodology + limitations — what was simulated, what was not")}
  <div style="margin-top:16px">{layer_html}</div>
  <div style="margin-top:16px">
    {cell(f'<div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.1em;text-transform:uppercase">Provenance</div><div style="margin-top:8px;font-family:var(--font-nh);font-weight:400;font-size:13px;line-height:1.6">Source r/{esc(subreddit)} · N≈{population:,} · {n} authors / ~{n*30} comments · selection: top commenters, thin (&lt;30) skipped · model {esc(model)} · prompt v1 (2-Q 5-opt) · run {esc(run_id)} · one simulation per persona, no cross-persona context · heuristic fallback: {agg.get("heuristic_count",0)} of {n}</div>')}
  </div>
  <div style="margin-top:12px;padding:20px;background:{INK};color:{PAPER};border:2px solid {INK};border-radius:0">
    <div style="font-family:var(--font-s-condensed);font-weight:500;font-size:12px;letter-spacing:0.1em;text-transform:uppercase;color:{PAPER}">Do not treat as population estimates</div>
    <div style="margin-top:8px;font-family:var(--font-nh);font-weight:300;font-size:16px;line-height:1.5;color:{PAPER}">{esc(SYNTHETIC_WARNING)}</div>
  </div>
</div>
<!-- final 8 -->
<div style="padding:43px 45px 20px;border-bottom:2px solid {INK}">
  {label("What this simulation can establish — and what must be tested with real people")}
  <div style="margin-top:16px">{finals_html}</div>
</div>
<!-- footer -->
<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 45px;border-top:2px solid {INK}">
  <div style="font-family:var(--font-s-condensed);font-weight:300;font-size:12px;letter-spacing:0.2em;text-transform:uppercase">© HERMES · SIMULATED SURVEY · r/{esc(subreddit)} · {now}</div>
  <div style="font-family:var(--font-s-condensed);font-weight:300;font-size:12px;letter-spacing:0.1em;text-transform:uppercase">Synthetic — not fielded · single-file HTML · opens offline</div>
</div>
</body></html>"""
    return html


def main():
    ap = argparse.ArgumentParser(description="AI-use survey on r/parenting personas (2-Q, 5-opt, mono)")
    ap.add_argument("--personas", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--population", type=int, default=None)
    ap.add_argument("--subreddit", default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="smoke test: only first N personas")
    ap.add_argument("--instrument", default=None, help="Path to custom positioning instrument JSON (title/intro/questions, single_choice only)")
    args = ap.parse_args()
    _load_env_file()

    global INSTRUMENT
    if args.instrument:
        try:
            custom = json.loads(Path(args.instrument).read_text())
            INSTRUMENT = custom
            print(f"[ai-survey] custom instrument: {custom.get('title','(no title)')[:80]} ({len(custom.get('questions',[]))} Qs)", file=sys.stderr)
        except Exception as e:
            print(f"[ai-survey] failed to load --instrument {args.instrument}: {e}", file=sys.stderr); sys.exit(1)
    personas_path = Path(args.personas)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    rubrics = []
    for line in personas_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            author = r.get("author")
            candidate = personas_path.parent / "dossiers" / f"u_{author}.json"
            if candidate.exists():
                try:
                    full = json.loads(candidate.read_text())
                    for k in ["engine", "big_five", "style", "one_line", "quotes", "arguments", "persona_stack", "engine_metrics"]:
                        if k not in r or not r[k]:
                            if k in full:
                                r[k] = full[k]
                except Exception:
                    pass
            rubrics.append(r)
        except Exception:
            continue
    if args.limit:
        rubrics = rubrics[: args.limit]
    if not rubrics:
        print("[ai-survey] no rubrics found", file=sys.stderr)
        sys.exit(1)

    subreddit = args.subreddit or personas_path.parent.name.replace("dataset-pilot-20-deepseek", "").strip("/-") or "parenting"
    if subreddit in ("dataset-385", "dataset-30"):
        subreddit = "parenting"
    try:
        mpath = personas_path.parent / "manifest.json"
        if mpath.exists():
            mj = json.loads(mpath.read_text())
            subreddit = mj.get("subreddit", subreddit)
    except Exception:
        pass
    population = args.population
    if population is None:
        try:
            from analyze import api_get
            data = api_get("/api/subreddits/search", {"subreddit": subreddit, "limit": 1, "meta-app": "reddit-intel"})
            population = (data.get("data") or [{}])[0].get("subscribers") or 8056434
        except Exception:
            population = 8056434

    print(f"[ai-survey] r/{subreddit} N≈{population:,} · {len(rubrics)} personas · model={args.model} llm={not args.no_llm}", file=sys.stderr)

    jsonl_path_ck = outdir / "responses.jsonl"
    existing_by_author = {}
    if jsonl_path_ck.exists():
        for line in jsonl_path_ck.read_text().splitlines():
            if line.strip():
                try:
                    j = json.loads(line)
                    if j.get("author"):
                        existing_by_author[j["author"]] = j
                except Exception:
                    pass
        if existing_by_author:
            print(f"[ai-survey] resume: {len(existing_by_author)} existing responses, will skip those authors", file=sys.stderr)

    todo = [r for r in rubrics if r.get("author") not in existing_by_author]
    responses_rehydrated = []
    rubrics_by_author = {r.get("author"): r for r in rubrics}
    for author, j in existing_by_author.items():
        r = rubrics_by_author.get(author)
        if r is not None:
            j["_author"] = author
            j["_rubric"] = r
            responses_rehydrated.append(j)

    def run_one(rubric):
        if args.no_llm:
            ans = heuristic_simulate(rubric)
        else:
            ans = simulate_one(rubric, args.model)
            if "_error" in ans:
                print(f"[ai-survey] u/{rubric.get('author')} error: {ans.get('_error')[:120]}", file=sys.stderr)
                ans = heuristic_simulate(rubric)
                ans["_fallback"] = True
        ans["_author"] = rubric.get("author")
        ans["_rubric"] = rubric
        try:
            out_ck = {"author": ans["_author"], **{k: v for k, v in ans.items() if not k.startswith("_")}}
            with open(jsonl_path_ck, "a") as _f:
                _f.write(json.dumps(out_ck, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return ans

    with ThreadPoolExecutor(max_workers=max(1, min(6, args.concurrency))) as ex:
        futs = {ex.submit(run_one, r): r.get("author") for r in todo}
        for fut in as_completed(futs):
            try:
                responses_rehydrated.append(fut.result())
            except Exception as e:
                print(f"[ai-survey] fut fail: {e}", file=sys.stderr)

    responses = responses_rehydrated
    responses.sort(key=lambda x: x.get("_author", ""))
    with open(jsonl_path_ck, "w") as f:
        for r in responses:
            out = {"author": r["_author"], **{k: v for k, v in r.items() if not k.startswith("_")}}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    csv_path = outdir / "responses.csv"
    headers = ["author", "engine_sig", "Q1", "Q1_why", "Q2", "Q2_why"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in responses:
            eng_sig = (r.get("_rubric", {}).get("engine") or {}).get("signature", "")
            w.writerow({
                "author": r["_author"], "engine_sig": eng_sig,
                "Q1": r.get("Q1", {}).get("choice", ""), "Q1_why": r.get("Q1", {}).get("why", ""),
                "Q2": r.get("Q2", {}).get("choice", ""), "Q2_why": r.get("Q2", {}).get("why", ""),
            })

    (outdir / "survey-instrument.json").write_text(json.dumps(INSTRUMENT, indent=2, ensure_ascii=False))
    agg = aggregate(responses)
    (outdir / "aggregates.json").write_text(json.dumps(agg, indent=2))

    _meta = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "model": args.model if not args.no_llm else "heuristic",
        "prompt_version": "1 (2-Q 5-opt)",
        "seed": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "collection_period": "archive (Arctic Shift)",
    }
    html = render_report(subreddit, population, responses, agg, _meta)
    report_path = outdir / "report.html"
    report_path.write_text(html, encoding="utf-8")

    print(f"[ai-survey] wrote {jsonl_path_ck} ({len(responses)} responses)", file=sys.stderr)
    print(f"[ai-survey] wrote {csv_path}", file=sys.stderr)
    print(f"[ai-survey] wrote {report_path} ({len(html)} bytes)", file=sys.stderr)
    q1 = agg["questions"]["Q1"]
    q2 = agg["questions"]["Q2"]
    print("[ai-survey] Q1:", ", ".join(f"{o[:24]}={pct}%" for o, pct in list(q1["pct"].items())[:5]), file=sys.stderr)
    print("[ai-survey] Q2:", ", ".join(f"{o[:24]}={pct}%" for o, pct in list(q2["pct"].items())[:5]), file=sys.stderr)
    print(str(report_path))


if __name__ == "__main__":
    main()
