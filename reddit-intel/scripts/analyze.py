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
""".split())

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

def tokenize(text: str):
    return re.findall(r"[a-z]{3,}", (text or "").lower())

def extract_keywords(posts, top_k=30):
    cnt=Counter()
    for p in posts:
        title=p.get("title","") or ""
        body=p.get("selftext","") or ""
        for tok in tokenize(title+" "+body):
            if tok not in STOPWORDS and len(tok)>=3:
                cnt[tok]+=1
    return cnt.most_common(top_k)

def cluster_themes(posts, k=4):
    """Very light keyword-overlap clustering. Returns list of {label, count, post_ids, keywords}."""
    if not posts:
        return []
    # score keywords then assign each post to dominant keyword cluster
    kw_counts=dict(extract_keywords(posts, top_k=40))
    # seed clusters by top keywords that are distinct
    seeds=[]
    for w,c in extract_keywords(posts, top_k=20):
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
