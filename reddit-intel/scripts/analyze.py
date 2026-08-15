#!/usr/bin/env python3
"""
analyze.py — Shared intelligence helpers for reddit-intel.
Importable by pulse.py / persona.py / build_dataset.py; also runnable as CLI for debugging.

No required dependencies beyond stdlib. LLM features are optional (OPENAI_API_KEY).
"""
import json, re, urllib.request, urllib.parse, urllib.error
from collections import Counter, defaultdict
from pathlib import Path
import sys

API = "https://arctic-shift.photon-reddit.com"

STOPWORDS = set("""
a an the and or but if then else when where while for with without within into onto
is are was were be been being have has had do does did will would could should may
might must can this that these those it its they them their what which who whom how
why about over under up down out in on at to of as by from per via just very more
most some any all each every own same so than too also only not no yes my your his
her our its i me you he she we us im ive id dont cant wont isnt arent wasnt
were hasnt havent hadnt shouldnt wouldnt couldnt mustnt needn wasnt doesnt didnt
youre youre hes shes theyre were youre weve theyve youve youre doesnt wont cant shall
am pm via etc removed deleted help need want get like one got would really still even
know think make going come take back much dont im know going think want need look let
""".split()) | set(["don", "him", "like", "old", "year", "get", "want", "time", "work", "feel", "know", "think", "make", "going", "back", "much", "really", "still", "even", "removed"])

SENT_POS = set("love great amazing awesome excellent fantastic wonderful best good nice cool fun happy glad win winning love loved recommend thanks thank helpful useful brilliant perfect love love".split())
SENT_NEG = set("hate bad terrible awful worst horrible sucks hate hated useless worst trash garbage scam fake toxic hate angry frustrated annoyed disappointed worst".split())

def api_get(path: str, params: dict, timeout=30) -> dict:
    qs = urllib.parse.urlencode({k:v for k,v in params.items() if v not in (None,"")})
    url = f"{API}{path}?{qs}" if qs else f"{API}{path}"
    req = urllib.request.Request(url, headers={"User-Agent":"reddit-intel/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def fetch_posts(subreddit: str, limit=100, sort="desc", after=None, before=None) -> list:
    params={"subreddit":subreddit,"limit":min(limit,100),"sort":sort,"meta-app":"reddit-intel"}
    if after: params["after"]=after
    if before: params["before"]=before
    data=api_get("/api/posts/search", params)
    if data.get("error"): raise RuntimeError(data["error"])
    return data.get("data",[])

def fetch_comments(subreddit=None, author=None, limit=100, sort="desc", after=None, before=None, body=None) -> list:
    params={"limit":min(limit,100),"sort":sort,"meta-app":"reddit-intel"}
    if subreddit: params["subreddit"]=subreddit
    if author: params["author"]=author
    if after: params["after"]=after
    if before: params["before"]=before
    if body: params["body"]=body
    data=api_get("/api/comments/search", params)
    if data.get("error"): raise RuntimeError(data["error"])
    return data.get("data",[])

def fetch_comments_paginated(author=None, subreddit=None, total=100) -> list:
    out=[]; after=None
    while len(out) < total:
        need=min(100, total-len(out))
        batch=fetch_comments(subreddit=subreddit, author=author, limit=need, sort="desc", after=after)
        if not batch: break
        out.extend(batch)
        if len(batch) < need: break
        last=batch[-1].get("created_utc")
        if last: after=str(int(last*1000))
        else: break
    return out[:total]

def fetch_posts_paginated(subreddit, total=25, sort="desc") -> list:
    out=[]; after=None
    while len(out) < total:
        need=min(100, total-len(out))
        batch=fetch_posts(subreddit=subreddit, limit=need, sort=sort, after=after)
        if not batch: break
        out.extend(batch)
        if len(batch) < need: break
        last=batch[-1].get("created_utc")
        if last: after=str(int(last*1000))
        else: break
    return out[:total]

def discover_authors(subreddit, target=100) -> list:
    """Discover unique authors from recent comments in subreddit."""
    seen=set(); authors=[]
    after=None
    while len(authors) < target:
        batch=fetch_comments(subreddit=subreddit, limit=100, sort="desc", after=after)
        if not batch: break
        for c in batch:
            a=c.get("author","")
            if not a or a in ("[deleted]","[removed]") or a.lower().startswith("automod"): continue
            if a not in seen:
                seen.add(a); authors.append(a)
                if len(authors) >= target: break
        last=batch[-1].get("created_utc")
        if last: after=str(int(last*1000))
        else: break
        if len(batch)<5: break
    return authors

# Tokens that are artifacts of contraction-splitting ("don't" -> "don", "didn't" -> "didn", etc.) — always drop
ARTIFACT_TOKENS = set(["don","didn","doesn","isn","aren","wasn","weren","hasn","haven","hadn","wouldn","couldn","shouldn","won","can","im","ive","id","ill","hes","shes","theyre","youre","weve","theyve","youve","him","like","old","year","get","want","time","work","feel","removed","deleted"])

def _clean_text(text: str) -> str:
    # Normalize contractions before tokenizing so "don't" -> "dont" not "don"
    s = (text or "").lower()
    # Expand common contractions to avoid artifact tokens
    s = s.replace("’","'").replace("`","'")
    s = re.sub(r"n't\b", " not", s)
    s = re.sub(r"'re\b", " are", s)
    s = re.sub(r"'ve\b", " have", s)
    s = re.sub(r"'ll\b", " will", s)
    s = re.sub(r"'d\b", " would", s)
    s = re.sub(r"'m\b", " am", s)
    s = re.sub(r"'s\b", " is", s)
    return s

def tokenize(text: str):
    cleaned = _clean_text(text)
    toks = re.findall(r"[a-z]{3,}", cleaned)
    # drop artifacts + stopwords
    return [w for w in toks if w not in ARTIFACT_TOKENS and w not in STOPWORDS and len(w) >= 3]

def extract_keywords(posts, top_k=30):
    cnt=Counter()
    for p in posts:
        title=p.get("title","") or ""
        body=p.get("selftext","") or ""
        for tok in tokenize(title+" "+body):
            if tok not in STOPWORDS and len(tok)>=3:
                cnt[tok]+=1
    return cnt.most_common(top_k)

def extract_phrases(posts, top_k=12):
    """Bigram phrase extraction — phrase-aware grouping (e.g. potty training, baby gate)."""
    cnt=Counter()
    for p in posts:
        title=p.get("title","") or ""
        toks=tokenize(title)
        for a,b in zip(toks, toks[1:]):
            phrase=f"{a} {b}"
            # filter low-signal bigrams where both words are too generic
            if a in STOPWORDS or b in STOPWORDS: 
                continue
            if a in ARTIFACT_TOKENS or b in ARTIFACT_TOKENS:
                continue
            cnt[phrase]+=1
    # also check selftext for extra signal but title-weighted 2x
    for p in posts:
        body=p.get("selftext","") or ""
        toks=tokenize(body[:400])
        for a,b in zip(toks, toks[1:]):
            if a in STOPWORDS or b in STOPWORDS: continue
            if a in ARTIFACT_TOKENS or b in ARTIFACT_TOKENS: continue
            cnt[phrase]+=0.3 if (phrase:=f"{a} {b}") else 0
    return cnt.most_common(top_k)

# Conversation intent — rule-based (advice-seeking, reassurance, venting, personal story, product recommendation, safety concern)
INTENT_PATTERNS = {
    "advice-seeking": [r"\bhow (do|to|should|can) ", r"\bwhat (should|do|would) ", r"\badvice\b", r"\bhelp\b.*\?", r"\?", r"\btips\b", r"\bany (advice|tips|suggestions)\b"],
    "reassurance": [r"\bis (this|it) normal", r"\bam i (overreacting|wrong|bad)", r"\bnormal\b", r"\bworried\b", r"\banxiety\b", r"\breassurance\b"],
    "venting": [r"\bso (tired|frustrated|done|over it)\b", r"\bvent\b", r"\bexhausted\b", r"\brant\b", r"\bcan't (take|do) (this|it) anymore\b"],
    "personal story": [r"\bmy (daughter|son|kid|baby|toddler|child)", r"\bwe (did|went|tried)\b", r"\byear old\b", r"\bmy (wife|husband|partner)\b"],
    "product recommendation": [r"\brecommend\b", r"\bbest (.*)(for|to buy)", r"\bwhich .*should i (buy|get)\b", r"\bcar seat\b", r"\bstroller\b", r"\bbaby gate\b"],
    "safety concern": [r"\bsafe\b", r"\bsafety\b", r"\bworried about\b", r"\bchoking\b", r"\ballerg", r"\bunlock\b.*\bgate\b", r"\bphone number\b"],
}

def classify_intent(text: str) -> str:
    s=_clean_text(text or "")
    if not s.strip():
        return "general"
    scores={}
    for label, pats in INTENT_PATTERNS.items():
        scores[label]=sum(1 for pat in pats if re.search(pat, s))
    # advice-seeking is common, require explicit signal; tie-break by order
    best=max(scores, key=lambda k: scores[k])
    if scores[best]==0:
        # fallback: question mark -> advice-seeking, else personal story heuristic
        if "?" in (text or ""): return "advice-seeking"
        if any(w in s for w in ["my daughter","my son","my kid","my baby"]): return "personal story"
        return "general"
    return best

def intent_breakdown(posts):
    cnt=Counter()
    for p in posts:
        title=p.get("title","") or ""
        body=p.get("selftext","") or ""
        cnt[classify_intent(title+" "+body)]+=1
    total=len(posts) or 1
    return {"counts": dict(cnt), "total": len(posts), "pct": {k: round(v/total*100) for k,v in cnt.items()}}

def timeline_by_day(posts):
    """Group posts by day (UTC) for 7-day timeline."""
    from datetime import datetime, timezone
    buckets=defaultdict(list)
    for p in posts:
        ts=p.get("created_utc",0) or 0
        if not ts: continue
        day=datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        buckets[day].append(p)
    # fill 7 days
    if buckets:
        days=sorted(buckets.keys())
        return {d: buckets[d] for d in days[-7:]}
    return {}

def theme_heatmap_data(posts, themes):
    """Theme x day matrix — count of posts per theme per day."""
    from datetime import datetime, timezone
    days=sorted(timeline_by_day(posts).keys())
    if not days or not themes:
        return {"days": [], "themes": [], "matrix": []}
    matrix=[]
    for t in themes:
        kw=t.get("keyword","")
        row=[]
        for d in days:
            cnt=sum(1 for p in timeline_by_day(posts)[d] if kw in set(tokenize(p.get("title","")+" "+(p.get("selftext","") or ""))))
            row.append(cnt)
        matrix.append(row)
    return {"days": days, "themes": [t.get("label","") for t in themes], "keywords": [t.get("keyword","") for t in themes], "matrix": matrix}

def quadrant_data(themes):
    """Volume vs engagement — each theme's post count vs median engagement."""
    out=[]
    for t in themes:
        posts=t.get("posts",[])
        count=t.get("count", len(posts))
        engagements=[(p.get("score",0) or 0)+(p.get("num_comments",0) or 0) for p in posts]
        median=sorted(engagements)[len(engagements)//2] if engagements else 0
        mean=sum(engagements)/len(engagements) if engagements else 0
        out.append({"label": t.get("label",""), "keyword": t.get("keyword",""), "count": count, "median_engagement": median, "mean_engagement": round(mean,1)})
    return out

def collection_meta(posts, subreddit=""):
    """Collection window, sample size, removed posts — for methodology box."""
    from datetime import datetime, timezone
    total=len(posts)
    removed=sum(1 for p in posts if (p.get("selftext","") or "").strip().lower() in ("[removed]","[deleted]") or p.get("title","").strip().lower() in ("[removed]","[deleted]"))
    selftext_removed=sum(1 for p in posts if (p.get("selftext","") or "").strip().lower() in ("[removed]","[deleted]"))
    if posts and any(p.get("created_utc") for p in posts):
        ts=[p.get("created_utc",0) for p in posts if p.get("created_utc")]
        lo=min(ts); hi=max(ts)
        window=f"{datetime.fromtimestamp(lo, tz=timezone.utc).strftime('%d %b %Y %H:%M')} → {datetime.fromtimestamp(hi, tz=timezone.utc).strftime('%d %b %Y %H:%M')} UTC"
        span_days=round((hi-lo)/86400,1) if hi>lo else 0
    else:
        window="—"; span_days=0
    avg_score=sum(p.get("score",0) or 0 for p in posts)/max(total,1) if total else 0
    return {"total": total, "removed": removed, "selftext_removed": selftext_removed, "window": window, "span_days": span_days, "avg_score": round(avg_score,2), "subreddit": subreddit}

def confidence_assessment(posts, themes):
    """Honest confidence — based on sample size + signal strength."""
    n=len(posts)
    if n==0: return {"level": "no data", "reason": "No posts in window.", "color": "#b3b3b3"}
    # Weak signals: very low engagement, many removed, few themes
    removed_ratio=sum(1 for p in posts if (p.get("selftext","") or "").strip().lower()=="[removed]")/max(n,1)
    avg_eng=sum((p.get("score",0) or 0)+(p.get("num_comments",0) or 0) for p in posts)/max(n,1)
    if n<8 or removed_ratio>0.4 or avg_eng<1.5:
        return {"level": "low", "reason": f"Small sample (n={n}) or low engagement (avg {avg_eng:.1f}) — treat themes as directional, not definitive.", "color": "#d97706"}
    if n<15 or avg_eng<3:
        return {"level": "moderate", "reason": f"n={n}, avg engagement {avg_eng:.1f} — useful for direction, not precision.", "color": "#6e6e6e"}
    return {"level": "moderate-high", "reason": f"n={n}, avg engagement {avg_eng:.1f} — themes are stable for this window.", "color": "#111"}

def cluster_themes(posts, k=4):
    """Very light keyword-overlap clustering. Returns list of {label, count, post_ids, keywords}."""
    if not posts:
        return []
    # score keywords then assign each post to dominant keyword cluster
    kw_counts=dict(extract_keywords(posts, top_k=40))
    phrase_counts=dict(extract_phrases(posts, top_k=20))
    # seed clusters by top keywords that are distinct — prefer phrases where they dominate
    seeds=[]
    # inject top phrase unigrams as seeds if phrase is strong
    phrase_unigrams=[]
    for phrase, cnt in phrase_counts.items():
        if cnt>=2:
            for w in phrase.split():
                if w not in phrase_unigrams and w not in seeds:
                    phrase_unigrams.append(w)
    # merge phrase unigrams early so "potty training" -> seeds include potty,training
    ranked_keywords=extract_keywords(posts, top_k=30)
    # interleave phrase unigrams with keyword ranking
    merged=[]
    seen=set()
    for w,_ in ranked_keywords:
        if w not in seen:
            merged.append(w); seen.add(w)
        # after each 2 keywords, inject a phrase unigram if useful
        if len(merged)%3==0 and phrase_unigrams:
            cand=phrase_unigrams.pop(0)
            if cand not in seen and cand not in STOPWORDS and cand not in ARTIFACT_TOKENS:
                merged.append(cand); seen.add(cand)
    for w in merged[:24]:
        if all(w not in s and s not in w for s in seeds):
            seeds.append(w)
        if len(seeds)>=k: break
    if not seeds: seeds=["general"]
    clusters=defaultdict(list)
    for p in posts:
        toks=set(tokenize(p.get("title","")+" "+(p.get("selftext","") or "")))
        best=seeds[0]; best_score=-1
        for s in seeds:
            # score by presence of seed + related keywords
            score = (1 if s in toks else 0) + sum(0.3 for t in toks if t in kw_counts)
            if score>best_score:
                best_score=score; best=s
        clusters[best].append(p)
    # order by size desc
    out=[]
    for label, plist in sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True):
        # label prettify
        pretty=" ".join(w.capitalize() for w in label.split("_")) if label!="general" else "General Discussion"
        out.append({"label": pretty, "keyword": label, "count": len(plist), "posts": plist[:5], "keywords": [label]})
    return out[:k]

def sentiment_score(text: str) -> float:
    toks=tokenize(text)
    if not toks: return 0.0
    pos=sum(1 for t in toks if t in SENT_POS)
    neg=sum(1 for t in toks if t in SENT_NEG)
    # normalize to -1..1
    raw=(pos-neg)/max(len(toks),10)
    return max(-1,min(1, raw*8))

def sentiment_for_posts(posts):
    if not posts: return {"label":"neutral","score":0,"pos":0,"neg":0,"neu":0}
    scores=[sentiment_score(p.get("title","")+" "+(p.get("selftext","") or "")) for p in posts]
    avg=sum(scores)/len(scores) if scores else 0
    pos=sum(1 for s in scores if s>0.1)
    neg=sum(1 for s in scores if s<-0.1)
    neu=len(scores)-pos-neg
    if avg>0.08: label="positive"
    elif avg<-0.08: label="negative"
    else: label="neutral"
    return {"label":label,"score":round(avg,2),"pos":pos,"neg":neg,"neu":neu,"count":len(posts)}

def rank_posts(posts, top=5):
    def comp(p):
        s=p.get("score",0) or 0
        c=p.get("num_comments",0) or 0
        return s*0.6 + c*0.9 + (s+c)*0.1
    ranked=sorted(posts, key=comp, reverse=True)
    return ranked[:top]

def _ensure_skill_path():
    """Ensure both skill roots (global + profile) are on sys.path so cross-root imports work (Issue 9)."""
    import sys
    from pathlib import Path as _P
    for root in [_P.home() / ".hermes/skills/research/reddit-intel/scripts", _P.home() / ".hermes/profiles/hermozi/skills/research/reddit-intel/scripts"]:
        s=str(root)
        if root.exists() and s not in sys.path:
            sys.path.insert(0, s)

_ensure_skill_path()

def _load_env_file():
    """Load keys from any hermes .env (global + profile) if not already in environ (Issues 1,9)."""
    import os
    from pathlib import Path as _P
    for env_path in [_P.home() / ".hermes/profiles/hermozi/.env", _P.home() / ".hermes/.env", _P.home() / ".config/hermes/.env"]:
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line=line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k,v=line.split("=",1)
                k=k.strip(); v=v.strip().strip('"').strip("'")
                if k not in os.environ or not os.environ[k]:
                    os.environ[k]=v
        except Exception:
            pass

def _llm_provider_and_key(requested_model: str):
    """Resolve provider from model name and env. DeepSeek direct wins for deepseek-* models."""
    _load_env_file()
    import os
    m=(requested_model or "").lower()
    if m.startswith("deepseek"):
        if os.environ.get("DEEPSEEK_API_KEY"):
            return ("deepseek", os.environ["DEEPSEEK_API_KEY"], "https://api.deepseek.com/v1/chat/completions")
        if os.environ.get("OPENROUTER_API_KEY"):
            return ("openrouter-deepseek", os.environ["OPENROUTER_API_KEY"], "https://openrouter.ai/api/v1/chat/completions")
    if os.environ.get("OPENROUTER_API_KEY"):
        # OpenRouter can route any model
        return ("openrouter", os.environ["OPENROUTER_API_KEY"], "https://openrouter.ai/api/v1/chat/completions")
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"):
        k=os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
        return ("openai", k, "https://api.openai.com/v1/chat/completions")
    if os.environ.get("DEEPSEEK_API_KEY"):
        return ("deepseek", os.environ["DEEPSEEK_API_KEY"], "https://api.deepseek.com/v1/chat/completions")
    return (None, None, None)

def try_llm(prompt: str, model="deepseek-v4-flash", max_tokens=None, system_prompt: str = None) -> str:
    """Optional LLM synthesis — supports DeepSeek direct, OpenRouter, and OpenAI. Prompt-cache friendly.
    Pass system_prompt separately so DeepSeek/OpenAI can cache it as a stable prefix (context caching).
    Returns None if no key is configured.
    """
    import os
    # Centralized reasoning budget (Issue 4/7): deepseek reasoning models need 12000, others 3000
    if max_tokens is None:
        max_tokens = 12000 if (model or "").lower().startswith("deepseek") else 3000
    provider, key, url = _llm_provider_and_key(model)
    if not key:
        return None
    try:
        import urllib.request, json as js
        # Prompt-cache optimization: stable system prefix (V3.3 template) as system role, variable corpus as user.
        # DeepSeek caches automatically on repeated prefixes — first call misses, rest hit cached_tokens.
        if system_prompt:
            messages=[{"role":"system","content": system_prompt}, {"role":"user","content": prompt}]
        else:
            messages=[{"role":"user","content": prompt}]
        payload_dict={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3}
        payload=js.dumps(payload_dict).encode()
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider in ("openrouter", "openrouter-deepseek"):
            headers["HTTP-Referer"]="https://github.com/hermes-agent/reddit-intel"
            headers["X-Title"]="reddit-intel"
        req=urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as r:
            data=js.loads(r.read().decode())
            # surface cache stats when available (DeepSeek: prompt_cache_hit_tokens)
            usage=data.get("usage", {})
            if usage.get("prompt_cache_hit_tokens"):
                print(f"[llm] {provider}/{model} cache hit {usage['prompt_cache_hit_tokens']}/{usage.get('prompt_tokens', '?')} prompt tokens", file=sys.stderr)
            elif usage.get("prompt_tokens_details", {}).get("cached_tokens"):
                print(f"[llm] {provider}/{model} cached_tokens {usage['prompt_tokens_details']['cached_tokens']}", file=sys.stderr)
            msg=data["choices"][0]["message"]
            content=msg.get("content") or ""
            # DeepSeek reasoning models may put chain-of-thought in reasoning_content and leave content empty if truncated
            if not content.strip() and msg.get("reasoning_content"):
                # reasoning_content may contain the JSON if model was cut off while reasoning
                content=msg.get("reasoning_content","")
                if "{" in content:
                    # extract JSON from reasoning
                    import re as _re
                    m=_re.search(r"\{.*\}", content, _re.S)
                    if m:
                        content=m.group(0)
            return content
    except Exception as e:
        print(f"[llm] {provider}/{model} unavailable: {e}", file=sys.stderr)
        return None

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser(description="reddit-intel analyze helpers")
    ap.add_argument("--subreddit", default="parenting")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--themes", action="store_true", help="show themes+sentiment")
    args=ap.parse_args()
    posts=fetch_posts_paginated(args.subreddit, total=args.limit)
    print(f"{len(posts)} posts from r/{args.subreddit}")
    for p in rank_posts(posts, top=5):
        print(f"  {p.get('score',0):5} | {p.get('num_comments',0):4} c | {p.get('title','')[:90]}")
    if args.themes:
        print("\nThemes:")
        for t in cluster_themes(posts, k=4):
            s=sentiment_for_posts(t["posts"])
            print(f"  {t['label']} ({t['count']}) sentiment={s['label']} {s['score']}")
        print("\nKeywords:", extract_keywords(posts, top_k=12))
