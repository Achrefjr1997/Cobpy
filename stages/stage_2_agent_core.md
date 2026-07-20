# Stage 2 — The Agent Loop

## Purpose

Build the thinking heart of the system: an agent that can plan, act, observe, and decide what to do next. This stage proves the LangGraph state machine works correctly—that the planner can route to different nodes, that state accumulates without mutation, and that the loop terminates appropriately.

The test case is deliberately trivial: migrate a "HELLO WORLD" COBOL program. If the architecture can't handle the simplest possible case, it won't handle complex ones.

## What Success Looks Like

Run the agent on a HELLO WORLD COBOL program. It produces valid Python that, when executed, prints the same output. The agent made decisions, generated code, ran tests, and finished—all observable through the event stream and final state.

## Architecture Concept

The agent is a cyclic graph with a central **planner** node that inspects the current state and decides which action to take next. Every action node does one thing, updates the state, and returns control to the planner. The planner keeps choosing actions until it decides to finish (or hits safety limits).

**State as Memory**: The agent's memory lives in a typed state dictionary. It contains the COBOL source, Python drafts (plural—we keep history), test results, lessons learned, and metadata. Nodes receive this state and return partial updates; nothing mutates in place.

**Planner as Conductor**: The planner sees the current state (what's been tried, what failed, what was learned) and selects the next action from a fixed menu: analyze, translate, generate tests, run tests, validate, reflect, or finish. Its decision is structured output from an LLM—no regex parsing of free text.

**Action Nodes**: Each does exactly one thing. Translate produces a new Python draft. Gen-tests creates a pytest file. Run-tests executes in a sandbox and captures results. Finalize closes the run. Analyze and reflect exist as placeholders—they'll become meaningful in Stage 3.

## Key Capabilities to Build

**State schema** with typed fields for COBOL source, draft history (append-only), test results, lessons learned, action history, step counter, and an emit function for events.

**Planner node** that uses structured LLM output to select the next action with reasoning. It never executes side effects—only decides.

**Translate node** that prompts the LLM with the COBOL source and any prior context, receiving structured output with code and rationale.

**Test generation node** that creates a minimal pytest file asserting the code runs and produces output.

**Test runner** that executes generated code in an isolated temporary directory with safety checks (AST-based import blocking for dangerous modules) and timeouts.

**Finalize node** that marks the run complete and emits the final event.

**Graph wrapper** that enforces robustness: step budget limits, repeat detection, exception handling that routes to finalize rather than crashing.

**CLI entry point** for running the agent directly on a COBOL file without the HTTP layer.

## Robustness Mechanisms

These are in code, not prompts—never trust the LLM to self-limit:

- **Step budget**: Hard cap on planner iterations. If exceeded, force finalize.
- **Repeat detection**: If the same action with the same inputs appears three times consecutively, force reflection (Stage 3) or finalize.
- **Exception handling**: Any node failure sets an error in state and routes to finalize. The API layer never sees raw exceptions.

## Safety for Generated Code

Generated Python is untrusted. Before execution:
- Parse the AST and reject any imports of dangerous modules (os, subprocess, socket, etc.)
- Execute in a fresh temporary directory, not the project root
- Use subprocess with timeout and minimal environment variables
- Truncate captured output to prevent state bloat

## Verification Criteria

- CLI successfully migrates HELLO WORLD COBOL to working Python
- Agent completes within step budget
- State shows at least one draft and one passing test run
- No state mutation—all updates are through returned dicts
- Every node emits exactly one event

## Boundary

Keep the analyze and reflect nodes as pass-throughs. Don't implement ingestion from URLs or repos. Don't add the validation stack. The goal is proving the loop topology works, not feature completeness.
