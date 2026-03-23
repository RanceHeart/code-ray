# code-ray

`code-ray` is a repo-scout CLI for AI agents.

It is built for one job:

> **Find the few files worth reading next.**

Use it when an AI enters an unfamiliar repository, needs context around one file, or needs a task-oriented reconnaissance pass before deep reading.

---

# What it does

`code-ray` gives you small, targeted context instead of forcing line-by-line repo crawling.

Main commands:

- `xray` — build an index for a repo
- `bootstrap` — get initial repo roots (entry/config/router/domain)
- `filepack` — gather context around one focal file
- `pack --goal` — gather task-oriented context when no focal file is known yet
- `entrypoints` — detect likely lifecycle / startup / route roots
- `symbol` — find files matching a symbol or domain term

---

# One-command install

## Recommended: install the CLI only

```bash
cd /Users/qili/PycharmProjects/code-ray
bash scripts/install.sh
```

This installs `coderay` using:
- `uv tool install` if available
- otherwise `pipx`
- otherwise `python3 -m pip install --user`

---

## Install the CLI and copy the OpenClaw skill

```bash
cd /Users/qili/PycharmProjects/code-ray
bash scripts/install.sh --workspace ~/.openclaw/workspace-opus46 --with-skill
```

This will:
- install `coderay`
- copy `skills/repo-context/SKILL.md` into:
  - `~/.openclaw/workspace-opus46/skills/repo-context/SKILL.md`

If your OpenClaw workspace is elsewhere, replace the path.

---

# AI-friendly quick start

If an agent can run shell commands, this is the shortest reliable setup:

```bash
cd /Users/qili/PycharmProjects/code-ray && bash scripts/install.sh --workspace ~/.openclaw/workspace-opus46 --with-skill
```

Then in a target repo:

```bash
coderay xray . --out .coderay/index.json --exclude node_modules .git .idea .cache
coderay bootstrap --index .coderay/index.json --goal "understand this repository" --budget-tokens 4000
```

If a focal file already exists:

```bash
coderay filepack --index .coderay/index.json --file path/to/file.ts --mode full-chain --budget-tokens 6000
```

---

# Install manually

If you prefer manual install:

## with uv

```bash
uv tool install /Users/qili/PycharmProjects/code-ray
```

## with pipx

```bash
pipx install /Users/qili/PycharmProjects/code-ray
```

## with pip

```bash
python3 -m pip install --user /Users/qili/PycharmProjects/code-ray
```

---

# Typical workflow

## 1. Build an index

```bash
coderay xray . --out .coderay/index.json --exclude node_modules .git .idea .cache
```

Useful excludes for larger repos:
- `dist`
- `build`
- `.next`
- `.venv`
- `Pods`
- `DerivedData`

---

## 2. If the repo is unfamiliar, start with bootstrap

```bash
coderay bootstrap --index .coderay/index.json --goal "understand this repository" --budget-tokens 4000
```

Use this to quickly find:
- entrypoints
- config files
- routers
- domain roots
- likely files to read first

---

## 3. If one file already matters, use filepack

```bash
coderay filepack --index .coderay/index.json --file src/server/models/page.ts --budget-tokens 5000
```

For a broader chain around the file:

```bash
coderay filepack --index .coderay/index.json --file src/server/models/page.ts --mode full-chain --goal "trace storage and recompute flow" --budget-tokens 6000
```

---

## 4. If the task is known but the file is not, use goal pack

```bash
coderay pack --index .coderay/index.json --goal "understand stamp business logic and data storage" --budget-tokens 5000
```

Then pick one returned root and switch to `filepack`.

---

# Why this exists

Most AI repo exploration fails in one of two ways:

1. it reads too much
2. it reads the wrong few files

`code-ray` is meant to be the middle layer:

- cheap local scouting
- token-aware context packs
- better first-file selection
- less blind exploration

It is a **scout**, not the final analyst.

---

# OpenClaw skill included in this repo

This repo ships with:

- `skills/repo-context/SKILL.md`

That skill documents the intended usage pattern for AI agents, including:
- when to use `bootstrap`
- when to use `filepack`
- when to use `full-chain`
- when raw search is better
- common failure modes

---

# Notes

- Parsing is intentionally approximate and fast.
- Results are meant to narrow scope, not replace code reading.
- Once you have the right 3-8 files, stop scouting and read the code.
