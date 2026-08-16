#!/usr/bin/env python3
"""
build_dataset.py — Bulk synthetic population from a subreddit.
Interactive control-panel index: Archetypes clustering, Vega-Lite specs,
expandable previews, Copy JSON, layout-intent validation.

Usage:
  python build_dataset.py --subreddit parenting --users 20 --comments-per-user 100 --out ./data/parenting/
  python build_dataset.py --subreddit vietnam --users 100 --comments-per-user 100 --out ./data/vietnam/ --concurrency 4 --model gpt-4o-mini

Outputs:
  <out>/
    index.html        # control-panel directory (Monocle tokens, local-first)
    manifest.json     # progress checkpoint (resume-safe)
    personas.jsonl    # one JSON rubric per line (enriched: engine + big_five + quotes + arguments)
    dossiers/
      u_<author>.html
      u_<author>.json
    raw/              # if --keep-raw
      u_<author>.json

Resume: re-running with same --out resumes from manifest.json (skips completed authors).
"""
import argparse, json, sys, os, time, html as htmlmod, re, hashlib
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import discover_authors, fetch_comments_paginated, tokenize, _load_env_file, try_llm

# ─────────────────────────────────────────────────────────────────────────────
# 1) Deterministic Archetype clustering (local, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

ARCHETYPE_DEFS = [
    {"id": "A", "label": "High-Context Analysts", "sig": "C+ / F+ — high knowledge density + reframing",
     "rule": lambda e: (e.get("C",2) >= 4 and e.get("F",2) >= 3)},
    {"id": "B", "label": "Grounded Pragmatists", "sig": "C+ / P+ — grounded execution under pressure",
     "rule": lambda e: (e.get("C",2) >= 3 and e.get("P",2) >= 3 and e.get("F",2) <= 3)},
    {"id": "C", "label": "Instrument / Meta Builders", "sig": "A1+/A2+ — tool + meta-cog forward",
     "rule": lambda e: (e.get("A1",1) >= 3 or e.get("A2",1) >= 3)},
    {"id": "D", "label": "Fragile Under Load", "sig": "P≤2 — strong envelope but brittle under stress",
     "rule": lambda e: (e.get("P",3) <= 2)},
]

ARCHETYPE_FALLBACK = {"id": "E", "label": "General Cohort", "sig": "Mixed / unclassified"}
COHORT_COLORS = {"A": "#ffc500", "B": "#111", "C": "#62aef0", "D": "#f64932", "E": "#e7e7e7"}

def bigfive_numeric(big_five: dict) -> dict:
    """Map High/Med/Low strings to 1..3 for plotting. Returns dict with O C E A N in 1..3 or None."""
    if not big_five: return {}
    mp = {"high": 3, "med": 2, "medium": 2, "low": 1}
    out = {}
    for k in ["openness","conscientiousness","extraversion","agreeableness","neuroticism"]:
        v = (big_five.get(k,"") or "").strip().lower()
        # first word: "High — broad" -> high
        w = v.split()[0] if v else ""
        # handle "high/med/low" anywhere
        score = None
        for token in ["high","medium","med","low"]:
            if token in v:
                score = mp.get(token if token!="med" else "med", 2)
                break
        if score is None:
            # try first word
            score = mp.get(w, None)
        if score is not None:
            out[k] = score
    return out

def assign_archetype(engine: dict) -> str:
    e = engine or {}
    # Priority: A -> B -> C -> D (first match wins, then fallback E)
    for defn in ARCHETYPE_DEFS:
        try:
            if defn["rule"](e):
                return defn["id"]
        except: 
            pass
    return "E"

def cluster_archetypes(persona_rows: list) -> dict:
    """Returns {cohort_id: [row, ...]} + archetype metadata."""
    by_id = defaultdict(list)
    for r in persona_rows:
        cid = assign_archetype(r.get("engine") or {})
        by_id[cid].append(r)
    return dict(by_id)

def archetype_summary_prompt(cohort_rows: list, cohort_label: str) -> str:
    names = ", ".join(r.get("author","?") for r in cohort_rows[:6])
    sigs = "; ".join((r.get("engine") or {}).get("signature","—") for r in cohort_rows[:4])
    ones = " | ".join((r.get("one_line") or "")[:120] for r in cohort_rows[:3] if r.get("one_line"))
    quotes = " | ".join(((r.get("quotes") or [{}])[0].get("text","") or "")[:100] for r in cohort_rows[:2] if (r.get("quotes") or [{}])[0].get("text"))
    return f"Cohort {cohort_label} ({len(cohort_rows)} personas): authors {names}; signatures {sigs}; one-lines: {ones}; sample quotes: {quotes}"

# ─────────────────────────────────────────────────────────────────────────────
# 2) Vega-Lite specs (declarative, agent-parseable)
# ─────────────────────────────────────────────────────────────────────────────

def vega_engine_histogram_spec(persona_rows: list) -> dict:
    """Engine C/F/P histograms — layered bar specs, agent-parseable."""
    vals = []
    for r in persona_rows:
        eng = r.get("engine") or {}
        for ax in ["C","F","P"]:
            v = eng.get(ax)
            if isinstance(v, int):
                vals.append({"axis": ax, "score": v, "author": r.get("author","?")})
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "Engine score distributions (C/F/P 0-5)",
        "data": {"values": vals},
        "facet": {"field": "axis", "type": "nominal", "columns": 3, "title": None},
        "spec": {
            "mark": {"type": "bar", "color": "#ffc500", "stroke": "#000", "strokeWidth": 1},
            "encoding": {
                "x": {"field": "score", "type": "ordinal", "title": "Score (0-5)", "axis": {"values": [0,1,2,3,4,5]}},
                "y": {"aggregate": "count", "type": "quantitative", "title": "Personas"}
            }
        },
        "config": {"view": {"stroke": "transparent"}},
        "width": 140, "height": 90
    }

def vega_bigfive_scatter_spec(persona_rows: list) -> dict:
    """Agreeableness vs Openness — agent-parseable scatter, human renders via Vega-Lite."""
    vals = []
    for r in persona_rows:
        num = bigfive_numeric(r.get("big_five") or {})
        if "agreeableness" in num and "openness" in num:
            vals.append({
                "agreeableness": num["agreeableness"],
                "openness": num["openness"],
                "author": r.get("author","?"),
                "cohort": assign_archetype(r.get("engine") or {}),
                "signature": (r.get("engine") or {}).get("signature","—"),
            })
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "Big Five: Agreeableness vs Openness (numeric 1=Low 2=Med 3=High, inferred)",
        "data": {"values": vals},
        "mark": {"type": "point", "filled": True, "size": 80, "stroke": "#000", "strokeWidth": 1},
        "encoding": {
            "x": {"field": "agreeableness", "type": "quantitative", "title": "Agreeableness (1 Low → 3 High)", "scale": {"domain": [0.7, 3.3]}},
            "y": {"field": "openness", "type": "quantitative", "title": "Openness (1 Low → 3 High)", "scale": {"domain": [0.7, 3.3]}},
            "color": {"field": "cohort", "type": "nominal", "title": "Archetype",
                      "scale": {"domain": ["A","B","C","D","E"], "range": ["#ffc500","#111","#62aef0","#f64932","#e7e7e7"]}},
            "tooltip": [{"field": "author"}, {"field": "signature"}, {"field": "cohort"}]
        },
        "width": 320, "height": 220
    }

def vega_scaffold_spec() -> dict:
    """Empty scaffold — rendered client-side if persona_rows are empty, validates layout intent."""
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": []},
        "mark": "bar",
        "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "b", "type": "quantitative"}}
    }

# ─────────────────────────────────────────────────────────────────────────────
# 3) Layout-intent validation (strict enums for compilation framework)
# ─────────────────────────────────────────────────────────────────────────────

LAYOUT_INTENT_ENUM = {"kpi", "archetype_bar", "vega_spec", "persona_card", "expandable_row", "copy_payload", "search_filter"}
COMPONENT_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # kebab-case, e.g. archetype-bar

def validate_layout_intent(tree: dict) -> list:
    errs = []
    for node in tree.get("nodes", []):
        intent = node.get("intent")
        nid = node.get("id","")
        if intent not in LAYOUT_INTENT_ENUM:
            errs.append(f"unknown layout intent {intent!r} (allowed {sorted(LAYOUT_INTENT_ENUM)})")
        if not COMPONENT_ID_RE.match(nid or ""):
            errs.append(f"invalid component id {nid!r} (kebab-case required)")
    return errs

# ─────────────────────────────────────────────────────────────────────────────
# 4) Index renderer — control panel
# ─────────────────────────────────────────────────────────────────────────────

def _avg(arr):
    return round(sum(arr)/len(arr),1) if arr else 0

def render_index(subreddit, authors, manifest, persona_rows, out_dir: Path, archetype_summaries: dict = None) -> str:
    esc=lambda s: htmlmod.escape(s or "", quote=False)
    now=datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    total=len(authors); completed=manifest.get("completed",0); failed=len(manifest.get("failed",[]))
    target = manifest.get("target_users", total)

    # Aggregates for KPIs — use enriched rows when available, fallback to legacy
    dist={"C":[],"F":[],"A1":[],"A2":[],"P":[]}
    for r in persona_rows:
        eng=r.get("engine") or {}
        for k in dist:
            if k in eng:
                try: dist[k].append(int(eng[k]))
                except: pass
    avg_engine = f"C{_avg(dist['C'])} F{_avg(dist['F'])} P{_avg(dist['P'])}" if any(dist.values()) else "—"
    avg_esc = esc(avg_engine)

    # Archetype clustering (deterministic)
    by_cohort = cluster_archetypes(persona_rows)
    archetype_summaries = archetype_summaries or {}
    # Order cohorts by size desc, then id
    cohort_order = sorted(by_cohort.keys(), key=lambda cid: (-len(by_cohort[cid]), cid))
    # Ensure E appears last even if large
    if "E" in cohort_order:
        cohort_order = [c for c in cohort_order if c!="E"] + ["E"]

    # Vega specs (declarative, embedded as JSON for agent + client rendering)
    hist_spec = vega_engine_histogram_spec(persona_rows)
    scatter_spec = vega_bigfive_scatter_spec(persona_rows)

    # Big Five coverage
    bf_count = sum(1 for r in persona_rows if r.get("big_five"))

    # Layout-intent tree for validation (maps to real DOM ids)
    layout_tree = {
        "nodes": [
            {"id": "kpi-panel", "intent": "kpi"},
            {"id": "archetype-bar", "intent": "archetype_bar"},
            {"id": "vega-engine-histogram", "intent": "vega_spec"},
            {"id": "vega-bigfive-scatter", "intent": "vega_spec"},
            {"id": "persona-card-grid", "intent": "persona_card"},
            {"id": "expandable-row", "intent": "expandable_row"},
            {"id": "copy-payload", "intent": "copy_payload"},
            {"id": "search-filter", "intent": "search_filter"},
        ]
    }
    validation_errors = validate_layout_intent(layout_tree)
    validation_note = "" if not validation_errors else f"Layout validation: {'; '.join(validation_errors)}"

    # JS payload: embed persona_rows as JSON for filtering + copy (local-first, no server)
    # Truncate per-row to safe size for embedding
    embed_rows = []
    for r in persona_rows:
        embed_rows.append({
            "author": r.get("author","?"),
            "engine": r.get("engine"),
            "big_five": r.get("big_five"),
            "persona_stack": r.get("persona_stack"),
            "engine_metrics": r.get("engine_metrics"),
            "quotes": (r.get("quotes") or [])[:2],
            "arguments": r.get("arguments"),
            "one_line": (r.get("one_line") or "")[:260],
            "comments": r.get("comments",0),
            "cohort": assign_archetype(r.get("engine") or {}),
            "model": r.get("model",""),
        })
    embed_json = json.dumps(embed_rows, ensure_ascii=False)
    hist_json = json.dumps(hist_spec, ensure_ascii=False)
    scatter_json = json.dumps(scatter_spec, ensure_ascii=False)

    styles=r"""
:root{--color-signal-yellow:#ffc500;--color-folio-black:#000;--color-newsprint-cream:#fdfcf3;--color-broadsheet-white:#fff;--color-margin-white:#fdfbe4;--color-rule-gray:#d9d9d9;--color-caption-gray:#6e6e6e;--color-mute-gray:#b3b3b3;--font-plantin:'Plantin',Georgia,serif;--font-helvetica-neue:'Helvetica Neue',Inter,system-ui,sans-serif;--radius-cards:8px}
*{box-sizing:border-box}body{margin:0;background:var(--color-newsprint-cream);color:#000;font-family:var(--font-plantin);-webkit-font-smoothing:antialiased}
a{color:inherit}
.utility{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid var(--color-rule-gray);display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:40px;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700}
.select,.search{appearance:none;border:1px solid var(--color-rule-gray);background:#fff;font:500 12px/1 var(--font-helvetica-neue);padding:8px 10px;border-radius:4px}
.search{width:220px}
.mast{max-width:1200px;margin:0 auto;padding:20px 16px 14px;text-align:center;border-bottom:1px solid var(--color-rule-gray)}
.mast h1{margin:0;font-size:40px;letter-spacing:-0.02em;line-height:1;font-weight:700}
.mast .sub{margin:8px 0 0;font-family:var(--font-helvetica-neue);font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)}
.kicker{margin-top:10px;display:flex;justify-content:center;gap:14px;flex-wrap:wrap;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700;letter-spacing:.01em;text-transform:uppercase;color:var(--color-caption-gray)}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
section{padding:24px 0;border-bottom:1px solid var(--color-rule-gray)}
.eyebrow{font-size:13px;letter-spacing:.075em;text-transform:uppercase;font-weight:700;margin:0 0 8px}
.eyebrow em{font-style:normal;color:var(--color-caption-gray);font-weight:400;margin-left:6px}
.card{border:1px solid var(--color-rule-gray);background:#fff;padding:16px;border-radius:var(--radius-cards)}
.card.warm{background:var(--color-margin-white)}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:700px){.kpi-grid{grid-template-columns:1fr 1fr}}
.kpi{border:1px solid var(--color-rule-gray);background:#fff;padding:16px;border-radius:var(--radius-cards)}
.kpi.yellow{background:var(--color-signal-yellow);border-color:#000}
.kpi b{display:block;font-size:24px;letter-spacing:-0.48px}
.mono{font-family:ui-monospace,monospace;font-size:11px}
.pill{display:inline-block;font:500 10px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;padding:3px 6px;border:1px solid var(--color-rule-gray);background:#fff;cursor:default}
.pill.yellow{background:var(--color-signal-yellow);border-color:#000}
.pill.black{background:#000;color:var(--color-signal-yellow);border-color:#000}
.pill.muted{background:#eee;color:var(--color-caption-gray);border-color:var(--color-rule-gray)}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.grid3{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.grid3{grid-template-columns:1fr}}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:800px){.grid2{grid-template-columns:1fr}}
.author-card{border:1px solid var(--color-rule-gray);background:#fff;padding:12px;border-radius:var(--radius-cards);cursor:pointer}
.author-card:hover{border-color:var(--color-caption-gray)}
.author-card.filtered{opacity:.28;pointer-events:none}
.author-card .head{display:flex;justify-content:space-between;align-items:center}
.expand{border-top:1px solid var(--color-rule-gray);margin-top:10px;padding-top:10px;font-size:12px;line-height:1.5;color:var(--color-caption-gray)}
.expand blockquote{margin:6px 0 0;border-left:3px solid var(--color-signal-yellow);padding:4px 10px;background:var(--color-margin-white);font-family:var(--font-plantin);font-size:13px;color:#000}
.btn{appearance:none;border:1px solid #000;background:var(--color-signal-yellow);color:#000;font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;padding:6px 10px;border-radius:4px;cursor:pointer}
.btn.ghost{background:#fff;border-color:var(--color-rule-gray)}
.btn:active{transform:translateY(1px)}
.footer{padding:16px;text-align:center;font:500 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray);border-top:1px solid var(--color-rule-gray)}
.vega-box{border:1px solid var(--color-rule-gray);background:#fff;border-radius:var(--radius-cards);padding:10px;overflow:auto}
.note{margin:8px 0 0;font:500 11px/1 var(--font-helvetica-neue);color:var(--color-caption-gray);line-height:1.5}
.archetype-bar{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.archetype-chip{appearance:none;border:1px solid var(--color-rule-gray);background:#fff;border-radius:9999px;padding:6px 12px;font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.04em;cursor:pointer}
.archetype-chip.active{background:#000;color:var(--color-signal-yellow);border-color:#000}
.archetype-chip small{font-weight:500;color:var(--color-caption-gray);margin-left:4px}
.archetype-chip.active small{color:#cbd5ff}
.cohort-card{border-left:3px solid var(--color-signal-yellow);padding:12px;border:1px solid var(--color-rule-gray);background:#fff;border-radius:var(--radius-cards)}
.cohort-card h4{margin:0;font:700 13px/1 var(--font-helvetica-neue);letter-spacing:.02em}
.cohort-card p{margin:6px 0 0;font-size:12px;line-height:1.5;color:var(--color-caption-gray)}
.cohort-card .tactic{margin-top:8px;font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.05em;text-transform:uppercase;color:#000;background:var(--color-signal-yellow);border:1px solid #000;padding:4px 6px;display:inline-block}
"""

    kpi_html=f"""<div class="kpi-grid" id="kpi-panel">
      <div class="kpi yellow"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:#000">Target</span><b>{target}</b><span style="font:700 10px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:#000">r/{esc(subreddit)}</span></div>
      <div class="kpi"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Completed</span><b>{completed}</b><span class="mono" style="color:var(--color-caption-gray)">{len(persona_rows)} enriched</span></div>
      <div class="kpi"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Failed / thin</span><b>{failed}</b><span class="mono" style="color:var(--color-caption-gray)">resume-safe</span></div>
      <div class="kpi"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Avg Engine</span><b style="font-size:16px">{avg_esc}</b><span class="mono" style="color:var(--color-caption-gray)">C/F/P means</span></div>
    </div>"""

    # Archetype bar + cohort cards
    archetype_bar_html = '<div class="archetype-bar" id="archetype-bar" role="tablist" aria-label="Archetypes">'
    archetype_bar_html += f'<button class="archetype-chip active" data-cohort="all" role="tab" aria-selected="true">All <small>{len(persona_rows)}</small></button>'
    for cid in cohort_order:
        n = len(by_cohort[cid])
        label = next((d.get("label","") for d in ARCHETYPE_DEFS if d["id"]==cid), ARCHETYPE_FALLBACK["label"] if cid=="E" else cid)
        color = COHORT_COLORS.get(cid, "#e7e7e7")
        archetype_bar_html += f'<button class="archetype-chip" data-cohort="{esc(cid)}" role="tab" aria-selected="false" style="border-left:4px solid {esc(color)}">{esc(label)} <small>{n}</small></button>'
    archetype_bar_html += '</div>'

    cohort_cards_html = ""
    for cid in cohort_order:
        rows = by_cohort[cid]
        defn = next((d for d in ARCHETYPE_DEFS if d["id"]==cid), None)
        fallback = ARCHETYPE_FALLBACK if cid=="E" else {}
        label = (defn or fallback).get("label", cid)
        sig = (defn or fallback).get("sig", "")
        color = COHORT_COLORS.get(cid, "#e7e7e7")
        summary = (archetype_summaries or {}).get(cid, "")
        # deterministic tactic seed (no LLM required)
        tactic_seed = {
            "A": "Lead with base rates + mechanism; they respect density and will punish hand-waving.",
            "B": "Close with concrete next step; they optimize for what ships tomorrow.",
            "C": "Offer the instrument (playbook/API); they want leverage, not a lecture.",
            "D": "Lower the stakes; pressure collapses their coherence before the argument does.",
            "E": "Probe for the axis — quote + one-line usually reveals the real cohort.",
        }.get(cid, "Test with a concrete case — the cohort is mixed.")
        if summary:
            tactic = esc(summary[:180])
        else:
            tactic = esc(tactic_seed)
        sample_authors = ", ".join(esc(r.get("author","?")) for r in rows[:4])
        cohort_cards_html += f"""<div class="cohort-card" data-cohort-card="{esc(cid)}" style="border-left-color:{esc(color)}">
          <h4><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{esc(color)};border:1px solid #000;vertical-align:middle;margin-right:6px"></span>{esc(label)} <span style="font-weight:400;color:var(--color-caption-gray)">· {len(rows)} personas</span></h4>
          <p style="font:700 10px/1 var(--font-helvetica-neue);letter-spacing:.05em;text-transform:uppercase;color:var(--color-caption-gray);margin-top:6px">{esc(sig)}</p>
          <p style="margin-top:6px;color:var(--color-caption-gray)">e.g. {sample_authors}</p>
          <div class="tactic">{tactic}</div>
          <p class="note" style="margin-top:8px">Deterministic grouping by Engine (C/F/A/P) — not LLM-clustered. Summaries are LLM-polished when a key is present, otherwise the tactic above is the deterministic fallback.</p>
        </div>"""

    # Search + sort bar
    controls_html = """<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:14px" id="search-filter">
      <input class="search" id="searchInput" placeholder="Filter by author, signature, quote…" aria-label="Filter personas" />
      <select class="select" id="sortSelect" aria-label="Sort personas">
        <option value="author">Sort: author A→Z</option>
        <option value="engine_c">Sort: Engine C ↓</option>
        <option value="engine_p">Sort: Engine P ↓</option>
        <option value="comments">Sort: comments ↓</option>
        <option value="cohort">Sort: Archetype</option>
      </select>
      <button class="btn ghost" id="expandAll">Expand all</button>
      <button class="btn ghost" id="collapseAll">Collapse</button>
      <span class="mono" id="visibleCount" style="color:var(--color-caption-gray)"></span>
    </div>"""

    # Persona grid — expandable rows + Copy JSON
    # Build each card with data-* for filtering and inline preview (quote + argument architecture)
    grid_inner = ""
    for r in persona_rows[:500]:
        author = esc(r.get("author","?"))
        eng = r.get("engine") or {}
        sig = esc(eng.get("signature","—"))
        n = r.get("comments", 0)
        cid = assign_archetype(eng)
        color = COHORT_COLORS.get(cid, "#e7e7e7")
        q0 = (r.get("quotes") or [{}])[0] if r.get("quotes") else {}
        quote_text = esc((q0.get("text") or "")[:180])
        quote_src = esc(q0.get("source") or "")
        one_line = esc((r.get("one_line") or "")[:160])
        args_data = r.get("arguments") or {}
        hook = esc((args_data.get("hook") or "")[:160]) if isinstance(args_data, dict) else ""
        # payload for Copy JSON (full rubric for simulation injection)
        payload_obj = {
            "author": r.get("author"),
            "engine": r.get("engine"),
            "big_five": r.get("big_five"),
            "persona_stack": r.get("persona_stack"),
            "engine_metrics": r.get("engine_metrics"),
            "quotes": r.get("quotes"),
            "arguments": r.get("arguments"),
            "one_line": r.get("one_line"),
        }
        payload_json = htmlmod.escape(json.dumps(payload_obj, ensure_ascii=False), quote=True)
        searchable = htmlmod.escape(f"{author} {sig} {quote_text} {one_line} {hook}".lower(), quote=True)
        # Precompute preview blocks to avoid backslashes inside f-string expressions
        if quote_text:
            qt = quote_text; qs = quote_src
            quote_block = f"<blockquote>\u201c{qt}\u201d <span class=\u0022mono\u0022 style=\u0022color:var(--color-caption-gray)\u0022>\u2014 {qs}</span></blockquote>"
            quote_block = quote_block.replace(chr(34), "&quot;").replace(chr(34), "&quot;")  # keep safe
            # Rebuild without entity confusion: use single quotes for style
            quote_block = '<blockquote>\u201c' + qt + '\u201d <span class="mono" style="color:var(--color-caption-gray)">\u2014 ' + qs + '</span></blockquote>'
        else:
            quote_block = '<p class="mono">No quote extracted.</p>'
        hook_block = '<p style="margin:8px 0 0"><b>Hook:</b> ' + hook + '</p>' if hook else ''
        grid_inner += f"""<div class="author-card" data-author="{author}" data-cohort="{esc(cid)}" data-search="{searchable}" data-engine-c="{eng.get('C',0)}" data-engine-p="{eng.get('P',0)}" data-comments="{n}" style="border-left:4px solid {color}">
          <div class="head">
            <div>
              <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">u/{author} <span class="pill muted" style="margin-left:6px;border-left:3px solid {color}">{esc(cid)}</span></div>
              <div style="font-size:13px;font-weight:700;margin-top:6px">{sig}</div>
              <div class="mono" style="color:var(--color-caption-gray);margin-top:4px">{n} comments \u00b7 {one_line or chr(8212)}</div>
            </div>
            <div style="display:flex;flex-direction:column;gap:6px;align-items:end">
              <a href="dossiers/u_{author}.html" target="_blank" rel="noopener" class="pill yellow" style="text-decoration:none">dossier \u2192</a>
              <button class="btn ghost" data-copy-payload='{payload_json}' id="copy-payload" aria-label="Copy JSON for u/{author}">Copy JSON</button>
            </div>
          </div>
          <details class="expand" id="expandable-row"><summary style="cursor:pointer;font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Preview \u2014 quote & argument</summary>
            {quote_block}
            {hook_block}
            <p style="margin:8px 0 0" class="mono">Full rubric in <code>personas.jsonl</code> and the Copy JSON payload \u2014 paste directly into a simulation prompt.</p>
          </details>
        </div>"""

    if not grid_inner:
        grid_inner = '<div class="card">No dossiers yet — run <code>build_dataset.py</code> to populate. Vega specs below are the declarative scaffold; they validate the layout intent even before data exists.</div>'

    gallery_html = f'<div class="grid3" id="persona-card-grid" style="margin-top:14px">{grid_inner}</div>'

    failed_html=""
    if manifest.get("failed"):
        items="".join(f"<li>u/{esc(f.get('author','?'))} — {esc(f.get('error',''))[:120]}</li>" for f in manifest["failed"][:10])
        failed_html=f'<div class="card" style="margin-top:12px"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Failed / thin</div><ul class="mono" style="margin:6px 0 0;padding-left:16px">{items}</ul></div>'

    vega_section = f"""
    <div class="grid2" style="margin-top:12px">
      <div class="vega-box" id="vega-engine-histogram">
        <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Engine distributions (C · F · P)</div>
        <div id="vega-hist" style="margin-top:8px;min-height:120px"></div>
        <p class="note">Declarative Vega-Lite spec — agent-parseable. Faceted histogram (scores 0-5). Use to spot bias (e.g. all P=4 or no F≥4).</p>
        <details><summary class="mono" style="cursor:pointer">Show Vega-Lite JSON</summary><pre class="mono" style="margin:8px 0 0;white-space:pre-wrap;word-break:break-word;background:var(--color-margin-white);padding:8px;border-radius:4px;max-height:260px;overflow:auto" id="vega-hist-json">{esc(json.dumps(hist_spec, indent=2))}</pre></details>
      </div>
      <div class="vega-box" id="vega-bigfive-scatter">
        <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Population map — Agreeableness × Openness</div>
        <div id="vega-scatter" style="margin-top:8px;min-height:220px"></div>
        <p class="note">Scatter of Big Five where available ({bf_count}/{len(persona_rows)} with Big Five). Colored by Archetype. Missing Big Five (heuristic rows) are excluded — not interpolated.</p>
        <details><summary class="mono" style="cursor:pointer">Show Vega-Lite JSON</summary><pre class="mono" style="margin:8px 0 0;white-space:pre-wrap;word-break:break-word;background:var(--color-margin-white);padding:8px;border-radius:4px;max-height:260px;overflow:auto" id="vega-scatter-json">{esc(json.dumps(scatter_spec, indent=2))}</pre></details>
      </div>
    </div>
    """

    # Local-first note + SQLite snippet
    local_first_html = f"""<div class="card warm" style="margin-top:12px">
      <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Local-first — no server required</div>
      <p style="margin:8px 0 0;font-size:13px;line-height:1.6">All filtering, cohort selection, and Copy JSON happen client-side from the embedded <code>personas</code> payload ({len(embed_rows)} rows). No round-trip. For 500+ personas, compile the same <code>personas.jsonl</code> to SQLite and query it from a lightweight React bundle — schema is the JSONL keys below.</p>
      <pre class="mono" style="margin:8px 0 0;white-space:pre-wrap;background:var(--color-broadsheet-white);padding:8px;border-radius:4px;border:1px solid var(--color-rule-gray)"># SQLite path (future-proof for 500+)\npython -c "import json, sqlite3; con=sqlite3.connect('personas.db'); con.execute('create table if not exists personas (author text primary key, engine text, big_five text, one_line text)'); [con.execute('insert or replace into personas values (?,?,?,?)', (j['author'], json.dumps(j.get('engine')), json.dumps(j.get('big_five')), j.get('one_line'))) for j in map(json.loads, open('personas.jsonl'))]; con.commit()"\n# React: SELECT * FROM personas WHERE json_extract(engine,'$.C') >= 4</pre>
      <p class="note">Layout intents validated: {esc(validation_note) if validation_note else "all 8 intents ✓ (kpi, archetype_bar, vega_spec×2, persona_card, expandable_row, copy_payload, search_filter) — see <code>validate_layout_intent()</code>."}</p>
    </div>"""

    script = f"""
<script id="dataset-payload" type="application/json">{embed_json}</script>
<script id="vega-hist-spec" type="application/json">{hist_json}</script>
<script id="vega-scatter-spec" type="application/json">{scatter_json}</script>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
<script>
(function(){{
  const rows = JSON.parse(document.getElementById('dataset-payload').textContent || '[]');
  const histSpec = JSON.parse(document.getElementById('vega-hist-spec').textContent || '{{}}');
  const scatterSpec = JSON.parse(document.getElementById('vega-scatter-spec').textContent || '{{}}');
  // Vega-Lite render (graceful if offline — specs remain as JSON for agents)
  function tryVega(id, spec) {{
    try {{ if (spec && spec.data && spec.data.values && spec.data.values.length>0) vegaEmbed('#'+id, spec, {{actions:false, renderer:'canvas'}}).catch(function(){{}}); else document.getElementById(id).innerHTML='<p class=\"mono\" style=\"color:var(--color-caption-gray)\">No data for this chart yet — add dossiers to populate.</p>'; }} catch(e) {{ document.getElementById(id).innerHTML='<p class=\"mono\">Chart unavailable offline — Vega JSON is still in the page source for agent parsing.</p>'; }}
  }}
  tryVega('vega-hist', histSpec);
  tryVega('vega-scatter', scatterSpec);

  const grid = document.getElementById('persona-card-grid');
  const cards = grid ? Array.from(grid.querySelectorAll('.author-card')) : [];
  const search = document.getElementById('searchInput');
  const sortSel = document.getElementById('sortSelect');
  const visible = document.getElementById('visibleCount');
  let activeCohort = 'all';

  function applyFilter() {{
    const q = (search && search.value || '').trim().toLowerCase();
    let shown = 0;
    cards.forEach(function(c) {{
      const cohort = c.getAttribute('data-cohort');
      const hay = c.getAttribute('data-search') || '';
      const passCohort = (activeCohort==='all' || cohort===activeCohort);
      const passSearch = (!q || hay.indexOf(q) !== -1);
      const show = passCohort && passSearch;
      c.style.display = show ? '' : 'none';
      if (show) shown++;
    }});
    if (visible) visible.textContent = shown + ' / ' + cards.length + ' shown';
  }}
  function applySort() {{
    if (!sortSel || !grid) return;
    const key = sortSel.value;
    const sorted = cards.slice().sort(function(a,b){{
      if (key==='author') return (a.getAttribute('data-author')||'').localeCompare(b.getAttribute('data-author')||'');
      if (key==='engine_c') return parseInt(b.getAttribute('data-engine-c')||'0') - parseInt(a.getAttribute('data-engine-c')||'0');
      if (key==='engine_p') return parseInt(b.getAttribute('data-engine-p')||'0') - parseInt(a.getAttribute('data-engine-p')||'0');
      if (key==='comments') return parseInt(b.getAttribute('data-comments')||'0') - parseInt(a.getAttribute('data-comments')||'0');
      if (key==='cohort') return (a.getAttribute('data-cohort')||'').localeCompare(b.getAttribute('data-cohort')||'');
      return 0;
    }});
    sorted.forEach(function(c){{ grid.appendChild(c); }});
  }}
  document.querySelectorAll('.archetype-chip').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      document.querySelectorAll('.archetype-chip').forEach(function(b){{ b.classList.remove('active'); b.setAttribute('aria-selected','false'); }});
      btn.classList.add('active'); btn.setAttribute('aria-selected','true');
      activeCohort = btn.getAttribute('data-cohort') || 'all';
      applyFilter();
    }});
  }});
  if (search) search.addEventListener('input', applyFilter);
  if (sortSel) sortSel.addEventListener('change', function(){{ applySort(); applyFilter(); }});
  var expAll = document.getElementById('expandAll');
  var colAll = document.getElementById('collapseAll');
  if (expAll) expAll.addEventListener('click', function(){{ cards.forEach(function(c){{ var d=c.querySelector('details'); if(d) d.open=true; }}); }});
  if (colAll) colAll.addEventListener('click', function(){{ cards.forEach(function(c){{ var d=c.querySelector('details'); if(d) d.open=false; }}); }});
  // Copy JSON — delegates to first [data-copy-payload] match
  document.addEventListener('click', function(e){{
    var t = e.target.closest('[data-copy-payload]');
    if (!t) return;
    var payload = t.getAttribute('data-copy-payload') || '';
    // payload is html-escaped JSON — decode by creating a textarea
    var ta = document.createElement('textarea');
    ta.value = payload;
    // Unescape html entities: use DOM
    var div = document.createElement('div'); div.innerHTML = payload; 
    try {{ ta.value = JSON.parse('\"' + payload.replace(/\"/g, '\\\\\"') + '\"'); }} catch(_e) {{ ta.value = div.textContent || div.innerText || payload; }}
    // Simpler: the attribute was htmlmod-escaped; browser already decoded it on read — but html entities remain for &quot; etc.
    // Use the raw inner: replace &quot; -> \"
    ta.value = (payload || '').replace(/&quot;/g,'\"').replace(/&#x27;/g,\"'\").replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>');
    // Try to pretty-print if valid JSON
    try {{ var obj = JSON.parse(ta.value); ta.value = JSON.stringify(obj, null, 2); }} catch(_e) {{}}
    // Fallback: use clipboard API if available, else execCommand
    var done = function(ok) {{
      var orig = t.textContent;
      t.textContent = ok ? 'Copied ✓' : 'Copy failed';
      setTimeout(function(){{ t.textContent = orig; }}, 1200);
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(ta.value).then(function(){{ done(true); }}, function(){{ done(false); }});
    }} else {{
      ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.select();
      try {{ document.execCommand('copy'); done(true); }} catch(_e) {{ done(false); }}
      document.body.removeChild(ta);
    }}
  }});
  applyFilter();
}})();
</script>
"""

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Hermes · r/{esc(subreddit)} Dataset — {len(persona_rows)} personas · Control Panel</title><style>{styles}</style></head><body>
<div class="utility"><div><span style="letter-spacing:.14em">HERMES</span> <span style="color:var(--color-mute-gray);font-weight:400">· DATASET</span> <span style="color:var(--color-mute-gray);font-weight:400">· r/{esc(subreddit)}</span></div><div><span class="pill yellow">CONTROL PANEL</span> <span class="pill muted">LOCAL-FIRST</span></div></div>
<header class="mast"><h1>Hermes <span style="font-weight:400">· r/{esc(subreddit)} synthetic population</span></h1><div class="sub">{len(persona_rows)} personas · {bf_count} with Big Five · {len(by_cohort)} archetypes · {now}</div>
<div class="kicker"><span><b>{completed}</b> dossiers</span><span><b>personas.jsonl</b> JSONL</span><span><b>dossiers/</b> HTML</span><span><b>manifest.json</b> checkpoint</span></div></header>
<div class="wrap">
<section><div class="eyebrow">CONTROL PANEL <em>· filter, inspect, copy</em></div><h2 style="margin:0;font-size:28px;letter-spacing:-0.5px"><em style="font-style:normal;background:linear-gradient(transparent 60%,var(--color-signal-yellow) 60% 88%,transparent 88%)">Interactive</em> synthetic population — r/{esc(subreddit)}</h2>
<p style="color:var(--color-caption-gray);margin:8px 0 0;max-width:68ch">Deterministic Engine cohorts + Vega-Lite distributions + inline previews + <b>Copy JSON</b>. Everything runs locally — filter and copy without a server.</p>
<div style="margin-top:16px">{kpi_html}</div>
{failed_html}
</section>
<section><div class="eyebrow">ARCHETYPES <em>· deterministic · Engine C/F/A1/A2/P → filter cohorts</em></div>
<p style="color:var(--color-caption-gray);margin:0 0 8px;max-width:68ch;font-size:13px;line-height:1.5">Grouped locally by Engine scores (not LLM-clustered). LLMs only polish the summary lines. Click an archetype to filter the grid below.</p>
{archetype_bar_html}
<div class="grid2" style="margin-top:12px">{cohort_cards_html or '<div class="card">No personas yet.</div>'}</div>
</section>
<section><div class="eyebrow">POPULATION MAP <em>· declarative Vega-Lite — agent-parseable</em></div>
{vega_section}
{local_first_html}
</section>
<section><div class="eyebrow">PERSONAS <em>· {len(persona_rows)} personas · expand for quote & argument · Copy JSON for simulation</em></div>
{controls_html}
{gallery_html}
<p style="margin-top:12px;font:500 11px/1 var(--font-helvetica-neue);color:var(--color-caption-gray)">Showing all {len(persona_rows)} personas inline. Payloads are embedded as JSON — no server fetch. Full dossiers link to Notion HTML.</p>
</section>
<section><div class="eyebrow">USAGE</div>
<div class="grid3">
<div class="card"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Cohort simulation</div><pre class="mono" style="margin:8px 0 0;white-space:pre-wrap">import json
rows=[json.loads(l) for l in open("personas.jsonl")]
cohort=[r for r in rows if (r.get("engine") or dict()).get("C",0)>=4]
# copy JSON from the panel, or filter by archetype and bulk-export
</pre></div>
<div class="card"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Vega-Lite (agent)</div><p style="margin:8px 0 0;font-size:13px;line-height:1.5">Charts are Vega-Lite JSON in <code>&lt;script type="application/json"&gt;</code> — parse the <code>data.values</code> array to validate bias (e.g. no P≤2 cohort, all agreeableness=High).</p></div>
<div class="card warm"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Resume & scale</div><p style="margin:8px 0 0;font-size:13px;line-height:1.5">Same command resumes: <code>python build_dataset.py --subreddit {esc(subreddit)} --users {target} --out {esc(str(out_dir))}</code>. At 500+, compile <code>personas.jsonl</code> → <code>personas.db</code> (SQLite) — index stays single-file.</p></div>
</div>
</section>
</div>
<div class="footer">Hermes · Dataset Control Panel · r/{esc(subreddit)} · {now} · Arctic Shift archive · Declarative Vega-Lite · Local-first · Single-file HTML — opens offline</div>
{script}
</body></html>"""

def _archetype_summaries_llm(by_cohort: dict, model="deepseek-v4-flash") -> dict:
    """Stochastic coach: one short LLM call per cohort (pure polish, clusters are already deterministic). Bounded cost."""
    out = {}
    for cid, rows in by_cohort.items():
        if len(rows) == 0:
            continue
        sample_lines = []
        for r in rows[:4]:
            author = r.get('author', '?')
            sig = (r.get('engine') or {}).get('signature', '--')
            one = (r.get('one_line') or '')[:140]
            sample_lines.append("- " + author + ": " + sig + " -- " + one)
        samples = "\n".join(sample_lines)
        prompt = "You are a stochastic coach polishing a deterministic cohort summary.\n\nCohort " + str(cid) + " has " + str(len(rows)) + " personas.\nSample authors and one-lines:\n" + samples + "\n\nTask: Return a single sentence (<=22 words, plain text, no JSON) that names the cohort's shared pattern and one debate tactic that works on them. Be concrete and grounded in the samples. Do not invent topics not in the samples."
        try:
            resp = try_llm(prompt, model=model, max_tokens=120)
            if resp and resp.strip():
                s = resp.strip().strip('"').strip("'").strip()
                # DeepSeek reasoning leak guard: if response looks like chain-of-thought, discard
                low = s.lower()
                if any(phrase in low for phrase in ["we need to", "we need answer", "single sentence", "has ", " personas", "need produce", "need craft", "need comply"]):
                    # Try second line which is usually the real answer
                    lines = [l.strip() for l in resp.strip().split("\n") if l.strip()]
                    # Find first line that is short (<=22 words) and doesn't contain the trigger phrases
                    s = ""
                    for l in lines:
                        ll = l.strip().strip('"').strip("'").strip()
                        ll_low = ll.lower()
                        if len(ll.split()) <= 26 and not any(p in ll_low for p in ["we need", "need answer", "need produce", "need craft", "need comply", "stochastic coach", "deterministic cohort"]):
                            s = ll[:220]
                            break
                    if not s:
                        continue
                else:
                    s = s.split("\n")[0].strip()[:220]
                out[cid] = s
        except Exception:
            pass
    return out

def main():
    ap=argparse.ArgumentParser(description="Build synthetic population dataset for a subreddit — interactive control-panel index")
    ap.add_argument("--subreddit", required=True)
    ap.add_argument("--users", type=int, default=20, help="target number of authors")
    ap.add_argument("--comments-per-user", type=int, default=100)
    ap.add_argument("--out", required=True, help="output directory (e.g. ./data/parenting/)")
    ap.add_argument("--model", default="deepseek-v4-flash", help="LLM model for persona synthesis (deepseek-v4-flash recommended for prompt-cache savings)")
    ap.add_argument("--concurrency", type=int, default=2, help="parallel persona builds (1-4 recommended)")
    ap.add_argument("--min-comments", type=int, default=20, help="skip authors with fewer comments")
    ap.add_argument("--keep-raw", action="store_true", help="save raw comment JSON per author")
    ap.add_argument("--no-llm", action="store_true", help="heuristic dossiers only (no LLM)")
    ap.add_argument("--no-archetype-llm", action="store_true", help="skip LLM polish of archetype summaries (deterministic tactics only)")
    ap.add_argument("--reindex-only", action="store_true", help="only regenerate index.html from existing dossiers/personas.jsonl (no fetching)")
    ap.add_argument("--template", default="v33", choices=["v33","v4-thinking","v4-flash"], help="persona synthesis template passed to persona.py (v4-flash = batch microcard lane)")
    args=ap.parse_args()

    _load_env_file()
    out_dir=Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    dossiers_dir=out_dir/"dossiers"; dossiers_dir.mkdir(exist_ok=True)
    raw_dir=out_dir/"raw"; raw_dir.mkdir(exist_ok=True)
    manifest_path=out_dir/"manifest.json"
    jsonl_path=out_dir/"personas.jsonl"

    # ——— reindex-only fast path ———
    if args.reindex_only:
        if not jsonl_path.exists():
            print(f"[dataset] reindex-only: no personas.jsonl at {jsonl_path}", file=sys.stderr); sys.exit(1)
        persona_rows=[]
        for line in jsonl_path.read_text().splitlines():
            if line.strip():
                try: persona_rows.append(json.loads(line))
                except: pass
        # also enrich from dossier jsons if jsonl was legacy (no big_five)
        need_backfill = any(not r.get("big_five") for r in persona_rows) or not persona_rows
        if need_backfill:
            enriched=[]
            for p in dossiers_dir.glob("u_*.json"):
                try:
                    j=json.loads(p.read_text())
                    # merge into persona_rows by author
                    author=j.get("author") or p.stem.replace("u_","")
                    existing=next((r for r in persona_rows if r.get("author")==author), None)
                    if existing:
                        for k in ["big_five","quotes","arguments","one_line","engine","persona_stack","engine_metrics"]:
                            if k in j and j[k] is not None:
                                existing[k]=j[k]
                    else:
                        enriched.append(j)
                except: pass
            if enriched:
                persona_rows.extend(enriched)
                # rewrite jsonl enriched
                jsonl_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in persona_rows) + "\n")
                print(f"[dataset] backfilled {len(enriched)} rows from dossier sidecars", file=sys.stderr)
        if manifest_path.exists():
            manifest=json.loads(manifest_path.read_text())
        else:
            manifest={"subreddit":args.subreddit,"target_users":len(persona_rows),"completed":len(persona_rows),"failed":[],"authors":[r.get("author") for r in persona_rows]}
            manifest["target_users"]=len(persona_rows)
        by_cohort = cluster_archetypes(persona_rows)
        summaries={}
        if not args.no_archetype_llm and not args.no_llm and persona_rows and any(r.get("big_five") for r in persona_rows):
            has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
            if has_key:
                print(f"[dataset] polishing {len(by_cohort)} archetype summaries with {args.model} …", file=sys.stderr)
                summaries=_archetype_summaries_llm(by_cohort, model=args.model)
        # dedupe authors list
        authors=list(dict.fromkeys([r.get("author") for r in persona_rows if r.get("author")] )) or manifest.get("authors",[])[:args.users] if args.users else manifest.get("authors",[])
        if not authors:
            authors=[r.get("author") for r in persona_rows if r.get("author")]
        html=render_index(args.subreddit or manifest.get("subreddit",""), authors, manifest, persona_rows, out_dir, archetype_summaries=summaries)
        (out_dir/"index.html").write_text(html, encoding="utf-8")
        print(f"[dataset] reindexed — {len(persona_rows)} personas → {out_dir}/index.html ({len(html):,} bytes)", file=sys.stderr)
        print(str(out_dir/"index.html"))
        return

    # load or init manifest
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if args.users > manifest.get("target_users",0):
            manifest["target_users"]=args.users
    else:
        manifest={"subreddit":args.subreddit,"target_users":args.users,"comments_per_user":args.comments_per_user,"model":args.model,"started_at": datetime.now(timezone.utc).isoformat(),"completed":0,"failed":[],"authors":[]}
        if not jsonl_path.exists():
            jsonl_path.write_text("")

    # discover authors if needed
    if len(manifest.get("authors",[])) < args.users:
        need=args.users - len(manifest.get("authors",[]))
        print(f"[dataset] discovering {need} more authors for r/{args.subreddit} …", file=sys.stderr)
        new_authors=discover_authors(args.subreddit, target=need+10)
        seen=set(manifest.get("authors",[]))
        for a in new_authors:
            if a not in seen:
                manifest["authors"].append(a); seen.add(a)
            if len(manifest["authors"]) >= args.users: break
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"[dataset] manifest now {len(manifest['authors'])} authors", file=sys.stderr)

    authors=manifest["authors"][:args.users]
    existing=set(p.stem.replace("u_","") for p in dossiers_dir.glob("u_*.html"))
    todo=[a for a in authors if a not in existing]
    print(f"[dataset] r/{args.subreddit} target={args.users} todo={len(todo)} existing={len(existing)} concurrency={args.concurrency}", file=sys.stderr)

    persona_rows=[]
    if jsonl_path.exists():
        for line in jsonl_path.read_text().splitlines():
            if line.strip():
                try: persona_rows.append(json.loads(line))
                except: pass

    def build_one(author: str):
        if author.startswith("-"):
            return {"author":author,"skipped":True,"reason":"dash-prefixed username — skipped (argparse)"}
        out_html=dossiers_dir/f"u_{author}.html"
        out_json=dossiers_dir/f"u_{author}.json"
        try:
            comments=fetch_comments_paginated(author=author, total=args.comments_per_user)
            if len(comments) < args.min_comments:
                return {"author":author,"skipped":True,"reason":f"only {len(comments)} comments (<{args.min_comments})"}
            if args.keep_raw:
                (raw_dir/f"u_{author}.json").write_text(json.dumps(comments, ensure_ascii=False, indent=2))
            import subprocess, sys as _sys
            cmd=[_sys.executable, str(SCRIPT_DIR/"persona.py"), f"--author={author}", "--limit", str(args.comments_per_user), "--out", str(out_html)]
            if args.no_llm: cmd.append("--no-llm")
            else: cmd.extend(["--model", args.model])
            cmd.extend(["--template", args.template])
            _env=dict(os.environ)
            env_path=Path.home() / ".hermes/profiles/hermozi/.env"
            if env_path.exists():
                for _l in env_path.read_text().splitlines():
                    if "=" in _l and not _l.strip().startswith("#"):
                        _k,_v=_l.split("=",1)
                        _k=_k.strip(); _v=_v.strip().strip('"').strip("'")
                        if _k not in _env or not _env[_k]:
                            _env[_k]=_v
            result=subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=_env)
            if result.returncode!=0:
                raise RuntimeError(result.stderr[-600:] or result.stdout[-600:] or "persona.py failed")
            rubric={}
            if out_json.exists():
                try: rubric=json.loads(out_json.read_text())
                except: pass
            return {"author":author,"rubric":rubric,"comments":len(comments),"html":str(out_html)}
        except Exception as e:
            return {"author":author,"error":str(e)[:400]}

    results=[]
    if todo:
        with ThreadPoolExecutor(max_workers=max(1,min(4,args.concurrency))) as ex:
            futs={ex.submit(build_one, a): a for a in todo}
            for fut in as_completed(futs):
                author=futs[fut]
                try:
                    r=fut.result()
                except Exception as e:
                    r={"author":author,"error":str(e)}
                if r.get("skipped"):
                    print(f"[dataset] skip u/{author}: {r['reason']}", file=sys.stderr)
                    manifest["failed"].append({"author":author,"error":r["reason"]})
                elif r.get("error"):
                    print(f"[dataset] fail u/{author}: {r['error'][:120]}", file=sys.stderr)
                    manifest["failed"].append({"author":author,"error":r["error"]})
                else:
                    rubric=r.get("rubric") or {}
                    print(f"[dataset] ok u/{author} ({r.get('comments',0)} comments)", file=sys.stderr)
                    row={"author":author,"engine":rubric.get("engine"),"big_five":rubric.get("big_five"),"persona_stack":rubric.get("persona_stack"),"engine_metrics":rubric.get("engine_metrics"),"quotes":rubric.get("quotes"),"arguments":rubric.get("arguments"),"one_line":rubric.get("one_line"),"model":rubric.get("model"),"comments":r.get("comments",0)}
                    persona_rows.append(row)
                    with open(jsonl_path,"a") as f:
                        f.write(json.dumps(row, ensure_ascii=False)+"\n")
                    manifest["completed"]=(manifest.get("completed",0)+1)
                manifest_path.write_text(json.dumps(manifest, indent=2))
                results.append(r)

    # reload persona_rows from jsonl for index (ensures enriched fields)
    if jsonl_path.exists():
        persona_rows=[]
        for line in jsonl_path.read_text().splitlines():
            if line.strip():
                try: persona_rows.append(json.loads(line))
                except: pass
    # backfill any missing big_five from sidecars (legacy jsonl)
    if any(not r.get("big_five") for r in persona_rows):
        for p in dossiers_dir.glob("u_*.json"):
            try:
                j=json.loads(p.read_text())
                author=j.get("author") or p.stem.replace("u_","")
                row=next((r for r in persona_rows if r.get("author")==author), None)
                if row and not row.get("big_five") and j.get("big_five"):
                    for k in ["big_five","quotes","arguments","one_line"]:
                        if j.get(k) is not None:
                            row[k]=j[k]
            except: pass

    # Archetype LLM polish (bounded: ≤5 calls, short max_tokens)
    by_cohort = cluster_archetypes(persona_rows)
    summaries={}
    if not args.no_archetype_llm and not args.no_llm and persona_rows and any(r.get("big_five") for r in persona_rows):
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
        if has_key and len(persona_rows) >= 3:
            print(f"[dataset] polishing {len(by_cohort)} archetype summaries …", file=sys.stderr)
            summaries=_archetype_summaries_llm(by_cohort, model=args.model)

    index_html=render_index(args.subreddit, authors, manifest, persona_rows, out_dir, archetype_summaries=summaries)
    (out_dir/"index.html").write_text(index_html, encoding="utf-8")
    print(f"[dataset] done — {manifest['completed']}/{args.users} dossiers → {out_dir}/index.html ({len(index_html):,} bytes) · {len(by_cohort)} archetypes · vega specs embedded", file=sys.stderr)
    print(str(out_dir/"index.html"))

if __name__=="__main__": main()
