#!/usr/bin/env python3
"""
persona.py — Single redditor dossier (DESIGN-Notion.md single-file HTML + V3.3 template).

Usage:
  python persona.py --author spez --limit 100 --out ./dossier-spez.html
  python persona.py --author someuser --limit 500 --model gpt-4o --out ./dossier-someuser.html --no-cache

Without DEEPSEEK_API_KEY/OPENAI_API_KEY: renders a corpus-driven dossier with real quotes + heuristic scores.
With DEEPSEEK_API_KEY (or OPENAI_API_KEY): LLM fills all 8 V3.3 sections with evidence-anchored scores.
"""
import argparse, json, sys, os, html as htmlmod, re, hashlib, time, time
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import fetch_comments_paginated, fetch_posts, fetch_posts_paginated, tokenize, try_llm, STOPWORDS, _load_env_file

CACHE_DIR = Path.home() / ".hermes" / "cache" / "reddit-intel" / "personas"
CACHE_TTL_DAYS = 7

PROMPT_V33 = """You are a communication-style analyst. Given a corpus of Reddit comments by one author, populate the UNIVERSAL COMMUNICATION-STYLE SYNTHESIS TEMPLATE V3.3 (Seven-Signal).

CORPUS (up to 500 comments, truncated):
---
{corpus}
---

TASK: Return a single JSON object with this exact shape (no prose outside JSON):
{{
  "engine": {{ "C": 0-5, "F": 0-5, "A1": 0-5, "A2": 0-5, "P": 0-5, "signature": "e.g. C+ F~ A1+ A2~ P+", "envelope_strong": "...", "envelope_fragile": "...", "failure_modes": ["...","..."], "anchors": {{ "C": "short real phrase", "F": "...", "A1": "...", "A2": "...", "P": "..." }} }},
  "big_five": {{ "openness": "High/Med/Low + one-sentence why", "conscientiousness": "...", "extraversion": "...", "agreeableness": "...", "neuroticism": "..." }},
  "attributes": {{ "enneagram": "...", "iq_band": "e.g. 115-130", "leanings": "...", "reflective_vs_reactive": "...", "thinking_style": "...", "pace": "..." }},
  "style": {{ "verbs": ["..."], "adjectives": ["..."], "transitions": ["..."], "sentence": "...", "rhetoric": "...", "delivery": "..." }},
  "quotes": [{{"text": "real quote from corpus (verbatim 8-30 words)", "source": "r/sub or context", "signal": "what it reveals"}} x 4-6],
  "arguments": {{ "hook": "...", "development": "...", "closure": "..." }},
  "problem_solving": {{ "approach": "...", "archetype_steps": ["step 1","step 2","step 3","step 4"] }},
  "humor": {{ "type": "...", "timing": "...", "range": "...", "destabilizes_when": "..." }},
  "response": {{ "challenge": "...", "reframing": "...", "closure": "...", "aftertaste": "..." }},
  "persona_stack": {{ "MBTI": {{"type":"ENTP","weight":0.9}}, "PRISM": {{"type":"FXMC","weight":0.85}}, "QuEST": {{"type":"QDVF","weight":0.9}}, "RealityLens": {{"type":"D-M-F-Ob","weight":0.82}}, "CauseCraft": {{"type":"T-H-G-X","weight":0.88}}, "ProofPurpose": {{"type":"Ex-Fo-Pr-Be","weight":0.9}}, "ENGINE": {{"type":"C+F+AP","weight":0.93}} }},
  "engine_metrics": {{ "knowledge_density":"C+","refactoring_velocity":"F+","augmentation_affinity":"A","stress_poise":"P" }},
  "one_line": "One sentence: who this person is as a communicator."
}}

Rules:
- Every score and claim needs an evidence anchor — a short real phrase from the corpus.
- Quotes must be verbatim substrings from the corpus (or very close paraphrase if truncated).
- Be directional and probabilistic, not absolute. Note uncertainty where corpus is thin.
- Keep each field concise (1-3 sentences except quotes).
"""

def corpus_text(comments, posts=None, max_chars=30000):
    parts=[]
    for c in comments[:150]:
        body=(c.get("body","") or "").strip()
        if body in ("[deleted]","[removed]","") : continue
        sub=c.get("subreddit","?")
        score=c.get("score",0)
        parts.append(f"[r/{sub} · {score}↑] {body[:380]}")
    if posts:
        for p in posts[:10]:
            t=(p.get("title","") or "")[:180]
            if t: parts.append(f"[post r/{p.get('subreddit','?')}] {t}")
    text="\n".join(parts)
    if len(text)>max_chars:
        text=text[:max_chars]+"… [truncated]"
    return text

def heuristic_engine(comments):
    if not comments: return {"C":2,"F":2,"A1":1,"A2":1,"P":3,"signature":"C~ F~ A1- A2- P~","envelope_strong":"casual discussion","envelope_fragile":"high-stakes debate","failure_modes":["thin corpus"],"anchors":{"C":"—","F":"—","A1":"—","A2":"—","P":"—"}}
    bodies=" ".join((c.get("body","") or "") for c in comments)
    toks=tokenize(bodies)
    uniq=len(set(toks)); total=len(toks) if toks else 1
    avg_len=sum(len((c.get("body","") or "").split()) for c in comments)/len(comments) if comments else 0
    vocab_ratio=uniq/max(total,1)
    # crude heuristics
    C = 4 if vocab_ratio>0.35 and avg_len>40 else (3 if avg_len>20 else 2)
    F = 4 if any(w in bodies.lower() for w in ["however","therefore","because","if","analogy","refactor","pattern"]) else 2
    A1 = 3 if any(w in bodies.lower() for w in ["gpt","ai","tool","script","code","api"]) else 1
    A2 = 2 if "i think" in bodies.lower() or "maybe" in bodies.lower() else 1
    P = 4 if avg_len<60 and bodies.count("!")<len(comments)*0.2 else 2
    sig = f"C{'+' if C>=4 else ('~' if C==3 else '-')} F{'+' if F>=4 else ('~' if F==3 else '-')} A1{'+' if A1>=3 else ('~' if A1==2 else '-')} A2{'+' if A2>=3 else ('~' if A2==2 else '-')} P{'+' if P>=4 else ('~' if P==3 else '-')}"
    # anchors = most distinctive phrases
    anchors={}
    for k,phrase in [("C", bodies[:80]),("F","however" if "however" in bodies.lower() else bodies[80:160]),("A1","tool" if "tool" in bodies.lower() else "—"),("A2","i think" if "i think" in bodies.lower() else "—"),("P", bodies[160:240] if len(bodies)>160 else "—")]:
        anchors[k]=phrase.strip()[:60] or "—"
    return {"C":C,"F":F,"A1":A1,"A2":A2,"P":P,"signature":sig,"envelope_strong":"low-pressure async writing","envelope_fragile":"real-time high-stakes debate","failure_modes":["lexicon-only until LLM pass"],"anchors":anchors}

def render_html(author, comments, posts, synthesis, heuristic, args) -> str:
    esc=lambda s: htmlmod.escape(s or "", quote=False)
    now=datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    n=len(comments)
    # choose synthesis source: LLM synthesis if present else heuristic-shaped
    if synthesis and not synthesis.get("_heuristic"):
        eng=synthesis.get("engine", heuristic)
        big5=synthesis.get("big_five", {})
        attrs=synthesis.get("attributes", {})
        style=synthesis.get("style", {})
        quotes=synthesis.get("quotes", [])[:6]
        args_sec=synthesis.get("arguments", {})
        ps=synthesis.get("problem_solving", {})
        humor=synthesis.get("humor", {})
        resp=synthesis.get("response", {})
        persona_stack=synthesis.get("persona_stack", {})
        engine_metrics=synthesis.get("engine_metrics", {})
        one_line=synthesis.get("one_line","")
        llm_badge="LLM-SYNTHESIZED"
    else:
        eng=heuristic
        # build minimal sections from corpus
        sample_quotes=[]
        for c in comments[:6]:
            body=(c.get("body","") or "").strip()
            if len(body)<20 or body in ("[deleted]","[removed]"): continue
            sample_quotes.append({"text":body[:180], "source": f"r/{c.get('subreddit','?')}", "signal": "corpus sample — heuristic mode"})
            if len(sample_quotes)>=4: break
        big5={"openness":"— (heuristic)","conscientiousness":"—","extraversion":"—","agreeableness":"—","neuroticism":"—"}
        attrs={"enneagram":"—","iq_band":"—","leanings":"—","reflective_vs_reactive":"—","thinking_style":"—","pace":"—"}
        style={"verbs":["—"],"adjectives":["—"],"transitions":["—"],"sentence":"—","rhetoric":"—","delivery":"—"}
        quotes=sample_quotes
        args_sec={"hook":"—","development":"—","closure":"—"}
        ps={"approach":"—","archetype_steps":["collect corpus","score heuristically","render dossier"]}
        humor={"type":"—","timing":"—","range":"—","destabilizes_when":"—"}
        resp={"challenge":"—","reframing":"—","closure":"—","aftertaste":"—"}
        persona_stack={}
        engine_metrics={}
        one_line=f"Heuristic dossier for u/{author} — {n} comments. Add DEEPSEEK_API_KEY for full V3.3 synthesis (deepseek-v4-flash)."
        llm_badge="HEURISTIC · ADD DEEPSEEK_API_KEY FOR FULL V3.3 (deepseek-v4-flash)"

    styles=r"""
:root{--color-notion-blue:#0075de;--color-paper-warmth:#f6f5f4;--color-pure-white:#fff;--color-ink-black:#000;--color-charcoal:#111;--color-stone:#757575;--color-graphite:#615d59;--color-slate:#696969;--color-sky-tint:#e6f3fe;--color-marigold:#ffb110;--color-coral:#f64932;--color-saffron:#e89d01;--color-signal-blue:#097fe8;--color-sky-wash:#62aef0;--color-midnight-ink:#02093a;
 --font-notioninter:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;--font-lyon-text:'Source Serif 4',Georgia,serif;
 --text-caption:12px;--text-body:16px;--text-heading-sm:22px;--text-heading:40px;--text-display:72px;
 --radius-cards:12px;--radius-pills:9999px;--radius-small:4px}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--color-paper-warmth);color:var(--color-ink-black);font-family:var(--font-notioninter);-webkit-font-smoothing:antialiased}
a{color:var(--color-notion-blue)}
.nav{position:sticky;top:0;z-index:20;background:var(--color-pure-white);border-bottom:1px solid rgba(0,0,0,.08);display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:48px}
.nav .left{display:flex;gap:12px;align-items:center;font:700 13px/1 var(--font-notioninter);letter-spacing:.02em}
.nav .right{display:flex;gap:8px;align-items:center}
.pill{display:inline-block;font:500 10px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;padding:4px 8px;border-radius:var(--radius-pills);border:1px solid rgba(0,0,0,.08);white-space:nowrap}
.pill.blue{background:var(--color-notion-blue);color:#fff;border-color:var(--color-notion-blue)}
.pill.warm{background:var(--color-marigold);color:#000;border-color:var(--color-marigold)}
.pill.dark{background:var(--color-midnight-ink);color:#fff;border-color:var(--color-midnight-ink)}
.hero{max-width:1100px;margin:0 auto;padding:28px 16px 18px;text-align:center}
.hero h1{margin:0;font-size:40px;line-height:1.05;letter-spacing:-0.03em;font-weight:700}
.hero h1 em{font-style:normal;background:var(--color-marigold);padding:2px 10px;border-radius:var(--radius-pills)}
.hero .sub{margin:10px auto 0;max-width:62ch;color:var(--color-graphite);font-size:15px;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:0 16px}
section{padding:24px 0;border-bottom:1px solid rgba(0,0,0,.08)}
section:last-of-type{border-bottom:none}
.eyebrow{font:700 11px/1 var(--font-notioninter);letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone);margin:0 0 8px}
h2{margin:0;font-size:22px;letter-spacing:-0.02em;font-weight:700}
.lede{margin:6px 0 0;color:var(--color-graphite);font-size:14px;line-height:1.5;max-width:68ch}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.card{background:var(--color-pure-white);border:1px solid rgba(0,0,0,.08);border-radius:var(--radius-cards);padding:16px}
.card.accent-marigold{background:var(--color-marigold);border-color:var(--color-marigold)}
.card.accent-coral{background:var(--color-coral);border-color:var(--color-coral);color:#fff}
.card.accent-coral .lede,.card.accent-coral p{color:rgba(255,255,255,.9)}
.card.accent-sky{background:var(--color-sky-wash);border-color:var(--color-sky-wash)}
.card.accent-midnight{background:var(--color-midnight-ink);border-color:var(--color-midnight-ink);color:#fff}
.card.accent-midnight .lede,.card.accent-midnight p{color:#cbd5ff}
.kpi{border:1px solid rgba(0,0,0,.08);background:var(--color-pure-white);padding:14px;border-radius:var(--radius-cards);text-align:center}
.kpi b{display:block;font-size:22px;letter-spacing:-0.02em}
.kpi span{font:700 10px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)}
.mono{font-family:ui-monospace,monospace;font-size:12px}
.quote{border-left:3px solid var(--color-marigold);padding:8px 12px;margin:8px 0;background:var(--color-paper-warmth);border-radius:0 var(--radius-small) var(--radius-small) 0}
.quote blockquote{margin:0;font-family:var(--font-lyon-text);font-size:15px;line-height:1.5}
.quote .meta{margin-top:4px;font:500 11px/1 var(--font-notioninter);color:var(--color-stone)}
.table-wrap{background:var(--color-pure-white);border:1px solid rgba(0,0,0,.08);border-radius:var(--radius-cards);overflow:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font:700 10px/1 var(--font-notioninter);letter-spacing:.08em;text-transform:uppercase;color:var(--color-stone);padding:10px 12px;border-bottom:1px solid rgba(0,0,0,.08);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid rgba(0,0,0,.06);vertical-align:top}
.note{margin:8px 0 0;font-size:11px;color:var(--color-stone);line-height:1.5}
.footer{padding:16px;text-align:center;font:500 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone);border-top:1px solid rgba(0,0,0,.08)}
"""
    # Engine score bars
    def score_bar(v):
        pct=max(0,min(100, int(v/5*100)))
        col="var(--color-notion-blue)" if v>=4 else ("var(--color-marigold)" if v>=3 else "var(--color-stone)")
        return f'<div style="height:8px;background:var(--color-paper-warmth);border-radius:999px;overflow:hidden;border:1px solid rgba(0,0,0,.06)"><div style="width:{pct}%;height:100%;background:{col}"></div></div>'
    eng_rows=""
    for ax in ["C","F","A1","A2","P"]:
        v=eng.get(ax,0) if isinstance(eng.get(ax), int) else 0
        anc=esc(eng.get("anchors",{}).get(ax,"—")) if isinstance(eng.get("anchors"), dict) else "—"
        eng_rows+=f"<tr><td><b>{ax}</b></td><td style='min-width:120px'>{score_bar(v)}</td><td class='mono'><b>{v}/5</b></td><td style='max-width:260px;color:var(--color-graphite)'>{anc}</td></tr>"
    # quotes html
    quotes_html=""
    for q in quotes[:6]:
        txt=esc(q.get("text","")[:260])
        src=esc(q.get("source",""))
        sig=esc(q.get("signal",""))
        quotes_html+=f'<div class="quote"><blockquote>“{txt}”</blockquote><div class="meta">{src} · <b style="color:var(--color-ink-black)">{sig}</b></div></div>'
    if not quotes_html:
        quotes_html='<div class="quote"><blockquote>— no quotes extracted (thin corpus)</blockquote></div>'
    # style chips
    def chips(arr): return " ".join(f'<span class="pill">{esc(x)}</span>' for x in (arr or [])[:8] if x and x!="—") or '<span class="pill">—</span>'
    verbs=chips(style.get("verbs",[]))
    adjs=chips(style.get("adjectives",[]))
    trans=chips(style.get("transitions",[]))
    # persona stack json
    stack_json=json.dumps({"persona_stack":persona_stack,"engine_metrics":engine_metrics}, indent=2) if persona_stack else json.dumps({"note":"heuristic mode — no LLM stack"}, indent=2)

    html=f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="color-scheme" content="light"/>
<title>NOTION · u/{esc(author)} — Communication Dossier</title><style>{styles}</style></head><body>
<div class="nav"><div class="left"><span>NOTION</span> <span style="color:var(--color-stone);font-weight:400">· DOSSIER</span> <span style="color:var(--color-stone);font-weight:400">· u/{esc(author)}</span></div>
<div class="right"><span class="pill {'blue' if 'LLM' in llm_badge else 'warm'}">{esc(llm_badge)}</span> <span class="pill">{n} comments</span></div></div>
<div class="hero"><h1>u/{esc(author)} — <em>dossier</em></h1>
<p class="sub">{esc(one_line)} <span style="color:var(--color-stone)">· {now} · {n} comments · V3.3 Seven-Signal</span></p></div>
<div class="wrap">

<section><div class="eyebrow">00 — ENGINE LAYER <em>· capacity & reliability</em></div>
<div class="grid2" style="align-items:start">
<div class="card accent-midnight">
  <div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.08em;text-transform:uppercase;color:var(--color-marigold)">Signature</div>
  <div style="font-size:24px;font-weight:700;letter-spacing:-0.02em;margin-top:6px">{esc(eng.get('signature','—'))}</div>
  <div class="lede" style="color:#cbd5ff">C Crystallized · F Fluid · A1 Instrumental · A2 Meta-Cog · P Pressure — 0-5 with polarity H/M/L</div>
  <div style="margin-top:10px;display:grid;gap:6px">
    <div style="font-size:12px"><b>Strong envelope:</b> {esc(eng.get('envelope_strong','—'))}</div>
    <div style="font-size:12px"><b>Fragile envelope:</b> {esc(eng.get('envelope_fragile','—'))}</div>
    <div style="font-size:12px"><b>Failure modes:</b> {esc(', '.join(eng.get('failure_modes',[])[:3]))}</div>
  </div>
</div>
<div class="table-wrap"><table><thead><tr><th>Axis</th><th>Score</th><th></th><th>Evidence anchor</th></tr></thead><tbody>{eng_rows}</tbody></table></div>
</div>
<p class="note">Engine modulates all downstream layers. Directional, probabilistic, revisable. Anchors are short real phrases from corpus.</p>
</section>

<section><div class="eyebrow">01 — CORE COMMUNICATION & PERSONALITY <em>· Big Five + attributes</em></div>
<div class="card" style="margin-top:10px">
<div class="grid2">
<div><div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)">Big Five (linguistically inferred)</div>
<ul style="margin:8px 0 0;padding:0 0 0 16px;font-size:13px;line-height:1.6">
<li><b>Openness:</b> {esc(big5.get('openness','—'))}</li>
<li><b>Conscientiousness:</b> {esc(big5.get('conscientiousness','—'))}</li>
<li><b>Extraversion:</b> {esc(big5.get('extraversion','—'))}</li>
<li><b>Agreeableness:</b> {esc(big5.get('agreeableness','—'))}</li>
<li><b>Neuroticism:</b> {esc(big5.get('neuroticism','—'))}</li>
</ul></div>
<div><div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)">Attributes</div>
<ul style="margin:8px 0 0;padding:0 0 0 16px;font-size:13px;line-height:1.6">
<li><b>Enneagram:</b> {esc(attrs.get('enneagram','—'))}</li>
<li><b>IQ band:</b> {esc(attrs.get('iq_band','—'))}</li>
<li><b>Leanings:</b> {esc(attrs.get('leanings','—'))}</li>
<li><b>Reflective vs Reactive:</b> {esc(attrs.get('reflective_vs_reactive', attrs.get('reflective_vs_reactive','—')) or attrs.get('reflective_vs_reactive','—'))}</li>
<li><b>Thinking style:</b> {esc(attrs.get('thinking_style','—'))}</li>
<li><b>Pace:</b> {esc(attrs.get('pace','—'))}</li>
</ul></div>
</div>
</div>
</section>

<section><div class="eyebrow">02 — SIGNATURE STYLE <em>· linguistic fingerprint</em></div>
<div class="grid2">
<div class="card"><div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)">Vocabulary</div>
<div style="margin-top:8px;font-size:12px;color:var(--color-stone)">Verbs</div><div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:6px">{verbs}</div>
<div style="margin-top:8px;font-size:12px;color:var(--color-stone)">Adjectives</div><div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:6px">{adjs}</div>
<div style="margin-top:8px;font-size:12px;color:var(--color-stone)">Transitions</div><div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:6px">{trans}</div>
</div>
<div class="card accent-marigold"><div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase">Sentence & rhetoric</div>
<p style="margin:8px 0 0;font-size:13px;line-height:1.5"><b>Sentence:</b> {esc(style.get('sentence','—'))}</p>
<p style="margin:6px 0 0;font-size:13px;line-height:1.5"><b>Rhetoric:</b> {esc(style.get('rhetoric','—'))}</p>
<p style="margin:6px 0 0;font-size:13px;line-height:1.5"><b>Delivery:</b> {esc(style.get('delivery','—'))}</p>
</div>
</div>
</section>

<section><div class="eyebrow">03 — EXAMPLE QUOTES <em>· grounded in corpus</em></div>
<div class="card" style="margin-top:10px">{quotes_html}</div>
</section>

<section><div class="eyebrow">04 — STRUCTURE OF ARGUMENTS <em>· hook → development → closure</em></div>
<div class="grid2">
<div class="card"><p style="margin:0;font-size:13px;line-height:1.6"><b>Hook:</b> {esc(args_sec.get('hook','—'))}</p><p style="margin:8px 0 0;font-size:13px;line-height:1.6"><b>Development:</b> {esc(args_sec.get('development','—'))}</p><p style="margin:8px 0 0;font-size:13px;line-height:1.6"><b>Closure:</b> {esc(args_sec.get('closure','—'))}</p></div>
<div class="card accent-sky"><div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-stone)">Corpus sample</div><p class="lede">Quotes above are verbatim from corpus. Below is raw comment count and avg length for calibration.</p>
<div class="grid2" style="margin-top:8px"><div class="kpi"><span>Comments</span><b>{n}</b></div><div class="kpi"><span>Avg words</span><b>{round(sum(len((c.get('body','') or '').split()) for c in comments)/max(n,1)) if n else 0}</b></div></div>
</div>
</div>
</section>

<section><div class="eyebrow">05 — PROBLEM-SOLVING <em>· how uncertainty is resolved</em></div>
<div class="card"><p style="margin:0;font-size:13px;line-height:1.6"><b>Approach:</b> {esc(ps.get('approach','—'))}</p>
<ol style="margin:8px 0 0;padding:0 0 0 18px;font-size:13px;line-height:1.7">
{''.join(f'<li>{esc(s)}</li>' for s in ps.get('archetype_steps',[])[:6])}
</ol></div>
</section>

<section><div class="eyebrow">06 — HUMOR, DRAMA & EMOTIONAL NUANCE</div>
<div class="grid2">
<div class="card"><p style="margin:0;font-size:13px;line-height:1.6"><b>Type:</b> {esc(humor.get('type','—'))}</p><p style="margin:6px 0 0;font-size:13px;line-height:1.6"><b>Timing:</b> {esc(humor.get('timing','—'))}</p><p style="margin:6px 0 0;font-size:13px;line-height:1.6"><b>Range:</b> {esc(humor.get('range','—'))}</p></div>
<div class="card accent-coral"><p style="margin:0;font-size:13px;line-height:1.6"><b>Destabilizes when:</b> {esc(humor.get('destabilizes_when','—'))}</p><p class="lede" style="color:rgba(255,255,255,.85);margin-top:8px">Critical for persuasion and digital twin fidelity — where humor sharpens vs collapses.</p></div>
</div>
</section>

<section><div class="eyebrow">07 — RESPONSE STRATEGIES & CLOSING TECHNIQUES</div>
<div class="card"><p style="margin:0;font-size:13px;line-height:1.6"><b>Challenge handling:</b> {esc(resp.get('challenge','—'))}</p><p style="margin:6px 0 0;font-size:13px;line-height:1.6"><b>Reframing:</b> {esc(resp.get('reframing','—'))}</p><p style="margin:6px 0 0;font-size:13px;line-height:1.6"><b>Closure:</b> {esc(resp.get('closure','—'))}</p><p style="margin:6px 0 0;font-size:13px;line-height:1.6"><b>Aftertaste:</b> {esc(resp.get('aftertaste','—'))}</p></div>
</section>

<section><div class="eyebrow">APPENDIX A — SEVEN-SIGNAL TABLE</div>
<div class="table-wrap"><table><thead><tr><th>Layer</th><th>Question</th><th>Primary signals</th></tr></thead><tbody>
<tr><td><b>Engine</b></td><td>Can they execute?</td><td>Speed, density, stress shifts</td></tr>
<tr><td>MBTI</td><td>How they think</td><td>Syntax, abstraction</td></tr>
<tr><td>PRISM</td><td>What they value</td><td>Moral framing</td></tr>
<tr><td>QuEST</td><td>How they act</td><td>Tempo, pressure</td></tr>
<tr><td>Reality Lens</td><td>What is real</td><td>Ontology, metaphor</td></tr>
<tr><td>Cause & Craft</td><td>How they build</td><td>Evidence type</td></tr>
<tr><td>Proof & Purpose</td><td>Why they speak</td><td>Ethical closure</td></tr>
</tbody></table></div>
</section>

<section><div class="eyebrow">APPENDIX B — JSON RUBRIC <em>· AI-friendly persona_stack</em></div>
<div class="card" style="background:var(--color-midnight-ink);color:#cbd5ff;border-color:var(--color-midnight-ink)">
<div style="font:700 11px/1 var(--font-notioninter);letter-spacing:.06em;text-transform:uppercase;color:var(--color-marigold)">persona_stack + engine_metrics</div>
<pre class="mono" style="margin:10px 0 0;white-space:pre-wrap;word-break:break-word;font-size:11px;line-height:1.5">{esc(stack_json)}</pre>
</div>
<p class="note">Heuristic mode uses lexicon/vocab signals. LLM mode fills every field with evidence anchors. Re-run with --limit 500 for deeper fidelity.</p>
</section>

</div>
<div class="footer">NOTION · Communication Dossier · u/{esc(author)} · {now} · Arctic Shift archive · Notion tokens #f6f5f4 / #ffb110 / 12px cards · Single-file HTML — opens offline</div>
</body></html>"""
    return html

def main():
    ap=argparse.ArgumentParser(description="Redditor dossier — Notion V3.3")
    ap.add_argument("--author", required=True, help="reddit username without u/")
    ap.add_argument("--limit", type=int, default=100, help="comments to fetch (100/500, paginated)")
    ap.add_argument("--model", default="deepseek-v4-flash", help="LLM model for synthesis (deepseek-v4-flash recommended for prompt-cache savings)")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="force heuristic even if key present")
    args=ap.parse_args()

    _load_env_file()
    print(f"[persona] u/{args.author} limit={args.limit} model={args.model}", file=sys.stderr)
    # cache
    cache_file=CACHE_DIR / f"u_{args.author}_{args.limit}.json"
    comments=None; posts=None
    if not args.no_cache and cache_file.exists():
        try:
            age_days=(time.time() - cache_file.stat().st_mtime)/86400
            if age_days < CACHE_TTL_DAYS:
                j=json.loads(cache_file.read_text())
                comments=j.get("comments",[])
                posts=j.get("posts",[])
                print(f"[persona] cache hit {cache_file} age {age_days:.1f}d {len(comments)} comments", file=sys.stderr)
        except Exception as e:
            print(f"[persona] cache miss: {e}", file=sys.stderr)

    if comments is None:
        comments=fetch_comments_paginated(author=args.author, total=args.limit)
        # also fetch a few posts for cross-check
        try:
            posts=fetch_posts(author=args.author, limit=20) if False else None
            # lightweight: fetch via posts search by author if available
            from analyze import api_get
            try:
                d=api_get("/api/posts/search", {"author":args.author,"limit":min(20,args.limit),"sort":"desc","meta-app":"reddit-intel"})
                posts=d.get("data",[])
            except: posts=[]
        except: posts=[]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"comments":comments,"posts":posts or [],"fetched_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
        print(f"[persona] fetched {len(comments)} comments, {len(posts or [])} posts → cached", file=sys.stderr)

    if not comments:
        print(f"[persona] no comments found for u/{args.author} — check username or try --limit 500", file=sys.stderr)
        # still render empty dossier
        comments=[]

    heuristic=heuristic_engine(comments)
    corpus=corpus_text(comments, posts, max_chars=30000)
    synthesis=None
    if not args.no_llm and (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        print(f"[persona] LLM synthesis with {args.model} …", file=sys.stderr)
        # Prompt-cache: system=full V3.3 template (stable prefix), user=corpus (variable). DeepSeek caches system automatically.
        # PROMPT_V33 has {corpus} placeholder — extract template part as system
        _system = PROMPT_V33.replace("{corpus}", "[CORPUS INSERTED IN USER MESSAGE]")
        _user = f"CORPUS (up to 500 comments, truncated):\n---\n{corpus}\n---\n\nTASK: Return ONLY the single JSON object with the exact shape described in the system prompt. No prose outside JSON."
        raw=try_llm(_user, model=args.model, system_prompt=_system)
        if raw:
            # DeepSeek sometimes wraps JSON in markdown or uses different top-level keys
            # Extract largest JSON object
            m=re.search(r"\{.*\}", raw, re.S)
            if m:
                # handle case where raw contains multiple top-level objects — find the one with "engine"
                candidates=re.findall(r"\{[^{}]*\"engine\"[^}]*\}", raw, re.S)
                # try full parse first, then fallback to engine-containing object
                try:
                    synthesis=json.loads(m.group(0))
                    # normalize DeepSeek's alternative shape if needed
                    if "engine" not in synthesis and "signals" in synthesis:
                        # DeepSeek returned signals/synthesis shape — map to V3.3 minimally
                        # keep raw as fallback and flag for manual mapping
                        print(f"[persona] LLM returned alternative shape (signals) — using as-is with heuristic fallback", file=sys.stderr)
                        # try to extract engine from signals if present
                        if "synthesis" in synthesis and isinstance(synthesis["synthesis"], dict):
                            # attempt to build minimal engine from signals
                            sig=synthesis["synthesis"]
                            # keep full synthesis for now
                            pass
                        synthesis={"_heuristic":True, **heuristic, "_raw_alternative": synthesis}
                    else:
                        print(f"[persona] LLM synthesis ok — signature {synthesis.get('engine',{}).get('signature','—')}", file=sys.stderr)
                except Exception as e:
                    print(f"[persona] LLM JSON parse failed: {e}\n{raw[:800]}", file=sys.stderr)
                    synthesis={"_heuristic":True, **heuristic}
            else:
                print(f"[persona] LLM returned no JSON — raw: {raw[:400]}", file=sys.stderr)
                synthesis={"_heuristic":True}
        else:
            synthesis={"_heuristic":True}
    else:
        if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
            print(f"[persona] no DEEPSEEK_API_KEY/OPENAI_API_KEY — heuristic mode (add key for full V3.3)", file=sys.stderr)
        synthesis={"_heuristic":True}

    # if synthesis is heuristic flag, render will use heuristic path
    if synthesis and synthesis.get("_heuristic"):
        synthesis=None

    html=render_html(args.author, comments, posts or [], synthesis, heuristic, args)
    out=Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[persona] wrote {out} ({len(html):,} bytes) — {len(comments)} comments", file=sys.stderr)
    print(str(out))
    # also emit rubric json sidecar (enriched for dataset clustering)
    # Always write sidecar when we have synthesis; also write minimal sidecar in heuristic mode so dataset can still cluster on Engine
    rubric_payload=None
    if synthesis:
        rubric_payload={
            "author": args.author,
            "engine": synthesis.get("engine"),
            "big_five": synthesis.get("big_five"),
            "persona_stack": synthesis.get("persona_stack"),
            "engine_metrics": synthesis.get("engine_metrics"),
            "quotes": (synthesis.get("quotes") or [])[:2],
            "arguments": synthesis.get("arguments"),
            "one_line": synthesis.get("one_line"),
            "model": args.model,
            "comments": len(comments),
        }
    elif heuristic:
        rubric_payload={
            "author": args.author,
            "engine": heuristic,
            "big_five": None,
            "persona_stack": None,
            "engine_metrics": None,
            "quotes": [{"text": (comments[0].get("body","") or "")[:160], "source": f"r/{comments[0].get('subreddit','?')}", "signal": "heuristic sample"}] if comments else [],
            "arguments": None,
            "one_line": f"Heuristic dossier for u/{author} — {n} comments.",
            "model": "heuristic",
            "comments": len(comments),
        }
    if rubric_payload:
        sidecar=out.with_suffix(".json")
        sidecar.write_text(json.dumps(rubric_payload, ensure_ascii=False, indent=2))
        print(f"[persona] rubric → {sidecar}", file=sys.stderr)

if __name__=="__main__": main()
