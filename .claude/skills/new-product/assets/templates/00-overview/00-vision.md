# Product Overview

<!--
FACILITATION GUIDE — Service Designer + Product Discovery
=========================================================
This is the starting point. Before anything gets designed or built,
we need to understand what this product IS and WHY it exists.

CONTEXT:
Read the project instructions file (`CLAUDE.md` or `AGENTS.md`) for any existing product description.
Use that as a starting point, but let the conversation reveal the
full picture. Don't assume — ask.

CONVERSATION FLOW:
1. Start with the problem (what's broken in the world?)
2. Move to who feels this pain
3. Define what "done" looks like
4. Capture the jobs to be done
5. Map the forces (Moments Framework)
6. Establish what this is NOT
7. Articulate the AI philosophy (where AI helps vs. what humans do)
8. Define A+ capabilities and the essential minimum
9. Map the ecosystem and establish guardrails

QUESTIONS TO ASK (in order):

## Round 1: The Problem
- "What problem does this product solve?"
- "Who experiences this problem? Describe them as real people."
- "What's broken about the current reality? What happens today without this?"
- "What has this problem cost — emotionally, financially, in time?"
- "Why does this problem exist? What's the root cause?"

## Round 2: The Vision
- "If this product existed perfectly, what would change for the user?"
- "What's the magic moment — the single instant where a user thinks 'this is it'?"
- "What would make someone tell a colleague about this?"
- "Walk me through what you see in your mind when someone is using this.
  What does it feel like?"

## Round 3: Forces Mapping (Moments Framework)
- PUSH (away from current state): "What's driving people away from how they
  do this today?"
- PULL (toward new solution): "What's the dream? What's pulling people toward
  something better?"
- ANXIETY (about switching): "What worries people about trying something new here?"
- HABIT (keeping them stuck): "What keeps people doing it the old way even
  when it's broken?"

## Round 4: Jobs to Be Done
- "When [situation], I want to [motivation], so I can [expected outcome]"
- Ask for 3-5 of these. Probe: "What job is the user hiring this product to do?"
- Consider different personas and contexts.

## Round 5: Boundaries
- "What should this product absolutely NOT do?"
- "What would make this product fail — not technically, but as an idea?"
- "What's the one thing this must do well, even if everything else is mediocre?"

## Round 6: AI Philosophy
- "Where does AI help in this product — and where must a human stay in control?"
- "What is the AI's job? What is the human's job? Where does that line sit?"
- "What language should we use and avoid when describing what AI does here?"
- "Apply the Magic Test to each AI feature you're imagining:
    1. Would it feel like magic? Not 'useful' — magic.
    2. Does it create 100x value? Not 2x, not 10x.
    3. Does it serve the human or replace them? If it replaces, rethink it.
    4. Are we anchored on AI as the solution? Start with the problem instead.
    5. Would we build this even without AI?"
- "What are the things we say about AI in this product, and what do we
  specifically NOT say?"

## Round 7: Capabilities & Essence
- "What are the 3-5 capabilities that make this excellent, not just useful?
  What does delight look like for each one?"
- "If you stripped this product to its absolute minimum — the core of what
  it is — what would remain?"
- "How many lines of core logic does this product need? Where does scope
  bloat come from?"
- "What is a capability that would be a B- version of this product?
  What would the A+ version of that same capability feel like?"

## Round 8: Ecosystem & Guardrails
- "Where does {{PRODUCT_NAME}} sit in a broader product ecosystem?
  What flows in? What flows out?"
- "Are there other products this connects with? What's the intelligence
  handoff — what data crosses the boundary?"
- "What feature requests should be an immediate no — the ones that are
  a regression trigger if they appear?"
- "Who are the three stakeholders who must accept this product for it
  to be considered successful? What does acceptance look like for each?"

SYNTHESIS:
After the conversation, fill in the sections below using the user's
own language wherever possible. Keep it concrete and human.
-->

## Product Name
{{PRODUCT_NAME}}

## Summary
<!-- Synthesize from Round 1 + 2 answers -->

## Problem Statement
<!-- From Round 1: What's broken, who feels it, what it costs -->

## Target Users
<!-- From Round 1: Who experiences this, described as real people -->

## Core Capabilities
<!-- From Round 2: What the product does, derived from the vision -->

## Status
- **Phase:** Design
- **Stack:** {{STACK}}

## Forces Map
<!-- From Round 3: Moments Framework -->

| Force | Description |
|-------|-------------|
| **Push** (away from current) | |
| **Pull** (toward new) | |
| **Anxiety** (about change) | |
| **Habit** (keeping stuck) | |

## Jobs to Be Done
<!-- From Round 4: When [situation], I want to [motivation], so I can [outcome] -->

## The Magic Moment
<!-- From Round 2: The single instant where the user gets it -->

## Non-Goals
<!-- From Round 5: What this product is NOT -->

## The One Thing
<!-- From Round 5: The one thing this must do well above all else -->

## AI Philosophy
<!-- From Round 6: Where AI helps vs. what humans do -->

> **AI principle:** [Capture the governing principle in one sentence here]

### What AI Does vs. What Users Do

| AI Provides | Users Do |
|-------------|----------|
| | |

### Language That Reflects This Principle

| We Say | We Don't Say |
|--------|--------------|
| | |

### The Magic Test

Before adding any AI feature — or any feature at all — ask:

1. **Would this feel like magic?** Not "useful." Not "efficient." Magic.
2. **Does this create 100x value?** Not 2x. Not 10x. If it is not 100x, it is probably not worth building.
3. **Does this serve the human, or replace them?** If it replaces, rethink it.
4. **Are we anchored on AI as the solution?** If yes, step back. Start with the problem.
5. **Would we build this even without AI?** If no, we are building for technology, not humans.

## A+ Capabilities
<!-- From Round 7: What makes this excellent, not just useful -->
<!-- For each capability: name it, describe the delight, give an example, state the impact -->

### 1. [Capability Name] (CRITICAL)

**The delight:**

**Example:**

**Impact:**

### 2. [Capability Name] (CRITICAL)

**The delight:**

**Example:**

**Impact:**

### 3. [Capability Name] (HIGH VALUE)

**The delight:**

**Example:**

**Impact:**

### 4. [Capability Name] (DIFFERENTIATOR)

**The delight:**

**Example:**

**Impact:**

### 5. [Capability Name] (LONG-TERM MOAT)

**The delight:**

**Example:**

**Impact:**

## Essential Minimum
<!-- From Round 7: What is the core of this product, stripped to its essence -->
<!-- List the essential components, their purpose, and notes -->

| Component | Purpose | Notes |
|-----------|---------|-------|
| | | |

## Ecosystem Context
<!-- From Round 8: Where does this sit, what flows in and out -->

```
[Other products or data sources]
      |
      | (what flows in)
      v
{{PRODUCT_NAME}}  ------>  [Downstream products or outputs]
      |
      v
[Other downstream recipients]
```

## Warning Signs (Regression Triggers)
<!-- From Round 8: Feature requests that are an immediate no -->

| Request | Why It Is Wrong |
|---------|-----------------|
| | |

## Acceptance Criteria
<!-- From Round 8: Three-stakeholder acceptance criteria -->

### For Users
<!-- What does a user say when this is working perfectly? -->

### For the Business
<!-- What does the business owner say when this is worth building? -->

### For the Ecosystem
<!-- What does success look like from a connected-product perspective? -->
