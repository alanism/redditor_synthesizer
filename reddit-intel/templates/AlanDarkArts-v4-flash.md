---
title: "Universal Communication-Style Synthesis Template — V4 Flash"
version: "4.1-flash"
parent: "V4.0 Thinking — Seven-Signal Predictive Integrated"
system: "Seven-Signal Predictive Batch"
status: "Canonical compact batch template (revised 2026-08-16)"
intended_batch: "20–100 profiles; 15–30+ comments per profile"
output_modes:
  - microcard
  - survey_simulation
  - review_simulation
  - campaign_prediction
  - segment_rollup
replaces: "4.0-flash (see adversarial-review-v4-flash.md for the delta)"
---

# Universal Communication-Style Synthesis — V4 Flash

> **V4 Flash · Seven-Signal Predictive Batch**
> Compact, repeatable, context-efficient, and **prompt-cache-native** analysis for many Reddit profiles at once.

V4 Flash is the high-throughput companion to [V4 Thinking](</Users/alannguyen/Documents/Vibe Code/reddit-intel-alanism/AlanDarkArts-v4-thinking.md>). Same Seven-Signal vocabulary and prediction logic, but it emits **one compact JSON card per profile** plus **one rollup per batch** — never essays, never per-person digital twins.

---

## 0. Routing — Flash vs Thinking

| Question | Answer |
|---|---|
| **Use V4 Flash when** | Synthetic data, simulated surveys, simulated reviews, campaign predictions, and social/cultural/economic/political rollups across **many** profiles (a cohort or segment). |
| **Use V4 Thinking when** | A **single** redditor needs deep analysis — full dossier, digital twin, debate prep, longitudinal arc. |
| **Escalate Flash → Thinking** | Only for decision-critical thin/contested/high-value profiles (see §7). Never for the whole batch. |

Flash optimizes **speed and "good enough"**. Thinking optimizes **depth and fidelity**. Do not let Flash drift into Thinking's job.

---

## 1. Prompt-Caching Contract (read this first)

DeepSeek/OpenAI cache the **system** prefix and reuse it across calls in a batch. The only way Flash hits its speed/cost target at N=100 is to keep the stable part byte-identical and put everything variable in the user message.

### Pass 1 — Microcard (one per profile)

| Role | Content | Stability |
|---|---|---|
| **SYSTEM** (cached) | §2 codebook + §3 microcard schema + compactness rules. No mermaid, no examples, no prose. Byte-identical across all profiles. | Fixed for the whole batch |
| **USER** (variable) | The single author's corpus (item IDs + bodies), truncated. | Changes per profile |

### Pass 2 — Stimulus (survey / review / campaign)

| Role | Content | Stability |
|---|---|---|
| **SYSTEM** (cached) | §2 codebook + §4 answer schema + the **instrument/stimulus** (questions or offer). | Fixed for one stimulus run |
| **USER** (variable) | The already-built microcard JSON (not raw corpus). | Changes per profile |

**Rules**

1. The microcard (Pass 1) is built once per profile and **reused** across many instruments (Pass 2). Do not re-infer Seven Signals per instrument.
2. Never vary the SYSTEM block per profile — even whitespace busts the cache.
3. Put the instrument in SYSTEM when one stimulus runs across many profiles (the common case). Put it in USER only if you must reuse one profile across many instruments in a single session.
4. Run sequentially (concurrency 1–2) so the KV cache stays warm.

---

## 2. Seven-Signal Flash Codebook

The Seven Signals are canonical and byte-stable with V4 Thinking. Flash stores the axis position, a short reading, an evidence grade, and 2–3 item IDs.

| Signal | Axis shorthand | What it predicts |
|---|---|---|
| **ENGINE** | `C · F · A₁ · A₂-H · A₂-X · P` | Processing bandwidth, augmentation, self-audit, pressure shift |
| **MBTI** | `E/I · N/S · T/F · J/P` | Framing, information order, decision style |
| **PRISM** | `Inst/Exp · Local/Global · Equity/Comp · Duty/Auto` | Value resonance and moral rejection |
| **QuEST** | `Rapid/Steady · Analytical/Relational · Tenacious/Adaptive · Blunt/Diplomatic` | Decision tempo, CTA response, action posture |
| **Reality Lens** | `Material/Field · Deterministic/Emergent · Objective/Relational · Fated/Free` | Causal plausibility and worldview friction |
| **Cause & Craft** | `Technical/Spiritual · Holistic/Reductionist · Open/Lineage · Empirical/Esoteric` | Method, mechanism, delivery trust |
| **Proof & Purpose** | `Empirical/Intuitive · Self/Collective · Results/Meaning · Pragmatic/Transcendent` | Proof threshold, beneficiary, closing purpose |

### Engine shorthand

`+` high/frequent · `~` mixed/contextual · `−` low/little evidence.
`P` is a vector: `P:b{{+/~/−}} t{{+/~/−}} r{{+/~/−}}` = baseline / trigger / recovery. `r?` means recovery unobserved — never infer it.
`A₂-H` = human-visible self-audit. `A₂-X` = tool-mediated / exocortex audit.

### Claim states

`O observed` · `S supported` · `G suggestive` · `C contested` · `U insufficient` · `X out of scope`

### Evidence grades

`E0 insufficient` · `E1 suggestive` · `E2 supported` · `E3 robust`

Use `E0`/`U` instead of guessing. **Acceptance rule:** `E1` is enough for a non-decision-critical signal; escalate only decision-critical `E0` or contested high-value cases.

### Hypothetical IQ-LP — OFF by default

IQ-LP is **not emitted in Flash** unless explicitly requested. When requested, report a half-SD band interval (`B+1.0–B+1.5 · 107.5–<122.5 · E1`) and label it `linguistic-performance only`. **Never aggregate IQ-LP into a group or segment claim.** Extreme bands (< `B−1.0` or > `B+2.0`) escalate to V4 Thinking.

### Compactness rules

- One code per signal; explanation only when a signal is contested.
- Codes first, prose second.
- 2–3 anchors max per card; item ID + short exact phrase, never a long quote.
- No corpus-method prose repeated inside cards.
- Nuance goes in `flags`, `counterevidence`, and `escalate` — not paragraphs.

---

## 3. Canonical Output — Microcard JSON (Pass 1)

JSON is the **single canonical output**. Markdown tables (if rendered) are derived from this JSON, never a second thing the model writes.

```json
{
  "v": "4.1-flash",
  "batch_id": "{{batch_id}}",
  "profile_id": "{{profile_id}}",
  "segment": "{{segment_label}}",
  "n_comments": 0,
  "coverage": "adequate | thin",
  "one_line": "{{stable communication pattern + worldview + action posture}}",
  "signature": "{{seven-signal one-liner}}",
  "signals": {
    "engine": {"code": "{{C+ F+ A1~ A2H+ A2X- P~}}", "grade": "{{E0-E3}}", "evidence": ["{{id}}", "{{id}}"]},
    "mbti":   {"code": "{{N/T/J}}",       "grade": "{{E0-E3}}", "evidence": ["{{id}}"]},
    "prism":  {"code": "{{Exp·Glo·Com·Aut}}", "grade": "{{E0-E3}}", "evidence": ["{{id}}"]},
    "quest":  {"code": "{{Steady·Ana·Ada·Blu}}", "grade": "{{E0-E3}}", "evidence": ["{{id}}"]},
    "reality":{"code": "{{Mat·Eme·Obj·Fre}}", "grade": "{{E0-E3}}", "evidence": ["{{id}}"]},
    "craft":  {"code": "{{Tec·Hol·Ope·Emp}}", "grade": "{{E0-E3}}", "evidence": ["{{id}}"]},
    "proof":  {"code": "{{Emp·Col·Res·Pra}}", "grade": "{{E0-E3}}", "evidence": ["{{id}}"]}
  },
  "voice": "{{3-8 words}}",
  "best_fit": "{{topics/products/contexts}}",
  "friction": "{{primary rejection or failure trigger}}",
  "mind_changer": "{{proof / mechanism / experience that updates belief}}",
  "anchors": [
    {"id": "{{id}}", "phrase": "{{short exact phrase}}"},
    {"id": "{{id}}", "phrase": "{{short exact phrase}}"}
  ],
  "flags": ["{{thin | topic_skew | missing_context | contested | tool_assisted}}"],
  "counterevidence": "{{one line, optional}}",
  "escalate": false,
  "escalate_reason": "",
  "iq_lp": null
}
```

### Coverage and escalation thresholds

| n_comments | Action |
|---|---|
| ≥ 30 | `coverage: adequate`, normal confidence |
| 15–29 | `coverage: thin`, add `thin` flag, downgrade confidence; **do not** auto-escalate |
| < 15 | drop the profile, or `flag-only` with `E0`/`U` on every signal — never fabricate |

### Segment label

`segment` is a short, stable label the harness assigns from the signature — default taxonomy = dominant PRISM pole + dominant Proof pole (e.g. `Equity·Empirical`, `Autonomy·Intuitive`, `Duty·Results`). If a subreddit-specific or observed attribute grouping is authorized, use that instead. The rollup groups by this label.

---

## 4. Canonical Output — Stimulus Answer JSON (Pass 2)

One stimulus per run. The same schema covers survey, review, and campaign.

### Stimulus input

| Field | Value |
|---|---|
| stimulus_id | `{{id}}` |
| type | `{{survey | review | campaign}}` |
| stimulus | `{{exact questions, product, offer, or message}}` |
| scale | `{{1-5 / forced / open}}` |
| context | `{{private / public / peer / expert / time pressure}}` |

### Answer JSON

```json
{
  "v": "4.1-flash",
  "stimulus_id": "{{id}}",
  "profile_id": "{{profile_id}}",
  "segment": "{{segment_label}}",
  "answers": [
    {"q": "{{Q1}}", "a": "{{answer}}", "rating": null, "confidence": "{{low/med/high}}", "signal_reason": "{{signal: reason}}"}
  ],
  "overall": "{{1-5 or choice}}",
  "primary_objection": "{{objection}}",
  "mind_changer": "{{proof}}",
  "fit": {"engine": "{{N/B/H}}", "mbti": "{{N/B/H}}", "prism": "{{N/B/H}}", "quest": "{{N/B/H}}", "reality": "{{N/B/H}}", "craft": "{{N/B/H}}", "proof": "{{N/B/H}}"},
  "simulated": true
}
```

- `fit` codes: `N` native · `B` bridgeable · `H` hard conflict.
- For open answers: 1–3 sentences in the predicted register, then `signal_reason` cites the signal code + an anchor ID.
- Every answer object carries `simulated: true`. A simulated answer must never read as a verbatim quote.

---

## 5. Segment Rollup JSON (per batch)

```json
{
  "v": "4.1-flash",
  "batch_id": "{{batch_id}}",
  "topic": "{{topic}}",
  "valid_n": 0,
  "min_evidence_grade": "{{E0-E3}}",
  "segments": [
    {
      "label": "{{segment_label}}",
      "n": 0,
      "distribution": {"SUP": 0, "MIX": 0, "OPP": 0, "OBS": 0, "ABST": 0},
      "median_rating": null,
      "top_reason": "{{signal}}",
      "main_objection": "{{objection}}",
      "difference": "{{how this segment differs from the batch median}}"
    }
  ],
  "finding": "{{one sentence, directional}}",
  "counter_pattern": "{{minority or disagreement, preserved}}",
  "confidence": "{{low/med/high}}",
  "caveat": "{{why this does not establish public opinion}}"
}
```

### Rollup rules

- Report **directional tendencies**, never public-opinion estimates.
- One weight per profile (unless the analysis is explicitly comment-frequency).
- `ABST` is **not** opposition — keep it separate.
- Every percentage shows its `n`.
- Separate explicit stance from inferred stance.
- Preserve minority patterns; do not average them away.
- **Confidence methodology:** `confidence = f(valid_n, min_evidence_grade among contributors, stance spread)`. A rollup of 12 E1 guesses reads `low`; a rollup of 80 E2/E3 cards reads `high`. State the grade floor.

### Stance codes

`SUP` support · `MIX` mixed/conditional · `OPP` oppose · `OBS` descriptive only · `ABST` insufficient evidence.

---

## 6. Batch Cost & Acceptance

### Cost formula

```
batch_cost ≈ N × (system_tokens + corpus_tokens) × price_in
           + (N−1) × system_tokens × price_in_cached   # cached-prefix discount
           + N × completion_tokens × price_out
```

Budget **before** you run. For DeepSeek V4 Flash, cached system tokens price at roughly 0.1× uncached — the whole point of the Pass 1 / Pass 2 split.

### Acceptance (stop when)

- All seven signals have a code or `U`, with an evidence grade.
- Every decision-critical inference has ≥ 2 exact item IDs.
- Simulated answers are labeled simulated.
- No fabricated biography, private motive, or unlabeled IQ claim.
- The rollup shows per-segment n, grade floor, and a representativeness caveat.

### Realistic per-card budget

A microcard is **~350–550 tokens**; a single-stimulus answer is **~80–200 tokens** per profile. The old "250–500" figure was only the card body and excluded signal rows + anchors; budget accordingly.

---

## 7. Escalation to V4 Thinking

Escalate a **single** profile or finding (never the whole batch) when:

- The profile is **decision-critical** and evidence is thin or `E0`.
- Signal codes conflict across major contexts.
- The prediction affects a high-value product or consequential decision.
- A review needs detailed reasoning or source comparison.
- The rollup changes materially when one subreddit / year / topic is removed.
- A simulated answer could be mistaken for a verbatim quote.
- A sensitive inference is requested (route to Thinking's consent/sensitivity gate).
- Two independent runs disagree beyond the chosen spread.

**Escalation payload:** `{{profile_id}}` · `{{raw items}}` · `{{signal conflict}}` · `{{decision at stake}}`.

---

## 8. Flash ↔ Thinking Handoff

| Flash field | V4 Thinking expansion |
|---|---|
| Seven-Signal code | Full axis rationale, anchors, counterevidence, context shifts |
| `E0–E3` | Claim–evidence ledger |
| Fit `N/B/H` | Persona–stimulus signature + interaction matrix |
| Survey answer | Full response simulation with context switchboard |
| Review verdict | Product adaptation + proof hierarchy |
| Segment rollup | Longitudinal, topic-matched, subgroup analysis |
| Escalation flag | Full calibration + adversarial review |

> **V4 Flash summary**
> `Seven-Signal microcard × one stimulus/topic × segment rollup → compact, directional, cache-efficient insight.`
