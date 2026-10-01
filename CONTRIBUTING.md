# Contributing to Vibe City

Ideas, bug reports and PRs are all welcome, including small ones.

## Share an idea
Open an [💡 Idea issue](https://github.com/themanasarora/Vibe_City/issues/new?template=idea.yml). The best ideas describe a problem in real code and how it could look in the city. Some on the wish list:
- 🌊 floods for slow endpoints
- 🧟 zombie dependencies
- 🚨 API routes with no auth check
- more languages: Go, Ruby, PHP

## Report something wrong
Open a [🐛 bug issue](https://github.com/themanasarora/Vibe_City/issues/new?template=bug.yml) with a small code sample. Missing or wrong roads are the most useful reports, because the analysis is heuristic.

## Hack on it
It's plain Python 3 plus one HTML file, with no build step and no dependencies.

```bash
python3 skills/vibe-city/scripts/vibecity.py serve examples/vibeshop   # live city, rebuilds on save
```

| File | What it does |
|---|---|
| `skills/vibe-city/scripts/vc_scan.py` | reads each file: symbols, calls, fetches, routes, services |
| `skills/vibe-city/scripts/vc_analyze.py` | links files together, finds disasters, works out the blast radius and health |
| `skills/vibe-city/assets/viewer.html` | the three.js city |
| `examples/vibeshop/` | a deliberately broken demo app to test against |

A new disaster usually means a detector in `vc_analyze.py` plus an effect in `viewer.html`. Look at how `ghost` or `construction` work end to end. Please check `examples/vibeshop` still renders before you open a PR.
