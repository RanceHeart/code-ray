---
name: repo-context
description: Use code-ray as a repo scout before reading a codebase. Best for unfamiliar repositories, file-centric context gathering, architecture tracing, and task-oriented reconnaissance with small token budgets. Use when you need to quickly identify entrypoints, config, storage paths, routers, lifecycle files, recompute jobs, or the few files worth reading next.
---

# Repo Context

Use `coderay` as a **scout**, not as the final analyst.

Its job is to:
- narrow a repo to the few files worth reading
- show likely entry/config/router/storage chains
- gather context around one focal file
- reduce blind reading

Its job is **not** to:
- make the final business conclusion
- replace reading the selected files
- act as the source of truth when results are noisy

---

# Default Decision Tree

Use this in order.

## 1. Do I already have a focal file?

### Yes
Use `filepack`.

```bash
coderay filepack --index .coderay/index.json --file path/to/file.ts --budget-tokens 5000
```

If you need the broader feature chain, use:

```bash
coderay filepack --index .coderay/index.json --file path/to/file.ts --mode full-chain --goal "trace this feature from the current file" --budget-tokens 6000
```

Choose this when the real question is:
- “Explain this file.”
- “What else should I read from here?”
- “What is this file connected to?”
- “Trace the full feature around this file.”

---

## 2. No focal file. Is the repo unfamiliar?

### Yes
Use `bootstrap`.

```bash
coderay bootstrap --index .coderay/index.json --goal "understand this repository" --budget-tokens 4000
```

Choose this when the real question is:
- “Where should I start?”
- “What kind of repo is this?”
- “What are the main moving parts?”

Then pick the best returned root and switch to `filepack`.

---

## 3. No focal file, but I know the task

Use `pack --goal`.

```bash
coderay pack --index .coderay/index.json --goal "understand stamp business logic and data storage" --budget-tokens 5000
```

Choose this when the real question is:
- “Trace this feature.”
- “Where is data stored?”
- “Which files matter for this business flow?”
- “What files are relevant for this task?”

Then switch to `filepack --mode full-chain` on the most promising root.

---

## 4. Is this a literal keyword/search task?

If the task is mainly:
- a rare UI label
- a literal domain term
- a small frontend special-case
- a text-only wording hunt

use raw search first, then return to `filepack` once a focal file is known.

Do **not** force graph-based scouting where text search is clearly faster.

---

# Fast Mode Selection

## Use `bootstrap` when:
- the repo is unfamiliar
- you need initial orientation
- you want likely entry/config/router/domain roots

## Use `filepack` when:
- one file already matters
- you want nearby context around that file

## Use `filepack --mode full-chain` when:
- you need direct deps + reverse deps + symbol-related files + entry chain
- you want a feature pack around one focal file

## Use `pack --goal` when:
- the task is known but the focal file is not
- you need task-oriented root selection first

## Use raw search first when:
- the question is mostly literal text matching
- `coderay` output is obviously noisy for the task

---

# Standard Workflow

## A. Unfamiliar repository

1. Build or refresh the index
2. Run `bootstrap`
3. Read only the selected roots
4. Pick one strong file and switch to `filepack`

```bash
coderay xray . --out .coderay/index.json --exclude node_modules .git .idea .cache
coderay bootstrap --index .coderay/index.json --goal "understand this repository" --budget-tokens 4000
```

---

## B. Known focal file

1. Build or refresh the index
2. Run `filepack`
3. If scope is still too shallow, rerun with `--mode full-chain`
4. Read only the returned files

```bash
coderay filepack --index .coderay/index.json --file src/server/models/page.ts --budget-tokens 5000
```

```bash
coderay filepack --index .coderay/index.json --file src/server/models/page.ts --mode full-chain --goal "trace storage and recompute flow" --budget-tokens 6000
```

---

## C. Task-first reconnaissance

1. Run `pack --goal`
2. Choose the best root it returns
3. Switch to `filepack --mode full-chain`
4. Read the layered result

This is often the best path for medium or large repositories.

---

# How to Read the Output

## Bootstrap

Focus on:
- `project_profile`
- `selected_roots`
- `entry_candidates`

Bootstrap is for **orientation**, not certainty.

Use it to answer:
- what kind of repo is this?
- where are entry/config/router/domain files?
- which 3-6 files should I read first?

---

## Filepack / Full-chain

Focus on:
- `layers`
- `related_files`
- `bootstrap_roots`

The most important section is `layers`:
- `focal`
- `direct_deps`
- `reverse_deps`
- `symbol_related`
- `entry_chain`
- `siblings`

Interpret them as:
- `direct_deps`: what the file directly imports or depends on
- `reverse_deps`: what depends on the file
- `symbol_related`: same-symbol neighborhood
- `entry_chain`: entry/config/router/lifecycle/cron anchors
- `siblings`: same feature or same local area

---

# Task Heuristics

## Storage / data tasks

If the task mentions:
- storage
- data
- db
- sql
- redis
- cache
- schema
- persistence
- recompute
- cron

prefer files that look like:
- model/store/domain
- cache wrappers
- kv/redis/db access
- recompute jobs / cron / async paths

Do **not** stop at one model file.
Usually inspect:
- model/store
- cache/kv layer
- cron/recompute/async path

---

## Flow / business logic tasks

Prefer:
- entry
- router
- controller/surface
- service/logic
- reverse deps around the focal file

Usually start with `pack --goal`, then move to `filepack --mode full-chain`.

---

## UI / rendering tasks

Prefer:
- route
- page
- component
- widget
- view/controller

For literal wording or rare labels, raw search may beat graph-based scouting.

---

## Config / startup / lifecycle tasks

Prefer:
- manifests
- package/config files
- app entry files
- lifecycle files
- cron/bootstrap/init files

Bootstrap often works well here.

---

# Red Lines

## 1. Do not treat `coderay` as the final answer
Always verify by reading the selected files.

## 2. Do not start with huge budgets
For the first pass, `3000-6000` tokens is usually enough.

## 3. Stop scouting once the scope is good enough
If you already have the right 3-8 files, stop rerunning packs and read the code.

## 4. Do not trust noisy output blindly
If the result is obviously drifting, switch to raw search or direct reading.

## 5. Do not overuse repo-level mode
Once a strong focal file exists, switch to `filepack` quickly.

---

# Common Failure Modes

## Frontend entrypoint noise
Symptoms:
- many `index.tsx` files rank high

What to do:
- treat `bootstrap` as orientation only
- switch quickly to `filepack` around the best-looking feature file

---

## UI pollution in storage tasks
Symptoms:
- page/fragment/view files appear because they touch data indirectly

What to do:
- prioritize model/store/cache/recompute files
- verify actual storage ownership by reading code

---

## Example/demo target pollution in mobile repos
Symptoms:
- iOS/Android example apps steal root slots

What to do:
- trust repo-level output less
- switch to `filepack --mode full-chain` if a main target file is known

---

## Literal keyword tasks where raw search is better
Symptoms:
- the task is really about one word or one display condition

What to do:
- use raw search first
- switch back to `filepack` once a focal file is known

---

# Canonical Commands

Build index:

```bash
coderay xray . --out .coderay/index.json --exclude node_modules .git .idea .cache
```

Bootstrap:

```bash
coderay bootstrap --index .coderay/index.json --goal "understand this repository" --budget-tokens 4000
```

Goal pack:

```bash
coderay pack --index .coderay/index.json --goal "understand stamp business logic and data storage" --budget-tokens 5000
```

Filepack:

```bash
coderay filepack --index .coderay/index.json --file src/server/models/page.ts --budget-tokens 5000
```

Full-chain filepack:

```bash
coderay filepack --index .coderay/index.json --file src/server/models/page.ts --mode full-chain --goal "trace storage and recompute flow" --budget-tokens 6000
```

Direct graph neighborhood:

```bash
coderay ctx --index .coderay/index.json --file src/server/models/page.ts --hops 1 --budget-tokens 4000
```

Entrypoints:

```bash
coderay entrypoints --index .coderay/index.json --top-n 20
```

Symbol candidates:

```bash
coderay symbol --index .coderay/index.json --name Anthology --top-n 20
```

---

# Final Principle

Use `coderay` to become **less blind**, not **more overconfident**.

If it quickly gives you the right few files, it is doing its job.
Once you have those files, stop scouting and read the code.
