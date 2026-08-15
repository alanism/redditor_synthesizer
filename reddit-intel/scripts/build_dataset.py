#!/usr/bin/env python3
"""
build_dataset.py — Bulk synthetic population from a subreddit.

Discovers N unique authors from r/<sub>, then for each fetches comments, runs
persona.py synthesis, and writes dossiers + index.

Usage:
  python build_dataset.py --subreddit parenting --users 20 --comments-per-user 100 --out ./data/parenting/
  python build_dataset.py --subreddit vietnam --users 100 --comments-per-user 100 --out ./data/vietnam/ --concurrency 4 --model gpt-4o-mini

Outputs:
  <out>/
    index.html        # Monocle directory (gallery of users + aggregate stats)
    manifest.json     # progress checkpoint (resume-safe)
    personas.jsonl    # one JSON rubric per line
    dossiers/
      u_<author>.html
      u_<author>.json
    raw/              # if --keep-raw
      u_<author>.json

Resume: re-running with same --out resumes from manifest.json (skips completed authors).
"""
import argparse, json, sys, os, time, html as htmlmod, re
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analyze import discover_authors, fetch_comments_paginated, tokenize, _load_env_file

def render_index(subreddit, authors, manifest, persona_rows, out_dir: Path) -> str:
    esc=lambda s: htmlmod.escape(s or "", quote=False)
    now=datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    total=len(authors); completed=manifest.get("completed",0); failed=len(manifest.get("failed",[]))
    # aggregate engine distribution if available
    dist={"C":[],"F":[],"A1":[],"A2":[],"P":[]}
    for r in persona_rows:
        eng=r.get("engine") or {}
        for k in dist:
            if k in eng: 
                try: dist[k].append(int(eng[k]))
                except: pass
    def avg(arr): return round(sum(arr)/len(arr),1) if arr else 0
    styles=r"""
:root{--color-signal-yellow:#ffc500;--color-folio-black:#000;--color-newsprint-cream:#fdfcf3;--color-broadsheet-white:#fff;--color-margin-white:#fdfbe4;--color-rule-gray:#d9d9d9;--color-caption-gray:#6e6e6e;--color-mute-gray:#b3b3b3;--font-plantin:'Plantin',Georgia,serif;--font-helvetica-neue:'Helvetica Neue',Inter,system-ui,sans-serif;--radius-cards:8px}
*{box-sizing:border-box}body{margin:0;background:var(--color-newsprint-cream);color:#000;font-family:var(--font-plantin);-webkit-font-smoothing:antialiased}
.utility{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid var(--color-rule-gray);display:flex;align-items:center;justify-content:space-between;padding:0 16px;height:40px;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700}
.btn{appearance:none;border:1px solid #000;background:var(--color-signal-yellow);color:#000;font:700 13px/1 var(--font-helvetica-neue);padding:8px 16px;cursor:pointer}
.mast{max-width:1200px;margin:0 auto;padding:20px 16px 14px;text-align:center;border-bottom:1px solid var(--color-rule-gray)}
.mast h1{margin:0;font-size:40px;letter-spacing:-0.02em;line-height:1;font-weight:700}
.mast .sub{margin:8px 0 0;font-family:var(--font-helvetica-neue);font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)}
.kicker{margin-top:10px;display:flex;justify-content:center;gap:14px;flex-wrap:wrap;font-family:var(--font-helvetica-neue);font-size:13px;font-weight:700;letter-spacing:.01em;text-transform:uppercase;color:var(--color-caption-gray)}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
section{padding:24px 0;border-bottom:1px solid var(--color-rule-gray)}
.eyebrow{font-size:13px;letter-spacing:.075em;text-transform:uppercase;font-weight:700;margin:0 0 8px}
.card{border:1px solid var(--color-rule-gray);background:#fff;padding:16px;border-radius:var(--radius-cards)}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:700px){.kpi-grid{grid-template-columns:1fr 1fr}}
.kpi{border:1px solid var(--color-rule-gray);background:#fff;padding:16px;border-radius:var(--radius-cards)}
.kpi.yellow{background:var(--color-signal-yellow);border-color:#000}
.kpi b{display:block;font-size:24px;letter-spacing:-0.48px}
.mono{font-family:ui-monospace,monospace;font-size:12px}
.pill{display:inline-block;font:500 10px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;padding:3px 6px;border:1px solid var(--color-rule-gray);background:#fff}
.pill.yellow{background:var(--color-signal-yellow);border-color:#000}
.pill.black{background:#000;color:var(--color-signal-yellow);border-color:#000}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.grid3{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.grid3{grid-template-columns:1fr}}
.author-card{border:1px solid var(--color-rule-gray);background:#fff;padding:12px;border-radius:var(--radius-cards)}
.author-card:hover{border-color:#000}
.footer{padding:16px;text-align:center;font:500 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray);border-top:1px solid var(--color-rule-gray)}
"""
    # KPI row
    kpi=f"""<div class="kpi-grid">
      <div class="kpi yellow"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:#000">Target users</span><b>{manifest.get('target_users', total)}</b></div>
      <div class="kpi"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Completed</span><b>{completed}</b></div>
      <div class="kpi"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Failed</span><b>{failed}</b></div>
      <div class="kpi"><span style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Avg Engine</span><b>C{avg(dist['C'])} F{avg(dist['F'])} P{avg(dist['P'])}</b></div>
    </div>"""
    # author gallery
    gallery=""
    for r in persona_rows[:200]:
        author=esc(r.get("author","?"))
        sig=esc((r.get("engine") or {}).get("signature","—"))
        n=r.get("comments",0)
        gallery+=f'<a href="dossiers/u_{author}.html" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div class="author-card"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">u/{author}</div><div style="font-size:14px;font-weight:700;margin-top:6px">{sig}</div><div class="mono" style="color:var(--color-caption-gray);margin-top:4px">{n} comments</div><div style="margin-top:6px"><span class="pill yellow">dossier →</span></div></div></a>'
    if not gallery:
        gallery='<div class="card">No dossiers yet — run build_dataset.py to populate.</div>'
    else:
        gallery=f'<div class="grid3">{gallery}</div>'
    # failed list
    failed_html=""
    if manifest.get("failed"):
        items="".join(f"<li>u/{esc(f.get('author','?'))} — {esc(f.get('error',''))[:120]}</li>" for f in manifest["failed"][:10])
        failed_html=f'<div class="card" style="margin-top:12px"><div class="eyebrow">Failed</div><ul class="mono" style="margin:6px 0 0;padding-left:16px">{items}</ul></div>'

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>MONOCLE · r/{esc(subreddit)} Dataset — {total} users</title><style>{styles}</style></head><body>
<div class="utility"><div><span style="letter-spacing:.14em">MONOCLE</span> <span style="color:var(--color-mute-gray);font-weight:400">· DATASET</span> <span style="color:var(--color-mute-gray);font-weight:400">· r/{esc(subreddit)}</span></div><div><span class="pill yellow">INDEX</span></div></div>
<header class="mast"><h1>MONOCLE <span style="font-weight:400">· r/{esc(subreddit)} DATASET</span></h1><div class="sub">{total} authors · dossiers in Notion · index in Monocle · {now}</div>
<div class="kicker"><span><b>{completed}</b> dossiers</span><span><b>personas.jsonl</b> JSONL</span><span><b>dossiers/</b> HTML</span><span><b>manifest.json</b> checkpoint</span></div></header>
<div class="wrap">
<section><div class="eyebrow">DATASET</div><h2 style="margin:0;font-size:28px;letter-spacing:-0.5px">Synthetic population — <em style="font-style:normal;background:linear-gradient(transparent 60%,var(--color-signal-yellow) 60% 88%,transparent 88%)">r/{esc(subreddit)}</em></h2>
<p style="color:var(--color-caption-gray);margin:8px 0 0;max-width:68ch">Each card links to a full V3.3 Notion dossier. Use <code>personas.jsonl</code> for programmatic simulation. Re-run the same command to resume from checkpoint.</p>
<div style="margin-top:16px">{kpi}</div>
{failed_html}
</section>
<section><div class="eyebrow">DOSSIERS <em>· click to open</em></div>
{gallery}
<p style="margin-top:12px;font:500 11px/1 var(--font-helvetica-neue);color:var(--color-caption-gray)">Showing {min(len(persona_rows),200)} of {len(persona_rows)} dossiers. Raw JSONL at <code>personas.jsonl</code>.</p>
</section>
<section><div class="eyebrow">USAGE</div>
<div class="grid3">
<div class="card"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Simulate reactions</div><pre class="mono" style="margin:8px 0 0;white-space:pre-wrap">import json
rows=[json.loads(l) for l in open("personas.jsonl")]
# feed persona_stack to your sim
</pre></div>
<div class="card"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Debate prep</div><p style="margin:8px 0 0;font-size:13px;line-height:1.5">Open any dossier — Engine + Big Five + quotes + argument architecture tell you how they'll engage.</p></div>
<div class="card" style="background:var(--color-margin-white)"><div style="font:700 11px/1 var(--font-helvetica-neue);letter-spacing:.06em;text-transform:uppercase;color:var(--color-caption-gray)">Resume</div><p style="margin:8px 0 0;font-size:13px;line-height:1.5">Same command resumes: <code>python build_dataset.py --subreddit {esc(subreddit)} --users {manifest.get('target_users', total)} --out {esc(str(out_dir))}</code></p></div>
</div>
</section>
</div>
<div class="footer">MONOCLE · Dataset Index · r/{esc(subreddit)} · {now} · Arctic Shift archive · Single-file HTML — opens offline</div>
</body></html>"""

def main():
    ap=argparse.ArgumentParser(description="Build synthetic population dataset for a subreddit")
    ap.add_argument("--subreddit", required=True)
    ap.add_argument("--users", type=int, default=20, help="target number of authors")
    ap.add_argument("--comments-per-user", type=int, default=100)
    ap.add_argument("--out", required=True, help="output directory (e.g. ./data/parenting/)")
    ap.add_argument("--model", default="deepseek-v4-flash", help="LLM model for persona synthesis (deepseek-v4-flash recommended for prompt-cache savings)")
    ap.add_argument("--concurrency", type=int, default=2, help="parallel persona builds (1-4 recommended)")
    ap.add_argument("--min-comments", type=int, default=20, help="skip authors with fewer comments")
    ap.add_argument("--keep-raw", action="store_true", help="save raw comment JSON per author")
    ap.add_argument("--no-llm", action="store_true", help="heuristic dossiers only (no LLM)")
    args=ap.parse_args()

    _load_env_file()
    out_dir=Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    dossiers_dir=out_dir/"dossiers"; dossiers_dir.mkdir(exist_ok=True)
    raw_dir=out_dir/"raw"; raw_dir.mkdir(exist_ok=True)
    manifest_path=out_dir/"manifest.json"
    jsonl_path=out_dir/"personas.jsonl"

    # load or init manifest
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        # allow retargeting to larger N
        if args.users > manifest.get("target_users",0):
            manifest["target_users"]=args.users
    else:
        manifest={"subreddit":args.subreddit,"target_users":args.users,"comments_per_user":args.comments_per_user,"model":args.model,"started_at": datetime.now(timezone.utc).isoformat(),"completed":0,"failed":[],"authors":[]}
        jsonl_path.write_text("")

    # discover authors if needed
    if len(manifest.get("authors",[])) < args.users:
        need=args.users - len(manifest.get("authors",[]))
        print(f"[dataset] discovering {need} more authors for r/{args.subreddit} …", file=sys.stderr)
        new_authors=discover_authors(args.subreddit, target=need+10)
        # filter to not already in manifest
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

    # load existing persona rows for index
    persona_rows=[]
    if jsonl_path.exists():
        for line in jsonl_path.read_text().splitlines():
            if line.strip():
                try: persona_rows.append(json.loads(line))
                except: pass

    def build_one(author: str):
        out_html=dossiers_dir/f"u_{author}.html"
        out_json=dossiers_dir/f"u_{author}.json"
        try:
            comments=fetch_comments_paginated(author=author, total=args.comments_per_user)
            if len(comments) < args.min_comments:
                return {"author":author,"skipped":True,"reason":f"only {len(comments)} comments (<{args.min_comments})"}
            if args.keep_raw:
                (raw_dir/f"u_{author}.json").write_text(json.dumps(comments, ensure_ascii=False, indent=2))
            # delegate to persona.py logic via subprocess for isolation
            import subprocess, sys as _sys
            cmd=[_sys.executable, str(SCRIPT_DIR/"persona.py"), "--author", author, "--limit", str(args.comments_per_user), "--out", str(out_html)]
            if args.no_llm: cmd.append("--no-llm")
            else: cmd.extend(["--model", args.model])
            # persona.py will use cache, so this reuses fetched comments
            # ensure DEEPSEEK key reaches subprocess (load from .env)
            _env=dict(os.environ)
            # also load from file if missing
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
            # read rubric sidecar if exists
            rubric={}
            if out_json.exists():
                try: rubric=json.loads(out_json.read_text())
                except: pass
            return {"author":author,"engine":rubric.get("engine"),"persona_stack":rubric.get("persona_stack"),"comments":len(comments),"html":str(out_html)}
        except Exception as e:
            return {"author":author,"error":str(e)[:400]}

    # run with threadpool (mostly IO-bound: API + LLM)
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
                    print(f"[dataset] ok u/{author} ({r.get('comments',0)} comments)", file=sys.stderr)
                    persona_rows.append({"author":author,"engine":r.get("engine"),"persona_stack":r.get("persona_stack"),"comments":r.get("comments",0)})
                    # append to jsonl
                    with open(jsonl_path,"a") as f:
                        f.write(json.dumps({"author":author,"engine":r.get("engine"),"persona_stack":r.get("persona_stack"),"engine_metrics":r.get("engine_metrics"),"comments":r.get("comments",0)})+"\n")
                    manifest["completed"]=(manifest.get("completed",0)+1)
                manifest_path.write_text(json.dumps(manifest, indent=2))
                results.append(r)

    # always rewrite index
    index_html=render_index(args.subreddit, authors, manifest, persona_rows, out_dir)
    (out_dir/"index.html").write_text(index_html, encoding="utf-8")
    print(f"[dataset] done — {manifest['completed']}/{args.users} dossiers → {out_dir}/index.html", file=sys.stderr)
    print(str(out_dir/"index.html"))

if __name__=="__main__": main()
