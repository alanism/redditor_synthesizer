---
title: "Adversarial Review — V4 Flash (Seven-Signal Predictive Batch)"
version: "4.0-flash-review"
reviewed: "2026-08-16"
purpose: "Synthetic data · simulated survey · group/segment prediction · speed + good-enough over digital-twin fidelity"
verdict: "Sound core. Not yet production-fit for high-throughput batch. Fix 3 critical + 4 high items before wiring into the pipeline."
---

# Adversarial Review — V4 Flash

**Target:** `AlanDarkArts-v4-flash.md` (Seven-Signal Predictive Batch, 20–100 profiles, 30+ comments each).

**Review lens:** V4 Flash exists for one reason — cheap, fast, honest *directional* output across a *cohort*, not a deep dossier per person. It wins when it maximizes insight-per-token and insight-per-dollar, and it loses when it drifts into V4 Thinking's territory (long prose, per-person digital-twin fidelity, IQ and personality depth) at batch scale. Every finding below is judged against that lens.

---

## Verdict

The Seven-Signal vocabulary, evidence grades, claim states, escalation routing, and scale-safe rollup are all correct and worth keeping. The template is a legitimate compressed companion to V4 Thinking.

But it is **not yet a prompt-caching-native, batch-honest artifact**. Three critical problems and four high problems will either (a) waste real money at N=100, (b) force half the cohort into the expensive Thinking lane for no reason, or (c) make the "speed and good-enough" promise false. Fix those first.

---

## CRITICAL — breaks the purpose or costs real money

### C1. No prompt-caching contract

The template is ~5,300 tokens. Sent as a per-profile prompt at N=100 that is ~530k prompt tokens before any corpus or completion. Without an explicit stable-prefix split, cache hits are accidental and every profile re-pays the full template.

The mermaid diagrams (4 blocks) and long explanatory prose are pure token waste inside an LLM prompt — they exist for *human readers*, not for generation. They inflate the cached prefix by ~1k+ tokens with zero output benefit.

**Fix (applied):** Split the template into a **SYSTEM** block (codebook + output schema + compactness rules — byte-identical across the whole batch, no mermaid, no examples) and a **USER** block (per-profile corpus + per-run stimulus). Document the exact split so the harness (`try_llm(system_prompt=…, prompt=… )`) can cache the SYSTEM prefix once and reuse it across all N profiles. This mirrors the existing V3.3 pattern (`PROMPT_V33.replace("{corpus}", "[CORPUS INSERTED IN USER MESSAGE]")`) and is the single highest-ROI change in this review.

### C2. "Fewer than 30 comments → escalate to V4 Thinking" is wrong for batch

Thin authors are structural, not exceptional. Small/suburban subreddits run 35–40% thin (<20 comments); large subs still run ~10%. If Flash escalates every <30-comment profile to Thinking, you rerun 30–40% of the cohort in the *expensive, slow, deep* lane — which defeats the entire point of Flash.

**Fix (applied):** `30` comments is *preferred*, `15–20` is *acceptable with a thin flag and downgraded confidence*, `<15` is *drop or flag-only*. Escalation to Thinking is reserved for **decision-critical** thin cases, not every thin case. The batch rolls forward; it does not stall on coverage.

### C3. Hypothetical IQ-LP per profile is a liability at batch scale

IQ-LP is (a) noisy at 15–30 comments, (b) ethically fraught, (c) useless for the actual question — "what would this *group* think?" — and (d) pure token cost in every card. It belongs in V4 Thinking (single-subject, deep, quarantined band), not in a 100-profile segment rollup.

**Fix (applied):** IQ-LP is **OFF by default in Flash**. Include only on explicit request. **Never aggregate** IQ-LP into a group or segment claim.

---

## HIGH — correctness, honesty, or rollup quality

### H1. Multi-output-mode sprawl invites over-production and drift

§2 (markdown card) + §3 (survey) + §4 (review) + §5 (campaign) + §6 (rollup) + §9 (JSON) + §10 (JSON rollup) ask the model to fill *seven* structures per run. A model told to emit all lanes will over-produce, repeat itself, and drift from the JSON shape. The markdown tables and the JSON duplicate each other.

**Fix (applied):** **JSON is the single canonical output.** One compact card object (Seven-Signal signature + evidence + optional stimulus answer) plus one rollup object. Markdown tables are a *human rendering derived from JSON*, not a second thing the model writes.

### H2. Token budget is unrealistically low

"250–500 tokens per profile card" is false against the schema it defines — seven signal rows (code + reading + grade + evidence IDs) + voice + best-fit + friction + mind-changer + anchors + flags lands closer to 400–700 tokens before any survey answer. A speed promise that under-states its own cost will silently blow budgets.

**Fix (applied):** Restate the budget honestly (see below) and shrink the card so the promise holds: JSON-first, codes before prose, 2–3 anchors max, no long quotes.

### H3. No segment / cluster step — the "consumer segment" promise is unfulfilled

The stated purpose includes "collective mass or specific consumer segments," but Flash only rolls up *all* profiles in one pile. There is no step that groups profiles into archetypes before rollup, so "what does segment X think" is unanswerable without re-processing by hand.

**Fix (applied):** Each card carries a `segment` label (derived from the dominant signal signature, or an observed attribute). The rollup reports per-segment distributions and the between-segment differences that actually matter for positioning.

### H4. Rollup confidence has no methodology

Per-row confidence exists, but there is no rule tying the *aggregate* directional claim to its inputs (valid n, minimum evidence grade, spread across profiles). This lets a rollup read as confident when it is actually 12 profiles of E1 guesses.

**Fix (applied):** Rollup confidence = f(valid n, minimum evidence grade among contributors, stance spread). State the rule; never report a bare percentage without its n and grade floor.

---

## MEDIUM — efficiency and consistency

- **M1. IQ-LP band table is truncated** vs V4 Thinking (missing B−3.0…B−1.5 and B+3.5). Intentional for Flash, but undocumented. Add: "extreme bands escalate to Thinking."
- **M2. Metadata linkage is loose.** §9 `meta` has `batch_id` + `profile_id`; §10 rollup has `rollup_id` but no `batch_id`. Add `batch_id` to the rollup so a card, its stimulus answers, and its rollup are provably one lineage.
- **M3. No "good enough" stopping rule.** Add an explicit acceptance rule: E1 suffices for non-decision-critical signals; escalate only decision-critical E0 or contested high-value; stop a batch when marginal insight-per-token flattens.
- **M4. "One line per signal" conflicts with the five-column signal table.** Clarify: the JSON `signature` string is the compact form; the table exists only for escalation and human rendering.

---

## LOW — hygiene

- **L1. Codebook shorthand must be byte-stable vs Thinking.** The shorthands are mostly identical, but document the canonical mapping (e.g. PRISM `Inst/Exp` ≡ `Institutional/Experimental`) so a Flash card expands into a Thinking profile without re-derivation.
- **L2. §0 batch card duplicates §9 meta.** Consolidate to one source of truth (JSON `meta`), keep the markdown card as a header for humans.
- **L3. No cost formula.** Add: `batch_cost ≈ N × (system_tokens + corpus_tokens) × price + N × completion_tokens × price`, with the cached-prefix discount called out. Budget before you run.

---

## What V4 Flash does *right* (keep these)

1. **"Compressed, not a different theory."** Correct. Shared vocabulary + evidence grades + handoff make Thinking↔Flash escalation lossless.
2. **Claim states + evidence grades** (`O/S/G/C/U/X`, `E0–E3`) force honesty at batch scale.
3. **Scale-safe interpretation** — one profile = one weight, `ABST` separate from `OPP`, `n` beside every %, no population claims.
4. **Escalation as a first-class lane** — once corrected (C2), this is the right safety valve.
5. **Simulated answers labeled as simulated** — non-negotiable, already correct.

---

## Fixes applied to the revised template

| # | Finding | Change |
|---|---|---|
| C1 | No caching contract | Added SYSTEM/USER split; removed mermaid from the prompt path |
| C2 | <30 escalation wrong for batch | 30 preferred / 15–20 thin-flag / <15 drop; escalate only decision-critical |
| C3 | IQ-LP liability | OFF by default; never aggregated |
| H1 | Output sprawl | JSON is canonical; markdown = rendering |
| H2 | Token budget false | Realistic budget restated |
| H3 | No segment step | `segment` label on card + per-segment rollup |
| H4 | Rollup confidence | Tied to n + grade floor + spread |
| M1–M4 | Efficiency/consistency | Band-table note, `batch_id` in rollup, stopping rule, compact-vs-table clarification |
| L1–L3 | Hygiene | Byte-stable shorthand note, metadata consolidation, cost formula |
