# Reddit-Intel Examples

Sample artifacts from r/parenting + r/stocks + Decision > Prediction pilot run (deepseek-v4-flash, 15 Aug 2026).

## What's here

| File | What it is |
|------|------------|
| `pulse-parenting.html` | Pipeline A Intelligence Brief (parenting — neutral-title fallback demonstrated) |
| `pulse-stocks.html` | Pipeline A Intelligence Brief (no MONOCLE — generated title, briefing, timeline, heatmap, quadrant, methodology) — 30 posts → 4 themes from `r/stocks` |
| `Cosmos-r-stocks-95-5-required.html` | Pipeline C Cosmos brief — `N=8,418,548 @95%/±5% → n=385, pull 482, pilot 50` |
| `Cosmos-r-stocks-95-3-tighter.html` | Tighter margin `@±3% → n=1,067` (tradeoff ref) |
| `Cosmos-N1300-stocks-lens.html` | Fixed-population `N=1,300 → n=297, pull 431` |
| `sample-dataset/` | Pipeline B **control panel** — 2 Notion dossiers + `index.html` (**Archetypes** bar + **Vega-Lite** 2 specs as JSON + expandable quote/argument + **Copy JSON**, local-first) + `personas.jsonl` (**enriched**: Big Five/quotes/arguments, not just Engine) + `manifest.json`. Real runs scale to 500+ via local SQLite. |
| `sample-survey/` | Pipeline 3 sample — `report.html` (Cosmos), `aggregates.json`, `survey-instrument.json`, 2 respondents sample. Full run is `~/Documents/Vibe Code/reddit-intel-stocks/survey-simulation/` (20 respondents). |

## Full runs (local, not committed)

- `~/Documents/Vibe Code/reddit-intel-homeschool/` — r/homeschool (hermes pilot)
- `~/Documents/Vibe Code/reddit-intel-parenting/` — r/parenting
- `~/Documents/Vibe Code/reddit-intel-stocks/` — r/stocks × Decision > Prediction (this sample's source: `learning_log.md` + `retrospective_scrap.md` there)
