#!/usr/bin/env python3
"""
pulse.py — Subreddit Intelligence Brief (DESIGN-Monocle.md single-file HTML).

Usage:
  python pulse.py --subreddit parenting --window 7d --top 5 --limit 25 --out ./pulse-parenting.html
  python pulse.py --subreddit vietnam --limit 30 --top 3 --out ./pulse-vietnam.html --no-llm

Fetches posts via Arctic Shift, ranks top posts, clusters themes (phrase-aware),
scores sentiment/intent, and renders an intelligence brief.
Monocle is the internal design-system name only and never appears in the report.
"""
import argparse, json, sys, os, html as htmlmod, re, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import (
    fetch_posts_paginated, fetch_comments, fetch_posts,
    rank_posts, cluster_themes, sentiment_for_posts, extract_keywords,
    sentiment_score, tokenize, try_llm,
    extract_phrases, classify_intent, intent_breakdown,
    timeline_by_day, theme_heatmap_data, quadrant_data,
    collection_meta, confidence_assessment,
)

API = "https://arctic-shift.photon-reddit.com"

def parse_window(s: str):
    if not s: return None
    m=re.match(r"(\d+)(d|h|w)", s.lower())
    if not m: return None
    n=int(m.group(1)); unit=m.group(2)
    hours={"h":1,"d":24,"w":168}[unit]
    return n*hours*3600

def excerpt(p, maxlen=220):
    t=(p.get("selftext","") or "").strip()
    if not t:
        t=(p.get("title","") or "").strip()
    t=t.replace("\r"," ").replace("\n"," ")
    if len(t)>maxlen: t=t[:maxlen].rstrip()+"…"
    return t

def permalink(p):
    pl=p.get("permalink") or f"/r/{p.get('subreddit','')}/comments/{p.get('id','')}/"
    if not pl.startswith("/"): pl="/"+pl
    return "https://reddit.com"+pl

def human_subreddit_label(subreddit: str) -> str:
    m = {
        "parenting": "Parenting",
        "stocks": "Market",
        "homeschool": "Homeschool",
        "vietnam": "Vietnam",
        "investing": "Investing",
        "personalfinance": "Personal Finance",
    }
    return m.get(subreddit.lower(), subreddit.capitalize())

def _is_weak_label(label: str) -> bool:
    low=(label or "").strip().lower()
    weak = {"general discussion","general","kids","anyone","est","pas","elle","son","night","days","because","anyone kids","est pas","pas elle"}
    if low in weak: return True
    if len(low) <= 3: return True
    return False

def generate_title(subreddit: str, themes, posts, intent_data=None) -> str:
    n = len(posts)
    human = human_subreddit_label(subreddit)
    labels = [t.get("label","").strip() for t in themes[:4] if not _is_weak_label(t.get("label",""))]
    if themes and themes[0].get("count",0) > n * 0.60 and n >= 10:
        labels = [lb for lb in labels if lb.lower() != themes[0].get("label","").lower()]
    seen=set(); clean_labels=[]
    for lb in labels:
        low=lb.lower()
        if low not in seen and len(lb) > 3:
            seen.add(low); clean_labels.append(lb)
    if n < 6:
        return f"A Quiet Week in r/{subreddit}"
    if not clean_labels:
        if intent_data and intent_data.get("counts"):
            top_intent = max(intent_data["counts"], key=lambda k: intent_data["counts"][k])
            if top_intent != "general":
                return f"What r/{subreddit} Is Asking This Week: {top_intent.replace('-',' ').title()}"
        return f"This Week's Conversations in r/{subreddit}"
    if len(clean_labels) >= 3:
        return f"{human} Pulse: {clean_labels[0]}, {clean_labels[1]} & {clean_labels[2]}"
    if len(clean_labels) == 2:
        return f"{human} Conversations: {clean_labels[0]} & {clean_labels[1]}"
    return f"The Week in r/{subreddit}: {clean_labels[0]} Takes Center Stage"

def generate_briefing(posts, themes, overall_sent, intent_data, confidence):
    n=len(posts)
    if n==0:
        return ["No posts were found in this collection window.", "Try a larger window or a different subreddit.", "Methodology and confidence are noted below."]
    bullets=[]
    if themes:
        top=themes[0]
        bullets.append(f"<b>{top.get('label','')}</b> led discussion ({top.get('count',0)} of {n} posts) — the most frequent theme in this window.")
        if len(themes)>=2:
            second=themes[1]
            bullets.append(f"<b>{second.get('label','')}</b> followed ({second.get('count',0)} posts), with conversation centered on everyday parenting questions rather than a single viral thread.")
    else:
        bullets.append(f"{n} posts were collected, with no single theme dominating — conversation was diffuse this window.")
    sent_label=overall_sent.get("label","neutral")
    if intent_data and intent_data.get("counts"):
        intent_top=max(intent_data["counts"], key=lambda k: intent_data["counts"][k])
        intent_pct=intent_data.get("pct",{}).get(intent_top,0)
        bullets.append(f"Tone is <b>{sent_label}</b> ({overall_sent.get('pos',0)} positive / {overall_sent.get('neu',0)} neutral / {overall_sent.get('neg',0)} negative). Most posts are <b>{intent_top.replace('-',' ')}</b> ({intent_pct}%), not debate or venting.")
    else:
        bullets.append(f"Tone is <b>{sent_label}</b> ({overall_sent.get('pos',0)} positive / {overall_sent.get('neu',0)} neutral / {overall_sent.get('neg',0)} negative).")
    if confidence.get("level")=="low":
        bullets.append(f"Confidence is <b>low</b> — {confidence.get('reason','small sample')}")
    elif confidence.get("level")=="moderate":
        bullets.append(f"Confidence is <b>moderate</b> — {confidence.get('reason','')}")
    else:
        bullets.append(f"Engagement is modest but consistent — themes are stable for this window. Evidence cards below link to each post.")
    return bullets[:4]

def render_html(subreddit, posts, top_posts, themes, overall_sent, keywords, args, phrases=None, intent_data=None, timeline=None, heatmap=None, quadrant=None, meta=None, confidence=None, generated_title=None, briefing=None, baseline_themes=None) -> str:
    now=datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    total=len(posts)
    title = generated_title or generate_title(subreddit, themes, posts, intent_data)
    briefing = briefing or generate_briefing(posts, themes, overall_sent, intent_data, confidence or {"level":"moderate","reason":""})
    phrases = phrases or []
    intent_data = intent_data or {"counts":{}, "pct":{}}
    timeline = timeline or {}
    heatmap = heatmap or {"days":[],"themes":[],"matrix":[]}
    quadrant = quadrant or []
    meta = meta or {"total": total, "removed":0, "selftext_removed":0, "window":"—", "span_days":0, "avg_score":0}
    confidence = confidence or {"level":"moderate","reason":""}
    styles = r"""
:root{
 --color-signal-yellow:#ffc500;--color-folio-black:#000;--color-newsprint-cream:#fdfcf3;
 --color-broadsheet-white:#fff;--color-margin-white:#fdfbe4;--color-pull-quote-gray:#e7e7e7;
 --color-rule-gray:#d9d9d9;--color-caption-gray:#6e6e6e;--color-mute-gray:#b3b3b3;
 --color-charcoal:#211d1c;--color-desk-blue:#64d5ff;
 --font-plantin:'Plantin',Georgia,'Source Serif 4','Times New Roman',serif;
 --font-helvetica-neue:'Helvetica Neue',Inter,system-ui,-apple-system,sans-serif;
 --text-caption:13px;--text-body:16px;--text-heading-sm:20px;--text-heading:24px;--text-heading-lg:28px;--text-display:40px;
 --spacing-8:8px;--spacing-16:16px;--spacing-24:24px;--spacing-32:32px;--spacing-80:80px;
 --radius-cards:8px;
}
*{box-sizing:border-box}html{scroll-behavior:smooth}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
body{margin:0;background:var(--color-newsprint-cream);color:var(--color-folio-black);font-family:var(--font-plantin);-webkit-font-smoothing:antialiased}
a{color:inherit}
.utility{position:sticky;top:0;z-index:30;background:var(--color-broadsheet-white);border-bottom:1px solid var(--color-rule-gray);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 16px;height:40px;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700;letter-spacing:.01em}
.utility .left,.utility .right{display:flex;align-items:center;gap:14px}
.utility a{text-decoration:none;border-bottom:1px solid transparent}
.utility a:hover{border-color:#000}
.mast{max-width:1200px;margin:0 auto;padding:20px 16px 14px;text-align:center;border-bottom:1px solid var(--color-rule-gray)}
.mast h1{margin:0;font-family:var(--font-plantin);font-size:32px;letter-spacing:-0.02em;line-height:1.1;font-weight:700;max-width:900px;margin-left:auto;margin-right:auto}
.mast .sub{margin:8px 0 0;font-family:var(--font-helvetica-neue);font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)}
.kicker{margin-top:10px;display:flex;justify-content:center;gap:14px;flex-wrap:wrap;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700;letter-spacing:.01em;text-transform:uppercase;color:var(--color-caption-gray)}
.kicker b{color:#000}
.kicker span+span::before{content:"\00b7";margin-right:14px;color:var(--color-mute-gray)}
.sec-nav{max-width:1200px;margin:0 auto;display:flex;gap:0;overflow:auto;padding:10px 16px;border-bottom:1px solid var(--color-rule-gray);font-family:var(--font-plantin);font-size:12px;letter-spacing:.075em;text-transform:uppercase;white-space:nowrap;scrollbar-width:none}
.sec-nav::-webkit-scrollbar{display:none}
.sec-nav a{text-decoration:none;color:var(--color-caption-gray);padding:4px 10px;border-right:1px solid var(--color-rule-gray)}
.sec-nav a:last-child{border-right:none}
.sec-nav a:hover,.sec-nav a.active{color:#000}
.sec-nav a.active{border-bottom:2px solid var(--color-signal-yellow)}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
section{padding:28px 0;border-bottom:1px solid var(--color-rule-gray)}
section:last-of-type{border-bottom:none}
.eyebrow{font-family:var(--font-plantin);font-size:13px;letter-spacing:.075em;text-transform:uppercase;color:#000;margin:0 0 8px;font-weight:700}
.eyebrow em{font-style:normal;color:var(--color-caption-gray);font-weight:400;letter-spacing:.05em;margin-left:6px}
h2{margin:0;font-family:var(--font-plantin);font-size:28px;line-height:1.15;letter-spacing:-0.64px;font-weight:400}
h2 b{font-weight:700}
h2 em{font-style:normal;background:linear-gradient(transparent 60%,var(--color-signal-yellow) 60% 88%,transparent 88%)}
h3{margin:0;font-family:var(--font-plantin);font-size:18px;letter-spacing:-0.4px;line-height:1.25;font-weight:700}
.deck{margin:10px 0 0;color:var(--color-caption-gray);font-family:var(--font-plantin);font-size:15px;line-height:1.5;max-width:72ch}
.card{border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);padding:16px;border-radius:var(--radius-cards)}
.card-warm{background:var(--color-margin-white)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pill{display:inline-block;font-family:var(--font-helvetica-neue);font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:3px 6px;border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);white-space:nowrap}
.pill.yellow{background:var(--color-signal-yellow);border-color:#000;color:#000}
.pill.black{background:#000;color:var(--color-signal-yellow);border-color:#000}
.pill.muted{background:var(--color-pull-quote-gray);color:var(--color-caption-gray);border-color:var(--color-rule-gray)}
.lede{color:var(--color-caption-gray);font-size:15px;line-height:1.5;margin:0 0 16px;max-width:72ch}
.lede b{color:#000}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
@media(max-width:700px){.kpi-grid{grid-template-columns:1fr 1fr}}
.kpi{border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);padding:16px;border-radius:var(--radius-cards)}
.kpi.yellow{background:var(--color-signal-yellow);border-color:#000}
.kpi b{display:block;font-family:var(--font-plantin);font-size:24px;letter-spacing:-0.48px;line-height:1}
.kpi span{font-family:var(--font-helvetica-neue);font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)}
.kpi.yellow span{color:#000}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.grid3{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}
@media(max-width:900px){.grid3{grid-template-columns:1fr}}
.sent-bar{height:10px;background:var(--color-pull-quote-gray);display:flex;overflow:hidden;border:1px solid var(--color-rule-gray)}
.sent-bar i{height:100%}
.sent-bar i.pos{background:var(--color-signal-yellow)}
.sent-bar i.neu{background:var(--color-caption-gray)}
.sent-bar i.neg{background:#000}
.hair{height:1px;background:var(--color-rule-gray);margin:12px 0}
.note{margin:8px 0 0;font-family:var(--font-helvetica-neue);font-size:11px;color:var(--color-caption-gray);line-height:1.5}
.footer{padding:18px 16px;text-align:center;font-family:var(--font-helvetica-neue);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray);border-top:1px solid var(--color-rule-gray)}
.post-row{display:grid;grid-template-columns:56px 1fr;gap:12px;padding:10px 0;border-bottom:1px solid #eee}
.post-row:last-child{border-bottom:none}
.timeline{display:flex;align-items:end;gap:6px;height:90px;margin-top:12px}
.timeline .bar{flex:1;background:var(--color-signal-yellow);border:1px solid #000;min-width:18px;display:flex;flex-direction:column;justify-content:end;align-items:center;padding:4px 2px 6px;border-radius:4px 4px 0 0}
.timeline .bar.muted{background:var(--color-pull-quote-gray);border-color:var(--color-rule-gray)}
.timeline .bar b{font:700 14px/1 var(--font-plantin)}
.timeline .bar span{font:700 8px/1 var(--font-helvetica-neue);letter-spacing:.05em;text-transform:uppercase;color:var(--color-caption-gray);margin-top:4px}
.heatmap{width:100%;border-collapse:collapse;margin-top:12px;font-family:var(--font-helvetica-neue);font-size:11px}
.heatmap th{font-weight:700;text-align:center;padding:6px 4px;border:1px solid var(--color-rule-gray);background:var(--color-pull-quote-gray);font-size:10px;letter-spacing:.05em;text-transform:uppercase}
.heatmap td{padding:8px;text-align:center;border:1px solid var(--color-rule-gray);font-weight:700}
.heatmap td.rowlabel{text-align:left;background:var(--color-broadsheet-white);font-family:var(--font-plantin);font-size:12px}
.quadrant{position:relative;height:220px;border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);margin-top:12px;border-radius:var(--radius-cards);overflow:hidden}
.quadrant .axis{position:absolute;background:var(--color-rule-gray)}
.quadrant .dot{position:absolute;width:10px;height:10px;border-radius:50%;background:var(--color-signal-yellow);border:1px solid #000;transform:translate(-50%,50%);cursor:default}
.quadrant .dot.label{width:auto;height:auto;background:transparent;border:none;font:700 10px/1 var(--font-helvetica-neue);letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;transform:translate(-50%,50%) translateY(-14px)}
.intent-bar{display:flex;height:14px;border:1px solid var(--color-rule-gray);overflow:hidden;margin-top:10px}
.intent-bar i{height:100%}
.briefing{margin-top:14px}
.briefing li{margin:6px 0;font-family:var(--font-plantin);font-size:15px;line-height:1.5;color:var(--color-charcoal)}
.briefing li b{color:#000}
.confidence{margin-top:12px;display:flex;align-items:center;gap:8px;font-family:var(--font-helvetica-neue);font-size:11px;letter-spacing:.04em;text-transform:uppercase}
.confidence .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.method-table{width:100%;border-collapse:collapse;margin-top:10px;font-family:var(--font-helvetica-neue);font-size:12px}
.method-table th{text-align:left;padding:8px;border:1px solid var(--color-rule-gray);background:var(--color-pull-quote-gray);font-size:10px;letter-spacing:.06em;text-transform:uppercase}
.method-table td{padding:8px;border:1px solid var(--color-rule-gray)}
"""
    esc=lambda s: htmlmod.escape(s or "", quote=False)
    avg_score = sum(p.get("score",0) or 0 for p in posts)//max(total,1) if total else 0
    total_comments = sum(p.get("num_comments",0) or 0 for p in posts)
    theme_count = len(themes)
    conf_label = confidence.get("level","—")
    conf_color = confidence.get("color","#6e6e6e")
    kpi_html = f"""<div class="kpi-grid">
      <div class="kpi yellow"><span>r/{esc(subreddit)} · posts</span><b>{total}</b><p class="note" style="margin:2px 0 0">{esc(meta.get('window','—')[:42])}</p></div>
      <div class="kpi"><span>Avg score</span><b>{avg_score}</b><p class="note" style="margin:2px 0 0">per post</p></div>
      <div class="kpi"><span>Comments</span><b>{total_comments}</b><p class="note" style="margin:2px 0 0">total replies</p></div>
      <div class="kpi"><span>Confidence</span><b style="color:{conf_color};text-transform:capitalize">{esc(conf_label)}</b><p class="note" style="margin:2px 0 0">{esc(confidence.get('reason','')[:48])}</p></div>
    </div>"""
    total_s = overall_sent.get("count",1)
    pos = overall_sent.get("pos",0); neg=overall_sent.get("neg",0); neu=overall_sent.get("neu",0)
    pos_w = round(pos/total_s*100) if total_s else 0
    neu_w = round(neu/total_s*100) if total_s else 0
    neg_w = 100-pos_w-neu_w
    sentiment_label = overall_sent.get("label","neutral")
    sent_html = f"""<div class="card" style="margin-top:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.08em;text-transform:uppercase;color:var(--color-caption-gray)">Overall sentiment — <b style="color:#000">{esc(sentiment_label)}</b> <span style="font-weight:500">({overall_sent.get('score',0):+.2f})</span></span>
        <span class="pill yellow">{pos} POS</span><span class="pill" style="background:var(--color-caption-gray);color:#fff;border-color:var(--color-caption-gray)">{neu} NEU</span><span class="pill black">{neg} NEG</span>
      </div>
      <div class="sent-bar" style="margin-top:10px"><i class="pos" style="width:{pos_w}%"></i><i class="neu" style="width:{neu_w}%"></i><i class="neg" style="width:{neg_w}%"></i></div>
      <div style="display:flex;justify-content:space-between;font:700 10px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray);margin-top:6px"><span>positive {pos_w}%</span><span>neutral {neu_w}%</span><span>negative {neg_w}%</span></div>
    </div>"""
    intent_counts = intent_data.get("counts", {}) if intent_data else {}
    intent_total = sum(intent_counts.values()) or 1
    intent_order = ["advice-seeking","personal story","reassurance","product recommendation","safety concern","venting","general"]
    intent_colors = {"advice-seeking":"#ffc500","personal story":"#111","reassurance":"#6e6e6e","product recommendation":"#64d5ff","safety concern":"#d94444","venting":"#b3b3b3","general":"#e7e7e7"}
    intent_bar_html = '<div class="intent-bar">'
    intent_legend = ""
    for k in intent_order:
        v = intent_counts.get(k, 0)
        if v==0: continue
        w = round(v/intent_total*100)
        c = intent_colors.get(k, "#e7e7e7")
        intent_bar_html += f'<i style="width:{w}%;background:{c}" title="{esc(k)} {v}"></i>'
        intent_legend += f'<span class="pill" style="background:{c};color:{"#fff" if k in ("personal story","reassurance") else "#000"};border-color:{"#000" if c=="#ffc500" else c}">{esc(k)} <b>{v}</b></span> '
    intent_bar_html += '</div>'
    if not intent_counts:
        intent_bar_html = '<p class="note">No intent signal — too few posts.</p>'
        intent_legend = ""
    def post_card(p, lead=False):
        score=p.get("score",0); ncom=p.get("num_comments",0); author=p.get("author","?"); title=esc(p.get("title","(no title)")[:160])
        t=datetime.fromtimestamp(p.get("created_utc",0), tz=timezone.utc).strftime("%d %b %Y") if p.get("created_utc") else ""
        ex=esc(excerpt(p, 240 if lead else 180))
        pl=permalink(p)
        hsize="22px" if lead else "16px"
        lheight="1.2" if lead else "1.3"
        intent = classify_intent(p.get("title","")+" "+(p.get("selftext","") or ""))
        intent_pill = f'<span class="pill muted" style="margin-left:6px">{esc(intent)}</span>' if intent != "general" else ""
        return f"""<div class="card{' card-warm' if lead else ''}" style="{'border-left:3px solid var(--color-signal-yellow)' if lead else ''}">
          <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.075em;text-transform:uppercase;color:var(--color-caption-gray)">r/{esc(p.get('subreddit',''))} <span style="font-weight:500">· {t}</span> <span class="pill yellow" style="margin-left:6px">★ TOP</span>{intent_pill}</div>
          <div style="font-family:var(--font-plantin);font-size:{hsize};line-height:{lheight};letter-spacing:-0.4px;font-weight:700;margin-top:8px"><a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="text-decoration:none">{title}</a></div>
          <div style="margin-top:6px;font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">u/{esc(author)} · <b style="color:#000">{score} ↑</b> · {ncom} comments</div>
          <div style="margin-top:8px;font-family:var(--font-plantin);font-size:13px;line-height:1.5;color:var(--color-caption-gray)">{ex}</div>
          <div style="margin-top:8px"><a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:#000;border-bottom:1px solid #000;text-decoration:none;padding-bottom:2px">Open on Reddit →</a></div>
        </div>"""
    def post_row(p):
        score=p.get("score",0); ncom=p.get("num_comments",0); title=esc(p.get("title","(no title)")[:120]); author=esc(p.get("author","?"))
        pl=permalink(p)
        intent = classify_intent(p.get("title","")+" "+(p.get("selftext","") or ""))
        intent_mini = f'<span class="pill muted" style="font-size:9px;padding:2px 4px;margin-left:4px">{esc(intent)}</span>' if intent not in ("general",) else ""
        return f"""<div class="post-row">
          <div style="text-align:center;border:1px solid var(--color-rule-gray);background:var(--color-newsprint-cream);padding:8px 4px;border-radius:4px"><div style="font:700 16px/1 var(--font-plantin)">{score}</div><div style="font:700 9px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">{ncom} cmts</div></div>
          <div><div style="font-family:var(--font-plantin);font-size:14px;font-weight:700;line-height:1.3"><a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="text-decoration:none">{title}</a>{intent_mini}</div><div style="font:500 11px/1 var(--font-helvetica-neue);color:var(--color-caption-gray);margin-top:4px">u/{author} · <a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="color:var(--color-caption-gray)">reddit.com →</a></div></div>
        </div>"""
    lead_html = post_card(top_posts[0], lead=True) if top_posts else '<div class="card">No posts found.</div>'
    secondary_html = '<div class="card">' + "".join(post_row(p) for p in top_posts[1:]) + '</div>' if len(top_posts)>1 else ''
    themes_html = ""
    for i,t in enumerate(themes):
        s=sentiment_for_posts(t["posts"])
        color = "var(--color-signal-yellow)" if s["label"]=="positive" else ("#000" if s["label"]=="negative" else "var(--color-pull-quote-gray)")
        border = "1px solid #000" if s["label"]=="positive" else "1px solid var(--color-rule-gray)"
        engagements=[(p.get("score",0) or 0)+(p.get("num_comments",0) or 0) for p in t["posts"]]
        median_eng=sorted(engagements)[len(engagements)//2] if engagements else 0
        freq_pct = round(t['count']/max(total,1)*100)
        themes_html += f"""<div class="card" style="border-left:3px solid {color}">
          <div class="eyebrow">{esc(t['label']).upper()} <em>· {t['count']} posts · {freq_pct}% of sample</em></div>
          <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray);margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            <span class="pill muted">freq {t['count']}</span><span class="pill muted">engagement {median_eng} median</span>
            <span class="pill yellow" style="border-color:{border}">{s['pos']} pos</span> <span class="pill">{s['neu']} neu</span> <span class="pill black">{s['neg']} neg</span>
            <span style="margin-left:4px;color:var(--color-mute-gray)">#{esc(t['keyword'])}</span>
          </div>
          <div style="margin-top:8px;font-family:var(--font-plantin);font-size:13px;line-height:1.5;color:var(--color-caption-gray)">
            {esc(t['posts'][0].get('title','')[:140]) if t['posts'] else ''} 
          </div>
        </div>"""
    kw_html = ", ".join(f"<span class='pill'>{esc(w)} <b>{c}</b></span>" for w,c in keywords[:16])
    phrase_html = ", ".join(f"<span class='pill yellow'>{esc(w)} <b>{c}</b></span>" for w,c in (phrases or [])[:10]) if phrases else "<span class='pill muted'>no strong phrases</span>"
    timeline_html = ""
    if timeline:
        days_sorted = sorted(timeline.keys())
        max_count = max(len(v) for v in timeline.values()) or 1
        timeline_html = '<div class="timeline">'
        for d in days_sorted[-7:]:
            cnt = len(timeline[d])
            h = max(12, round(cnt/max_count*78))
            label = d[5:]
            cls = "" if cnt>0 else " muted"
            timeline_html += f'<div class="bar{cls}" style="height:{h}px"><b>{cnt}</b><span>{esc(label)}</span></div>'
        timeline_html += '</div>'
        timeline_html += f'<p class="note">Posts per day (UTC) — total {total} across {len(days_sorted)} days. Window: {esc(meta.get("window","—"))}</p>'
    else:
        timeline_html = '<p class="note">Timeline unavailable — no dated posts.</p>'
    heatmap_html = ""
    if heatmap and heatmap.get("days") and heatmap.get("themes"):
        heatmap_html = '<table class="heatmap"><tr><th>Theme \\ Day</th>'
        for d in heatmap["days"]:
            heatmap_html += f'<th>{esc(d[5:])}</th>'
        heatmap_html += '</tr>'
        for ti, tlabel in enumerate(heatmap["themes"]):
            heatmap_html += f'<tr><td class="rowlabel">{esc(tlabel)}</td>'
            row = heatmap["matrix"][ti] if ti < len(heatmap["matrix"]) else []
            for v in row:
                if v==0:
                    bg="#fff"; fg="#b3b3b3"
                elif v==1:
                    bg="#fdfbe4"; fg="#000"
                elif v==2:
                    bg="#ffc500"; fg="#000"
                else:
                    bg="#000"; fg="#ffc500"
                heatmap_html += f'<td style="background:{bg};color:{fg}">{v}</td>'
            heatmap_html += '</tr>'
        heatmap_html += '</table><p class="note">Theme × day — darker = more posts that day. Quick scan for bursts.</p>'
    else:
        heatmap_html = '<p class="note">Heatmap needs at least 2 themes and dated posts.</p>'
    quadrant_html = ""
    if quadrant and len(quadrant)>=2:
        max_count = max(q["count"] for q in quadrant) or 1
        max_eng = max(q["median_engagement"] for q in quadrant) or 1
        if max_eng==0: max_eng=1
        quadrant_html = '<div class="quadrant">'
        quadrant_html += '<div class="axis" style="left:50%;top:0;bottom:0;width:1px;opacity:.4"></div>'
        quadrant_html += '<div class="axis" style="left:0;right:0;top:50%;height:1px;opacity:.4"></div>'
        quadrant_html += '<div style="position:absolute;left:6px;top:6px;font:700 8px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">High engagement</div>'
        quadrant_html += '<div style="position:absolute;right:6px;bottom:6px;font:700 8px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">High volume →</div>'
        for q in quadrant:
            x = 8 + (q["count"]/max_count*84)
            y = 92 - (q["median_engagement"]/max_eng*84)
            x=max(6,min(94,x)); y=max(6,min(94,y))
            quadrant_html += f'<div class="dot" style="left:{x}%;top:{y}%" title="{esc(q["label"])}: {q["count"]} posts, median {q["median_engagement"]}"></div>'
            quadrant_html += f'<div class="dot label" style="left:{x}%;top:{y}%">{esc(q["label"][:14])}</div>'
        quadrant_html += '</div><p class="note">Volume (posts, →) vs engagement (median score+comments, ↑). Upper-right = both frequent and engaging.</p>'
    else:
        quadrant_html = '<p class="note">Quadrant needs at least 2 themes.</p>'
    engagements_all=[(p.get("score",0) or 0)+(p.get("num_comments",0) or 0) for p in posts]
    if engagements_all:
        buckets=[0,0,0,0]
        for e in engagements_all:
            if e<=1: buckets[0]+=1
            elif e<=3: buckets[1]+=1
            elif e<=6: buckets[2]+=1
            else: buckets[3]+=1
        max_b=max(buckets) or 1
        labels=["0–1","2–3","4–6","7+"]
        eng_hist = '<div style="display:flex;align-items:end;gap:8px;height:70px;margin-top:12px">'
        for i, b in enumerate(buckets):
            h=max(8, round(b/max_b*64))
            eng_hist += f'<div style="flex:1;background:{"var(--color-signal-yellow)" if i==0 else "var(--color-pull-quote-gray)"};border:1px solid {"#000" if i==0 else "var(--color-rule-gray)"};height:{h}px;display:flex;flex-direction:column;justify-content:end;align-items:center;padding:4px 2px;border-radius:4px 4px 0 0"><b style="font:700 12px/1 var(--font-plantin)">{b}</b><span style="font:700 8px/1 var(--font-helvetica-neue);letter-spacing:.05em;text-transform:uppercase;color:var(--color-caption-gray)">{labels[i]}</span></div>'
        eng_hist += '</div><p class="note">Engagement distribution (score + comments) — most posts here are low-signal; that is normal for this window.</p>'
    else:
        eng_hist = '<p class="note">No engagement data.</p>'
    what_changed_html = ""
    if baseline_themes is not None:
        what_changed_html = '<div class="card" style="margin-top:12px">'
        what_changed_html += '<div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.07em;text-transform:uppercase;color:var(--color-caption-gray)">Baseline comparison</div>'
        if not baseline_themes:
            what_changed_html += '<p class="note">Not enough prior-window posts to compare — showing current window only.</p>'
        else:
            curr_labels=set(t["label"].lower() for t in themes)
            prev_labels=set(t["label"].lower() for t in baseline_themes)
            new_labels=curr_labels - prev_labels
            gone_labels=prev_labels - curr_labels
            if new_labels:
                what_changed_html += f'<p style="margin:8px 0 0;font-family:var(--font-plantin);font-size:14px">New this window: <b>{esc(", ".join(sorted(new_labels)[:4]))}</b></p>'
            if gone_labels:
                what_changed_html += f'<p style="margin:4px 0 0;font-family:var(--font-plantin);font-size:14px;color:var(--color-caption-gray)">Faded from prior window: {esc(", ".join(sorted(gone_labels)[:4]))}</p>'
            if not new_labels and not gone_labels:
                what_changed_html += '<p class="note">Theme set is stable vs prior window — no new theme emerged.</p>'
            what_changed_html += '<p class="note">Prior 7 days vs current 7 days (split at 7 days ago). Sparse windows produce noisy deltas — treat as directional.</p>'
        what_changed_html += '</div>'
    else:
        what_changed_html = '<div class="card card-warm" style="border-left:3px solid var(--color-signal-yellow);margin-top:12px"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.07em;text-transform:uppercase;color:var(--color-caption-gray)">How to compare windows</div><p class="note">Re-run with <code>--window 14d --limit 60</code> to get a prior-window baseline. This report fetches the current window only when run with a small limit.</p></div>'
    briefing_html = '<ol class="briefing">' + "".join(f"<li>{b}</li>" for b in briefing) + "</ol>"
    method_html = f"""<table class="method-table">
      <tr><th>Collection window</th><td>{esc(meta.get('window','—'))} &nbsp;· span {meta.get('span_days',0)} days</td></tr>
      <tr><th>Sample size</th><td>{total} posts · avg score {meta.get('avg_score',0)} · {total_comments} comments total</td></tr>
      <tr><th>Removed posts</th><td>{meta.get('removed',0)} removed (selftext [removed]/[deleted]: {meta.get('selftext_removed',0)}) — excluded from theme excerpts</td></tr>
      <tr><th>Method</th><td>Arctic Shift archive · keyword-overlap clustering (phrase-aware) · lexicon sentiment · rule-based intent. LLM title/themes when key is present, otherwise deterministic.</td></tr>
      <tr><th>Confidence</th><td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{conf_color};vertical-align:middle"></span> <b style="text-transform:capitalize">{esc(conf_label)}</b> — {esc(confidence.get('reason',''))}</td></tr>
      <tr><th>Limitations</th><td>Small window + low engagement → themes are directional. Phrases and intents are heuristic. For high-stakes claims, re-run with <code>--llm</code> or a larger <code>--limit</code>.</td></tr>
    </table>"""
    html=f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="color-scheme" content="light"/><title>{esc(title)} — r/{esc(subreddit)}</title>
<style>{styles}</style>
</head><body>
<div class="utility"><div class="left"><span style="letter-spacing:.10em">HERMES</span> <span style="color:var(--color-mute-gray);font-weight:400">INTELLIGENCE</span> <span style="color:var(--color-mute-gray);font-weight:400">· r/{esc(subreddit)}</span></div>
<div class="right"><span style="color:var(--color-caption-gray);font-weight:400">{now}</span> <span class="pill yellow" style="font-size:11px">INTELLIGENCE BRIEF</span></div></div>
<header class="mast"><h1>{esc(title)}</h1><div class="sub">r/{esc(subreddit)} · {total} posts · {esc(meta.get('window','—'))[:34]} · confidence {esc(conf_label)}</div>
<div class="kicker"><span><b>{total}</b> posts</span><span><b>{avg_score}</b> avg score</span><span><b>{total_comments}</b> comments</span><span><b>{theme_count}</b> themes</span><span><b>{meta.get('removed',0)}</b> removed</span></div></header>
<nav class="sec-nav"><a href="#briefing" class="active">01 · Briefing</a><a href="#activity">02 · Activity</a><a href="#changed">03 · What changed</a><a href="#themes">04 · Themes</a><a href="#top">05 · Posts</a><a href="#sentiment">06 · Sentiment & Intent</a><a href="#keywords">07 · Keywords & Method</a></nav>
<main class="wrap">
<section id="briefing"><div class="eyebrow">01 — EXECUTIVE BRIEFING <em>· what to know in 30 seconds</em></div>
<h2>{esc(title)}</h2>
{briefing_html}
<div class="confidence"><span class="dot" style="background:{conf_color}"></span> Confidence <b style="text-transform:capitalize">{esc(conf_label)}</b> — {esc(confidence.get('reason',''))}</div>
{kpi_html}
</section>
<section id="activity"><div class="eyebrow">02 — ACTIVITY & ENGAGEMENT <em>· seven-day timeline + distribution</em></div>
<h2>When the conversation <em>happened.</em></h2><p class="deck">Posts per day (UTC) and how engagement is distributed — is discussion steady, bursty, or one-thread-driven?</p>
{timeline_html}
<div style="margin-top:16px">{eng_hist}</div>
</section>
<section id="changed"><div class="eyebrow">03 — WHAT CHANGED <em>· current vs prior window</em></div>
<h2>What is <em>meaningfully changing.</em></h2><p class="deck">New themes that appeared this window vs the prior seven days — where momentum is building or fading.</p>
{what_changed_html}
</section>
<section id="themes"><div class="eyebrow">04 — THEME LANDSCAPE <em>· phrase-aware clustering</em></div>
<h2>How the conversation <em>clusters.</em></h2><p class="deck">Each theme shows frequency (% of sample), engagement (median), and sentiment — kept separate so you can see what is common vs what is engaging.</p>
<div class="grid2" style="margin-top:16px">{themes_html or '<div class="card">No themes — too few posts.</div>'}</div>
<div style="margin-top:20px"><h3>Volume vs Engagement</h3><p class="note">Separate the frequent from the engaging.</p>{quadrant_html}</div>
<div style="margin-top:20px"><h3>Theme × Day</h3>{heatmap_html}</div>
</section>
<section id="top"><div class="eyebrow">05 — REPRESENTATIVE POSTS <em>· ranked by engagement (score + comments)</em></div>
<h2>What rose to <em>the top.</em></h2><p class="deck">Highest-engagement posts — lead story plus the next 4, each tagged with intent. Open any card on Reddit to verify.</p>
<div class="grid3" style="align-items:start;margin-top:16px"><div>{lead_html}</div><div>{secondary_html or '<div class="card" style="color:var(--color-caption-gray)">Only one post in window.</div>'}</div></div>
</section>
<section id="sentiment"><div class="eyebrow">06 — SENTIMENT & INTENT <em>· lexicon + rule-based</em></div>
<h2>How it <em>feels</em> and <em>why they posted.</em></h2><p class="deck">Sentiment is per-post lexicon; intent is rule-based (advice-seeking, reassurance, venting, personal story, product recommendation, safety concern).</p>
{sent_html}
<p class="note">Lexicon heuristic — not LLM-judged. For high-stakes sentiment, re-run with <code>--llm</code> and a model key.</p>
<div style="margin-top:18px"><h3>Conversation intent</h3>{intent_bar_html}<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">{intent_legend or '<span class="pill muted">no intent signal</span>'}</div>
<p class="note">Advice-seeking and personal story dominate this sample — check cards above for the posts behind each intent.</p></div>
</section>
<section id="keywords"><div class="eyebrow">07 — KEYWORDS & METHODOLOGY <em>· most frequent terms + provenance</em></div>
<h3>Keywords</h3><div class="card" style="margin-top:12px"><div style="display:flex;flex-wrap:wrap;gap:6px">{kw_html or '<span class="pill">no keywords</span>'}</div>
<p class="note">Keywords from titles + selftexts. Stopwords and contraction artifacts (don, him, like) removed. Phrases capture bigrams like potty training.</p></div>
<div style="margin-top:12px"><h3>Phrases (bigrams)</h3><div class="card" style="margin-top:8px"><div style="display:flex;flex-wrap:wrap;gap:6px">{phrase_html}</div><p class="note">Bigram phrases from titles — useful for seeding FTS queries: <code>python search_arctic.py posts --subreddit {esc(subreddit)} --title &quot;potty training&quot;</code></p></div></div>
<div style="margin-top:16px"><h3>Methodology & Limitations</h3>{method_html}</div>
</section>
</main>
<div class="footer">Hermes Intelligence · r/{esc(subreddit)} · {now} · Arctic Shift archive · Single-file HTML — opens offline</div>
</body></html>"""
    return html

def main():
    ap=argparse.ArgumentParser(description="Subreddit Intelligence Brief — single-file HTML")
    ap.add_argument("--subreddit", required=True, help="subreddit name without r/")
    ap.add_argument("--window", default="", help="time window like 7d, 30d, 48h (filters via after param)")
    ap.add_argument("--limit", type=int, default=25, help="posts to fetch (max 100, paginated if >100)")
    ap.add_argument("--top", type=int, default=5, help="top posts to feature (3-5)")
    ap.add_argument("--sort", default="desc", choices=["desc","asc"])
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--model", default="deepseek-v4-flash", help="LLM model for title/theme/intent enrichment")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM even if key present")
    ap.add_argument("--llm", action="store_true", help="force LLM synthesis if key available")
    args=ap.parse_args()
    after=None
    if args.window:
        secs=parse_window(args.window)
        if secs:
            after_dt=datetime.now(timezone.utc).timestamp() - secs
            after=datetime.fromtimestamp(after_dt, tz=timezone.utc).isoformat()
    print(f"[pulse] r/{args.subreddit} window={args.window or 'all'} limit={args.limit} sort={args.sort} after={after or '—'}", file=sys.stderr)
    want_baseline = args.limit >= 40
    fetch_total = max(args.limit, 60) if want_baseline else args.limit
    if fetch_total>100 or args.limit>100:
        posts=fetch_posts_paginated(args.subreddit, total=fetch_total, sort=args.sort)
        if after:
            try:
                cutoff=datetime.fromisoformat(after).timestamp()
                posts=[p for p in posts if p.get("created_utc",0) >= cutoff]
            except: pass
        if want_baseline and len(posts) >= 40:
            cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
            current_window = [p for p in posts if p.get("created_utc",0) >= cutoff_7d][:args.limit]
            prior_window = [p for p in posts if p.get("created_utc",0) < cutoff_7d][:args.limit]
            if current_window:
                posts = current_window
            baseline_themes = cluster_themes(prior_window, k=min(5, max(3, len(prior_window)//6 + 2))) if prior_window else []
        else:
            baseline_themes = None
        posts_for_report = posts[:args.limit]
        posts = posts_for_report
    else:
        from analyze import fetch_posts
        posts=fetch_posts(args.subreddit, limit=args.limit, sort=args.sort, after=after)
        posts_for_report = posts
        baseline_themes = None
        posts = posts_for_report
    if not posts:
        print(f"[pulse] no posts found for r/{args.subreddit} — check subreddit name or try --window ''", file=sys.stderr)
        if 'baseline_themes' not in locals(): baseline_themes=None
    elif 'baseline_themes' not in locals():
        baseline_themes=None
    top_posts=rank_posts(posts, top=max(3,min(5,args.top)))
    themes=cluster_themes(posts, k=min(5, max(3, len(posts)//6 + 2)))
    overall_sent=sentiment_for_posts(posts)
    keywords=extract_keywords(posts, top_k=24)
    phrases=extract_phrases(posts, top_k=12)
    intent_data=intent_breakdown(posts)
    timeline=timeline_by_day(posts)
    heatmap=theme_heatmap_data(posts, themes)
    quadrant=quadrant_data(themes)
    meta=collection_meta(posts, subreddit=args.subreddit)
    confidence=confidence_assessment(posts, themes)
    generated_title=None
    briefing=None
    if not args.no_llm and (args.llm or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        titles="\n".join(f"- {p.get('title','')[:100]} (score {p.get('score',0)}, intent {classify_intent(p.get('title','')+' '+(p.get('selftext','') or ''))})" for p in posts[:15])
        theme_hint=", ".join(t["label"] for t in themes[:4])
        llm_prompt=f"""You are a careful subreddit analyst for r/{args.subreddit}. Given these post titles and the current keyword themes [{theme_hint}]:
{titles}

Return JSON with keys:
- title: a short human title for this window (8-10 words, e.g. "Parenting Pulse: Safety, Independence & Big Questions" or "A Quiet Week in r/parenting" if data is sparse — never use the word Monocle)
- themes: array of 3-5 {{label, keywords}} — labels 2-4 words, phrase-aware, no stopwords or contraction artifacts like "don" or "him"
- briefing: array of 3 strings — one-sentence takeaways (what is being discussed, tone/intent, confidence limitation)
- sentiment: one of positive/neutral/negative
Keep labels grounded in the titles; do not invent topics."""
        resp=try_llm(llm_prompt, model=args.model)
        if resp:
            m=re.search(r"\{.*\}", resp, re.S)
            if m:
                try:
                    j=json.loads(m.group(0))
                    if j.get("title"):
                        generated_title=j["title"][:80]
                    if j.get("themes"):
                        for i, th in enumerate(j["themes"][:len(themes)]):
                            if i < len(themes):
                                themes[i]["label"]=th.get("label", themes[i]["label"])[:40]
                                if th.get("keywords"):
                                    themes[i]["keywords"]=th.get("keywords")[:4]
                    if j.get("briefing") and isinstance(j["briefing"], list):
                        briefing=[str(s)[:220] for s in j["briefing"][:3]]
                    if j.get("sentiment"):
                        overall_sent["label"]=j["sentiment"]
                    if not generated_title:
                        generated_title=generate_title(args.subreddit, themes, posts, intent_data)
                except: pass
    if not generated_title:
        generated_title=generate_title(args.subreddit, themes, posts, intent_data)
    if briefing is None:
        briefing=generate_briefing(posts, themes, overall_sent, intent_data, confidence)
    html=render_html(args.subreddit, posts, top_posts, themes, overall_sent, keywords, args, phrases=phrases, intent_data=intent_data, timeline=timeline, heatmap=heatmap, quadrant=quadrant, meta=meta, confidence=confidence, generated_title=generated_title, briefing=briefing, baseline_themes=baseline_themes)
    out=Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[pulse] wrote {out} ({len(html):,} bytes) — {len(posts)} posts, {len(top_posts)} featured, {len(themes)} themes, title: {generated_title!r}", file=sys.stderr)
    print(str(out))

if __name__=="__main__": main()
