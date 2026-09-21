# Documentation Index

Welcome to the technical documentation for the Pharmaceutical Document Extraction and Validation Engine.

---

## 📚 Guides & Specifications

1. **[Pipeline Architecture (PIPELINE.md)](./PIPELINE.md)**
   - Two-layer extraction philosophy (Raw layer vs. Semantic layer).
   - Stages chaining: `file` $\rightarrow$ `router` $\rightarrow$ `reader` $\rightarrow$ `column_mapper` (Stage A) $\rightarrow$ `validator` (Stage B).
   - Column role discovery, sectioning, arithmetic validation gates, and cumulative multi-page reconciliation.

2. **[Benchmark & Evaluation (BENCHMARK.md)](./BENCHMARK.md)**
   - 31-file real-world distributor scan corpus evaluation.
   - Per-page classification accuracy, cell-level precision/recall, and timing profiles.
   - Error categorization and failure mode analysis.

3. **[Test Suite Report (TEST_REPORT.md)](./TEST_REPORT.md)**
   - 126 automated test cases across readers, geometry, Stage A column mapping, taxonomy, and Stage B validation.
   - Ground truth verification methodology and edge-case testing.

---

## 🔗 Quick Links
- [Project Overview & Web Studio Guide](../README.md)
- [Benchmark Suite](../benchmarks/README.md)
