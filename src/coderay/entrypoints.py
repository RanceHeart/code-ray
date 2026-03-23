from __future__ import annotations

import os
from typing import Dict, List, Tuple


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

PYTHON_ENTRY_BASENAMES = {
    "main.py",
    "app.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "__main__.py",
}

PYTHON_ENTRY_SEGMENTS = {
    "bin",
    "cli",
    "command",
    "commands",
    "script",
    "scripts",
    "service",
    "server",
    "api",
    "views",
    "view",
    "handlers",
    "jobs",
    "tasks",
}

PYTHON_CORE_SEGMENTS = {
    "model",
    "models",
    "domain",
    "controller",
    "controllers",
    "view",
    "views",
}


def _normalize_adj(index: dict) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    adj = index.get("adj") or {}
    raw_out = adj.get("out") or {}
    raw_in = adj.get("in") or {}
    nodes = index.get("nodes") or []
    id_to_path = {str(n.get("id")): n.get("path") for n in nodes if n.get("path") is not None and n.get("id") is not None}

    def convert(raw: Dict[str, List[str]]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for key, vals in raw.items():
            src = id_to_path.get(str(key), key)
            if not src:
                continue
            mapped: List[str] = []
            for v in vals or []:
                tgt = id_to_path.get(str(v), v)
                if tgt:
                    mapped.append(tgt)
            out[src] = sorted(set(mapped))
        return out

    return convert(raw_in), convert(raw_out)


def detect_entrypoints(index: dict, top_n: int = 50) -> dict:
    nodes = index.get("nodes") or []
    in_adj, out_adj = _normalize_adj(index)

    ranked: List[dict] = []
    for n in nodes:
        path = n.get("path") or ""
        if not path:
            continue

        base = os.path.basename(path)
        low_path = path.lower()
        lang = n.get("lang") or "other"
        parts = [p for p in low_path.split("/") if p]
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
        if "/page/" in low_path and base.startswith("index."):
            score += 35
            reasons.append("page-index")
        if path.endswith("map.json"):
            score += 30
            reasons.append("route-map")
        if "/service/" in low_path:
            score += 12
            reasons.append("service-layer")
        if "/components/" in low_path or "/widget/" in low_path:
            score += 8
            reasons.append("ui-leaf-candidate")

        if lang == "python":
            if base in PYTHON_ENTRY_BASENAMES:
                score += 55
                reasons.append(f"python-entry:{base}")
            if base == "__init__.py":
                if any(seg in PYTHON_ENTRY_SEGMENTS for seg in parts[:-1]):
                    score += 22
                    reasons.append("python-package-entry")
                if any(seg in PYTHON_CORE_SEGMENTS for seg in parts[:-1]):
                    score += 14
                    reasons.append("python-core-package")
            if any(seg in PYTHON_ENTRY_SEGMENTS for seg in parts[:-1]):
                score += 12
                reasons.append("python-service-area")
            if any(seg in PYTHON_CORE_SEGMENTS for seg in parts[:-1]):
                score += 8
                reasons.append("python-core-area")
            if low_path.count("/") <= 2:
                score += 6
                reasons.append("python-shallow")

        in_degree = len(in_adj.get(path, []))
        out_degree = len(out_adj.get(path, []))
        score += min(24, in_degree * 2)
        score += min(16, out_degree * 2)

        if lang == "python":
            score += min(12, in_degree)
            if base == "__init__.py" and in_degree >= 8:
                score += 10
                reasons.append("python-hub")

        if score > 0:
            ranked.append(
                {
                    "path": path,
                    "lang": lang,
                    "score": score,
                    "reasons": reasons,
                    "in_degree": in_degree,
                    "out_degree": out_degree,
                }
            )

    ranked.sort(key=lambda x: (-x["score"], -x["in_degree"], x["path"]))
    return {
        "meta": index.get("meta") or {},
        "entrypoints": ranked[:top_n],
    }
