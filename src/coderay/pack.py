from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Set, Tuple

from .context import build_context_pack
from .entrypoints import detect_entrypoints
from .tokens import estimate_tokens_from_chars

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

DEFAULT_GOAL_WORDS = {
    "trace", "understand", "investigate", "debug", "fix", "flow", "data", "code", "repo", "project",
    "repository", "system", "feature", "logic",
}

PYTHON_SERVICE_HINTS = {
    "python", "backend", "server", "service", "model", "models", "view", "views",
    "controller", "controllers", "api", "worker", "task", "job", "jobs", "cli",
}

FRONTEND_HINTS = {
    "frontend", "ui", "react", "tsx", "typescript", "javascript", "component", "components", "page",
}


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
    }
    return [t for t in tokens if t not in stop and t not in DEFAULT_GOAL_WORDS]


def _goal_profile(goal: str) -> str:
    tokens = set(_tokenize_goal(goal))
    if tokens & FRONTEND_HINTS:
        return "frontend"
    if tokens & PYTHON_SERVICE_HINTS:
        return "backend"
    return "generic"


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


def _score_files(index: dict, goal: str, limit: int = 25) -> List[dict]:
    nodes = index.get("nodes") or []
    root = (index.get("meta") or {}).get("project_root", "")
    words = _tokenize_goal(goal)
    profile = _goal_profile(goal)
    in_adj, out_adj = _normalize_adj(index)

    scored: List[dict] = []
    for n in nodes:
        path = n.get("path") or ""
        if not path:
            continue
        lang = n.get("lang") or "other"
        base = os.path.basename(path).lower()
        low_path = path.lower()
        parts = [p for p in low_path.split("/") if p]
        in_degree = len(in_adj.get(path, []))
        out_degree = len(out_adj.get(path, []))

        score = 0
        why: List[str] = []

        for w in words:
            if w in low_path:
                score += 18
                why.append(f"path-match:{w}")

        should_read = (
            score > 0
            or any(k in low_path for k in ("index", "app", "main", "service", "page", "route", "map", "widget", "component", "model", "view"))
            or (lang == "python" and base == "__init__.py")
        )
        if should_read:
            text = _file_text(root, path, limit=30000).lower()
            for w in words[:8]:
                hits = text.count(w)
                if hits:
                    score += min(24, hits * 3)
                    why.append(f"content-match:{w}x{hits}")

        if path.endswith("map.json"):
            score += 16
            why.append("route-map")

        if "/page/" in low_path:
            score += 8
            why.append("page")
        if "/service/" in low_path:
            score += 7
            why.append("service")
        if "/widget/" in low_path or "/components/" in low_path:
            score += 3
            why.append("ui")

        if lang == "python":
            if base in {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "__main__.py"}:
                score += 30
                why.append("python-entry")
            if base == "__init__.py":
                score += 18
                why.append("python-package")
            if any(seg in {"model", "models", "view", "views", "service", "api", "controller", "controllers"} for seg in parts[:-1]):
                score += 14
                why.append("python-domain")
            score += min(24, in_degree * 2)
            score += min(14, out_degree)
        elif lang in {"typescript", "javascript"}:
            if base.startswith("index."):
                score += 10
                why.append("index-file")
            score += min(16, in_degree * 2)
            score += min(12, out_degree)
        else:
            score += min(10, in_degree)
            score += min(8, out_degree)

        if profile == "backend":
            if lang == "python":
                score += 18
                why.append("goal-prefers-backend")
            elif lang in {"typescript", "javascript"} and "/components/" in low_path:
                score -= 12
        elif profile == "frontend":
            if lang in {"typescript", "javascript"}:
                score += 12
                why.append("goal-prefers-frontend")
            elif lang == "python":
                score -= 8
        else:
            if lang == "python" and any(seg in {"model", "models", "view", "views", "service"} for seg in parts[:-1]):
                score += 8
                why.append("generic-python-bias")

        if score > 0:
            scored.append(
                {
                    "path": path,
                    "lang": lang,
                    "score": score,
                    "why": why[:8],
                    "in_degree": in_degree,
                    "out_degree": out_degree,
                }
            )

    scored.sort(key=lambda x: (-x["score"], -x["in_degree"], x["path"]))
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
    candidates = _score_files(index, goal, limit=16)

    chosen: List[dict] = []
    seen_roots: Set[str] = set()
    for item in candidates:
        path = item["path"]
        if path in seen_roots:
            continue
        chosen.append(item)
        seen_roots.add(path)
        if len(chosen) >= 4:
            break

    packs: List[dict] = []
    seen: Set[str] = set()
    used = 0
    truncated_files = 0

    for idx, item in enumerate(chosen):
        remaining = None if max_total_chars is None else max(0, max_total_chars - used)
        if remaining == 0:
            break

        remaining_roots = max(1, len(chosen) - idx)
        per_root_budget = None
        if remaining is not None:
            per_root_budget = max(2500, remaining // remaining_roots)

        p = build_context_pack(
            index=index,
            file=item["path"],
            hops=hops,
            direction="both",
            page=page,
            page_size=page_size,
            max_chars_per_file=min(max_chars_per_file, per_root_budget or max_chars_per_file),
            max_total_chars=per_root_budget,
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

    packs.sort(key=lambda f: (f.get("distance", 999), -(f.get("size") or 0), f.get("path", "")))

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
