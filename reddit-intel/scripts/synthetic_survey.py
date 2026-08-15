#!/usr/bin/env python3
"""
synthetic_survey.py — Pipeline 3: synthetic survey simulation on top of dossiers.

Given a personas.jsonl (from build_dataset.py), simulate how each persona would
answer a survey about UCC Hermes / Thrice Great — usefulness for parents involved
in their kids' education.

Survey is grounded in UCC_Hermes_SOP_Playbook_v6.md (v6.0):
- File-first private learning OS on family VPS
- School Model Canvas (14 dims) as macro vision
- 11 assessment instruments + M/C/M/F/N interpretation
- 8 UCC app pathways (Math Generator, Reader Engine, Writer's White Board, etc.)
- Agent fleet (Student Task, Tutor, Parent Agent, Receipt Interpreter, etc.)
- Two journeys: Journey A (DIY/BYOK) vs Journey B (Managed LearningOps)

Output: CSV + JSONL + single-file HTML report (Cosmos methodology + Notion results grid).

Usage:
  python synthetic_survey.py --personas ./personas.jsonl --out ./survey-simulation --model deepseek-v4-flash --concurrency 2
  python synthetic_survey.py --personas ./personas.jsonl --out ./survey-simulation --no-llm   # heuristic demo

Prompt-cache: system=survey instrument (stable), user=persona evidence + rubric (variable).
DeepSeek V4 Flash: cached_tokens on system prefix.
"""

import argparse, json, csv, re, html as htmlmod, sys, os, time
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import try_llm, _load_env_file

# ── Survey instrument (grounded in SOP v6) ──────────────────────────────────

SURVEY_INSTRUMENT = {
    "title": "UCC Hermes — Thrice Great — Usefulness for Parents Involved in Their Kids' Education",
    "intro": (
        "UCC (UnCommon Core) Hermes is a private, file-first learning OS. It runs on a family's own VPS/Discord, "
        "reads a School Model Canvas (14-dimension educational constitution), ingests .md learning receipts from 11 assessment instruments, "
        "interprets them via M/C/M/F/N (Measured/Calculated/Modeled/Forecasted/Noted), and routes families to 8 UCC app pathways "
        "(Canvas, Assessment Tests, Math Generator, Reader Engine, Writer's White Board, STEM Generator, History Story Maps, Movement Coach) "
        "via a 6-agent fleet (Student Task, Student Tutor, Parent Agent, Receipt Interpreter, Curriculum Generator, Safety/Audit). "
        "Two journeys: Journey A = DIY open-source + BYOK; Journey B = Managed LearningOps (UCC provisions VPS/Discord/agents). "
        "Hermes is 'Thrice Great' (Trismegistus): great in philosophy (Canvas), great in evidence (receipts/ledger), great in action (routing/generation)."
    ),
    "questions": [
        {"id": "Q1", "type": "likert_1_7", "prompt": "Overall, how useful would UCC Hermes be for a parent who is actively involved in their kid's education?", "labels": "1=Not at all useful … 7=Extremely useful"},
        {"id": "Q2", "type": "likert_1_7", "prompt": "How useful is the School Model Canvas (14-dimension family educational constitution) for aligning learning to your family's values?", "labels": "1-7"},
        {"id": "Q3", "type": "likert_1_7", "prompt": "How useful is the file-first receipt/memory model (family owns .md files on their VPS, not a platform lock-in)?", "labels": "1-7"},
        {"id": "Q4", "type": "likert_1_7", "prompt": "How useful is M/C/M/F/N evidence interpretation (separating what happened / what the numbers say / what it likely means / what to do next)?", "labels": "1-7"},
        {"id": "Q5", "type": "likert_1_7", "prompt": "How useful is the weekly Parent Agent report (5-card: Coverage, Strengths, Growth Edges, Cross-Domain Pattern, This Week's Plan)?", "labels": "1-7"},
        {"id": "Q6", "type": "likert_1_7", "prompt": "How useful is app-pathway routing (Hermes recommends the right UCC app — Math Generator, Reader Engine, Writer's White Board, STEM Generator, History Story Maps, Movement Coach — instead of inventing curriculum)?", "labels": "1-7"},
        {"id": "Q7", "type": "likert_1_7", "prompt": "How likely would you be to try UCC Hermes in the next 3 months (Journey A or B)?", "labels": "1=Not at all likely … 7=Extremely likely"},
        {"id": "Q8", "type": "nps_0_10", "prompt": "How likely would you be to recommend UCC Hermes to another involved parent? (NPS 0-10)", "labels": "0=Not at all likely … 10=Extremely likely"},
        {"id": "Q9", "type": "single_choice", "prompt": "Which journey fits you best?", "options": ["Journey A — DIY open-source + BYOK (I want full control)", "Journey B — Managed LearningOps (UCC provisions/maintains my VPS/Discord/fleet)", "Neither — not a fit", "Undecided — need to see it first"]},
        {"id": "Q10", "type": "max_3", "prompt": "Which 3 Hermes capabilities matter most to you? (pick up to 3)", "options": ["School Model Canvas", "Learning receipts / evidence coverage map", "Mastery & misconception maps", "Weekly plan + workload estimate", "Student Tutor (one-concept-at-a-time)", "Curriculum generation from evidence", "File-first ownership / data stays on my VPS", "Discord-native workflows (#student-tasks / #parent-agent / #receipts)", "Safety/Audit guardrails"]},
        {"id": "Q11", "type": "open", "max_chars": 280, "prompt": "In your own words, what would make UCC Hermes genuinely helpful (or not helpful) for a parent like you? (1-2 sentences)"},
        {"id": "Q12", "type": "open", "max_chars": 280, "prompt": "Biggest concern or blocker that would stop you from adopting Hermes in the next 3 months? (1-2 sentences, be blunt)"},
    ]
}

SURVEY_SYSTEM_PROMPT = """You are a survey simulator. Given a Reddit persona's communication style and worldview (engine, Big Five, anchors), simulate how THEY would answer a survey about UCC Hermes — a private, file-first learning OS described in the system.

Rules:
- Stay in character. Use the persona's directness, warmth, skepticism, and vocabulary.
- Likert/NPS: return integers in range. Distribution should reflect the persona's actual values (e.g., a skeptical, control-oriented parent scores file-first higher but managed service lower).
- Q9 single_choice: return exactly one option string verbatim.
- Q10 max_3: return 1-3 option strings verbatim.
- Q11/Q12 open: 1-2 sentences, ≤280 chars, in the persona's voice, with a verbatim quote anchor if possible. Be specific — no generic filler.
- Every answer must have a one-line "why" (≤120 chars) grounding it in the persona's evidence (e.g., "you value hands-on control" or "you distrust platform lock-in per anchor '…'").
- Return ONLY a single JSON object — no prose outside JSON.

SURVEY INSTRUMENT:
{instrument_json}

Return shape:
{{
  "Q1": {{"score": 1-7, "why": "…"}},
  "Q2": {{"score": 1-7, "why": "…"}},
  "Q3": {{"score": 1-7, "why": "…"}},
  "Q4": {{"score": 1-7, "why": "…"}},
  "Q5": {{"score": 1-7, "why": "…"}},
  "Q6": {{"score": 1-7, "why": "…"}},
  "Q7": {{"score": 1-7, "why": "…"}},
  "Q8": {{"score": 0-10, "why": "…"}},
  "Q9": {{"choice": "…verbatim…", "why": "…"}},
  "Q10": {{"choices": ["…", "…"], "why": "…"}},
  "Q11": {{"text": "… ≤280 chars …", "why": "…"}},
  "Q12": {{"text": "… ≤280 chars …", "why": "…"}}
}}
"""

def persona_summary_for_survey(rubric: dict) -> str:
    """Compact persona summary for the LLM — evidence-anchored."""
    eng = rubric.get("engine") or {}
    big = rubric.get("big_five") or {}
    style = rubric.get("style") or {}
    one_line = rubric.get("one_line") or rubric.get("one_line_summary") or ""
    quotes = rubric.get("quotes") or []
    quote_lines = []
    for q in quotes[:3]:
        if isinstance(q, dict):
            quote_lines.append(f"  - \"{q.get('text','')[:140]}\" — {q.get('signal','')}")
        elif isinstance(q, str):
            quote_lines.append(f"  - \"{q[:140]}\"")
    if not quote_lines and rubric.get("arguments"):
        args = rubric["arguments"]
        if isinstance(args, list) and args:
            quote_lines.append(f"  - Argument style: {str(args[0])[:140]}")
    anchors = eng.get("anchors") or {}
    return (
        f"Author: u/{rubric.get('author','?')} — {one_line}\n"
        f"Engine: C={eng.get('C','?')} F={eng.get('F','?')} A1={eng.get('A1','?')} A2={eng.get('A2','?')} P={eng.get('P','?')} sig={eng.get('signature','—')}\n"
        f"Big Five: O={big.get('O','?')} C={big.get('C','?')} E={big.get('E','?')} A={big.get('A','?')} N={big.get('N','?')}\n"
        f"Style: {str(style)[:300]}\n"
        f"Envelope strong: {eng.get('envelope_strong','')[:180]}\n"
        f"Envelope fragile: {eng.get('envelope_fragile','')[:180]}\n"
        f"Anchors: {json.dumps(anchors, ensure_ascii=False)[:600]}\n"
        f"Quotes:\n" + ("\n".join(quote_lines) if quote_lines else "  (no quotes in rubric)")
    )

def simulate_one(rubric: dict, model: str) -> dict:
    system = SURVEY_SYSTEM_PROMPT.format(instrument_json=json.dumps(SURVEY_INSTRUMENT, ensure_ascii=False, indent=2))
    user = persona_summary_for_survey(rubric) + "\n\nTASK: Simulate this persona's survey answers. Return ONLY the JSON object with Q1..Q12."
    raw = try_llm(user, model=model, system_prompt=system)
    if not raw:
        return {"_error": "llm returned empty"}
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"_error": f"no JSON in raw: {raw[:400]}", "_raw": raw[:2000]}
    try:
        parsed = json.loads(m.group(0))
        for qid in ["Q1","Q2","Q3","Q4","Q5","Q6","Q7"]:
            if qid in parsed:
                v = parsed[qid].get("score") if isinstance(parsed[qid], dict) else parsed[qid]
                if isinstance(v, int) and not (1 <= v <= 7):
                    parsed[qid]["_warn"] = f"score {v} out of 1-7"
        if "Q8" in parsed and isinstance(parsed["Q8"], dict) and "score" in parsed["Q8"]:
            if not (0 <= int(parsed["Q8"]["score"]) <= 10):
                parsed["Q8"]["_warn"] = "NPS out of 0-10"
        return parsed
    except Exception as e:
        return {"_error": f"JSON parse failed: {e}", "_raw": raw[:2000]}

def heuristic_simulate(rubric: dict) -> dict:
    import random
    random.seed(hash(rubric.get("author","")) % 100000)
    def likert(base=4):
        return max(1, min(7, base + random.randint(-1,1)))
    return {
        "Q1": {"score": likert(5), "why": "heuristic — no LLM key"},
        "Q2": {"score": likert(5), "why": "heuristic"},
        "Q3": {"score": likert(5), "why": "heuristic"},
        "Q4": {"score": likert(4), "why": "heuristic"},
        "Q5": {"score": likert(5), "why": "heuristic"},
        "Q6": {"score": likert(5), "why": "heuristic"},
        "Q7": {"score": likert(4), "why": "heuristic"},
        "Q8": {"score": random.randint(5,8), "why": "heuristic"},
        "Q9": {"choice": "Journey B — Managed LearningOps (UCC provisions/maintains my VPS/Discord/fleet)", "why": "heuristic default"},
        "Q10": {"choices": ["Weekly plan + workload estimate", "Learning receipts / evidence coverage map", "File-first ownership / data stays on my VPS"], "why": "heuristic"},
        "Q11": {"text": "Heuristic placeholder — add DEEPSEEK_API_KEY for persona-grounded open text.", "why": "heuristic"},
        "Q12": {"text": "Heuristic placeholder — add key for grounded blocker.", "why": "heuristic"},
        "_heuristic": True,
    }

def aggregate(responses: list) -> dict:
    import statistics
    likerts = {f"Q{i}": [] for i in range(1,8)}
    nps_scores = []
    journey_counts = {}
    top3_counts = {}
    for r in responses:
        for qid in likerts:
            try: likerts[qid].append(int(r[qid]["score"]))
            except: pass
        try: nps_scores.append(int(r["Q8"]["score"]))
        except: pass
        try:
            c = r["Q9"]["choice"]
            journey_counts[c] = journey_counts.get(c, 0) + 1
        except: pass
        try:
            for ch in r["Q10"]["choices"]:
                top3_counts[ch] = top3_counts.get(ch, 0) + 1
        except: pass
    def stats(arr):
        if not arr: return {"n":0,"mean":0,"median":0,"top2box":0}
        top2 = sum(1 for x in arr if x >= 6) / len(arr)
        return {"n": len(arr), "mean": round(statistics.mean(arr),2), "median": round(statistics.median(arr),1), "top2box": round(top2*100,1), "dist": {str(k): arr.count(k) for k in sorted(set(arr))}}
    nps = {"promoters": 0, "passives": 0, "detractors": 0, "score": 0}
    if nps_scores:
        prom = sum(1 for x in nps_scores if x >= 9)
        pas = sum(1 for x in nps_scores if 7 <= x <= 8)
        detr = sum(1 for x in nps_scores if x <= 6)
        n = len(nps_scores)
        nps = {"promoters": round(prom/n*100,1), "passives": round(pas/n*100,1), "detractors": round(detr/n*100,1), "score": round((prom/n - detr/n)*100,1), "mean": round(statistics.mean(nps_scores),2), "dist": {str(k): nps_scores.count(k) for k in sorted(set(nps_scores))}}
    heuristic_count = sum(1 for r in responses if r.get("_heuristic") or r.get("_fallback"))
    return {"likerts": {k: stats(v) for k,v in likerts.items()}, "nps": nps, "journeys": journey_counts, "top3": dict(sorted(top3_counts.items(), key=lambda x: x[1], reverse=True)), "n": len(responses), "heuristic_count": heuristic_count}

def render_report(subreddit: str, population: int, responses: list, aggregates: dict, instrument: dict) -> str:
    esc = lambda s: htmlmod.escape(s or "", quote=False)
    now = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    n = len(responses)
    import math
    def margin_for(n_, N, z=1.96, p=0.5):
        if n_ >= N: return 0
        if n_ <= 0: return 0
        fpc = (N - n_) / (N - 1) if N > 1 else 1
        var = p*(1-p)/n_ * fpc
        return z * math.sqrt(var)
    pilot_margin = margin_for(n, population) * 100
    def bar(pct, color="#ffc500"):
        return f'<div style="height:10px;background:#eee;border-radius:9999px;overflow:hidden"><div style="width:{pct}%;height:100%;background:{color}"></div></div>'
    def chip(t, bg="#ffc500"):
        return f'<span style="display:inline-block;font:700 10px/1 Inter,system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;padding:4px 8px;border-radius:9999px;background:{bg};border:1px solid rgba(0,0,0,.08)">{esc(t)}</span>'
    likert_questions = [q for q in instrument["questions"] if q["id"] in aggregates["likerts"]]
    likert_rows = ""
    for q in likert_questions:
        qid = q["id"]
        st = aggregates["likerts"][qid]
        likert_rows += f'<div style="border:1px solid #d9d9d9;background:#fff;border-radius:12px;padding:14px"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e">{esc(qid)} · {esc(q["prompt"][:90])}</div><div style="display:flex;align-items:baseline;gap:10px;margin-top:8px"><b style="font-size:28px;letter-spacing:-.02em">{st["mean"]}</b><span style="font:500 11px/1 Inter,sans-serif;color:#6e6e6e">mean · median {st["median"]} · top-2-box {st["top2box"]}%</span></div>{bar(st["top2box"])}<div style="font:500 11px/1.4 Inter,sans-serif;color:#6e6e6e;margin-top:6px">n={st["n"]} · dist {json.dumps(st["dist"])}</div></div>'
    journey_rows = "".join(f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #eee'><span style='font:500 13px/1 Inter,sans-serif'>{esc(k)}</span><b>{v}</b></div>" for k,v in aggregates["journeys"].items())
    top3_rows = "".join(f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #eee'><span style='font:500 13px/1 Inter,sans-serif'>{esc(k)}</span><span style='font:700 13px/1 Inter,sans-serif'>{v} · {round(v/n*100,1)}%</span></div>" for k,v in aggregates["top3"].items())
    cards = ""
    for r in responses:
        author = esc(r.get("_author","?"))
        eng_sig = esc((r.get("_rubric",{}).get("engine") or {}).get("signature","—"))
        q1 = r.get("Q1",{}).get("score","—")
        npsv = r.get("Q8",{}).get("score","—")
        journey = esc(r.get("Q9",{}).get("choice","—")[:42])
        q11 = esc(r.get("Q11",{}).get("text","")[:180])
        q12 = esc(r.get("Q12",{}).get("text","")[:180])
        q1_why = esc(r.get("Q1",{}).get("why","")[:100])
        cards += f'<a href="../dataset-pilot-20-deepseek/dossiers/u_{author}.html" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div style="border:1px solid #d9d9d9;background:#fff;border-radius:12px;padding:14px"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e">u/{author} · {eng_sig}</div><div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">{chip(f"Q1 usefulness {q1}/7")} {chip(f"NPS {npsv}/10", "#e6f3fe")} {chip(journey, "#f6f5f4")}</div><div style="margin-top:10px;font:500 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#757575">What would make it helpful</div><div style="font:400 13px/1.45 Georgia,serif;margin-top:4px">“{q11}”</div><div style="margin-top:8px;font:500 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#757575">Blocker</div><div style="font:400 13px/1.45 Georgia,serif;margin-top:4px;color:#615d59">“{q12}”</div><div style="margin-top:8px;font:500 10px/1.3 Inter,sans-serif;color:#6e6e6e">{q1_why}</div></div></a>'
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="color-scheme" content="light"/>
<title>UCC Hermes — Simulated Survey · r/{esc(subreddit)} · n={n}</title>
<style>
:root{{--c-cream:#fdfcf3;--c-linen:#f7f5f3;--c-paper:#fff;--c-ink:#0d0d0d;--c-rule:#d9d9d9;--c-mute:#6e6e6e;--c-yellow:#ffc500;--c-blue:#0075de;--r:16px}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--c-linen);color:var(--c-ink);font-family:Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
a{{color:var(--c-blue)}}
.hero{{max-width:1100px;margin:0 auto;padding:28px 16px 18px}}
.card{{border:1px solid var(--c-rule);background:var(--c-paper);border-radius:var(--r);padding:16px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}@media(max-width:700px){{.kpi-grid{{grid-template-columns:1fr 1fr}}}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media(max-width:860px){{.grid2{{grid-template-columns:1fr}}}}
.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}@media(max-width:900px){{.grid3{{grid-template-columns:1fr 1fr}}}}@media(max-width:560px){{.grid3{{grid-template-columns:1fr}}}}
.pill{{display:inline-block;font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;padding:4px 8px;border-radius:9999px;border:1px solid rgba(0,0,0,.08)}}
.eyebrow{{font:700 11px/1 Inter,sans-serif;letter-spacing:.07em;text-transform:uppercase;color:var(--c-mute);margin:0 0 8px}}
</style></head><body>
<div style="position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid var(--c-rule);display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:40px;font:700 13px/1 Inter,sans-serif;letter-spacing:.06em">MONOCLE · SURVEY SIMULATION · r/{esc(subreddit)} <span class="pill" style="background:var(--c-yellow)">n={n} personas</span></div>
<header class="hero">
  <div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--c-mute)">{esc(instrument.get('title','UCC HERMES — THRICE GREAT')[:80])} · PIPELINE 3 · SYNTHETIC SURVEY</div>
  <h1 style="margin:8px 0 0;font-family:Georgia,serif;font-size:38px;line-height:1.02;letter-spacing:-.03em">Would <em style="font-style:normal;background:linear-gradient(transparent 60%,var(--c-yellow) 60% 88%,transparent 88%)">r/{esc(subreddit)}</em> want this?</h1>
  <p style="max-width:68ch;color:var(--c-mute);line-height:1.5;margin:10px 0 0">{esc(instrument.get('intro','Synthetic responses simulated from V3.3 dossiers — engine, Big Five, and verbatim anchors shape Likert, NPS, journey preference, and open text.')[:520])}</p>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><span class="pill" style="background:var(--c-yellow)">n={n} simulated respondents</span><span class="pill">r/{esc(subreddit)} · N≈{population:,}</span><span class="pill">instrument: 12 questions</span><span class="pill">model: deepseek-v4-flash</span></div>
</header>
<div style="max-width:1100px;margin:0 auto;padding:0 16px">
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">01 · Methodology — with what confidence do we know this?</div>
  <div class="card" style="background:#fdfcf3">
    <div style="font:700 13px/1 Inter,sans-serif">Sample-size context</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px">
      <div style="border:1px solid var(--c-rule);background:#fff;border-radius:12px;padding:12px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Population</div><b style="font-size:22px">r/{esc(subreddit)} · {population:,}</b><div style="font:500 11px/1.3 Inter,sans-serif;color:var(--c-mute);margin-top:4px">Arctic Shift subscribers</div></div>
      <div style="border:1px solid var(--c-rule);background:var(--c-yellow);border-radius:12px;padding:12px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase">Required @95% ±5%</div><b style="font-size:22px">385</b><div style="font:500 11px/1.3 Inter,sans-serif;margin-top:4px">pull 482 · pilot 50</div></div>
      <div style="border:1px solid var(--c-rule);background:#fff;border-radius:12px;padding:12px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">This pilot</div><b style="font-size:22px">n={n} → ±{pilot_margin:.1f}%</b><div style="font:500 11px/1.3 Inter,sans-serif;color:var(--c-mute);margin-top:4px">@95% · p=0.5 · fpc applied</div></div>
    </div>
    <p style="font:500 12px/1.5 Inter,sans-serif;color:var(--c-mute);margin:10px 0 0">With <b style="color:var(--c-ink)">{population:,} at 95% / ±5%</b> we think you need 385 completes. We recommend 482 pulls (buffer for thin authors) and a pilot of 50. This pilot is <b style="color:var(--c-ink)">n={n}</b> (±{pilot_margin:.1f}% at 95%) — directionally useful, not inferential. Scale to 385 to claim ±5%.</p>
  </div>
</section>
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">02 · Topline — usefulness</div>
  <div class="kpi-grid">
    <div class="card" style="background:var(--c-yellow);border-color:#000"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase">Q1 Overall usefulness</div><b style="font-size:28px">{aggregates['likerts']['Q1']['mean']}/7</b><div style="font:500 11px/1 Inter,sans-serif;color:rgba(0,0,0,.6)">median {aggregates['likerts']['Q1']['median']} · top-2-box {aggregates['likerts']['Q1']['top2box']}%</div>{bar(aggregates['likerts']['Q1']['top2box'])}</div>
    <div class="card"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Q7 Try in 3 months</div><b style="font-size:28px">{aggregates['likerts']['Q7']['mean']}/7</b><div style="font:500 11px/1 Inter,sans-serif;color:var(--c-mute)">top-2-box {aggregates['likerts']['Q7']['top2box']}%</div>{bar(aggregates['likerts']['Q7']['top2box'], "#62aef0")}</div>
    <div class="card"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Q8 NPS</div><b style="font-size:28px">{aggregates['nps']['score']}</b><div style="font:500 11px/1 Inter,sans-serif;color:var(--c-mute)">{aggregates['nps']['promoters']}% promoters · {aggregates['nps']['detractors']}% detractors</div>{bar(aggregates['nps']['promoters'], "#0075de")}</div>
    <div class="card"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Signal</div><div style="font:500 12px/1.4 Inter,sans-serif;margin-top:6px">Synthetic — persona-grounded. Each “why” cites an anchor from the dossier. Treat Q11/Q12 open text as the richest signal.</div></div>
  </div>
</section>
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">03 · Usefulness by Hermes capability (Q2–Q6)</div>
  <div class="grid3">{likert_rows}</div>
</section>
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">04 · Journey & priorities</div>
  <div class="grid2">
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Q9 Journey preference</div><div style="margin-top:8px">{journey_rows or "<div style='color:var(--c-mute)'>No data</div>"}</div></div>
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Q10 Top 3 capabilities (up to 3 each)</div><div style="margin-top:8px">{top3_rows or "<div style='color:var(--c-mute)'>No data</div>"}</div></div>
  </div>
</section>
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">05 · Individual simulated responses — click card for dossier</div>
  <div class="grid2">{cards}</div>
</section>
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">06 · Instrument & reproducibility</div>
  <div class="grid2">
    <div class="card" style="background:#f6f5f4"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Survey instrument (12 Qs)</div>
      <div style="font:500 12px/1.5 Inter,sans-serif;margin-top:8px">Q1–Q7 Likert 1-7 · Q8 NPS 0-10 · Q9 single choice (Journey A/B/Neither/Undecided) · Q10 max-3 · Q11–Q12 open (≤280 chars). Grounded in SOP v6 sections cited above.</div>
      <div style="font:500 11px/1.4 Inter,sans-serif;color:var(--c-mute);margin-top:8px">Prompt-cache: system=instrument (stable, ~3k tokens), user=persona summary (variable, ~1k). DeepSeek context caching on system prefix.</div>
    </div>
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Files</div>
      <div style="font:500 12px/1.5 Inter,sans-serif;margin-top:8px">
        <code>responses.jsonl</code> — one JSON per persona (full Q1..Q12 + why)<br/>
        <code>responses.csv</code> — flat table for Sheets/Excel<br/>
        <code>personas.jsonl</code> — source dossiers (V3.3)<br/>
        Re-run: <code>python synthetic_survey.py --personas ../dataset-pilot-20-deepseek/personas.jsonl --out .</code>
      </div>
    </div>
  </div>
</section>
<div style="padding:12px 0;text-align:center;font:500 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute);border-top:1px solid var(--c-rule);margin-top:12px">MONOCLE · Pipeline 3 · r/{esc(subreddit)} · {now} · Synthetic — not fielded · Single-file HTML — opens offline</div>
</div>
</body></html>"""

def main():
    ap = argparse.ArgumentParser(description="Pipeline 3: synthetic survey simulation")
    ap.add_argument("--personas", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--population", type=int, default=None)
    ap.add_argument("--subreddit", default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--instrument", default=None, help="Path to custom 12-Q instrument JSON (title/intro/questions). If omitted, uses SOP-v6 UCC Hermes instrument.")
    args = ap.parse_args()
    _load_env_file()
    # Load custom instrument if provided (e.g. Decision>Prediction for r/stocks)
    global SURVEY_INSTRUMENT
    if args.instrument:
        try:
            custom = json.loads(Path(args.instrument).read_text())
            SURVEY_INSTRUMENT = custom
            print(f"[survey] custom instrument: {custom.get('title','(no title)')[:80]} ({len(custom.get('questions',[]))} Qs)", file=sys.stderr)
        except Exception as e:
            print(f"[survey] failed to load --instrument {args.instrument}: {e}", file=sys.stderr); sys.exit(1)
    personas_path = Path(args.personas)
    outdir = Path(args.out); outdir.mkdir(parents=True, exist_ok=True)
    rubrics = []
    for line in personas_path.read_text().splitlines():
        if not line.strip(): continue
        try:
            r = json.loads(line)
            author = r.get("author")
            candidate = personas_path.parent / "dossiers" / f"u_{author}.json"
            if candidate.exists():
                try:
                    full = json.loads(candidate.read_text())
                    for k in ["engine","big_five","style","one_line","quotes","arguments","persona_stack","engine_metrics"]:
                        if k not in r or not r[k]:
                            if k in full: r[k] = full[k]
                    if "one_line" not in r and "one_line_summary" in full:
                        r["one_line"] = full["one_line_summary"]
                except: pass
            rubrics.append(r)
        except Exception as e:
            print(f"[survey] skip bad line: {e}", file=sys.stderr)
    if not rubrics:
        print("[survey] no rubrics found", file=sys.stderr); sys.exit(1)
    subreddit = args.subreddit or personas_path.parent.name.replace("dataset-pilot-20-deepseek","").strip("/-") or "parenting"
    try:
        mpath = personas_path.parent / "manifest.json"
        if mpath.exists():
            mj = json.loads(mpath.read_text())
            subreddit = mj.get("subreddit", subreddit)
    except: pass
    population = args.population
    if population is None:
        try:
            from analyze import api_get
            data = api_get("/api/subreddits/search", {"subreddit": subreddit, "limit": 1, "meta-app": "reddit-intel"})
            population = (data.get("data") or [{}])[0].get("subscribers") or 8056434
        except:
            population = 8056434
    print(f"[survey] r/{subreddit} N≈{population:,} · {len(rubrics)} personas · model={args.model} llm={not args.no_llm}", file=sys.stderr)
    # checkpoint: resume from existing responses.jsonl if present
    jsonl_path_ck = outdir / "responses.jsonl"
    existing_by_author = {}
    if jsonl_path_ck.exists():
        for line in jsonl_path_ck.read_text().splitlines():
            if line.strip():
                try:
                    j=json.loads(line)
                    if j.get("author"): existing_by_author[j["author"]] = j
                except: pass
        if existing_by_author:
            print(f"[survey] resume: {len(existing_by_author)} existing responses, will skip those authors", file=sys.stderr)
    todo_rubrics = [r for r in rubrics if r.get("author") not in existing_by_author]
    # rehydrate skipped as full response dicts
    responses_rehydrated = []
    rubrics_by_author = {r.get("author"): r for r in rubrics}
    for author, j in existing_by_author.items():
        r = rubrics_by_author.get(author)
        if r is not None:
            j["_author"] = author
            j["_rubric"] = r
            responses_rehydrated.append(j)
    responses = []
    def run_one(rubric):
        if args.no_llm:
            ans = heuristic_simulate(rubric)
        else:
            ans = simulate_one(rubric, args.model)
            if "_error" in ans:
                print(f"[survey] u/{rubric.get('author')} error: {ans.get('_error')[:120]}", file=sys.stderr)
                ans = heuristic_simulate(rubric); ans["_fallback"] = True
        ans["_author"] = rubric.get("author")
        ans["_rubric"] = rubric
        # incremental checkpoint: append to jsonl
        try:
            _ck_path = outdir / "responses.jsonl"
            out_ck = {"author": ans["_author"], **{k: v for k,v in ans.items() if not k.startswith("_")}}
            with open(_ck_path, "a") as _f:
                _f.write(json.dumps(out_ck, ensure_ascii=False) + "\n")
        except: pass
        return ans
    # merge rehydrated (already on disk) with to-do futures
    with ThreadPoolExecutor(max_workers=max(1, min(4, args.concurrency))) as ex:
        futs = {ex.submit(run_one, r): r.get("author") for r in todo_rubrics}
        for fut in as_completed(futs):
            try: responses_rehydrated.append(fut.result())
            except Exception as e: print(f"[survey] fut fail: {e}", file=sys.stderr)
    responses = responses_rehydrated
    responses.sort(key=lambda x: x.get("_author",""))
    jsonl_path = outdir / "responses.jsonl"
    with open(jsonl_path, "w") as f:
        for r in responses:
            out = {"author": r["_author"], **{k: v for k,v in r.items() if not k.startswith("_")}}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    csv_path = outdir / "responses.csv"
    headers = ["author","engine_sig","Q1","Q1_why","Q2","Q3","Q4","Q5","Q6","Q7","Q7_why","Q8_NPS","Q8_why","Q9_choice","Q9_why","Q10_choices","Q11_text","Q12_text"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in responses:
            eng_sig = (r.get("_rubric",{}).get("engine") or {}).get("signature","")
            w.writerow({"author": r["_author"],"engine_sig": eng_sig,"Q1": r.get("Q1",{}).get("score",""),"Q1_why": r.get("Q1",{}).get("why",""),"Q2": r.get("Q2",{}).get("score",""),"Q3": r.get("Q3",{}).get("score",""),"Q4": r.get("Q4",{}).get("score",""),"Q5": r.get("Q5",{}).get("score",""),"Q6": r.get("Q6",{}).get("score",""),"Q7": r.get("Q7",{}).get("score",""),"Q7_why": r.get("Q7",{}).get("why",""),"Q8_NPS": r.get("Q8",{}).get("score",""),"Q8_why": r.get("Q8",{}).get("why",""),"Q9_choice": r.get("Q9",{}).get("choice",""),"Q9_why": r.get("Q9",{}).get("why",""),"Q10_choices": "; ".join(r.get("Q10",{}).get("choices",[])),"Q11_text": r.get("Q11",{}).get("text",""),"Q12_text": r.get("Q12",{}).get("text","")})
    (outdir / "survey-instrument.json").write_text(json.dumps(SURVEY_INSTRUMENT, indent=2, ensure_ascii=False))
    aggregates = aggregate(responses)
    (outdir / "aggregates.json").write_text(json.dumps(aggregates, indent=2))
    html = render_report(subreddit, population, responses, aggregates, SURVEY_INSTRUMENT)
    report_path = outdir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"[survey] wrote {jsonl_path} ({len(responses)} responses)", file=sys.stderr)
    print(f"[survey] wrote {csv_path}", file=sys.stderr)
    print(f"[survey] wrote {report_path} ({len(html)} bytes)", file=sys.stderr)
    print(f"[survey] aggregates: Q1 mean {aggregates['likerts']['Q1']['mean']} NPS {aggregates['nps']['score']} journeys {aggregates['journeys']}", file=sys.stderr)
    print(str(report_path))

if __name__ == "__main__":
    main()
