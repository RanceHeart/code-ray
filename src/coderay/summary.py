from __future__ import annotations

from typing import Dict, List


def summarize_index(index: dict, top_n: int = 20) -> dict:
    nodes = index.get("nodes") or []
    edges = index.get("edges") or []
    adj = index.get("adj") or {}
    out_adj = adj.get("out") or {}
    in_adj = adj.get("in") or {}

    node_map = {n.get("path"): n for n in nodes if n.get("path")}

    ranked: List[dict] = []
    for path, n in node_map.items():
        out_deg = len(out_adj.get(path, []))
        in_deg = len(in_adj.get(path, []))
        ranked.append(
            {
                "path": path,
                "lang": n.get("lang"),
                "lines": n.get("lines"),
                "size": n.get("size"),
                "in_degree": in_deg,
                "out_degree": out_deg,
                "degree": in_deg + out_deg,
            }
        )

    ranked.sort(key=lambda x: (-x["degree"], -int(x.get("lines") or 0), x["path"]))

    return {
        "meta": index.get("meta") or {},
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "external_deps": len(index.get("external_deps") or []),
        },
        "top_files": ranked[:top_n],
        "external_deps": index.get("external_deps") or [],
    }
