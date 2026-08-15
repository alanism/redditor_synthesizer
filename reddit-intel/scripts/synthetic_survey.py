#!/usr/bin/env python3
"""
synthetic_survey.py — Pipeline 3: synthetic survey simulation on top of dossiers.

Given a personas.jsonl (from build_dataset.py), simulate how each persona would
answer any product/concept survey (instrument-driven, subreddit-agnostic) — usefulness for parents involved
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

SURVEY_SYSTEM_PROMPT = """You are a survey simulator. Given a Reddit persona's communication style and worldview (engine, Big Five, anchors), simulate how THEY would answer the survey described in SURVEY INSTRUMENT.

Rules:
- Stay in character. Use the persona's directness, warmth, skepticism, and vocabulary.
- Likert/NPS: return integers in range. Distribution should reflect the persona's actual values — use their anchors, quotes, and Big Five to calibrate optimism vs skepticism.
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
    def _first_choice(qid):
        for qq in SURVEY_INSTRUMENT.get("questions", []):
            if qq.get("id")==qid and qq.get("options"):
                return qq["options"][0]
        return "Heuristic choice"
    def _first_max3(qid):
        for qq in SURVEY_INSTRUMENT.get("questions", []):
            if qq.get("id")==qid and qq.get("options"):
                return qq["options"][:2]
        return ["Heuristic placeholder"]
    return {
        "Q1": {"score": likert(5), "why": "heuristic — no LLM key"},
        "Q2": {"score": likert(5), "why": "heuristic"},
        "Q3": {"score": likert(5), "why": "heuristic"},
        "Q4": {"score": likert(4), "why": "heuristic"},
        "Q5": {"score": likert(5), "why": "heuristic"},
        "Q6": {"score": likert(5), "why": "heuristic"},
        "Q7": {"score": likert(4), "why": "heuristic"},
        "Q8": {"score": random.randint(5,8), "why": "heuristic"},
        "Q9": {"choice": _first_choice("Q9"), "why": "heuristic default"},
        "Q10": {"choices": _first_max3("Q10"), "why": "heuristic"},
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


# ── Subreddit-agnostic report helpers ─────────────────────────────────────

SYNTHETIC_WARNING = "Synthetic responses are simulations of likely opinions and language patterns. They are not responses from these Redditors and should not be treated as population estimates."

def _derive_segments(responses: list) -> dict:
    """Group responses into cohorts by Engine signature for audience composition / segment comparison."""
    buckets: dict = {}
    for r in responses:
        eng = (r.get("_rubric", {}).get("engine") or {})
        c = eng.get("C")
        f = eng.get("F")
        # simple deterministic 3-way split: analyst / pragmatist / skeptic — derived from C and F
        try:
            cs = float(c) if c is not None else 2.5
            fs = float(f) if f is not None else 2.5
        except: cs, fs = 2.5, 2.5
        if cs >= 4 and fs >= 3.5:
            key = "High-Context Analysts"
        elif cs >= 3.5:
            key = "Pragmatists"
        else:
            key = "Skeptics / Low-Context"
        buckets.setdefault(key, []).append(r)
    # merge tiny buckets (<2) into Pragmatists for stability
    if len(buckets) > 1:
        tiny = [k for k,v in list(buckets.items()) if len(v) < 2]
        for k in tiny:
            if k != "Pragmatists":
                buckets.setdefault("Pragmatists", []).extend(buckets.pop(k))
    return buckets

def _top_choice_per_bucket(bucket_responses: list, qid: str, field: str = "choice"):
    from collections import Counter
    vals = []
    for r in bucket_responses:
        v = (r.get(qid) or {}).get(field)
        if isinstance(v, list):
            vals.extend([x for x in v if x])
        elif v:
            vals.append(v)
        elif qid == "Q10":
            vals.extend([x for x in (r.get(qid) or {}).get("choices", []) if x])
    if not vals: return "—"
    c = Counter(vals)
    return c.most_common(1)[0][0]

def _segment_stats(responses: list, segments: dict) -> list:
    out = []
    for name, bucket in segments.items():
        n = len(bucket)
        def mean_for(q):
            vals = [int((x.get(q) or {}).get("score", 0)) for x in bucket if (x.get(q) or {}).get("score") is not None]
            return round(sum(vals)/len(vals),2) if vals else 0
        q1 = mean_for("Q1")
        q7 = mean_for("Q7") if any(x.get("Q7") for x in bucket) else mean_for("Q3")
        # motivation / objection from open whys
        mot = _top_choice_per_bucket(bucket, "Q9") if any(x.get("Q9") for x in bucket) else "—"
        # most frequent Q10 choice in bucket as proxy for preferred framing / proof
        proof = _top_choice_per_bucket(bucket, "Q10", "choices")
        # blocker: most common first words of Q12
        blockers = [(x.get("Q12") or {}).get("text","")[:60] for x in bucket if (x.get("Q12") or {}).get("text")]
        blocker = blockers[0][:50] + "…" if blockers else "—"
        out.append({"name": name, "n": n, "q1": q1, "q7": q7, "motivation": mot[:80], "objection": blocker, "proof": proof[:80]})
    return sorted(out, key=lambda x: x["q1"], reverse=True)

def _barrier_themes(responses: list) -> list:
    from collections import Counter
    import re
    words = []
    for r in responses:
        txt = ((r.get("Q12") or {}).get("text","") + " " + (r.get("Q6") or {}).get("text","") + " " + (r.get("Q12") or {}).get("why","")).lower()
        # simple keyword buckets
        for kw in ["trust","hallucin","price","pricing","cost","setup","onboarding","time","privacy","control","complex","learning curve","not useful","accuracy","wrong","disappoint","integration","standalone","hermes","evidence","source","manual"]:
            if kw in txt:
                words.append(kw if kw not in ("hermes","evidence") else "trust/evidence")
    c = Counter(words)
    return c.most_common(8)

def _value_ranking(instrument: dict, aggregates: dict) -> list:
    order = []
    for q in instrument.get("questions", []):
        qid = q["id"]
        if qid in aggregates.get("likerts", {}):
            order.append((q.get("prompt","")[:70], aggregates["likerts"][qid]["mean"], qid))
    return sorted(order, key=lambda x: x[1], reverse=True)

def render_report(subreddit: str, population: int, responses: list, aggregates: dict, instrument: dict, meta=None) -> str:
    meta = meta or {}
    esc = lambda s: htmlmod.escape(s or "", quote=False)
    now = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    run_id = meta.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    n = len(responses)
    import math, json as _json
    def margin_for(n_, N, z=1.96, p=0.5):
        if n_ >= N: return 0
        if n_ <= 0: return 0
        fpc = (N - n_) / (N - 1) if N > 1 else 1
        var = p*(1-p)/n_ * fpc
        return z * math.sqrt(var)
    pilot_margin = margin_for(n, population) * 100
    def bar(pct, color="#ffc500"):
        pct = max(0, min(100, float(pct)))
        return f'<div style="height:10px;background:#eee;border-radius:9999px;overflow:hidden"><div style="width:{pct}%;height:100%;background:{color}"></div></div>'
    def chip(t, bg="#ffc500"):
        return f'<span style="display:inline-block;font:700 10px/1 Inter,system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;padding:4px 8px;border-radius:9999px;background:{bg};border:1px solid rgba(0,0,0,.08)">{esc(t)}</span>'
    # instrument-agnostic Q discovery
    q_by_id = {q["id"]: q for q in instrument.get("questions", [])}
    likert_qs = [q for q in instrument.get("questions", []) if q.get("id") in aggregates.get("likerts", {})]
    # derive segments and value ranking generically
    segments = _derive_segments(responses)
    seg_stats = _segment_stats(responses, segments) if segments else []
    ranking = _value_ranking(instrument, aggregates)
    barriers = _barrier_themes(responses)
    # strongest positive / barrier (generic: top likert mean, lowest / most common Q12 theme)
    strongest_q = max(likert_qs, key=lambda q: aggregates["likerts"][q["id"]]["mean"]) if likert_qs else None
    weakest_q = min(likert_qs, key=lambda q: aggregates["likerts"][q["id"]]["mean"]) if likert_qs else None
    barrier_label = barriers[0][0] if barriers else "see Q12 open text"
    top_segment = seg_stats[0]["name"] if seg_stats else "—"
    # recommended next experiment: generic, tied to top barrier
    next_exp_map = {"trust": "Blind trust / source-verification test with real users", "price": "Willingness-to-pay / pricing ladder test", "setup": "First-use onboarding burden test", "time": "Time-to-value / setup friction test"}
    next_exp = next_exp_map.get(barrier_label.split("/")[0], "Message comparison: architecture-led vs outcome-led explanation")
    # --- build HTML fragments ---
    # 0) likert cards
    likert_rows = ""
    for q in likert_qs:
        qid = q["id"]
        st = aggregates["likerts"][qid]
        _dist = st.get("dist", {})
        likert_rows += f'<div style="border:1px solid #d9d9d9;background:#fff;border-radius:12px;padding:14px"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e">{esc(qid)} · {esc(q.get("prompt","")[:90])}</div><div style="display:flex;align-items:baseline;gap:10px;margin-top:8px"><b style="font-size:28px;letter-spacing:-.02em">{st.get("mean",0)}</b><span style="font:500 11px/1 Inter,sans-serif;color:#6e6e6e">mean · median {st.get("median",0)} · top-2-box {st.get("top2box",0)}%</span></div>{bar(st.get("top2box",0))}<div style="font:500 11px/1.4 Inter,sans-serif;color:#6e6e6e;margin-top:6px">n={st.get("n",0)} · dist {_json.dumps(_dist)}</div></div>'
    # 1) value ranking bars
    ranking_rows = "".join(f'<div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #eee"><span style="flex:1;font:500 12px/1.3 Inter,sans-serif">{esc(lbl[:64])}</span><span style="font:700 13px/1 Inter,sans-serif;min-width:44px;text-align:right">{m:.1f}</span><span style="width:90px">{bar((m-1)/6*100, "#0075de" if i==0 else "#62aef0")}</span></div>' for i,(lbl,m,_qid) in enumerate(ranking))
    # 2) funnel (Q1 relevance -> usefulness -> try -> recommend -> barrier inverse)
    funnel = []
    for qid, label, color in [("Q1","Usefulness","#ffc500"),("Q7","Try","#62aef0"),("Q8","Recommend (NPS)","#0075de")]:
        vals = []
        if qid == "Q8":
            vals = [int((x.get("Q8") or {}).get("score", 0)) for x in responses if (x.get("Q8") or {}).get("score") is not None]
            pct = sum(1 for v in vals if v >= 7)/len(vals)*100 if vals else 0
        else:
            vals = [int((x.get(qid) or {}).get("score", 0)) for x in responses if (x.get(qid) or {}).get("score") is not None]
            pct = sum(1 for v in vals if v >= 5)/len(vals)*100 if vals else 0
        funnel.append((label, pct, color))
    funnel_rows = "".join(f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0"><span style="min-width:140px;font:700 11px/1 Inter,sans-serif;letter-spacing:.05em;text-transform:uppercase;color:#6e6e6e">{esc(lbl)}</span><span style="flex:1">{bar(p, c)}</span><span style="min-width:44px;font:700 12px/1 Inter,sans-serif;text-align:right">{p:.0f}%</span></div>' for lbl,p,c in funnel)
    # 3) barrier chart
    max_b = max((v for _,v in barriers), default=1)
    barrier_rows = "".join(f'<div style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid #f0ece6"><span style="min-width:140px;font:500 12px/1 Inter,sans-serif">{esc(k)}</span><span style="flex:1">{bar(v/max_b*100, "#c0392b")}</span><span style="min-width:28px;font:700 12px/1 Inter,sans-serif;text-align:right">{v}</span></div>' for k,v in barriers) or '<div style="color:#6e6e6e;font:500 12px/1 Inter,sans-serif">No dominant barrier phrase in Q12 at this n — read open text directly.</div>'
    # 4) segment table
    seg_head = '<div style="display:grid;grid-template-columns:1.2fr .6fr .6fr 1fr 1fr;gap:8px;padding:8px 10px;background:#f6f5f4;border-radius:10px;font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e"><span>Segment</span><span>Value</span><span>Try</span><span>Motivation</span><span>Objection</span></div>'
    seg_rows = "".join(f'<div style="display:grid;grid-template-columns:1.2fr .6fr .6fr 1fr 1fr;gap:8px;padding:10px;border-bottom:1px solid #eee;align-items:center"><span style="font:600 12px/1 Inter,sans-serif">{esc(s["name"])} <span style="color:#6e6e6e;font-weight:500">n={s["n"]}</span></span><span style="font:700 13px/1 Inter,sans-serif">{s["q1"]:.1f}</span><span style="font:700 13px/1 Inter,sans-serif">{s["q7"]:.1f}</span><span style="font:500 11px/1.3 Inter,sans-serif">{esc(s["motivation"])}</span><span style="font:500 11px/1.3 Inter,sans-serif;color:#615d59">{esc(s["objection"])}</span></div>' for s in seg_stats)
    # 5) single-choice / max-3 summaries (generic: detect any single_choice / max_3 in instrument)
    choice_blocks = ""
    for q in instrument.get("questions", []):
        if q.get("type") == "single_choice":
            counts = aggregates.get("journeys", {}) if q["id"] == "Q9" else {}
            # generic fallback: count any single_choice answers if journeys empty
            if not counts:
                raw = [(x.get(q["id"]) or {}).get("choice") for x in responses]
                from collections import Counter as _C
                counts = dict(_C([v for v in raw if v]))
            if counts:
                rows = "".join(f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #eee'><span style='font:500 12px/1 Inter,sans-serif'>{esc(k)}</span><b style='font:700 12px/1 Inter,sans-serif'>{v}</b></div>" for k,v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
                choice_blocks += f'<div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e">{esc(q["id"])} · {esc(q.get("prompt","")[:60])}</div><div style="margin-top:8px">{rows}</div></div>'
        elif q.get("type") == "max_3":
            counts = aggregates.get("top3", {})
            if not counts:
                from collections import Counter as _C2
                flat = []
                for x in responses: flat.extend((x.get(q["id"]) or {}).get("choices", []))
                counts = dict(_C2(flat))
            if counts:
                rows2 = "".join(f"<div style='display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #eee'><span style='font:500 12px/1 Inter,sans-serif'>{esc(k)}</span><span style='font:700 12px/1 Inter,sans-serif'>{v} · {round(v/max(1,n)*100,1)}%</span></div>" for k,v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
                choice_blocks += f'<div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e">{esc(q["id"])} · {esc(q.get("prompt","")[:60])}</div><div style="margin-top:8px">{rows2}</div></div>'
    # 6) respondent cards (generic: show Q1 + Q7/NPS + primary choice)
    cards = ""
    for r in responses:
        author = esc(r.get("_author","?"))
        eng_sig = esc((r.get("_rubric",{}).get("engine") or {}).get("signature", "—"))
        q1 = r.get("Q1",{}).get("score", "—")
        q7 = r.get("Q7",{}).get("score", r.get("Q3",{}).get("score", "—"))
        npsv = r.get("Q8",{}).get("score", "—")
        primary = ""
        if r.get("Q9"): primary = esc(r.get("Q9",{}).get("choice","")[:48])
        q11 = esc((r.get("Q11") or {}).get("text","")[:180])
        q12 = esc((r.get("Q12") or {}).get("text","")[:180])
        q1_why = esc((r.get("Q1") or {}).get("why","")[:110])
        # link: try canonical dataset path
        cards += f'<a href="../dataset-pilot-20/dossiers/u_{author}.html" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div style="border:1px solid #d9d9d9;background:#fff;border-radius:12px;padding:14px"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6e6e6e">u/{author} · {eng_sig}</div><div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">{chip(f"Q1 {q1}/7")} {chip(f"NPS {npsv}/10", "#e6f3fe")} {chip(primary, "#f6f5f4") if primary else ""}</div><div style="margin-top:10px;font:500 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#757575">What would make it helpful</div><div style="font:400 13px/1.45 Georgia,serif;margin-top:4px">“{q11}”</div><div style="margin-top:8px;font:500 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#757575">Blocker</div><div style="font:400 13px/1.45 Georgia,serif;margin-top:4px;color:#615d59">“{q12}”</div><div style="margin-top:8px;font:500 10px/1.3 Inter,sans-serif;color:#6e6e6e">{q1_why}</div></div></a>'
    # 7) final 8 (generic recommendations)
    strongest_insight = f"{strongest_q.get('prompt','')[:80]} — mean {aggregates['likerts'][strongest_q['id']]['mean']:.1f}/7" if strongest_q else "See value ranking"
    biggest_uncertainty = f"n={n} → ±{pilot_margin:.1f}% at 95%; synthetic, not fielded — language ≈ attitude > behavior"
    tradeoff = f"Strongest capability ({strongest_q['id'] if strongest_q else '—'}) vs weakest ({weakest_q['id'] if weakest_q else '—'}) — test whether weak signal is product or messaging"
    best_msg = "Test architecture-led vs outcome-led framing with real users (brief’s required experiment)"
    riskiest = f"Top barrier ‘{barrier_label}’ — if unaddressed, adoption intent collapses even among {top_segment}"
    product_change = f"Reduce friction for ‘{barrier_label}’ before adding features"
    real_test = next_exp
    cannot = "Simulation cannot establish causal behavior, willingness to pay, or population prevalence — only simulated language/attitude distributions"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="color-scheme" content="light"/>
<title>{esc(instrument.get("title","Synthetic Survey")[:80])} · r/{esc(subreddit)} · n={n}</title>
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
.warn{{background:#fff7cc;border:1px solid #e6c200;border-radius:12px;padding:12px 14px;font:500 12px/1.5 Inter,sans-serif}}
</style></head><body>
<div style="position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid var(--c-rule);display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:40px;font:700 13px/1 Inter,sans-serif;letter-spacing:.06em">HERMES · SYNTHETIC SURVEY · r/{esc(subreddit)} <span class="pill" style="background:var(--c-yellow)">n={n} simulated</span></div>
<div class="warn" style="max-width:1100px;margin:12px auto 0;padding:10px 14px;text-align:center">⚠ {esc(SYNTHETIC_WARNING)}</div>
<header class="hero">
  <div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--c-mute)">{esc(instrument.get("title","Synthetic Survey")[:90])} · PIPELINE 3 · SYNTHETIC SURVEY</div>
  <h1 style="margin:8px 0 0;font-family:Georgia,serif;font-size:34px;line-height:1.05;letter-spacing:-.03em">What <em style="font-style:normal;background:linear-gradient(transparent 60%,var(--c-yellow) 60% 88%,transparent 88%)">r/{esc(subreddit)}</em> appears to value — and what would prevent adoption</h1>
  <p style="max-width:68ch;color:var(--c-mute);line-height:1.5;margin:10px 0 0">{esc(instrument.get("intro","Synthetic responses simulated from V3.3 dossiers — engine, Big Five, and verbatim anchors shape Likert, NPS, choice, and open text.")[:520])}</p>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><span class="pill" style="background:var(--c-yellow)">n={n} simulated respondents</span><span class="pill">r/{esc(subreddit)} · N≈{population:,}</span><span class="pill">instrument: {len(instrument.get("questions",[]))} questions</span><span class="pill">run {esc(run_id)}</span></div>
</header>
<div style="max-width:1100px;margin:0 auto;padding:0 16px">
<!-- 01 EXECUTIVE SUMMARY -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">01 · Executive summary — what this community appears to value</div>
  <div class="grid2">
    <div class="card" style="background:#fdfcf3">
      <div style="font:700 13px/1 Inter,sans-serif">Product / concept</div>
      <div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px;color:#2b2b2b">{esc(instrument.get("title","—"))}</div>
      <div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Source</div><div style="font:700 12px/1 Inter,sans-serif;margin-top:4px">r/{esc(subreddit)} · N={population:,}</div><div style="font:500 11px/1 Inter,sans-serif;color:var(--c-mute)">{n} source Redditors · {n} simulated</div></div>
        <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Strongest signal</div><div style="font:700 12px/1.3 Inter,sans-serif;margin-top:4px">{esc(strongest_insight)}</div></div>
      </div>
      <div style="margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#8a1f1f">Strongest barrier</div><div style="font:700 12px/1.3 Inter,sans-serif;margin-top:4px">{esc(barrier_label)}</div></div>
        <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Most promising segment</div><div style="font:700 12px/1.3 Inter,sans-serif;margin-top:4px">{esc(top_segment)} (n={[s["n"] for s in seg_stats if s["name"]==top_segment][0] if top_segment!="—" and seg_stats else 0})</div></div>
      </div>
      <div style="margin-top:12px;padding:10px;background:#fff;border:1px solid var(--c-rule);border-radius:10px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Recommended next experiment</div><div style="font:700 12px/1.4 Inter,sans-serif;margin-top:4px">{esc(real_test)}</div></div>
    </div>
    <div class="card">
      <div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">At a glance</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px">
        <div style="border:1px solid var(--c-rule);border-radius:12px;padding:12px;background:var(--c-yellow)"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase">Strongest positive</div><b style="font-size:22px">{aggregates["likerts"][strongest_q["id"]]["mean"] if strongest_q else "—"}/7</b><div style="font:500 11px/1 Inter,sans-serif;color:rgba(0,0,0,.6)">{esc(strongest_q["id"] if strongest_q else "—")} · top-2-box {aggregates["likerts"][strongest_q["id"]]["top2box"] if strongest_q else 0}%</div></div>
        <div style="border:1px solid var(--c-rule);border-radius:12px;padding:12px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Weakest signal</div><b style="font-size:22px">{aggregates["likerts"][weakest_q["id"]]["mean"] if weakest_q else "—"}/7</b><div style="font:500 11px/1 Inter,sans-serif;color:var(--c-mute)">{esc(weakest_q["id"] if weakest_q else "—")} · top-2-box {aggregates["likerts"][weakest_q["id"]]["top2box"] if weakest_q else 0}%</div></div>
      </div>
      <div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div style="border:1px solid var(--c-rule);border-radius:12px;padding:12px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Adoption intent (Q7)</div><b style="font-size:20px">{aggregates["likerts"].get("Q7",{}).get("mean", aggregates["likerts"].get("Q1",{}).get("mean",0))}/7</b><div style="font:500 11px/1 Inter,sans-serif;color:var(--c-mute)">top-2-box {aggregates["likerts"].get("Q7",{}).get("top2box", 0)}%</div></div>
        <div style="border:1px solid var(--c-rule);border-radius:12px;padding:12px"><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">NPS</div><b style="font-size:20px">{aggregates["nps"]["score"]}</b><div style="font:500 11px/1 Inter,sans-serif;color:var(--c-mute)">{aggregates["nps"]["promoters"]}% prom · {aggregates["nps"]["detractors"]}% detr</div></div>
      </div>
      <div style="margin-top:10px;font:500 11px/1.4 Inter,sans-serif;color:var(--c-mute)">Sample-size note: with N={population:,} @95%/±5% need 385. This pilot n={n} → ±{pilot_margin:.1f}% — directionally useful, not inferential.</div>
    </div>
  </div>
</section>
<!-- 02 METHODOLOGY + LIMITATIONS -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">02 · Methodology and limitations — what was simulated, what was not</div>
  <div class="card" style="background:#fff">
    <div style="display:grid;grid-template-columns:1.15fr .85fr;gap:14px">
      <div>
        <div style="font:700 12px/1 Inter,sans-serif">Five layers — do not conflate</div>
        <ol style="margin:8px 0 0 18px;font:500 12px/1.6 Inter,sans-serif;color:#2b2b2b">
          <li><b>Comments collected</b> — Arctic Shift archive, r/{esc(subreddit)}, {n} Redditors, ~{n*30} comments (limit 30/author), {esc(meta.get("collection_period","7d window"))}</li>
          <li><b>Profiles inferred</b> — V3.3 dossier per author (Engine C/F/A1/A2/P, Big Five, quotes, arguments, one_line); inferred independently per author</li>
          <li><b>Synthetic responses generated</b> — one simulated completion per persona via <code>{esc(meta.get("model","deepseek-v4-flash"))}</code> (prompt v{esc(meta.get("prompt_version","3"))}, seed {esc(meta.get("seed","run_id"))})</li>
          <li><b>Metrics calculated</b> — mean/median/top-2-box/dist per Likert; NPS; choice/max-3 frequencies; segment splits</li>
          <li><b>Real-world evidence</b> — {esc(meta.get("real_world_evidence","none in this pilot — calibration requires fielded interviews/surveys/conversions; see scorecard below"))}</li>
        </ol>
        <div class="warn" style="margin-top:12px">⚠ {esc(SYNTHETIC_WARNING)}</div>
      </div>
      <div style="border:1px solid var(--c-rule);border-radius:12px;padding:12px;background:#f6f5f4">
        <div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Run provenance</div>
        <table style="width:100%;margin-top:8px;border-collapse:collapse;font:500 11px/1.4 Inter,sans-serif">
          <tr><td style="color:var(--c-mute);padding:4px 8px 4px 0">Source</td><td><b>r/{esc(subreddit)}</b> · N={population:,}</td></tr>
          <tr><td style="color:var(--c-mute);padding:4px 8px 4px 0">Authors / comments</td><td>{n} / ~{n*30} · ≥30/author where available</td></tr>
          <tr><td style="color:var(--c-mute);padding:4px 8px 4px 0">Selection</td><td>{esc(meta.get("selection","top commenters by recent activity; thin authors (&lt;20 comments) skipped; 0 removed for this report"))}</td></tr>
          <tr><td style="color:var(--c-mute);padding:4px 8px 4px 0">Model / prompt</td><td>{esc(meta.get("model","deepseek-v4-flash"))} · prompt v{esc(meta.get("prompt_version","3"))} · run {esc(run_id)}</td></tr>
          <tr><td style="color:var(--c-mute);padding:4px 8px 4px 0">Independence</td><td>One simulation per persona; no cross-persona context</td></tr>
          <tr><td style="color:var(--c-mute);padding:4px 8px 4px 0">Heuristic fallback</td><td>{aggregates.get("heuristic_count",0)} of {n} (re-run with DEEPSEEK_API_KEY for full LLM)</td></tr>
        </table>
        <div style="margin-top:10px;font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Known biases</div>
        <ul style="margin:6px 0 0 16px;font:500 11px/1.5 Inter,sans-serif;color:#6e6e6e">
          <li>Sampling: Reddit-active only; thin authors excluded may underrepresent lurkers/casuals</li>
          <li>Model: LLM conservatism + persona anchoring may overstate barriers vs field</li>
          <li>n={n} · use for hypothesis generation (brief’s guidance: 20=“qual”, 50–100=“themes”, 100–300=“segments”)</li>
          <li>Language ≈ attitude &gt; behavior: confidence in wording does not transfer to purchase/retention</li>
        </ul>
      </div>
    </div>
  </div>
</section>
<!-- 03 AUDIENCE COMPOSITION -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">03 · Audience composition — who this community appears to be</div>
  <div class="card">
    <div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Inferred segments (Engine C/F-derived; not generic personality labels)</div>
    <div style="margin-top:10px">{seg_head}{seg_rows or '<div style="padding:10px;color:#6e6e6e">Insufficient n for stable segments — recruit to 50+ per brief.</div>'}</div>
    <details style="margin-top:10px"><summary style="cursor:pointer;font:600 11px/1 Inter,sans-serif;color:var(--c-blue)">Segment dimensions the brief recommends capturing (show when n≥50)</summary><div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">{chip("experience: beginner ↔ expert","#f6f5f4")} {chip("enthusiast ↔ skeptic","#f6f5f4")} {chip("professional ↔ hobbyist","#f6f5f4")} {chip("spending power","#f6f5f4")} {chip("privacy sensitivity","#f6f5f4")} {chip("urgency","#f6f5f4")} {chip("current alternatives","#f6f5f4")} {chip("technical comfort","#f6f5f4")} {chip("identity investment","#f6f5f4")}</div><div style="font:500 11px/1.4 Inter,sans-serif;color:#6e6e6e;margin-top:6px">Do not impose categories unsupported by source data — these are prompts for the analyst to code from quotes when n is larger.</div></details>
  </div>
</section>
<!-- 04 CONCEPT EVALUATION -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">04 · Concept evaluation — usefulness, relevance, and what prevents adoption</div>
  <div class="grid3">{likert_rows or '<div style="color:#6e6e6e">No Likert questions in instrument.</div>'}</div>
  <div style="margin-top:12px" class="grid2"><div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Adoption funnel (generic)</div><div style="margin-top:8px">{funnel_rows}</div><div style="font:500 11px/1.3 Inter,sans-serif;color:#6e6e6e;margin-top:8px">% scoring ≥5 (Likert) or ≥7 (NPS). Real funnel requires fielded awareness ↔ trial ↔ repeat.</div></div><div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Barrier frequency (from Q12 open text)</div><div style="margin-top:8px">{barrier_rows}</div></div></div>
</section>
<!-- 05 VALUE RANKING + SEGMENT COMPARISON -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">05 · Segment comparison — which groups differ meaningfully</div>
  <div class="grid2">
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Value ranking (which benefits score highest)</div><div style="margin-top:8px">{ranking_rows or '<div style="color:#6e6e6e">No Likert ranking available.</div>'}</div></div>
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">What people use instead — and switching triggers (from Q11/Q12)</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:8px;color:#2b2b2b">Read Q11 “what would make it helpful” + Q12 “blocker” per respondent below for alternatives and triggers. At n≥50, code alternatives into: <code>current-alternative map</code> (manual, spreadsheet, competing app, nothing) and triggers (price drop, trust proof, integration, failure of current tool).</div><div style="margin-top:10px;font:500 11px/1.4 Inter,sans-serif;color:#6e6e6e">Decision-journey and message-comparison views are instrument-dependent — add them when you test multiple framings (architecture-led vs outcome-led).</div></div>
  </div>
  <div class="card" style="margin-top:12px"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Per-segment detail — value · intent · motivation · objection · proof needed · trigger (brief §5)</div><div style="margin-top:8px">{seg_head}{seg_rows or '<div style="padding:10px;color:#6e6e6e">Segment table requires n≥20 with valid Engine scores.</div>'}</div><div style="font:500 11px/1.3 Inter,sans-serif;color:#6e6e6e;margin-top:8px">Cut the data by inferred segment, not by treating the subreddit as one audience. At n=20, treat segment deltas as hypotheses.</div></div>
</section>
<!-- 06 INDIVIDUAL RESPONSES -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">06 · Simulated individual responses — click card for dossier</div>
  <div class="grid2">{cards}</div>
</section>
<!-- 07 CALIBRATION & TRUST -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">07 · Calibration and trust — where synthetic predictions should and should not be used</div>
  <div class="grid2">
    <div class="card" style="background:#fdfcf3"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase">Four prediction types — do not conflate</div><table style="width:100%;margin-top:8px;border-collapse:collapse;font:500 12px/1.4 Inter,sans-serif"><tr style="border-bottom:1px solid var(--c-rule)"><td style="padding:6px 8px 6px 0"><b>Language</b></td><td>What words/phrases this community uses</td><td style="text-align:right"><span class="pill" style="background:#d4edda">most reliable</span></td></tr><tr style="border-bottom:1px solid var(--c-rule)"><td style="padding:6px 8px 6px 0"><b>Attitude</b></td><td>Stated usefulness / intent</td><td style="text-align:right"><span class="pill" style="background:#fff3cd">moderate</span></td></tr><tr style="border-bottom:1px solid var(--c-rule)"><td style="padding:6px 8px 6px 0"><b>Behavior</b></td><td>Trial, setup, repeat use</td><td style="text-align:right"><span class="pill" style="background:#f8d7da">weak — field it</span></td></tr><tr><td style="padding:6px 8px 6px 0"><b>Business outcome</b></td><td>Paid conversion, churn</td><td style="text-align:right"><span class="pill" style="background:#f8d7da">do not infer</span></td></tr></table><div style="font:500 11px/1.4 Inter,sans-serif;color:#6e6e6e;margin-top:8px">Confidence in wording does not transfer to action. Each row needs its own calibration.</div></div>
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Calibration scorecard (fill as real evidence arrives)</div><table style="width:100%;margin-top:8px;border-collapse:collapse;font:500 11px/1.4 Inter,sans-serif"><tr style="background:#f6f5f4"><th style="text-align:left;padding:6px 8px">Signal</th><th style="text-align:left;padding:6px 8px">Synthetic</th><th style="text-align:left;padding:6px 8px">Real</th><th style="text-align:left;padding:6px 8px">Delta</th></tr><tr style="border-top:1px solid #eee"><td style="padding:6px 8px">Interview language</td><td style="padding:6px 8px">—</td><td style="padding:6px 8px;color:var(--c-mute)">pending</td><td style="padding:6px 8px">—</td></tr><tr style="border-top:1px solid #eee"><td style="padding:6px 8px">Landing-page CVR</td><td style="padding:6px 8px">—</td><td style="padding:6px 8px;color:var(--c-mute)">pending</td><td style="padding:6px 8px">—</td></tr><tr style="border-top:1px solid #eee"><td style="padding:6px 8px">Signup → activation</td><td style="padding:6px 8px">—</td><td style="padding:6px 8px;color:var(--c-mute)">pending</td><td style="padding:6px 8px">—</td></tr><tr style="border-top:1px solid #eee"><td style="padding:6px 8px">Repeat use / paid</td><td style="padding:6px 8px">—</td><td style="padding:6px 8px;color:var(--c-mute)">pending</td><td style="padding:6px 8px">—</td></tr></table><div style="font:500 11px/1.3 Inter,sans-serif;color:#6e6e6e;margin-top:8px">Sample-size guidance: 20=“qual hypotheses” · 50–100=“themes + message tests” · 100–300=“segments” · 1000+=“rare segments only”. Run multiple simulations per persona to separate person vs model variance.</div></div>
  </div>
</section>
<!-- 08 FINAL 8 -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">08 · What this simulation can establish — and what must be tested with real people</div>
  <div class="card" style="background:#0d0d0d;color:#f7f5f3;border-color:#0d0d0d">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Strongest insight (simulated)</div><div style="font:600 13px/1.4 Inter,sans-serif;margin-top:6px">{esc(strongest_insight)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Biggest uncertainty</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(biggest_uncertainty)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Top contradiction / trade-off</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(tradeoff)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Best-performing message (simulated)</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(best_msg)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Highest-risk assumption</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(riskiest)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Recommended product change</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(product_change)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">Recommended real-world test</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(real_test)}</div></div>
      <div><div style="font:700 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#c9c9c9">What simulation cannot establish</div><div style="font:500 12px/1.5 Inter,sans-serif;margin-top:6px">{esc(cannot)}</div></div>
    </div>
    <div style="margin-top:14px;padding:10px;background:#1a1a1a;border-radius:10px;font:500 11px/1.5 Inter,sans-serif;color:#c9c9c9">Goal: not a larger synthetic survey, but a clearer decision — what to build, who to target, how to communicate, and what must be tested with real people. Compare architecture-led vs outcome-led explanations to separate product signal from messaging signal.</div>
  </div>
</section>
<!-- APPENDIX -->
<section style="padding:18px 0;border-top:1px solid var(--c-rule)">
  <div class="eyebrow">Appendix · Instrument, choices, and files</div>
  <div class="grid2">
    <div class="card" style="background:#f6f5f4"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Instrument ({len(instrument.get("questions",[]))} questions)</div>
      <div style="font:500 12px/1.5 Inter,sans-serif;margin-top:8px">{esc(", ".join(f'{q["id"]}:{q.get("type","")}' for q in instrument.get("questions",[])))} — driven by <code>survey-instrument.json</code>; change the instrument per product without changing the template.</div>
      <div style="font:500 11px/1.4 Inter,sans-serif;color:var(--c-mute);margin-top:8px">Prompt-cache: system=instrument (stable, ~2–3k tokens), user=persona summary (variable, ~1k). DeepSeek context caching on system prefix.</div>
    </div>
    <div class="card"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Choice & trade-off summaries</div><div style="margin-top:8px;display:grid;gap:12px">{choice_blocks or '<div style="color:var(--c-mute);font:500 12px/1 Inter,sans-serif">No single_choice / max_3 in this instrument.</div>'}</div></div>
  </div>
  <div class="card" style="margin-top:12px"><div style="font:700 11px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute)">Files & reproducibility</div>
      <div style="font:500 12px/1.5 Inter,sans-serif;margin-top:8px">
        <code>responses.jsonl</code> — one JSON per persona (full answers + why)<br/>
        <code>responses.csv</code> — flat table for Sheets/Excel<br/>
        <code>personas.jsonl</code> — source dossiers (V3.3)<br/>
        <code>survey-instrument.json</code> — instrument used for this run<br/>
        <code>aggregates.json</code> — means/medians/top-2-box/dist<br/>
        Re-run: <code>python synthetic_survey.py --personas ../dataset-pilot-20/personas.jsonl --out . --instrument ./survey-instrument.json</code><br/>
        Range note: re-run with varied seeds / multiple simulations per persona to separate person vs model vs prompt variance.
      </div>
    </div>
</section>
<div style="padding:12px 0;text-align:center;font:500 10px/1 Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--c-mute);border-top:1px solid var(--c-rule);margin-top:12px">HERMES · Pipeline 3 · r/{esc(subreddit)} · {now} · Synthetic — not fielded · Single-file HTML — opens offline</div>
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
    # Build run provenance for methodology section
    _run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _meta = {
        "run_id": _run_id,
        "model": args.model if not args.no_llm else "heuristic",
        "prompt_version": "3",
        "seed": _run_id,
        "collection_period": "7d window (Arctic Shift)",
        "selection": "top commenters by recent activity; thin authors (<20 comments) skipped",
        "real_world_evidence": "none in this pilot — calibration requires fielded interviews/surveys/conversions",
    }
    try:
        _mpath = Path(args.personas).parent / "manifest.json"
        if _mpath.exists():
            import json as _jm
            _mj = _jm.loads(_mpath.read_text())
            _meta["selection"] = f"{len(_mj.get('authors',[]))} authors targeted, {len(_mj.get('failed',[]))} thin/failed"
    except: pass
    html = render_report(subreddit, population, responses, aggregates, SURVEY_INSTRUMENT, _meta)
    report_path = outdir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"[survey] wrote {jsonl_path} ({len(responses)} responses)", file=sys.stderr)
    print(f"[survey] wrote {csv_path}", file=sys.stderr)
    print(f"[survey] wrote {report_path} ({len(html)} bytes)", file=sys.stderr)
    print(f"[survey] aggregates: Q1 mean {aggregates['likerts']['Q1']['mean']} NPS {aggregates['nps']['score']} journeys {aggregates['journeys']}", file=sys.stderr)
    print(str(report_path))

if __name__ == "__main__":
    main()
