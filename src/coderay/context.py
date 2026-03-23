from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from .tokens import chars_from_token_budget, estimate_tokens_from_chars


def _to_posix(p: str) -> str:
    return p.replace(os.sep, "/")


def _read_file(abs_path: str, max_chars: int, head_tail: bool = True) -> str:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except OSError:
        return ""

    if len(data) <= max_chars:
        return data

    if not head_tail or max_chars < 2000:
        return data[:max_chars] + "\n\n/* ...TRUNCATED... */\n"

    half = max_chars // 2
    return data[:half] + "\n\n/* ...TRUNCATED (middle)... */\n\n" + data[-half:]


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

    return convert(raw_out), convert(raw_in)


def _bfs_neighborhood(
    start: str,
    out_adj: Dict[str, List[str]],
    in_adj: Dict[str, List[str]],
    hops: int,
    direction: str = "both",
) -> List[Tuple[str, int]]:
    start = _to_posix(start)
    if hops < 0:
        hops = 0

    dist: Dict[str, int] = {start: 0}
    q: List[str] = [start]

    while q:
        cur = q.pop(0)
        d = dist[cur]
        if d >= hops:
            continue

        neigh: List[str] = []
        if direction in ("both", "out"):
            neigh.extend(out_adj.get(cur, []))
        if direction in ("both", "in"):
            neigh.extend(in_adj.get(cur, []))

        for nxt in neigh:
            if nxt not in dist:
                dist[nxt] = d + 1
                q.append(nxt)

    items = list(dist.items())
    items.sort(key=lambda kv: (kv[1], kv[0]))
    return items


def build_context_pack(
    index: dict,
    file: str,
    hops: int = 1,
    direction: str = "both",
    page: int = 1,
    page_size: int = 20,
    max_chars_per_file: int = 20_000,
    max_total_chars: Optional[int] = None,
    budget_tokens: Optional[int] = None,
) -> dict:
    meta = index.get("meta", {})
    root = meta.get("project_root", "")

    if budget_tokens is not None and max_total_chars is None:
        max_total_chars = chars_from_token_budget(budget_tokens)

    out_adj, in_adj = _normalize_adj(index)

    nodes = index.get("nodes") or []
    node_map = {n.get("path"): n for n in nodes if n.get("path")}
    neighborhood = _bfs_neighborhood(file, out_adj, in_adj, hops=hops, direction=direction)

    scored: List[Tuple[str, int, int]] = []
    for path, dist in neighborhood:
        size = int((node_map.get(path) or {}).get("size") or 0)
        scored.append((path, dist, size))
    scored.sort(key=lambda t: (t[1], -t[2], t[0]))

    if page_size <= 0:
        page_size = 20
    if page <= 0:
        page = 1

    total_files = len(scored)
    total_pages = (total_files + page_size - 1) // page_size if total_files else 0
    start = (page - 1) * page_size
    end = start + page_size
    page_items = scored[start:end]

    files_out: List[dict] = []
    used = 0
    truncated_files = 0

    for path, dist, _size in page_items:
        abs_path = os.path.join(root, path)
        raw_content = _read_file(abs_path, max_chars=max_chars_per_file, head_tail=True)
        content = raw_content

        if max_total_chars is not None:
            if used >= max_total_chars:
                break
            if used + len(content) > max_total_chars:
                remain = max_total_chars - used
                content = content[: max(0, remain)] + "\n\n/* ...TRUNCATED (pack limit)... */\n"
                truncated_files += 1

        used += len(content)
        n = node_map.get(path) or {}
        files_out.append(
            {
                "path": path,
                "distance": dist,
                "lang": n.get("lang"),
                "lines": n.get("lines"),
                "size": n.get("size"),
                "truncated": content != raw_content,
                "content": content,
            }
        )

    return {
        "query": {
            "file": _to_posix(file),
            "hops": hops,
            "direction": direction,
            "page": page,
            "page_size": page_size,
            "max_chars_per_file": max_chars_per_file,
            "max_total_chars": max_total_chars,
            "budget_tokens": budget_tokens,
        },
        "meta": {
            "project_root": root,
            "total_files_in_neighborhood": total_files,
            "total_pages": total_pages,
            "returned_files": len(files_out),
            "returned_chars": used,
            "estimated_tokens": estimate_tokens_from_chars(used),
            "truncated_files": truncated_files,
            "next_page": page + 1 if total_pages and page < total_pages else None,
        },
        "files": files_out,
    }
