#!/usr/bin/env python3
"""
pulse.py — Subreddit Pulse newspaper (DESIGN-Monocle.md single-file HTML).

Usage:
  python pulse.py --subreddit parenting --window 7d --top 5 --limit 25 --out ./pulse-parenting.html
  python pulse.py --subreddit vietnam --limit 30 --top 3 --out ./pulse-vietnam.html --no-llm

Fetches posts+comments via Arctic Shift, ranks top posts, clusters themes,
scores sentiment, and renders a Monocle broadsheet.
"""
import argparse, json, sys, os, html as htmlmod, re, time, hashlib
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import fetch_posts_paginated, fetch_comments, rank_posts, cluster_themes, sentiment_for_posts, extract_keywords, sentiment_score, tokenize, try_llm

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

def render_html(subreddit, posts, top_posts, themes, overall_sent, keywords, args) -> str:
    now=datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    total=len(posts)
    # read Monocle tokens inline
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
.btn-sub{appearance:none;border:1px solid #000;background:var(--color-signal-yellow);color:#000;font:700 13px/1 var(--font-helvetica-neue);letter-spacing:.01em;text-transform:uppercase;padding:8px 16px;cursor:pointer}
.mast{max-width:1200px;margin:0 auto;padding:20px 16px 14px;text-align:center;border-bottom:1px solid var(--color-rule-gray)}
.mast h1{margin:0;font-family:var(--font-plantin);font-size:40px;letter-spacing:-0.02em;line-height:1;font-weight:700}
.mast h1 span{font-weight:400}
.mast .sub{margin:8px 0 0;font-family:var(--font-helvetica-neue);font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)}
.kicker{margin-top:10px;display:flex;justify-content:center;gap:14px;flex-wrap:wrap;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700;letter-spacing:.01em;text-transform:uppercase;color:var(--color-caption-gray)}
.kicker b{color:#000}
.kicker span+span::before{content:"\00b7";margin-right:14px;color:var(--color-mute-gray)}
.sec-nav{max-width:1200px;margin:0 auto;display:flex;gap:0;overflow:auto;padding:10px 16px;border-bottom:1px solid var(--color-rule-gray);font-family:var(--font-plantin);font-size:13px;letter-spacing:.075em;text-transform:uppercase;white-space:nowrap;scrollbar-width:none}
.sec-nav::-webkit-scrollbar{display:none}
.sec-nav a{text-decoration:none;color:var(--color-caption-gray);padding:4px 12px;border-right:1px solid var(--color-rule-gray)}
.sec-nav a:last-child{border-right:none}
.sec-nav a:hover,.sec-nav a.active{color:#000}
.sec-nav a.active{border-bottom:2px solid var(--color-signal-yellow)}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
section{padding:32px 0;border-bottom:1px solid var(--color-rule-gray)}
section:last-of-type{border-bottom:none}
.eyebrow{font-family:var(--font-plantin);font-size:13px;letter-spacing:.075em;text-transform:uppercase;color:#000;margin:0 0 8px;font-weight:700}
.eyebrow em{font-style:normal;color:var(--color-caption-gray);font-weight:400;letter-spacing:.05em;margin-left:6px}
h2{margin:0;font-family:var(--font-plantin);font-size:32px;line-height:1.15;letter-spacing:-0.64px;font-weight:400}
h2 b{font-weight:700}
h2 em{font-style:normal;background:linear-gradient(transparent 60%,var(--color-signal-yellow) 60% 88%,transparent 88%)}
h3{margin:0;font-family:var(--font-plantin);font-size:20px;letter-spacing:-0.4px;line-height:1.25;font-weight:700}
.deck{margin:10px 0 0;color:var(--color-caption-gray);font-family:var(--font-plantin);font-size:16px;line-height:1.5;max-width:68ch}
.card{border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);padding:16px;border-radius:var(--radius-cards)}
.card-warm{background:var(--color-margin-white)}
.card-black{background:#000;color:#fff;border-color:#000}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pill{display:inline-block;font-family:var(--font-helvetica-neue);font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:3px 6px;border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);white-space:nowrap}
.pill.yellow{background:var(--color-signal-yellow);border-color:#000;color:#000}
.pill.black{background:#000;color:var(--color-signal-yellow);border-color:#000}
.pill.gray{background:#000;color:#fff;border-color:#000}
.lede{color:var(--color-caption-gray);font-size:16px;line-height:1.5;margin:0 0 16px;max-width:68ch}
.lede b{color:#000}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
@media(max-width:700px){.kpi-grid{grid-template-columns:1fr 1fr}}
.kpi{border:1px solid var(--color-rule-gray);background:var(--color-broadsheet-white);padding:16px;border-radius:var(--radius-cards)}
.kpi.yellow{background:var(--color-signal-yellow);border-color:#000}
.kpi b{display:block;font-family:var(--font-plantin);font-size:24px;letter-spacing:-0.48px;line-height:1}
.kpi span{font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)}
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
"""
    esc=lambda s: htmlmod.escape(s or "", quote=False)
    # KPIs
    avg_score = sum(p.get("score",0) or 0 for p in posts)//max(total,1) if total else 0
    total_comments = sum(p.get("num_comments",0) or 0 for p in posts)
    theme_count = len(themes)
    kpi_html = f"""<div class="kpi-grid">
      <div class="kpi yellow"><span>r/{esc(subreddit)} · posts</span><b>{total}</b><p class="note" style="margin:2px 0 0">window · sorted {esc(args.sort)}</p></div>
      <div class="kpi"><span>Avg score</span><b>{avg_score}</b><p class="note" style="margin:2px 0 0">median signal</p></div>
      <div class="kpi"><span>Comments</span><b>{total_comments}</b><p class="note" style="margin:2px 0 0">total discussion</p></div>
      <div class="kpi"><span>Themes detected</span><b>{theme_count}</b><p class="note" style="margin:2px 0 0">top keyword clusters</p></div>
    </div>"""
    # sentiment bar
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
    # lead post + secondary
    def post_card(p, lead=False):
        score=p.get("score",0); ncom=p.get("num_comments",0); author=p.get("author","?"); title=esc(p.get("title","(no title)")[:160])
        t=datetime.fromtimestamp(p.get("created_utc",0), tz=timezone.utc).strftime("%d %b %Y") if p.get("created_utc") else ""
        ex=esc(excerpt(p, 240 if lead else 180))
        pl=permalink(p)
        hsize="24px" if lead else "18px"
        lheight="1.2" if lead else "1.3"
        return f"""<div class="card{' card-warm' if lead else ''}" style="{'border-left:3px solid var(--color-signal-yellow)' if lead else ''}">
          <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.075em;text-transform:uppercase;color:var(--color-caption-gray)">LEAD · r/{esc(p.get('subreddit',''))} <span style="font-weight:500">· {t}</span> <span class="pill yellow" style="margin-left:6px">★ TOP</span></div>
          <div style="font-family:var(--font-plantin);font-size:{hsize};line-height:{lheight};letter-spacing:-0.4px;font-weight:700;margin-top:8px"><a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="text-decoration:none">{title}</a></div>
          <div style="margin-top:6px;font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">u/{esc(author)} · <b style="color:#000">{score} ↑</b> · {ncom} comments</div>
          <div style="margin-top:8px;font-family:var(--font-plantin);font-size:14px;line-height:1.5;color:var(--color-caption-gray)">{ex}</div>
          <div style="margin-top:8px"><a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:#000;border-bottom:1px solid #000;text-decoration:none;padding-bottom:2px">Open on Reddit →</a></div>
        </div>"""
    def post_row(p):
        score=p.get("score",0); ncom=p.get("num_comments",0); title=esc(p.get("title","(no title)")[:120]); author=esc(p.get("author","?"))
        pl=permalink(p)
        return f"""<div class="post-row">
          <div style="text-align:center;border:1px solid var(--color-rule-gray);background:var(--color-newsprint-cream);padding:8px 4px;border-radius:4px"><div style="font:700 16px/1 var(--font-plantin)">{score}</div><div style="font:700 9px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">{ncom} cmts</div></div>
          <div><div style="font-family:var(--font-plantin);font-size:15px;font-weight:700;line-height:1.3"><a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="text-decoration:none">{title}</a></div><div style="font:500 11px/1 var(--font-helvetica-neue);color:var(--color-caption-gray);margin-top:4px">u/{author} · <a href="{htmlmod.escape(pl)}" target="_blank" rel="noopener" style="color:var(--color-caption-gray)">reddit.com →</a></div></div>
        </div>"""
    lead_html = post_card(top_posts[0], lead=True) if top_posts else '<div class="card">No posts found.</div>'
    secondary_html = '<div class="card">' + "".join(post_row(p) for p in top_posts[1:]) + '</div>' if len(top_posts)>1 else ''
    themes_html = ""
    for i,t in enumerate(themes):
        s=sentiment_for_posts(t["posts"])
        color = "var(--color-signal-yellow)" if s["label"]=="positive" else ("#000" if s["label"]=="negative" else "var(--color-pull-quote-gray)")
        border = "1px solid #000" if s["label"]=="positive" else "1px solid var(--color-rule-gray)"
        themes_html += f"""<div class="card" style="border-left:3px solid {color}">
          <div class="eyebrow">THEME · {esc(t['label']).upper()} <em>· {t['count']} posts · {s['label']} {s['score']:+.2f}</em></div>
          <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray);margin-top:4px">
            <span class="pill yellow" style="border-color:{border}">{s['pos']} pos</span> <span class="pill">{s['neu']} neu</span> <span class="pill black">{s['neg']} neg</span>
            <span style="margin-left:8px;color:var(--color-mute-gray)">#{esc(t['keyword'])}</span>
          </div>
          <div style="margin-top:8px;font-family:var(--font-plantin);font-size:13px;line-height:1.5;color:var(--color-caption-gray)">
            {esc(t['posts'][0].get('title','')[:120]) if t['posts'] else ''} 
          </div>
        </div>"""
    kw_html = ", ".join(f"<span class='pill'>{esc(w)} <b>{c}</b></span>" for w,c in keywords[:14])
    trend_hint = ""
    if len(themes)>=2:
        top_kw = themes[0]["keyword"]
        trend_hint = f"Most discussed: <b>{esc(themes[0]['label'])}</b> ({themes[0]['count']} posts) · conversation centers on <b>#{esc(top_kw)}</b>."
    else:
        trend_hint = f"Sample of {total} posts — themes emerge from keyword overlap in titles."
    html=f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="color-scheme" content="light"/><title>MONOCLE · r/{esc(subreddit)} Intelligence — Pulse</title>
<style>{styles}</style>
</head><body>
<div class="utility"><div class="left"><span style="letter-spacing:.14em">MONOCLE</span> <span style="color:var(--color-mute-gray);font-weight:400">INTELLIGENCE</span> <span style="color:var(--color-mute-gray);font-weight:400">· r/{esc(subreddit)}</span></div>
<div class="right"><span style="color:var(--color-caption-gray);font-weight:400">{now}</span> <span class="pill yellow" style="font-size:11px">PULSE</span></div></div>
<header class="mast"><h1>MONOCLE <span>· r/{esc(subreddit)} INTELLIGENCE</span></h1><div class="sub">Themes · sentiment · trends — what r/{esc(subreddit)} is actually talking about</div>
<div class="kicker"><span><b>{total}</b> posts</span><span><b>{avg_score}</b> avg score</span><span><b>{total_comments}</b> comments</span><span><b>{theme_count}</b> themes</span></div></header>
<nav class="sec-nav"><a href="#top" class="active">01 · Top posts</a><a href="#themes">02 · Themes</a><a href="#sentiment">03 · Sentiment</a><a href="#trends">04 · Trends</a><a href="#keywords">05 · Keywords</a></nav>
<main class="wrap">
<section id="top"><div class="eyebrow">01 — TOP POSTS <em>· ranked by engagement (score + comments)</em></div>
<h2>What rose to <em>the top.</em></h2><p class="deck">Highest-engagement posts in the current window — lead story plus the next {max(0,len(top_posts)-1)}.</p>
<div class="grid3" style="align-items:start;margin-top:16px"><div>{lead_html}</div><div>{secondary_html or '<div class="card" style="color:var(--color-caption-gray)">Only one post in window.</div>'}</div></div>
</section>
<section id="themes"><div class="eyebrow">02 — THEMES <em>· keyword-overlap clustering</em></div>
<h2>How the conversation <em>clusters.</em></h2><p class="deck">{trend_hint}</p>
<div class="grid2" style="margin-top:16px">{themes_html or '<div class="card">No themes — too few posts.</div>'}</div>
</section>
<section id="sentiment"><div class="eyebrow">03 — SENTIMENT <em>· lexicon-scored per theme</em></div>
<h2>How it <em>feels.</em></h2><p class="deck">Per-post lexicon sentiment (positive/neutral/negative) — aggregate below, per-theme in the cards above. LLM sentiment replaces this when a key is available.</p>
{sent_html}
<p class="note">Lexicon heuristic — not LLM-judged. For high-stakes sentiment, re-run with <code>--llm</code> and an OPENAI_API_KEY.</p>
</section>
<section id="trends"><div class="eyebrow">04 — TRENDS <em>· rising keywords + velocity</em></div>
<h2>Where it's <em>moving.</em></h2>
<div class="card card-warm" style="border-left:3px solid var(--color-signal-yellow);margin-top:12px">
  <div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.07em;text-transform:uppercase;color:var(--color-caption-gray)">Signal</div>
  <div style="font-family:var(--font-plantin);font-size:20px;font-weight:700;letter-spacing:-0.4px;margin-top:6px">Top trend: <em style="font-style:normal;background:linear-gradient(transparent 60%,var(--color-signal-yellow) 60% 88%,transparent 88%)">{esc(themes[0]['label']) if themes else '—'}</em></div>
  <div class="lede" style="margin-top:6px">{trend_hint} Re-run with <code>--window 30d</code> vs <code>7d</code> to compare momentum.</div>
  <div class="hair"></div>
  <div style="font:700 10px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Method — keyword frequency in titles + median score velocity. Swap in LLM trend pass with --llm.</div>
</div>
</section>
<section id="keywords"><div class="eyebrow">05 — KEYWORDS <em>· most frequent non-stopword terms</em></div>
<div class="card" style="margin-top:12px"><div style="display:flex;flex-wrap:wrap;gap:6px">{kw_html or '<span class="pill">no keywords</span>'}</div>
<p class="note">Keywords from titles + selftexts. Stopwords removed. Use to seed FTS queries: <code>python search_arctic.py posts --subreddit {esc(subreddit)} --title {esc(keywords[0][0]) if keywords else '...'}</code></p></div>
</section>
</main>
<div class="footer">MONOCLE · Reddit Intelligence · r/{esc(subreddit)} · {now} · Arctic Shift archive · Monocle tokens #fdfcf3 / #ffc500 / Plantin · Single-file HTML — opens offline</div>
</body></html>"""
    return html

def main():
    ap=argparse.ArgumentParser(description="Subreddit Pulse — Monocle newspaper")
    ap.add_argument("--subreddit", required=True, help="subreddit name without r/")
    ap.add_argument("--window", default="", help="time window like 7d, 30d, 48h (filters via after param)")
    ap.add_argument("--limit", type=int, default=25, help="posts to fetch (max 100, paginated if >100)")
    ap.add_argument("--top", type=int, default=5, help="top posts to feature (3-5)")
    ap.add_argument("--sort", default="desc", choices=["desc","asc"])
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--model", default="deepseek-v4-flash", help="LLM model for theme/sentiment enrichment")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM even if key present")
    ap.add_argument("--llm", action="store_true", help="force LLM synthesis if key available")
    args=ap.parse_args()
    # fetch
    after=None
    if args.window:
        secs=parse_window(args.window)
        if secs:
            after_dt=datetime.now(timezone.utc).timestamp() - secs
            after=datetime.fromtimestamp(after_dt, tz=timezone.utc).isoformat()
    print(f"[pulse] r/{args.subreddit} window={args.window or 'all'} limit={args.limit} sort={args.sort} after={after or '—'}", file=sys.stderr)
    # paginated fetch if limit>100
    if args.limit>100:
        posts=fetch_posts_paginated(args.subreddit, total=args.limit, sort=args.sort)
        # if window filter, filter manually
        if after:
            cutoff=datetime.fromisoformat(after).timestamp()
            posts=[p for p in posts if p.get("created_utc",0) >= cutoff]
    else:
        params_extra={}
        if after: params_extra["after"]=after
        # use fetch_posts for single page
        from analyze import fetch_posts
        posts=fetch_posts(args.subreddit, limit=args.limit, sort=args.sort, after=after)
    if not posts:
        print(f"[pulse] no posts found for r/{args.subreddit} — check subreddit name or try --window ''", file=sys.stderr)
    top_posts=rank_posts(posts, top=max(3,min(5,args.top)))
    themes=cluster_themes(posts, k=min(5, max(3, len(posts)//6 + 2)))
    overall_sent=sentiment_for_posts(posts)
    keywords=extract_keywords(posts, top_k=24)
    # optional LLM enrichment
    if not args.no_llm and (args.llm or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        # ask LLM to label themes better + sentiment nuance
        titles="\n".join(f"- {p.get('title','')[:100]} (score {p.get('score',0)})" for p in posts[:15])
        llm_prompt=f"You are a subreddit analyst for r/{args.subreddit}. Given these post titles:\n{titles}\n\nReturn JSON with keys: themes (array of 3-5 {{label, keywords}}), sentiment (positive/neutral/negative), one_sentence_trend. Keep labels 2-4 words."
        resp=try_llm(llm_prompt, model=args.model)
        if resp:
            # try to parse json out of response
            m=re.search(r"\{.*\}", resp, re.S)
            if m:
                try:
                    j=json.loads(m.group(0))
                    if j.get("themes"):
                        # rebuild themes from LLM labels, keep counts from keyword clusters proportionally
                        for i, th in enumerate(j["themes"][:len(themes)]):
                            if i < len(themes):
                                themes[i]["label"]=th.get("label", themes[i]["label"])[:40]
                    if j.get("sentiment"):
                        overall_sent["label"]=j["sentiment"]
                except: pass
    html=render_html(args.subreddit, posts, top_posts, themes, overall_sent, keywords, args)
    out=Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[pulse] wrote {out} ({len(html):,} bytes) — {len(posts)} posts, {len(top_posts)} featured, {len(themes)} themes", file=sys.stderr)
    print(str(out))

if __name__=="__main__": main()
