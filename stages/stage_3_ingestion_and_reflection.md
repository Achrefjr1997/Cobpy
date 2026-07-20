# Stage 3 — Learning From Failure

## Purpose

Transform the agent from a single-shot translator into a genuine learning system. This is where the "agentic" in "agentic migrator" earns its name: the agent must observe failures, extract lessons, and apply them to subsequent attempts. A system that succeeds or fails on the first try isn't an agent—it's a pipeline.

Additionally, this stage opens up how COBOL enters the system (not just files, but URLs and repos) and makes the analysis phase meaningful.

## What Success Looks Like

Run the agent on a COBOL program that reliably fails on the first translation attempt (packed decimal arithmetic is a classic LLM blind spot). Watch it fail, reflect, learn a lesson, try again with that lesson in context, and succeed on a later attempt. The state should show multiple drafts and at least one entry in lessons learned.

If the agent can recover from its own mistakes, the architecture works.

## The Reflection Mechanism

When tests fail, the planner can route to a **reflect** node. Reflection examines:
- The failing test output
- The code that produced it
- The I/O contract describing expected behavior
- Any lessons already learned

From this, reflection produces a **lesson**: a concise statement about what went wrong and how to fix it. This lesson is appended to state (never overwritten) and becomes part of the context for subsequent translation attempts.

The planner prompt includes all accumulated lessons. This is the core mechanism: past failures inform future attempts without hardcoded rules.

## The Analysis Phase

Before translation, **analyze** the COBOL to produce:
- A human-readable program summary
- An I/O contract: what inputs does the program expect, what outputs does it produce, what invariants must hold

The I/O contract drives test generation. Instead of generic "did it run?" tests, we generate tests that exercise the actual interface and verify documented invariants. This makes test failures meaningful feedback rather than noise.

## Input Flexibility

COBOL can now enter the system three ways:

**Snippet**: Raw text pasted directly. Quick for demos and small programs.

**URL**: Fetch from a public URL. Validate it looks like COBOL (presence of IDENTIFICATION DIVISION or PROGRAM-ID).

**Repository**: Clone a public GitHub repo, find the entry-point COBOL file (prefer files with PROGRAM-ID, else largest .cbl/.cob file), extract its contents.

All paths have size limits and validation. Repository clones are shallow and temporary.

## Draft Versioning

Drafts are append-only with parent references. When the planner decides to translate again, it can optionally target a specific earlier draft as the starting point (useful if a recent attempt diverged badly). The translate node sees which draft it's building from.

This isn't git—it's simpler. But it means we never lose work and can trace the evolution of attempts.

## Planner Context Evolution

The planner prompt now includes:
1. Program summary (what this COBOL does)
2. I/O contract (the behavioral specification)
3. Latest test results with key error lines
4. All accumulated lessons (most recent last)
5. Compressed action history (to detect loops)
6. Available actions

The richness of this context is what enables learning. Each reflection adds signal; each planning decision draws on accumulated signal.

## Verification Criteria

- Agent recovers from a first-attempt failure through reflection
- Final state shows multiple drafts (at least 2)
- Lessons learned is non-empty
- All three input modes work (snippet, URL, repo)
- I/O contract influences generated tests (not just generic smoke tests)
- Action history shows the reflection-then-retry pattern

## Boundary

Don't implement the validation stack yet (differential testing, property testing, LLM judge). The "tests" are still pytest-based functional checks. Don't wire this to the HTTP API—continue using CLI for testing. Database persistence comes in Stage 4.
