from __future__ import annotations

import os
import re
from typing import List

DEF_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+(?P<fn>[A-Za-z_][A-Za-z0-9_]*)|"
    r"class\s+(?P<class>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?:export\s+)?const\s+(?P<const>[A-Za-z_][A-Za-z0-9_]*)(?:\s*:[^=]+)?\s*=",
    re.MULTILINE,
)
PY_DEF_RE = re.compile(
    r"^\s*def\s+(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*\(|^\s*class\s+(?P<class>[A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
SWIFT_DEF_RE = re.compile(
    r"(?:^\s*|(?:public|private|internal|fileprivate|open)\s+)"
    r"(?:class|struct|enum|protocol|extension|func)\s+"
    r"(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
JAVA_DEF_RE = re.compile(
    r"(?:^\s*|(?:public|private|protected|static|final|abstract|synchronized)\s+)*"
    r"(?:class|interface|enum)\s+(?P<class>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?:^\s*|(?:public|private|protected|static|final|abstract|synchronized)\s+)*"
    r"(?:void|int|long|double|float|boolean|char|byte|short|String|List|Map|Set|[A-Z][A-Za-z0-9_]*)\s+"
    r"(?P<method>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)


def _read_text(abs_path: str, limit: int = 120000) -> str:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def find_symbol(index: dict, name: str, top_n: int = 20) -> dict:
    root = (index.get("meta") or {}).get("project_root", "")
    nodes = index.get("nodes") or []
    needle = name.strip()
    low = needle.lower()
    hits: List[dict] = []

    def _lang_from_path(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".py":
            return "python"
        if ext in {".js", ".jsx", ".mjs", ".cjs"}:
            return "javascript"
        if ext in {".ts", ".tsx", ".mts"}:
            return "typescript"
        if ext == ".swift":
            return "swift"
        if ext == ".java":
            return "java"
        return "other"

    for n in nodes:
        path = n.get("path") or ""
        lang = n.get("lang") or _lang_from_path(path)
        if lang not in {"python", "javascript", "typescript", "swift", "java"}:
            continue

        text = _read_text(os.path.join(root, path))
        if not text:
            continue

        score = 0
        kinds: List[str] = []
        if low in path.lower():
            score += 20
            kinds.append("path")

        if lang == "python":
            regex = PY_DEF_RE
        elif lang == "swift":
            regex = SWIFT_DEF_RE
        elif lang == "java":
            regex = JAVA_DEF_RE
        else:
            regex = DEF_RE
        for m in regex.finditer(text):
            gd = m.groupdict()
            found = gd.get("fn") or gd.get("class") or gd.get("const") or gd.get("symbol") or gd.get("method")
            if found == needle:
                score += 100
                kinds.append("definition")
                break
            if found and found.lower() == low:
                score += 80
                kinds.append("definition-casefold")
                break

        content_hits = text.lower().count(low)
        if content_hits:
            score += min(25, content_hits)
            kinds.append(f"content:{content_hits}")

        if score > 0:
            hits.append(
                {
                    "path": path,
                    "lang": lang,
                    "score": score,
                    "kinds": kinds,
                    "lines": n.get("lines"),
                    "size": n.get("size"),
                }
            )

    hits.sort(key=lambda x: (-x["score"], x["path"]))
    return {"query": name, "results": hits[:top_n]}
