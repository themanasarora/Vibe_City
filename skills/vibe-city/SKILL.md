---
name: vibe-city
description: Turns the current codebase into an interactive 3D city — files are buildings, functions are floors, calls/fetches are glowing roads, external services (Stripe, Supabase, OpenAI…) are towers on the horizon, and problems show up as disasters (fires = errors, toxic leaks = exposed secrets, broken bridges = missing imports, gridlock = circular imports, ghosts = dead code, construction = TODOs). Also shows the "blast radius" of uncommitted changes. Use when the user asks to visualize / map / see their project or architecture, asks "what did my changes affect", "what breaks if I change X", "how does data flow", "show me my vibe city", or wants a health check of a vibe-coded project.
---

# Vibe City

Show the user their project as a living 3D city they can explore in the browser, with plain-English explanations of every building.

All tooling lives in `scripts/vibecity.py` inside this skill's directory (the base directory shown when this skill loaded — call it `$VC`). It is Python 3 stdlib only: no installs. Output goes to `<project>/.vibecity/`.

## Workflow

### 1. Build the city

```bash
python3 "$VC/scripts/vibecity.py" build <project-dir>
```

Prints a one-line health summary (score, disasters, blast radius). Add flags when they help:

- `--check` — run the project's own TypeScript checker (if `node_modules/.bin/tsc` exists); type errors become 🔥 fires.
- `--check-cmd "npm test"` — run any command; every `file:line` error in its output becomes a fire. Use when the user says something is broken.
- `--errors <log>` — map a saved error log / stack trace onto the city.
- `--base main` — blast radius against a branch instead of uncommitted changes vs `HEAD`.
- `--json` — also print health, impact and incidents as JSON (useful for your own reporting).

### 2. Explain the buildings (the part only you can do)

The scanner knows *structure*; you add *meaning*. Get the list of files lacking a summary:

```bash
python3 "$VC/scripts/vibecity.py" pending <project-dir> --limit 40
```

Read those files, then write `<project-dir>/.vibecity/notes.partial.json`:

```json
{
  "project": { "summary": "2–3 sentences: what this app does and how it's put together." },
  "files": {
    "src/lib/cart.ts": {
      "summary": "Saves and loads the shopping cart in Supabase.",
      "symbols": { "addToCart": "Adds a product to the cart after checking it exists." }
    }
  },
  "incidents": [
    { "type": "fire", "file": "src/app/api/checkout/route.ts", "symbol": "POST", "message": "No try/catch — a Stripe outage crashes checkout." }
  ]
}
```

Then merge it (this stamps file hashes so summaries are marked stale when code changes):

```bash
python3 "$VC/scripts/vibecity.py" notes <project-dir> --merge <project-dir>/.vibecity/notes.partial.json
```

Writing rules — the audience is a vibe coder, not a senior engineer:
- One sentence, ≤ 15 words, plain English, say what it does for the *user of the app* when possible ("Shows the cart page", not "Renders CartPage component").
- Symbol summaries only for exported / important functions; skip trivial ones.
- `incidents` is optional: add only real, specific risks you noticed while reading (missing error handling on payments, auth checks missing on an API route, secrets on the client). Types: `fire`, `toxic`, `broken`, `gridlock`, `ghost`, `construction`. Passing `incidents` replaces earlier Claude-written ones.
- Large projects: summarize the most important files first (API routes, data layer, entry pages, then components) and tell the user how many remain; they can ask for more later.

### 3. Show it

```bash
python3 "$VC/scripts/vibecity.py" build <project-dir> --open
```

Or, for a live city that rebuilds on every save (great while vibe coding), run in the background:

```bash
python3 "$VC/scripts/vibecity.py" serve <project-dir>     # http://127.0.0.1:4321
```

Deep links (append to the city URL): `#select=src/lib/cart.ts` or `#select=src/lib/cart.ts#addToCart`, `#trace=<file>#<fn>` to auto-play a flow, `#breaks=<file>#<fn>` for a reverse blast radius, `#impact` to focus on changed code.

### 4. Report back in chat

Keep it short and concrete:
1. Health line (score + weather) and what the city looks like (districts, services).
2. Each disaster: what it means in plain words, the file, and the fix. Offer to fix them.
3. If there are uncommitted changes: what changed, and the blast radius — which screens/routes could break, so the user knows what to test.
4. Remind them what to click: floors → inspector, "▶ Trace" to watch data flow, "💥 What breaks if I change this?".

## Answering specific questions

- **"What did my changes affect?"** → `build --json`, read `impact.changedFloors` and `impact.blast` (id → hops away), explain the chain from the change to user-facing screens/routes.
- **"What breaks if I change X?"** → find X's floor id (`file#name`) in `.vibecity/graph.json`, walk edges backwards (`edges[].to == id`), and give the user the `#breaks=` link.
- **"How does data get from A to B?"** → walk `edges` forward from the UI floor (types: `render`, `call`, `fetch` = network request to an API route, `service` = external service) and narrate it; give the `#trace=` link.
- **"Why is my app broken?"** → `build --check-cmd "<their test/build command>"` and walk them through the fires.

## Notes

- Languages: JS/TS/JSX/TSX (React, Next.js, Express, Hono, Vue/Svelte script blocks) and Python (FastAPI/Flask routes). Analysis is static and heuristic; dynamic calls can be missed — say so if the user relies on something that isn't shown.
- `.vibecity/notes.json` is worth committing; `city.html` and `graph.json` are gitignored automatically.
- The viewer loads three.js from a CDN, so the page needs internet the first time.
