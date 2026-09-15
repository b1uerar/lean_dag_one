# Public Lean proof example

The unmodified `Online/Lcm.lean` file is downloaded from the Lean 4.26.0
standard library. Its original copyright and Apache 2.0 notice are preserved.

- Repository: https://github.com/leanprover/lean4
- Source: https://github.com/leanprover/lean4/blob/v4.26.0/src/Init/Data/Nat/Lcm.lean
- Download mirror: https://cdn.jsdelivr.net/gh/leanprover/lean4@v4.26.0/src/Init/Data/Nat/Lcm.lean
- Theorem: `Nat.lcm_assoc`, associativity of the least common multiple.

From the tool's root directory:

```sh
python3 lean_dag.py examples/online/Online/Lcm.lean Nat.lcm_assoc --no-sorry-only -o output/lcm_assoc_local
```

Only theorem dependencies within `Lcm.lean` are extracted. Imported GCD,
arithmetic, and logical declarations are excluded. `graph.html` is the interactive
output; `graph.json` preserves all dependencies in this file's target subgraph.
This proof has no sorry, so `--no-sorry-only` is needed to show its seven nodes.
With the default filter, only the root `Nat.lcm_assoc` is exported.

`preview.cjs` optionally renders `full.svg`/`full.png` with Graphviz, using all
nodes and edges of this file-local graph. Its default output directory is
`output/lcm_assoc_local`; an alternate directory can be passed as an argument.

Image export requires the optional Node packages `@viz-js/viz` and `playwright`,
plus Playwright's Chromium. `VIZ_MODULE` and `PLAYWRIGHT_MODULE` can specify
existing module installations. The extractor itself does not require them.

```sh
node examples/online/preview.cjs
```

## Larger example: bitvectors

`Online/BitVecLemmas.lean` is the unmodified 6294-line Lean 4.26.0 source file:

- Source: https://github.com/leanprover/lean4/blob/v4.26.0/src/Init/Data/BitVec/Lemmas.lean
- Download: https://cdn.jsdelivr.net/gh/leanprover/lean4@v4.26.0/src/Init/Data/BitVec/Lemmas.lean
- SHA-256: `b794ef4f6f0978ba8b231dddfe1332d0d73ecde65ff1787bc68c130bc3b07ea1`
- Target: `BitVec.two_pow_ctz_le_toNat_of_ne_zero`, at line 6289.

For a nonzero bitvector `x`, its natural-number value is at least
`2 ^ (ctz x).toNat`, where `ctz` counts trailing zero bits. The file contains
many supporting theorems; the 6294-line count is the whole file, not one proof block.

```sh
python3 lean_dag.py examples/online/Online/BitVecLemmas.lean \
  BitVec.two_pow_ctz_le_toNat_of_ne_zero --no-sorry-only -o output/bitvec_ctz
node examples/online/preview.cjs output/bitvec_ctz
```

The result has 36 nodes and 60 edges, with no sorry. All nodes belong to the
input file, imports are excluded, and the sorry-only filter is disabled.
`output/bitvec_ctz/full.png` and `full.svg` show every extracted node and edge;
`graph.html` provides the interactive view and `graph.json` the full data.
