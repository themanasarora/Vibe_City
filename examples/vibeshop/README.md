# VibeShop (demo)

A tiny Next.js + Supabase + Stripe store, used to show off [Vibe City](../../README.md). It doesn't need to run, and you don't need to `npm install` anything. Vibe City only reads the code.

It's broken on purpose so the city has something to show: a syntax error (🔥), a server secret read in browser code (☣️), an import to a missing file (🌉), a circular import (🚦), an unused file (👻) and two TODOs (🚧).

```bash
python3 skills/vibe-city/scripts/vibecity.py build examples/vibeshop --open
```
