# AgentICU — Upgrade Plan (✅ COMPLETE)

> Supersedes the earlier remodel, which narrowed AgentICU's scope to protect
> it from a crowded observability market. This version keeps the full
> ambition and adds real capability from 2026 research on proactive failure
> forecasting and causal failure attribution in multi-agent systems — neither
> of which any existing observability platform does today.
>
> **Status: All 6 weeks fully implemented. Outcome tracking feedback loop added
> in Phase 8. 97 tests passing.**

## Status Quo

AgentICU instruments agents via decorators, classifies failures using the
MAST taxonomy (NeurIPS 2025, 14 failure modes across 3 categories), runs
recovery playbooks, and escalates to humans when recovery fails.

## The Upgrade: From Reactive Classification to Proactive, Causal Diagnosis

MAST gives you a taxonomy for labeling a failure once it's happened. Recent
research goes two steps further:

**1. Proactive forecasting.** PROMAS models multi-agent execution as a
Markov transition process and forecasts the probability of reaching an error
state *before* the agent chain gets there — the same "predict, don't just
detect" idea behind Pro2Guard (used in the AgentOps upgrade), applied
specifically to multi-agent failure modes instead of single-agent safety
violations.

**2. Causal failure attribution.** AgentRx, DOVER, and a growing 2025-2026
body of work on hierarchical and causal-inference-based attribution in
multi-agent systems address a gap MAST doesn't: when five agents hand off a
task and it fails, MAST tells you what *kind* of failure occurred, not which
agent actually *caused* it versus which agent merely inherited a bad state.
Causal attribution traces the failure back through the handoff chain to the
actual root cause — critical for pointing a recovery playbook at the right
target instead of restarting the wrong agent.

**3. Restore and extend the embedding-similarity classifier.** The original
scoped-down plan cut this for time. Put it back: pattern-matching catches
known failure signatures, embedding similarity catches novel ones that don't
match an existing pattern. Run both, not either/or.

## Scope: Everything Kept, Three Capabilities Added

**Keep everything from the original design:**
- `@trace`, `@tool_call`, `@handoff`, and `@decision` decorators — restore
  `@decision`; causal attribution needs branching rationale, not just actions
- Full 14-failure-mode MAST classification, not the 4-5-playbook cut
- The recovery playbook engine

**Add:**
- A PROMAS-style forecaster: learn transition dynamics from your own
  collected traces, predict failure probability at each handoff, and trigger
  early intervention before a failure completes
- A causal attribution layer: when a failure is detected, trace back through
  the handoff chain (using `@handoff` / `@decision` trace data) to the agent
  whose action was the actual root cause, and route the recovery playbook
  there
- Embedding-similarity classification as a second detection path alongside
  pattern matching, catching novel failure signatures pattern-matching alone
  would miss

**Still smart, not a cut:** consume traces via an OTel-GenAI-compatible
adapter from whatever tracing stack (Langfuse / Phoenix / raw OTel) the user
already has, instead of building a redundant custom collector. This doesn't
reduce AgentICU's capability — forecasting, attribution, and recovery all
still run at full strength; it just avoids rebuilding commodity plumbing a
dozen funded companies already do well.

## Updated Architecture

```
Existing traces (Langfuse / Phoenix / raw OTel) — includes @decision rationale
              │
              ▼
   AgentICU Adapter Layer
              │
              ├──────────────► PROMAS-style Forecaster (predicts failure probability ahead of time)
              │
              ▼
   MAST Classifier (pattern-matching + embedding similarity, both active)
              │
              ▼
   Causal Attribution Layer (traces failure back through handoff chain to root-cause agent)
              │
              ▼
   Recovery Playbook Engine (targets the actual root-cause agent) ──► Escalation
              │
              ▼
   Outcome Tracking — feeds back into both the forecaster and the classifier
```

## Updated Competitive Landscape

| Tool | Traces? | MAST? | Proactive forecasting? | Causal attribution? | Auto-recovery? |
|---|---|---|---|---|---|
| Langfuse / Arize Phoenix / LangSmith / Braintrust | ✅ | ❌ | ❌ | ❌ | ❌ |
| Microsoft AGT (Agent SRE) | ✅ | ❌ | Partial (generic circuit breaking) | ❌ | Partial |
| Research prototypes (PROMAS, AgentRx, DOVER individually) | ❌ | ❌ | PROMAS only | AgentRx / DOVER only | ❌ |
| **AgentICU (upgraded)** | Consumes | ✅ | ✅ | ✅ | ✅ |

No other system combines all five columns.

## Updated Build Plan (full 6 weeks)

| Week | Work |
|---|---|
| 1 | Full decorator set (`@trace`/`@tool_call`/`@handoff`/`@decision`) + OTel-compatible adapter layer |
| 2 | Full 14-mode MAST classifier: pattern-matching + embedding-similarity paths both active |
| 3 | PROMAS-style forecaster: learn transition model from traces, predict failure probability ahead of completion |
| 4 | Causal attribution layer: trace failures back through the handoff/decision chain to the root-cause agent |
| 5 | Recovery playbook engine targeting the root-cause agent + dashboard |
| 6 | Real end-to-end demo on a live LangGraph/CrewAI agent: record a forecasted failure caught early, and a completed failure correctly attributed and recovered |

## Updated Interview Narrative

> "MAST tells you multi-agent systems fail 41-86.7% of the time and gives you
> a taxonomy for what kind of failure it was — but it's diagnostic, after the
> fact. Newer 2026 work like PROMAS shows you can forecast these failures
> before they complete using Markov transition dynamics, and separate work on
> causal attribution shows you can trace a failure back through a handoff
> chain to the agent that actually caused it, not just the one holding the
> bag when it surfaced. I built AgentICU to combine both: it predicts
> failures ahead of time, and when one does happen, it attributes it causally
> so the recovery playbook targets the right agent. No observability
> platform does either of these, let alone both."

## Sources

- arXiv:2503.13657 — MAST Failure Taxonomy (NeurIPS 2025)
- arXiv:2603.20260 — PROMAS: Proactive error forecasting for multi-agent
  systems using Markov transition dynamics
- arXiv:2602.02475 — AgentRx: Diagnosing AI agent failures from execution
  trajectories
- arXiv:2512.06749 — DOVER: Intervention-driven auto debugging for LLM
  multi-agent systems
- arXiv:2605.14892 — survey covering causal/hierarchical failure attribution
  methods in LLM multi-agent systems
