---
created: 2026-03-23T14:14:52.791Z
title: Scout other dotmd forks for ideas
area: general
files: []
---

## Problem

inventivepotter/dotmd has 5 forks. We've diverged architecturally but other forks may have interesting ideas, approaches, or features worth borrowing. No visibility into what the community is doing with this project.

## Solution

Use `gh api repos/inventivepotter/dotmd/forks` to list all forks. For each:
- Check commit count and recency
- Diff against upstream to see what they changed
- Note any interesting patterns (different vector stores, search strategies, UI approaches, deployment models)

Low priority — do when curious, not urgent.
