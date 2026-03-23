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

PYTHON_HINTS = {
    "python", "backend", "server", "service", "model", "models", "view", "views",
    "controller", "controllers", "api", "worker", "task", "job", "jobs", "cli",
}

FRONTEND_HINTS = {
    "frontend", "ui", "react", "tsx", "typescript", "javascript", "component", "components", "page",
}

ANDROID_HINTS = {
    "android", "activity", "fragment", "application", "manifest", "gradle", "app", "rexxar",
}

IOS_HINTS = {
    "ios", "swift", "xcode", "appdelegate", "scenedelegate", "uikit", "viewcontroller", "podfile", "rexxar",
}


ARCH_FILES = {
    "package.json", "tsconfig.json", "pyproject.toml", "requirements.txt", "setup.py",
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties",
    "podfile", "podfile.lock", "package.swift", "cartfile", "cartfile.resolved", "project.pbxproj",
    "androidmanifest.xml",
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
    stop = {"the", "and", "for", "with", "from", "into", "that", "this", "how", "what", "when", "where"}
    return [t for t in tokens if t not in stop and t not in DEFAULT_GOAL_WORDS]


def _goal_profile(goal: str) -> str:
    tokens = set(_tokenize_goal(goal))
    if tokens & IOS_HINTS:
        return "ios"
    if tokens & ANDROID_HINTS:
        return "android"
    if tokens & FRONTEND_HINTS:
        return "frontend"
    if tokens & PYTHON_HINTS:
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


def _node_map(index: dict) -> Dict[str, dict]:
    return {n.get("path"): n for n in (index.get("nodes") or []) if n.get("path")}


def _path_parts(path: str) -> List[str]:
    return [p for p in path.lower().split("/") if p]


def _common_prefix_len(a: str, b: str) -> int:
    ap = _path_parts(a)
    bp = _path_parts(b)
    n = 0
    for x, y in zip(ap, bp):
        if x != y:
            break
        n += 1
    return n


def _target_key(path: str) -> str:
    parts = _path_parts(path)
    if not parts:
        return "root"
    lowered = "/".join(parts)
    for marker in ("example", "examples", "demo", "tests", "test"):
        if marker in parts:
            idx = parts.index(marker)
            return "/".join(parts[: min(len(parts), idx + 2)])
    if ".xcodeproj" in lowered:
        idx = next((i for i, p in enumerate(parts) if p.endswith(".xcodeproj")), None)
        if idx is not None:
            return "/".join(parts[: idx + 1])
    if "src" in parts:
        idx = parts.index("src")
        return "/".join(parts[: idx]) or "root"
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _kind_for_path(path: str, lang: str) -> str:
    low = path.lower()
    base = os.path.basename(low)
    if base in ARCH_FILES or low.endswith("androidmanifest.xml"):
        return "config"
    if base in {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "__main__.py", "main.m"}:
        return "entry"
    if base.endswith("appdelegate.swift") or base.endswith("appdelegate.m") or base.endswith("scenedelegate.swift"):
        return "entry"
    if base.endswith("application.java") or base.endswith("application.kt"):
        return "entry"
    if "route" in base or "router" in low or "urldispatch" in low or "urlroutes" in low or "rexxar" in low:
        return "router"
    if any(tok in low for tok in ("controller", "activity", "fragment", "viewcontroller")):
        return "surface"
    if any(tok in low for tok in ("service", "/api/", "manager", "handler")):
        return "logic"
    if any(tok in low for tok in ("model", "entity", "schema", "store")):
        return "domain"
    return "other"


def _detect_project_profile(index: dict) -> dict:
    nodes = index.get("nodes") or []
    langs: Dict[str, int] = {}
    for n in nodes:
        lang = n.get("lang") or "other"
        langs[lang] = langs.get(lang, 0) + 1

    paths = [n.get("path") or "" for n in nodes]
    path_set = {p.lower() for p in paths}
    tags: List[str] = []

    if any(p.endswith("package.json") for p in path_set):
        tags.append("node")
    if any(p.endswith("androidmanifest.xml") or p.endswith("build.gradle") or p.endswith("settings.gradle") for p in path_set):
        tags.append("android")
    if any(p.endswith("project.pbxproj") or p.endswith("podfile") or p.endswith("package.swift") for p in path_set):
        tags.append("ios")
    if langs.get("python", 0) >= 10 or any(p.endswith("pyproject.toml") for p in path_set):
        tags.append("python")
    if langs.get("typescript", 0) + langs.get("javascript", 0) >= 20:
        tags.append("frontend")
    if len({p.split("/")[0] for p in paths if p}) >= 4:
        tags.append("multimodule")

    return {
        "languages": langs,
        "tags": tags,
    }


def _score_candidate(index: dict, path: str, lang: str, in_adj: Dict[str, List[str]], out_adj: Dict[str, List[str]], goal: str) -> dict:
    root = (index.get("meta") or {}).get("project_root", "")
    low_path = path.lower()
    base = os.path.basename(low_path)
    parts = _path_parts(path)
    profile = _goal_profile(goal)
    words = _tokenize_goal(goal)
    in_degree = len(in_adj.get(path, []))
    out_degree = len(out_adj.get(path, []))
    kind = _kind_for_path(path, lang)
    score = 0
    why: List[str] = []

    for w in words:
        if w in low_path:
            score += 18
            why.append(f"path-match:{w}")

    should_read = (
        score > 0
        or kind != "other"
        or any(k in low_path for k in ("index", "app", "main", "delegate", "controller", "activity", "fragment", "model", "service", "router"))
    )
    text = _file_text(root, path, limit=25000) if should_read else ""
    low_text = text.lower()
    for w in words[:8]:
        hits = low_text.count(w)
        if hits:
            score += min(24, hits * 3)
            why.append(f"content-match:{w}x{hits}")

    if lang == "python":
        if base in {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "__main__.py"}:
            score += 40
            why.append("python-entry")
        if base == "__init__.py":
            score += 10
            why.append("python-package")
    elif lang in {"javascript", "typescript"}:
        if base in {"package.json", "tsconfig.json"}:
            score += 40
            why.append("frontend-config")
        if base.startswith("index."):
            score += 14
            why.append("index-file")
    elif lang == "java" or low_path.endswith(".kt"):
        if low_path.endswith("androidmanifest.xml"):
            score += 90
            why.append("android-manifest")
        if base in {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties"}:
            score += 42
            why.append("build-config")
        if base.endswith("application.java") or base.endswith("application.kt"):
            score += 56
            why.append("application-class")
        if base.endswith("activity.java") or base.endswith("activity.kt"):
            score += 36
            why.append("activity-class")
        if base.endswith("fragment.java") or base.endswith("fragment.kt"):
            score += 28
            why.append("fragment-class")
        if "rexxar" in low_text or "uridispatcher" in low_text or "routemanager" in low_text:
            score += 18
            why.append("navigation-or-rexxar")
    elif lang == "swift":
        if base in {"project.pbxproj", "podfile", "podfile.lock", "package.swift", "cartfile", "cartfile.resolved"}:
            score += 48
            why.append("ios-build-config")
        if base.endswith("appdelegate.swift"):
            score += 62
            why.append("ios-app-entry")
        if base.endswith("scenedelegate.swift"):
            score += 40
            why.append("ios-scene-entry")
        if base.endswith("viewcontroller.swift"):
            score += 28
            why.append("ios-view-controller")
        if "rexxar" in low_text or "urlroutes" in low_text or "rxr" in low_text:
            score += 20
            why.append("rexxar-or-routing")
    elif lang == "objective-c":
        if base in {"project.pbxproj", "podfile", "podfile.lock"}:
            score += 48
            why.append("ios-build-config")
        if base == "main.m" or base.endswith("appdelegate.m") or base.endswith("appdelegate.h"):
            score += 64
            why.append("ios-app-entry")
        if base.endswith("viewcontroller.m") or base.endswith("viewcontroller.h"):
            score += 26
            why.append("ios-view-controller")
        if "rexxar" in low_text or "urlroutes" in low_text or "rxr" in low_text:
            score += 20
            why.append("rexxar-or-routing")

    if kind == "config":
        score += 20
        why.append("architecture-file")
    elif kind == "entry":
        score += 16
        why.append("entry-surface")
    elif kind == "router":
        score += 14
        why.append("router")
    elif kind == "surface":
        score += 10
        why.append("surface")
    elif kind == "logic":
        score += 8
        why.append("logic")
    elif kind == "domain":
        score += 8
        why.append("domain")

    score += min(24, in_degree * 2)
    score += min(16, out_degree * 2)

    if profile == "backend":
        if lang == "python":
            score += 20
            why.append("goal-prefers-backend")
        elif lang in {"javascript", "typescript"} and "/components/" in low_path:
            score -= 10
    elif profile == "frontend":
        if lang in {"javascript", "typescript"}:
            score += 14
            why.append("goal-prefers-frontend")
        elif lang == "python":
            score -= 8
    elif profile == "android":
        if low_path.endswith("androidmanifest.xml") or base in {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties"} or lang == "java" or low_path.endswith(".kt"):
            score += 24
            why.append("goal-prefers-android")
        if lang == "python":
            score -= 12
    elif profile == "ios":
        if lang in {"swift", "objective-c"} or base in {"project.pbxproj", "podfile", "podfile.lock", "package.swift"}:
            score += 24
            why.append("goal-prefers-ios")
        if lang == "python":
            score -= 14
    else:
        if kind in {"config", "entry", "router"}:
            score += 12
            why.append("generic-architecture-bias")

    if "/src/test/" in low_path or "/src/androidtest/" in low_path or "/tests/" in low_path:
        score -= 42
        why.append("test-penalty")
    if low_path.startswith("scripts/") or low_path.startswith("dsymtool/"):
        score -= 30
        why.append("tooling-penalty")
    if "proguard" in low_path:
        score -= 30
        why.append("build-noise-penalty")
    if "/example/" in low_path or "/examples/" in low_path or "/demo/" in low_path:
        score -= 14
        why.append("example-penalty")

    return {
        "path": path,
        "lang": lang,
        "score": score,
        "why": why[:8],
        "kind": kind,
        "target": _target_key(path),
        "in_degree": in_degree,
        "out_degree": out_degree,
    }


def _rank_candidates(index: dict, goal: str, limit: int = 40) -> List[dict]:
    in_adj, out_adj = _normalize_adj(index)
    ranked: List[dict] = []
    for n in index.get("nodes") or []:
        path = n.get("path") or ""
        if not path:
            continue
        item = _score_candidate(index, path, n.get("lang") or "other", in_adj, out_adj, goal)
        if item["score"] > 0:
            ranked.append(item)
    ranked.sort(key=lambda x: (-x["score"], -x["in_degree"], x["path"]))
    return ranked[:limit]


def _select_diverse_roots(candidates: List[dict], limit: int = 4) -> List[dict]:
    chosen: List[dict] = []
    seen_paths: Set[str] = set()
    seen_targets: Dict[str, int] = {}
    seen_kinds: Set[str] = set()

    preferred_kinds = ["config", "entry", "router", "surface", "logic", "domain"]
    for kind in preferred_kinds:
        for item in candidates:
            if item["kind"] != kind or item["path"] in seen_paths:
                continue
            if seen_targets.get(item["target"], 0) >= 2:
                continue
            chosen.append(item)
            seen_paths.add(item["path"])
            seen_targets[item["target"]] = seen_targets.get(item["target"], 0) + 1
            seen_kinds.add(item["kind"])
            break
        if len(chosen) >= limit:
            return chosen

    for item in candidates:
        if item["path"] in seen_paths:
            continue
        target_hits = seen_targets.get(item["target"], 0)
        if target_hits >= 2:
            continue
        if item["kind"] in seen_kinds and len(chosen) < max(2, limit - 1):
            continue
        chosen.append(item)
        seen_paths.add(item["path"])
        seen_targets[item["target"]] = target_hits + 1
        seen_kinds.add(item["kind"])
        if len(chosen) >= limit:
            return chosen

    for item in candidates:
        if item["path"] in seen_paths:
            continue
        chosen.append(item)
        seen_paths.add(item["path"])
        if len(chosen) >= limit:
            break
    return chosen


def _structure_map(index: dict) -> Dict[str, dict]:
    return index.get("structure") or {}


def _focal_symbols(index: dict, file: str) -> Set[str]:
    structure = _structure_map(index)
    info = structure.get(file) or {}
    out: Set[str] = set()
    for name, _kind, _recv in info.get("funcs") or []:
        if name:
            out.add(name)
    for name in info.get("classes") or []:
        if name:
            out.add(name)
    return out


def _chain_candidates(index: dict, file: str, hops: int = 2) -> List[Tuple[str, int, int]]:
    in_adj, out_adj = _normalize_adj(index)
    structure = _structure_map(index)
    node_map = _node_map(index)
    focal_syms = _focal_symbols(index, file)

    scored: Dict[str, Tuple[int, int]] = {}

    def push(path: str, distance: int, score: int):
        if path == file or path not in node_map:
            return
        prev = scored.get(path)
        if prev is None or distance < prev[0] or (distance == prev[0] and score > prev[1]):
            scored[path] = (distance, score)

    for path in out_adj.get(file, []):
        push(path, 1, 100)
    for path in in_adj.get(file, []):
        push(path, 1, 90)

    frontier = list(out_adj.get(file, [])) + list(in_adj.get(file, []))
    seen = set(frontier)
    for _ in range(max(0, hops - 1)):
        new_frontier: List[str] = []
        for cur in frontier:
            for nxt in out_adj.get(cur, []) + in_adj.get(cur, []):
                if nxt == file or nxt in seen:
                    continue
                seen.add(nxt)
                push(nxt, 2, 55)
                new_frontier.append(nxt)
        frontier = new_frontier

    if focal_syms:
        for path, info in structure.items():
            if path == file or path not in node_map:
                continue
            score = 0
            calls = {name for name, _recv in (info.get("calls") or []) if name}
            defs = {name for name, _kind, _recv in (info.get("funcs") or []) if name}
            classes = set(info.get("classes") or [])
            imports = set(info.get("imports") or [])

            overlap = focal_syms & calls
            if overlap:
                score += min(60, 18 * len(overlap))
            overlap = focal_syms & defs
            if overlap:
                score += min(50, 14 * len(overlap))
            overlap = focal_syms & classes
            if overlap:
                score += min(50, 18 * len(overlap))

            focal_stem = os.path.splitext(os.path.basename(file))[0]
            if focal_stem and any(focal_stem in imp for imp in imports):
                score += 24

            if score > 0:
                push(path, 2, score)

    ranked = [(p, d, s) for p, (d, s) in scored.items()]
    ranked.sort(key=lambda t: (t[1], -t[2], t[0]))
    return ranked


def _collect_files(index: dict, paths: List[str], max_chars_per_file: int, max_total_chars: Optional[int]) -> Tuple[List[dict], int, int]:
    node_map = _node_map(index)
    root = (index.get("meta") or {}).get("project_root", "")
    files_out: List[dict] = []
    used = 0
    truncated = 0
    seen: Set[str] = set()

    for path in paths:
        if path in seen or path not in node_map:
            continue
        seen.add(path)
        raw = _file_text(root, path, limit=max_chars_per_file)
        content = raw
        was_truncated = False
        if len(raw) >= max_chars_per_file:
            was_truncated = True
        if max_total_chars is not None and used + len(content) > max_total_chars:
            remain = max(0, max_total_chars - used)
            content = content[:remain] + ("\n\n/* ...TRUNCATED (pack limit)... */\n" if remain > 0 else "")
            was_truncated = True
        used += len(content)
        n = node_map[path]
        files_out.append({
            "path": path,
            "distance": None,
            "lang": n.get("lang"),
            "lines": n.get("lines"),
            "size": n.get("size"),
            "truncated": was_truncated,
            "content": content,
        })
        if was_truncated:
            truncated += 1
        if max_total_chars is not None and used >= max_total_chars:
            break
    return files_out, used, truncated


def _layered_file_relations(
    index: dict,
    file: str,
    ordered: List[Tuple[str, int]],
    bootstrap_roots: List[dict],
    chain_scores: Dict[str, int],
) -> dict:
    in_adj, out_adj = _normalize_adj(index)
    node_map = _node_map(index)
    structure = _structure_map(index)
    focal_syms = _focal_symbols(index, file)
    bootstrap_paths = {item.get("path") for item in bootstrap_roots if item.get("path") and item.get("path") != file}

    direct_deps: List[dict] = []
    reverse_deps: List[dict] = []
    symbol_related: List[dict] = []
    entry_chain: List[dict] = []
    siblings: List[dict] = []

    file_dir = os.path.dirname(file)
    used: Set[str] = set()

    for path, dist in ordered:
        if path == file or path not in node_map or path in used:
            continue
        item = {
            "path": path,
            "distance": dist,
            "kind": _kind_for_path(path, (node_map[path].get("lang") or "other")),
            "lang": node_map[path].get("lang"),
            "chain_score": chain_scores.get(path, 0),
        }
        if path in out_adj.get(file, []):
            direct_deps.append(item)
            used.add(path)
            continue
        if path in in_adj.get(file, []):
            reverse_deps.append(item)
            used.add(path)
            continue

    for path, dist in ordered:
        if path == file or path not in node_map or path in used:
            continue
        item = {
            "path": path,
            "distance": dist,
            "kind": _kind_for_path(path, (node_map[path].get("lang") or "other")),
            "lang": node_map[path].get("lang"),
            "chain_score": chain_scores.get(path, 0),
        }
        info = structure.get(path) or {}
        calls = {name for name, _recv in (info.get("calls") or []) if name}
        defs = {name for name, _kind, _recv in (info.get("funcs") or []) if name}
        classes = set(info.get("classes") or [])
        if focal_syms & (calls | defs | classes):
            symbol_related.append(item)
            used.add(path)
            continue
        if path in bootstrap_paths or item["kind"] in {"config", "entry", "router"}:
            entry_chain.append(item)
            used.add(path)
            continue
        if os.path.dirname(path) == file_dir or _common_prefix_len(file, path) >= 3:
            siblings.append(item)
            used.add(path)
            continue

    return {
        "focal": [{
            "path": file,
            "distance": 0,
            "kind": _kind_for_path(file, (node_map[file].get("lang") or "other")),
            "lang": node_map[file].get("lang"),
            "chain_score": 0,
        }],
        "direct_deps": direct_deps[:8],
        "reverse_deps": reverse_deps[:8],
        "symbol_related": symbol_related[:8],
        "entry_chain": entry_chain[:8],
        "siblings": siblings[:8],
    }


def build_bootstrap_pack(
    index: dict,
    goal: str = "understand this repository",
    limit_roots: int = 6,
    max_chars_per_file: int = 12000,
    max_total_chars: Optional[int] = None,
) -> dict:
    profile = _detect_project_profile(index)
    entrypoints = detect_entrypoints(index, top_n=20).get("entrypoints", [])
    candidates = _rank_candidates(index, goal=goal, limit=50)
    roots = _select_diverse_roots(candidates, limit=limit_roots)
    root_paths = [r["path"] for r in roots]
    files, used, truncated = _collect_files(index, root_paths, max_chars_per_file, max_total_chars)
    return {
        "goal": goal,
        "project_profile": profile,
        "entry_candidates": entrypoints[:10],
        "selected_roots": roots,
        "meta": {
            "returned_files": len(files),
            "returned_chars": used,
            "estimated_tokens": estimate_tokens_from_chars(used),
            "truncated_files": truncated,
        },
        "files": files,
    }


def build_file_pack(
    index: dict,
    file: str,
    goal: Optional[str] = None,
    hops: int = 1,
    page_size: int = 12,
    max_chars_per_file: int = 12000,
    max_total_chars: Optional[int] = None,
    mode: str = "standard",
) -> dict:
    in_adj, out_adj = _normalize_adj(index)
    node_map = _node_map(index)
    if file not in node_map:
        raise KeyError(f"file not in index: {file}")

    profile = _detect_project_profile(index)
    ctx = build_context_pack(
        index=index,
        file=file,
        hops=hops,
        direction="both",
        page=1,
        page_size=page_size,
        max_chars_per_file=max_chars_per_file,
        max_total_chars=max_total_chars,
    )

    best_dist: Dict[str, int] = {}
    chain_scores: Dict[str, int] = {}

    def push(path: str, dist: int, score: int = 0):
        if path == file or path not in node_map:
            return
        if path not in best_dist or dist < best_dist[path]:
            best_dist[path] = dist
        if score > chain_scores.get(path, 0):
            chain_scores[path] = score

    for f in ctx.get("files", []):
        dist = f.get("distance")
        push(f["path"], 0 if dist is None else dist, 0)

    directory = os.path.dirname(file)
    kind = _kind_for_path(file, (node_map[file].get("lang") or "other"))
    for path in node_map:
        if path == file:
            continue
        score = 0
        if os.path.dirname(path) == directory:
            score += 10
        score += _common_prefix_len(file, path) * 3
        if _kind_for_path(path, node_map[path].get("lang") or "other") == kind:
            score += 8
        if path in out_adj.get(file, []):
            score += 18
        if path in in_adj.get(file, []):
            score += 16
        if score > 0:
            push(path, 10 - min(9, score // 4), score)

    if mode == "full-chain":
        for path, dist, score in _chain_candidates(index, file, hops=max(2, hops + 1)):
            push(path, dist, score)

    bootstrap = build_bootstrap_pack(
        index=index,
        goal=goal or f"understand context around {file}",
        limit_roots=4,
        max_chars_per_file=max_chars_per_file,
        max_total_chars=None,
    )
    for item in bootstrap.get("selected_roots", []):
        if item["path"] != file:
            push(item["path"], 2, 40 if mode == "full-chain" else 0)

    ordered = sorted(
        best_dist.items(),
        key=lambda kv: (
            kv[1],
            -(chain_scores.get(kv[0], 0)),
            -int((node_map.get(kv[0]) or {}).get("size") or 0),
            kv[0],
        ),
    )
    ordered_paths = [file] + [p for p, _ in ordered if p != file]
    per_file_chars = max_chars_per_file
    if max_total_chars is not None and ordered_paths:
        divisor = 8 if mode == "full-chain" else 6
        per_file_chars = min(max_chars_per_file, max(1500, max_total_chars // min(divisor, len(ordered_paths))))
    files, used, truncated = _collect_files(index, ordered_paths, per_file_chars, max_total_chars)
    best_dist[file] = 0
    for f in files:
        if f["path"] in best_dist:
            f["distance"] = best_dist[f["path"]]

    related = [
        {
            "path": p,
            "distance": d,
            "kind": _kind_for_path(p, (node_map[p].get("lang") or "other")),
            "lang": node_map[p].get("lang"),
            "chain_score": chain_scores.get(p, 0),
        }
        for p, d in ordered[:16]
    ]
    layers = _layered_file_relations(index, file, ordered, bootstrap.get("selected_roots", [])[:4], chain_scores)

    return {
        "file": file,
        "goal": goal,
        "mode": mode,
        "project_profile": profile,
        "bootstrap_roots": bootstrap.get("selected_roots", [])[:4],
        "related_files": related,
        "layers": layers,
        "meta": {
            "returned_files": len(files),
            "returned_chars": used,
            "estimated_tokens": estimate_tokens_from_chars(used),
            "truncated_files": truncated,
            "hops": hops,
        },
        "files": files,
    }


def build_goal_pack(
    index: dict,
    goal: str,
    hops: int = 1,
    page_size: int = 12,
    page: int = 1,
    max_chars_per_file: int = 16000,
    max_total_chars: Optional[int] = None,
) -> dict:
    del page  # reserved for future paging; keep CLI compatibility
    bootstrap = build_bootstrap_pack(
        index=index,
        goal=goal,
        limit_roots=4,
        max_chars_per_file=max_chars_per_file,
        max_total_chars=max_total_chars,
    )
    selected = bootstrap.get("selected_roots", [])
    packs: List[dict] = []
    seen: Set[str] = set()
    used = 0
    truncated_files = 0

    for idx, item in enumerate(selected):
        remaining = None if max_total_chars is None else max(0, max_total_chars - used)
        if remaining == 0:
            break
        remaining_roots = max(1, len(selected) - idx)
        per_root_budget = None if remaining is None else max(2500, remaining // remaining_roots)
        p = build_context_pack(
            index=index,
            file=item["path"],
            hops=hops,
            direction="both",
            page=1,
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

    packs.sort(key=lambda f: ((f.get("distance") if f.get("distance") is not None else 999), -(f.get("size") or 0), f.get("path", "")))
    return {
        "goal": goal,
        "project_profile": bootstrap.get("project_profile"),
        "entry_candidates": bootstrap.get("entry_candidates", [])[:10],
        "selected_roots": selected,
        "meta": {
            "returned_files": len(packs),
            "returned_chars": used,
            "estimated_tokens": estimate_tokens_from_chars(used),
            "truncated_files": truncated_files,
            "page_size": page_size,
            "hops": hops,
        },
        "files": packs,
    }
