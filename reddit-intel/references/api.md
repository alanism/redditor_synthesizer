# Arctic Shift API — Quick Reference for reddit-intel

Base: `https://arctic-shift.photon-reddit.com` — no key, add `meta-app=reddit-intel`.

## Endpoints

- `GET /api/posts/search?subreddit=X&limit=25&sort=desc&after=ISO` — posts
- `GET /api/comments/search?subreddit=X&limit=100&sort=desc` — comments for velocity
- `GET /api/comments/search?author=X&limit=100&sort=desc` — persona corpus (paginate)
- `GET /api/posts/search?author=X&limit=100` — author's posts
- `GET /api/utils/min?subreddit=X` — earliest date

## Pagination

```python
import urllib.request, json, urllib.parse
API="https://arctic-shift.photon-reddit.com"
def fetch_posts(subreddit, limit=100, after=None):
    p={"subreddit":subreddit,"limit":limit,"sort":"desc","meta-app":"reddit-intel"}
    if after: p["after"]=after
    qs=urllib.parse.urlencode(p)
    with urllib.request.urlopen(f"{API}/api/posts/search?{qs}") as r:
        return json.loads(r.read().decode())["data"]
# paginate: after = str(data[-1]["created_utc"]*1000)  # ms
```

Limits: `limit` 1-100. FTS (`title`/`selftext`/`body`) requires `subreddit` or `author` or silently ignored.
Timestamps: stored `created_utc` in seconds; `after`/`before` accept ISO or ms.
