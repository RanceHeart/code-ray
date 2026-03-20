from __future__ import annotations

import os
from typing import Dict, List


ENTRY_BASENAMES = {
    "main.py",
    "main.ts",
    "main.tsx",
    "main.js",
    "index.ts",
    "index.tsx",
    "index.js",
    "index.jsx",
    "app.ts",
    "app.tsx",
    "app.js",
    "app.jsx",
    "server.ts",
    "server.js",
    "rexxar-cli.ts",
}


def detect_entrypoints(index: dict, top_n: int = 50) -> dict:
    nodes = index.get("nodes") or []
    adj = index.get("adj") or {}
    in_adj = adj.get("in") or {}
    out_adj = adj.get("out") or {}

    ranked: List[dict] = []
    for n in nodes:
        path = n.get("path") or ""
        if not path:
            continue

        base = os.path.basename(path)
        score = 0
        reasons: List[str] = []

        if path == "package.json":
            score += 100
            reasons.append("package-manifest")
        if path == "tsconfig.json":
            score += 25
            reasons.append("tsconfig")
        if base in ENTRY_BASENAMES:
            score += 40
            reasons.append(f"entry-basename:{base}")
        if "/page/" in path and base.startswith("index."):
            score += 35
            reasons.append("page-index")
        if path.endswith("map.json"):
            score += 30
            reasons.append("route-map")
        if "/service/" in path:
            score += 12
            reasons.append("service-layer")
        if "/components/" in path or "/widget/" in path:
            score += 8
            reasons.append("ui-leaf-candidate")

        score += min(20, len(in_adj.get(path, [])) * 2)
        score += min(20, len(out_adj.get(path, [])) * 2)

        if score > 0:
            ranked.append(
                {
                    "path": path,
                    "lang": n.get("lang"),
                    "score": score,
                    "reasons": reasons,
                    "in_degree": len(in_adj.get(path, [])),
                    "out_degree": len(out_adj.get(path, [])),
                }
            )

    ranked.sort(key=lambda x: (-x["score"], x["path"]))
    return {
        "meta": index.get("meta") or {},
        "entrypoints": ranked[:top_n],
    }
