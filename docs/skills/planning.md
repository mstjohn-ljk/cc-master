# Planning Skills

Skills for competitive analysis, roadmapping, and research.

---

## `/cc-master:competitors`

Competitor analysis via web search. Identifies 3-5 competitors, extracts user pain points from reviews and forums, maps market gaps. Produces `.cc-master/competitor_analysis.json`. Optional — the pipeline works without it.

```
Usage:  /cc-master:competitors [--auto]
Output: .cc-master/competitor_analysis.json
Chains: → roadmap (prompted or --auto)
```

---

## `/cc-master:roadmap`

Strategic feature generation from project understanding. MoSCoW prioritization, complexity/impact assessment, dependency-ordered phases. When competitor data is available, features are enriched with user stories, linked to market evidence, and given priority boosts based on pain point severity.

```
Usage:  /cc-master:roadmap [--auto] [--competitors]
Output: .cc-master/roadmap.json
Chains: → kanban-add (prompted or --auto)
```

| Flag | Effect |
|------|--------|
| `--auto` | Skip chain prompt, continue to kanban-add |
| `--competitors` | Run competitor analysis inline before generating the roadmap |

---

## `/cc-master:research`

Perplexity-style deep web research for software development topics. Decomposes questions into parallel search angles, fetches and synthesizes sources with citations. Saves to `.cc-master/research/` and optionally creates kanban tasks.

```
Usage:  /cc-master:research <question or topic>
Output: .cc-master/research/<slug>.md
```

Standalone — no auto-chain.
