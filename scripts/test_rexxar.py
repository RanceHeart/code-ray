#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: test_rexxar.py <coderay_bin> <repo_root>", file=sys.stderr)
        return 2

    coderay = sys.argv[1]
    repo = Path(sys.argv[2]).resolve()
    index = repo / ".coderay" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> dict:
        out = subprocess.check_output([coderay, *args], cwd=str(repo), text=True)
        return json.loads(out)

    subprocess.check_call([coderay, "xray", str(repo), "--out", str(index), "--exclude", "node_modules", ".git", ".idea", ".cache", "--quiet"])

    summary = run("summary", "--index", str(index), "--top-n", "10")
    entrypoints = run("entrypoints", "--index", str(index), "--top-n", "10")
    symbol = run("symbol", "--index", str(index), "--name", "Intro", "--top-n", "10")
    ctx = run("ctx", "--index", str(index), "--file", "src/subject/page/intro/index.tsx", "--hops", "1", "--page-size", "6", "--budget-tokens", "4000")
    pack = run("pack", "--index", str(index), "--goal", "understand subject intro data flow", "--hops", "1", "--page-size", "6", "--budget-tokens", "5000")

    report = {
        "summary_stats": summary.get("stats"),
        "top_files": [x.get("path") for x in summary.get("top_files", [])[:5]],
        "entrypoints": [x.get("path") for x in entrypoints.get("entrypoints", [])[:5]],
        "symbol_hits": [x.get("path") for x in symbol.get("results", [])[:5]],
        "ctx_meta": ctx.get("meta"),
        "ctx_files": [x.get("path") for x in ctx.get("files", [])],
        "pack_roots": [x.get("path") for x in pack.get("selected_roots", [])],
        "pack_files": [x.get("path") for x in pack.get("files", [])[:10]],
        "pack_meta": pack.get("meta"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
