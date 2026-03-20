from __future__ import annotations

import os
import re
from typing import List, Optional, Set

from .context import build_context_pack
from .entrypoints import detect_entrypoints
from .tokens import estimate_tokens_from_chars

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _file_text(root: str, rel_path: str, limit: int = 120000) -> str:
    abs_path = os.path.join(root, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _tokenize_goal(goal: str) -> List[str]:
    tokens = [w.lower() for w in WORD_RE.findall(goal)]
    stop = {
        "the", "and", "for", "with", "from", "into", "that", "this", "how", "what", "when", "where",
        "trace", "understand", "investigate", "debug", "fix", "flow", "data", "code", "repo", "project",
    }
    return [t for t in tokens if t not in stop]


def _score_files(index: dict, goal: str, limit: int = 25) -> List[dict]:
    nodes = index.get("nodes") or []
    root = (index.get("meta") or {}).get("project_root", "")
    words = _tokenize_goal(goal)
    adj = index.get("adj") or {}
    in_adj = adj.get("in") or {}
    out_adj = adj.get("out") or {}

    scored: List[dict] = []
    for n in nodes:
        path = n.get("path") or ""
        if not path:
            continue
        lang = n.get("lang") or "other"

        score = 0
        why: List[str] = []
        low_path = path.lower()

        for w in words:
            if w in low_path:
                score += 18
                why.append(f"path-match:{w}")

        if path.endswith("map.json"):
            for w in words:
                if w in low_path:
                    score += 12
                    why.append("route-map-match")
                    break

        text = ""
        if score > 0 or any(k in low_path for k in ("index", "app", "main", "service", "page", "route", "map", "widget", "component")):
            text = _file_text(root, path, limit=30000).lower()
            for w in words[:8]:
                hits = text.count(w)
                if hits:
                    score += min(20, hits * 2)
                    why.append(f"content-match:{w}x{hits}")

        if "/page/" in low_path:
            score += 6
            why.append("page")
        if "/service/" in low_path:
            score += 5
            why.append("service")
        if "/widget/" in low_path or "/components/" in low_path:
            score += 3
            why.append("ui")

        score += min(10, len(in_adj.get(path, [])))
        score += min(10, len(out_adj.get(path, [])))

        if score > 0:
            scored.append(
                {
                    "path": path,
                    "lang": lang,
                    "score": score,
                    "why": why[:6],
                    "in_degree": len(in_adj.get(path, [])),
                    "out_degree": len(out_adj.get(path, [])),
                }
            )

    scored.sort(key=lambda x: (-x["score"], x["path"]))
    return scored[:limit]


def build_goal_pack(
    index: dict,
    goal: str,
    hops: int = 1,
    page_size: int = 12,
    page: int = 1,
    max_chars_per_file: int = 16000,
    max_total_chars: Optional[int] = None,
) -> dict:
    entrypoints = detect_entrypoints(index, top_n=20).get("entrypoints", [])
    candidates = _score_files(index, goal, limit=12)
    chosen = candidates[:3]

    packs: List[dict] = []
    seen: Set[str] = set()
    used = 0
    truncated_files = 0

    for item in chosen:
        remaining = None if max_total_chars is None else max(0, max_total_chars - used)
        if remaining == 0:
            break

        p = build_context_pack(
            index=index,
            file=item["path"],
            hops=hops,
            direction="both",
            page=page,
            page_size=page_size,
            max_chars_per_file=max_chars_per_file,
            max_total_chars=remaining,
        )
        for f in p.get("files", []):
            if f["path"] in seen:
                continue
            seen.add(f["path"])
            packs.append(f)
            used += len(f.get("content") or "")
            if f.get("truncated"):
                truncated_files += 1
            if max_total_chars is not None and used >= max_total_chars:
                break
        if max_total_chars is not None and used >= max_total_chars:
            break

    packs.sort(key=lambda f: (f.get("distance", 999), f.get("size", 0), f.get("path", "")))

    return {
        "goal": goal,
        "entry_candidates": entrypoints[:10],
        "selected_roots": chosen,
        "meta": {
            "returned_files": len(packs),
            "returned_chars": used,
            "estimated_tokens": estimate_tokens_from_chars(used),
            "truncated_files": truncated_files,
            "page": page,
            "page_size": page_size,
            "hops": hops,
        },
        "files": packs,
    }
