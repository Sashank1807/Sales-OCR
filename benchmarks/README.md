# Benchmarking Suite

This directory contains evaluation benchmarks, profiling utilities, and cached results across the 31-document real-world pharmaceutical distributor scan corpus.

---

## 📁 Layout

```
benchmarks/
├── README.md               # This guide
├── benchmark.py            # Main accuracy and validation benchmark harness
├── profile_image_path.py   # Latency and stage profiling (render, det, rec, geometry)
└── cache/                  # Cached per-page results for zero-compute re-analysis
    ├── benchmark_cache.json
    ├── benchmark_cache_dev.json
    └── benchmark_cache_heldout.json
```

---

## 🚀 Running Benchmarks

### 1. Run Benchmark against Development Manifest
```bash
python benchmarks/benchmark.py --set dev
```

### 2. Re-render Benchmark Report from Cache (Fast, no OCR)
```bash
python benchmarks/benchmark.py --reuse --markdown
```
*Emits the detailed evaluation report directly to [docs/BENCHMARK.md](../docs/BENCHMARK.md).*

### 3. Output as JSON
```bash
python benchmarks/benchmark.py --reuse --json
```

### 4. Profile Latency on Scanned Pages
```bash
python benchmarks/profile_image_path.py
# Or profile a specific document page:
python benchmarks/profile_image_path.py path/to/document.pdf --page 1
```

---

## 📊 Evaluation Documentation
For full benchmark results, failure mode analysis, and accuracy breakdowns, see **[docs/BENCHMARK.md](../docs/BENCHMARK.md)**.
