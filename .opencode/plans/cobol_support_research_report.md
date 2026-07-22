# COBOL-to-Python Migration: Comprehensive Research & Recommendations

> **Date:** July 2026
> **Context:** Analysis of existing `cobol2python` tooling, industry research on COBOL→Python migration approaches, and recommendations for filling critical gaps (OCCURS, REDEFINES, 88-levels, transitive deps, etc.)

---

## 1. Executive Summary

The existing `cobol2python` tool follows a **hybrid AST+LLM architecture**:
- **Deterministic parsers** handle DATA DIVISION layout, interfaces, and dependency graphs (~20% of COBOL constructs)
- **LLM-based translation** handles PROCEDURE DIVISION logic (~50% of constructs)
- **~30% of constructs have no tool-level support** and rely entirely on the LLM getting it right

**Industry consensus** (ICSME 2025 COB2PY paper, kelapure 2025 market analysis, multiple production tools) is that **hybrid deterministic + LLM approaches demonstrably outperform** pure-LLM or pure-rule-based translations across all metrics.

**Key recommendation:** Keep the hybrid architecture but replace the three weakest deterministic parsers — `shared_model_generator.py`, `cobol_parser.py`, and `batch_manager.py` transitive dep logic — with properly engineered solutions inspired by `python-cobol` (for copybook parsing) and `cobol-safe-translator` (for full COBOL AST parsing).

---

## 2. Landscape of Existing Tools (as of July 2026)

### 2.1 Open Source Tools

| Tool | Approach | COBOL Coverage | License | Key Strength |
|------|----------|---------------|---------|-------------|
| **cobol-safe-translator** (IronAdamant/PythonBol-Translator) | Rule-based AST -> Python; MCP server for AI agents | **Full**: 5,288 files, 32 projects, 100% syntax valid; OCCURS, REDEFINES, 88-levels, SORT, STRING, COMP-3, SCREEN SECTION, GO TO, 50+ verbs, 43 FUNCTION intrinsics | MIT | Zero dependencies, offline, MCP integration for AI review |
| **python-cobol** (royopa) | Copybook parser with denormalization | OCCURS, REDEFINES, INDEXED BY, PIC parsing | GPLv3 | Clean API for copybook parsing; denormalizes OCCURS into expanded fields |
| **COB2PY** (IIT Tirupati, ICSME 2025) | Full COBOL AST -> Python, rule-based | CodeNet dataset validated; Computational Accuracy metric | N/A (academic) | Proven rule-based approach with published evaluation |
| **LegacyBridge** (nnffmlabs) | Hybrid AST + LLM with semantic validation | Claimed wide coverage | N/A | Semantic validation of generated code |

### 2.2 Commercial / Services Landscape

- **AI-first pure-plays**: Moderne ($30M), Mechanical Orchard ($74M), CoreStory ($68M) — all using hybrid deterministic+LLM approaches
- **Cloud hyperscalers**: AWS Transform, Azure Migrate, IBM watsonx Code Assistant
- **System integrators**: Accenture, TCS, Infosys — COBOL->Java/Python practices

### 2.3 Key Market Insight

Per the 2025 kelapure analysis: *"Hybrid AST-LLM architectures demonstrate substantially higher success rates than pure LLM or pure AST approaches"*. The most successful tools **parse COBOL structurally** and **use LLMs for semantic reasoning**, not for translation from raw source.

---

## 3. Architecture Comparison: Current vs. Best Practices

### 3.1 Current Architecture (cobol2python)

```
COBOL Source
  |-- zip_processor.py       -> CALL/COPY dependency graph (flat string names)
  |-- cobol_parser.py        -> FD record layout (flat fields only, no hierarchy)
  |-- interface_extractor.py -> LINKAGE SECTION params (flat list)
  |-- shared_model_generator.py -> Flat Pydantic model from copybook (NO OCCURS/REDEFINES)
  |-- copybook_resolver.py   -> Inline COPY statements (plain text)
  |
  +-- Agent Workflow (LLM-powered)
        |-- analyze.py      -> I/O contract via LLM
        |-- translate.py    -> Python code via LLM (raw COBOL source + contexts)
        |-- gen_tests.py    -> pytest tests via LLM
        |-- run_tests.py    -> Execute in isolated sandbox
        +-- reflect.py      -> Fix failures iteratively
```

**Critical gap:** The parsers produce flat, lossy field lists. The LLM receives the raw COBOL source but gets no structured AST. All hierarchical relationships (OCCURS nesting, REDEFINES aliasing, 88-level conditions) are lost in the deterministic layer and must be re-inferred by the LLM from raw text.

### 3.2 Recommended Architecture (Hybrid with Proper Parsing)

```
COBOL Source
  |-- COBOL AST Parser (new/enhanced)
  |     |-- DATA DIVISION AST: OCCURS, REDEFINES, 88-levels, hierarchy preserved
  |     |-- PROCEDURE DIVISION AST: paragraph/section boundaries, CALL targets
  |     +-- FILE SECTION AST: FD, SELECT, ORGANIZATION, RECORD KEY
  |
  |-- Deterministic Generators
  |     |-- Nested Pydantic models (OCCURS -> list[ChildModel], REDEFINES -> Union/discriminator)
  |     |-- Record layouts with hierarchy (for file I/O)
  |     +-- Dependency graph with transitive closure
  |
  +-- Enhanced Agent Workflow
        |-- analyze.py      + AST context
        |-- translate.py    + structured DATA DIVISION AST -> better LLM guidance
        |-- gen_tests.py    + model-aware test scaffolding (LineItem factory, etc.)
        |-- run_tests.py    + transitive dep bundling
        +-- reflect.py      + AST-aware error diagnosis
```

---

## 4. Detailed Gap Analysis & Solution Paths

### 4.1 OCCURS Clause -> Nested Pydantic Models

**Current behavior:** `shared_model_generator.py:88-122` produces flat `rma_line_table: str`

**Target behavior:**
```python
class LineItem(BaseModel):
    rl_item_id: str
    rl_item_category: str
    rl_original_qty: int
    rl_return_qty: int
    rl_unit_price: Decimal

class RmamastModel(BaseModel):
    rma_number: str
    rma_line_count: int
    rma_line_table: list[LineItem]  # <- was str
```

**Solution options (ranked):**

| Option | Effort | Impact | Risk | Best For |
|--------|--------|--------|------|----------|
| **A. Integrate `python-cobol`** for copybook parsing | Low (2-3 days) | Solves OCCURS + REDEFINES + INDEXED BY for copybooks | Low (well-tested library, 26 stars, 15 forks) | Copybook-only parsing |
| **B. Build hierarchy-aware generator** inspired by `cobol-safe-translator` parser | Medium (1-2 weeks) | Full control, no external dep | Medium (must implement and test OCCURS handling) | Long-term ownership |
| **C. Use `cobol-safe-translator` CLI as preprocessor** | Low (1 day) | Instant full coverage | Medium (shelling out, output format mapping) | Quick wins / prototyping |

**Recommendation: Path A first (quick win for copybook models) + Path B for full control.**

### 4.2 REDEFINES -> Overlapping Storage / Union Types

**Current behavior:** Not modeled at all. `interface_extractor.py:48-49` just captures REDEFINES as raw text in the PIC group.

**Target behavior:**
```python
# For fixed-width record parsing:
# All REDEFINES variants share the same memory
class DataRecord:
    def __init__(self, raw: bytes):
        self._raw = raw

    @property
    def text_field(self) -> str:
        return self._raw[0:20].decode()

    @property
    def numeric_field(self) -> int:
        return int(self._raw[0:20].decode())
```

**Solution:** `cobol-safe-translator` handles REDEFINES via `RedefinesAlias/RedefinesSlice` with `post_init` wiring. For our purposes:
1. Track which fields REDEFINE which other fields in the field metadata
2. Generate a `bytes`-backed record class with property-based accessors
3. OR generate `Union` types where REDEFINES creates overlapping views

### 4.3 88-Level Conditions -> Constants / Enums

**Current behavior:** `shared_model_generator.py:38-39` has `if level == 88: continue`. Constants are only generated if the parent field has a VALUE clause.

**Target behavior:**
```python
class RmamastModel(BaseModel):
    rma_overall_status: str

    @validator("rma_overall_status")
    def validate_status(cls, v):
        valid = {"A": "Approved", "R": "Rejected", "P": "Pending"}
        if v not in valid:
            raise ValueError(f"Invalid status: {v}")
        return v
```

**Solution:** Parse 88-level entries from copybooks, generate validation logic. The `python-cobol` library does not specifically handle 88-levels — this requires custom logic.

### 4.4 Transitive Dependency Resolution

**Current behavior:** `batch_manager.py:180-184` includes only direct CALL targets in dep_code.

**Target behavior:** Build transitive closure of all reachable CALL targets.

```python
def get_transitive_calls(pid, graph, visited=None):
    if visited is None:
        visited = set()
    calls = set(graph.get(pid, {}).get("calls", []))
    for caller in calls:
        if caller not in visited and caller in graph:
            visited.add(caller)
            calls |= get_transitive_calls(caller, graph, visited)
    return calls

dep_pids = get_transitive_calls(program_id, graph)
dep_code = {pid: code for pid, code in completed_code.items() if pid in dep_pids}
```

### 4.5 Test Environment Module Discovery

**Current behavior:** `test_environment.py:154` hardcodes `local_modules = {"main", "test_main", "__init__", "shared_models"}`

**Target behavior:** After writing dependency stubs, parse each stub's import statements and add unknown modules to the local set. Or simply rely on the transitive closure from SS4.4:

```python
local_modules = {"main", "test_main", "__init__", "shared_models"}
local_modules.update(m.lower() for m in dependency_code.keys())
```

---

## 5. Recommended Implementation Plan

### Phase 1: Quick Wins (Week 1)

| Task | Files | Effort |
|------|-------|--------|
| Fix transitive deps in batch_manager | `batch_manager.py:180-184` | 2 hours |
| Fix extra_local_modules recognition | `test_environment.py:549` | 1 hour |
| Generate nested models for OCCURS | `shared_model_generator.py` | 2-3 days |
| Generate LineItem-style child models | `shared_model_generator.py` | 1 day |

### Phase 2: Copybook Parsing Upgrade (Week 2)

| Task | Files | Effort |
|------|-------|--------|
| Integrate `python-cobol` for copybook field extraction | `shared_model_generator.py` (replace internals) | 2 days |
| Add REDEFINES field tracking | New `cobol_data_descriptor.py` module | 2 days |
| Add 88-level enum/constant generation | New logic in `shared_model_generator.py` | 1 day |
| Generate from copybook hierarchy -> nested Pydantic | Update `generate_pydantic_model()` | 2 days |

### Phase 3: Record I/O & Test Scaffolding (Week 3)

| Task | Files | Effort |
|------|-------|--------|
| Enhanced cobol_parser.py for hierarchical FD records | `cobol_parser.py` | 2 days |
| AST-aware context builder for LLM translate prompt | New `ast_context_builder.py` | 2 days |
| Structured DATA DIVISION -> Pydantic in LLM prompt | `translate.py:_build_shared_models_context` | 1 day |
| Test scaffolding with model factories | `gen_tests.py` + new `test_factories.py` | 2 days |

### Phase 4: Evaluation & Hardening (Week 4)

| Task | Effort |
|------|--------|
| Run against monolith_corpus_1 (2 programs, 3 copybooks) | 1 day |
| Run against returns_corpus (7 programs, inter-CALL, OCCURS) | 1 day |
| Iterative fix of detected regressions | 2 days |
| Documentation & migration guide | 1 day |

---

## 6. Key Architectural Decisions

### 6.1 To Depend on External Libraries or Not?

| Approach | Pros | Cons |
|----------|------|------|
| Use `python-cobol` (pip install) | Proven, tested, handles OCCURS/REDEFINES | GPLv3 license (viral), may not cover all edge cases |
| Use `cobol-safe-translator` (CLI/API) | MIT license, 100% on 5,288 files, full COBOL support | 21MB install, subprocess dependency |
| Build in-house | Full control, no license concerns, tailored to our data flow | 2-3 weeks dev time, must maintain |

**Recommendation:** Use `python-cobol` as a parsing library for copybooks only (its GPL license covers the library, not our generated output). For full-program parsing, consider calling `cobol-safe-translator` via its MCP server or CLI.

### 6.2 Nested Model Strategy

For OCCURS tables:

**Option A: Denormalized (flat with index suffix)** — matches COBOL memory layout, simple but awkward API

**Option B: Nested (hierarchical)** — `record.items[4].code` — natural Python, requires serialization logic from flat bytes

**Recommendation:** Option B for the *shared model* layer (Pydantic for LLM context + test data), Option A for the *file I/O* layer (record parsing where byte offsets matter). These are distinct use cases.

### 6.3 LLM Context Enhancement

The biggest quality improvement per token cost is to **give the LLM structured DATA DIVISION information** rather than raw COBOL source:

```python
# Current:
## COBOL Source
# ... 2000 lines of raw COBOL ...

# Enhanced:
## DATA DIVISION (Structure)
# - RmamastModel (from RMAMAST copybook):
#   rma_number: str[12]
#   rma_line_table: list[LineItem]  <- OCCURS 50
#     - rl_item_id: str[12]
#     - rl_return_qty: int[4]
# - WORKING-STORAGE:
#   WS-RETURN-CODE: PIC 9(2) -> int[2]
# - LINKAGE:
#   RMA-BLOCK (from RMAMAST):
#     .rma_number: str[12]
```

This reduces the LLM's cognitive load from "parse COBOL syntax" to "translate known structure."

---

## 7. Specific File Changes Summary

### Priority: HIGH (currently breaking the pipeline)

| File | Change | Why Now |
|------|--------|---------|
| `shared_model_generator.py:88-122` | Add OCCURS parsing -> nested models + list[] types | Current `rma_line_table: str` breaks all generated code that accesses table elements |
| `batch_manager.py:180-184` | Transitive closure for dependency stubs | Direct-deps-only causes ModuleNotFoundError on transitive CALL chains |
| `test_environment.py:154` | Auto-discover local modules from all dependency code | Unknown modules treated as pip packages -> install failure |

### Priority: MEDIUM (quality improvement)

| File | Change | Why |
|------|--------|-----|
| `shared_model_generator.py:38-39` | Parse 88-level conditions -> validation constants/enums | Currently `if level == 88: continue` — silently dropped |
| `interface_extractor.py:46-51` | Structural OCCURS + REDEFINES parsing (not raw text capture) | Better interface info for LLM context |

### Priority: LOW (nice to have)

| File | Change | Why |
|------|--------|-----|
| `cobol_parser.py` | Hierarchical FD field support (groups, nested OCCURS) | More accurate record layouts for dummy file generation |
| `translate.py:_build_shared_models_context` | Structured context instead of raw model_code text | Better token efficiency in LLM prompts |
| `gen_tests.py` | Model-aware test factories | Tests that actually construct valid nested model instances |

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OCCURS denormalization produces wrong offsets | Medium | High | Validate against actual COBOL memory layout; test with known copybooks |
| GPLv3 license conflict with python-cobol | Low (our code not derivative) | N/A | Use python-cobol as separate process/CLI call if needed; or reimplement its logic |
| LLM still produces incorrect code for complex OCCURS logic | Medium | Medium | Use deterministic code generation for table indexing boilerplate; leave business logic to LLM |
| Transitive closure explosion (too many deps) | Low | Low | Limit to programs known from the graph; cap depth to 3 |

---

## 9. References

1. **cobol-safe-translator** — https://github.com/IronAdamant/PythonBol-Translator (MIT, 5,288 file corpus)
2. **python-cobol** — https://github.com/royopa/python-cobol (GPLv3, OCCURS/REDEFINES/INDEXED BY parsing)
3. **COB2PY** — ICSME 2025 Tool Demo, IIT Tirupati — https://rishalab.github.io/COB2PY/
4. **kelapure AI Modernization Analysis** — https://github.com/kelapure/ai-powered-modernization-analysis
5. **LegacyBridge** (hybrid AST+LLM) — https://github.com/nnffmlabs/legacybridge
6. **IBM COBOL OCCURS documentation** — https://www.ibm.com/docs/en/cobol-zos/6.3.0?topic=entry-occurs-clause
