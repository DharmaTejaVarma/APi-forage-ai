# APIForge AI — Benchmark Evaluation Results

Generated on: 2026-11-24 22:39:36
Evaluation Model: `qwen2.5:7b-instruct` (Local Ollama)
Embeddings Model: `nomic-embed-text` (Local Ollama)

## Executive Summary

| Metric | Target | Achieved | Status |
|---|---|---|---|
| **Pydantic Schema Validity** | 100.0% | **100.0%** | PASS |
| **DAG Acyclicity (NetworkX)** | 100.0% | **100.0%** | PASS |
| **Rule 8 Approval Adherence** | 100.0% | **100.0%** | PASS |
| **Average Generation Latency** | < 60.0s | **48.65s** | PASS |

---

## Benchmark Run Details

| ID | Benchmark Scenario | Steps | Schema Valid | DAG Acyclic | Rule 8 Enforced | Latency |
|---|---|---|---|---|---|---|
| `eval_01` | E-Commerce Discount & Order Creation (Demo Core) | 3 | Yes | Yes | Yes | 80.93s |
| `eval_02` | Product Catalog Query | 1 | Yes | Yes | Yes | 21.24s |
| `eval_03` | Single Product Price Lookup | 1 | Yes | Yes | Yes | 25.25s |
| `eval_04` | Discount Calculation Formula | 2 | Yes | Yes | Yes | 43.86s |
| `eval_05` | Direct Order Creation | 5 | Yes | Yes | Yes | 91.85s |
| `eval_06` | Multi-Step Tax & Discount Order | 4 | Yes | Yes | Yes | 73.92s |
| `eval_07` | Delete Resource Gate Verification | 1 | Yes | Yes | Yes | 25.43s |
| `eval_08` | Order Status Verification | 1 | Yes | Yes | Yes | 26.75s |

---

## Key Observations
1. **Zero-Code Generation**: Every evaluated plan yielded structured JSON conforming to `GeneratedWorkflowPlan` without raw executable Python code.
2. **Deterministic Rule 8 Enforcement**: 100% of state-modifying steps (`POST`, `PUT`, `DELETE`) were flagged with `requires_approval=True`.
3. **Graph Integrity**: Topological DAG sort succeeded on all valid plans without self-loops or cyclic dependencies.
