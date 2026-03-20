# code-ray

`code-ray` is a repo-context CLI for AI agents, especially OpenClaw-style workflows.

It does four main things:

1. **xray** — scan a project and build a file-level dependency index
2. **summary** — show dependency hotspots first
3. **ctx** — fetch a file-neighborhood context pack with paging-by-file
4. **pack** — fetch a task-oriented context pack from a goal string

It is inspired by `code-xray`, but is **agent-first**: precompute once, then pull small, targeted packs instead of reading an entire repo line-by-line.

## Install (dev)

```bash
cd /Users/qili/PycharmProjects/code-ray
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Commands

### Build an index

```bash
coderay xray . --out .coderay/index.json
```

Useful flags:

- `--exclude node_modules .git dist build .venv venv`
- `--max-files 5000`
- `--max-bytes 300000`

### Show hotspots

```bash
coderay summary --index .coderay/index.json --top-n 20
```

### Detect entrypoints / route maps

```bash
coderay entrypoints --index .coderay/index.json --top-n 20
```

### Find symbol candidates

```bash
coderay symbol --index .coderay/index.json --name Intro
```

### Fetch file-neighborhood context

```bash
coderay ctx --index .coderay/index.json --file src/subject/page/intro/index.tsx --hops 1 --budget-tokens 4000
```

### Fetch goal-oriented context

```bash
coderay pack --index .coderay/index.json --goal "understand subject intro data flow" --budget-tokens 5000
```

## Design choices

- **paging is by file**, not line
- **budget can be token-oriented** (`--budget-tokens`)
- **TS alias resolution** supports common `tsconfig.json` patterns such as `@/*`
- **goal pack** is heuristic, not semantic search; it is meant to be cheap and local

## OpenClaw usage pattern

Recommended loop for code tasks:

1. `coderay xray`
2. `coderay summary`
3. `coderay entrypoints` or `coderay symbol`
4. `coderay ctx` or `coderay pack`
5. Only then `read` specific files deeply

## Notes

- Parsing is approximate and regex-based by design.
- Python + JS/TS dependency extraction is supported.
- Other file types still enter the node set and may appear in packs when heuristics match.
