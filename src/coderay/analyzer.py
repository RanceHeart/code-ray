from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from .project_hints import load_project_hints
from .scanner import FileInfo
from .parser import TreeSitterParser, TS_AVAILABLE, ParsedFile

PY_IMPORT = re.compile(
    r"^\s*(?:import\s+(?P<plain>[\w][\w.]*)|from\s+(?P<from>\.*[\w][\w.]*|\.+)\s+import\s+.+)",
    re.MULTILINE,
)

JS_IMPORT_FROM = re.compile(
    r"(?:^|\b)(?:import|export)\b.+?\bfrom\s*['\"](?P<path>[^'\"]+)['\"]",
    re.MULTILINE,
)
JS_REQUIRE = re.compile(r"\brequire\s*\(\s*['\"](?P<path>[^'\"]+)['\"]\s*\)", re.MULTILINE)
JS_DYNAMIC_IMPORT = re.compile(r"\bimport\s*\(\s*['\"](?P<path>[^'\"]+)['\"]\s*\)", re.MULTILINE)

SWIFT_IMPORT = re.compile(r"^\s*(?:import|@import)\s+(?P<module>[\w]+)", re.MULTILINE)
JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?P<pkg>[\w.]+);", re.MULTILINE)

# Tree-sitter parser instance (lazy init)
_TS_PARSER: Optional[TreeSitterParser] = None

def _get_ts_parser() -> TreeSitterParser:
    global _TS_PARSER
    if _TS_PARSER is None:
        _TS_PARSER = TreeSitterParser()
    return _TS_PARSER


def _to_posix(p: str) -> str:
    return p.replace(os.sep, "/")


def _read_text(abs_path: str, max_chars: int = 200_000) -> str:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except OSError:
        return ""


def _rel(root: str, abs_path: str) -> str:
    return _to_posix(os.path.relpath(abs_path, root))


def _resolve_py_module(project_root: str, src_abs: str, mod: str) -> Tuple[Optional[str], bool]:
    leading = len(mod) - len(mod.lstrip("."))
    mod_clean = mod.lstrip(".")

    if leading > 0:
        base_dir = os.path.dirname(src_abs)
        for _ in range(leading - 1):
            base_dir = os.path.dirname(base_dir)
        search_root = base_dir
    else:
        search_root = project_root

    parts = mod_clean.split(".") if mod_clean else []
    base = os.path.join(search_root, *parts) if parts else ""

    if base and os.path.isfile(base + ".py"):
        return _rel(project_root, base + ".py"), False

    if base:
        init = os.path.join(base, "__init__.py")
        if os.path.isfile(init):
            return _rel(project_root, init), False

    if leading == 0 and mod_clean:
        return None, True
    return None, False


def _try_file_candidates(project_root: str, target: str) -> Optional[str]:
    target = os.path.normpath(target)
    if os.path.isfile(target):
        return _rel(project_root, target)

    exts = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    for ext in exts:
        if os.path.isfile(target + ext):
            return _rel(project_root, target + ext)

    for ext in exts:
        idx = os.path.join(target, "index" + ext)
        if os.path.isfile(idx):
            return _rel(project_root, idx)

    return None


def _resolve_js_relative(project_root: str, src_abs: str, ref: str) -> Optional[str]:
    src_dir = os.path.dirname(src_abs)
    ref_clean = ref.split("?")[0].split("#")[0]
    target = os.path.normpath(os.path.join(src_dir, ref_clean))
    return _try_file_candidates(project_root, target)


def _resolve_ts_alias(project_root: str, ref: str, hints: dict) -> Optional[str]:
    ref_clean = ref.split("?")[0].split("#")[0]
    paths = hints.get("ts_paths") or {}
    base_url = hints.get("base_url") or project_root

    if ref_clean.startswith("@/"):
        target = os.path.join(base_url, ref_clean[2:])
        resolved = _try_file_candidates(project_root, target)
        if resolved:
            return resolved

    for alias, targets in paths.items():
        if not targets:
            continue
        if alias.endswith("/*"):
            prefix = alias[:-2]
            if ref_clean.startswith(prefix):
                suffix = ref_clean[len(prefix):].lstrip("/")
                for raw_t in targets:
                    t_prefix = raw_t[:-2] if raw_t.endswith("/*") else raw_t
                    target = os.path.join(base_url, t_prefix, suffix)
                    resolved = _try_file_candidates(project_root, target)
                    if resolved:
                        return resolved
        elif alias == ref_clean:
            for raw_t in targets:
                target = os.path.join(base_url, raw_t)
                resolved = _try_file_candidates(project_root, target)
                if resolved:
                    return resolved

    return None


def _parse_py_imports(text: str) -> List[str]:
    out: List[str] = []
    for m in PY_IMPORT.finditer(text):
        ref = m.group("plain") or m.group("from")
        if ref:
            out.append(ref.strip())
    return out


def _parse_js_imports(text: str) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []

    def add(p: str) -> None:
        if p and p not in seen:
            seen.add(p)
            out.append(p)

    for m in JS_IMPORT_FROM.finditer(text):
        add(m.group("path") or "")
    for m in JS_REQUIRE.finditer(text):
        add(m.group("path") or "")
    for m in JS_DYNAMIC_IMPORT.finditer(text):
        add(m.group("path") or "")

    return out


def _parse_swift_imports(text: str) -> List[str]:
    """Parse Swift import statements: `import Foo` and `@import Foo`."""
    seen: Set[str] = set()
    out: List[str] = []
    for m in SWIFT_IMPORT.finditer(text):
        mod = m.group("module")
        if mod and mod not in seen:
            seen.add(mod)
            out.append(mod)
    return out


def _resolve_java_import(
    project_root: str,
    src_abs: str,
    ref: str,
    known: Set[str],
    java_pkg_map: Dict[str, str],
) -> Tuple[Optional[str], bool]:
    """Resolve a Java import to a local file via java_pkg_map (O(1)).

    Returns (resolved_rel_path, is_external).
    """
    # 1. Relative import: ".Foo" from "com.douban.frodo.foo" -> "com.douban.frodo.foo.Foo"
    if ref.startswith("."):
        src_pkg = None
        try:
            with open(src_abs, "r", encoding="utf-8", errors="replace") as f:
                header = f.read(500)
            m = _PKG_LINE_RE.search(header)
            if m:
                src_pkg = m.group(1)
        except OSError:
            pass
        if src_pkg:
            full_pkg = src_pkg + ref
            if full_pkg in java_pkg_map:
                return java_pkg_map[full_pkg], False
            alt = src_pkg + "." + ref.lstrip(".")
            if alt in java_pkg_map:
                return java_pkg_map[alt], False

    # 2. Absolute import: look up in pkg map
    if ref in java_pkg_map:
        return java_pkg_map[ref], False

    # 3. No match -> external (third-party or JDK)
    return None, True


def _build_swift_module_map(known: Set[str]) -> Dict[str, str]:
    """Build a fast basename → path lookup for Swift module resolution."""
    mod_map: Dict[str, List[str]] = {}
    for p in known:
        if p.endswith(".swift"):
            basename = os.path.splitext(os.path.basename(p))[0]
            mod_map.setdefault(basename, []).append(p)
    # Prefer shorter paths (more likely to be a direct module root)
    return {k: sorted(vs, key=lambda p: p.count("/"))[0] for k, vs in mod_map.items()}


_PKG_LINE_RE = re.compile(r"^\s*package\s+([\w.]+);", re.MULTILINE)


def _build_java_pkg_map(files: List[FileInfo], abs_by_rel: Dict[str, str]) -> Dict[str, str]:
    """Build a fast fully-qualified-package → file path map for Java.

    Reads only the first 500 chars of each .java file to extract its package decl.
    Handles Android project path conventions where files live under e.g.
    "app/src/main/java/com/douban/frodo/rexxar/" but package is "com.douban.frodo.rexxar".
    """
    pkg_map: Dict[str, str] = {}

    # Strip common Android/Java source path prefixes
    SOURCE_PREFIXES = (
        "app/src/main/java/",
        "app/src/test/java/",
        "app/src/androidTest/java/",
        "src/main/java/",
        "src/test/java/",
        "src/androidTest/java/",
    )

    for fi in files:
        if fi.lang != "java":
            continue
        abs_path = abs_by_rel.get(fi.path)
        if not abs_path:
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                header = f.read(500)
            m = _PKG_LINE_RE.search(header)
            if not m:
                continue
            pkg = m.group(1)
            # Strip Android source prefix to get relative-to-source-root path
            rel = fi.path
            for prefix in SOURCE_PREFIXES:
                if rel.startswith(prefix):
                    rel = rel[len(prefix):]
                    break
            # Build FQCN: "com.douban.frodo.rexxar.toolbox.RexxarRemoteService"
            fname = rel.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if fname.endswith(".java"):
                class_name = fname[:-5]
                if class_name:
                    fqcn = f"{pkg}.{class_name}"
                    if fqcn not in pkg_map:
                        pkg_map[fqcn] = fi.path
        except OSError:
            continue
    return pkg_map




def _resolve_swift_import(
    project_root: str, ref: str, known: Set[str], module_map: Dict[str, str]
) -> Tuple[Optional[str], bool]:
    """Resolve a Swift import module name to a local file path via known set.

    Returns (resolved_path, is_external).
    - is_external=True means it's likely a pod/framework, not a local file.
    """
    # Fast path: check pre-built module map
    if ref in module_map:
        return module_map[ref], False
    return None, True


def build_index(project_root: str, files: List[FileInfo]) -> dict:
    project_root = os.path.abspath(project_root)
    hints = load_project_hints(project_root)

    abs_by_rel: Dict[str, str] = {fi.path: os.path.join(project_root, fi.path) for fi in files}
    known: Set[str] = set(abs_by_rel.keys())

    # Assign an integer ID to each file path for compact edge references
    path_to_id: Dict[str, int] = {}
    for i, fi in enumerate(files):
        path_to_id[fi.path] = i

    nodes = [
        {
            "id": path_to_id[fi.path],
            "path": fi.path,
            "lang": fi.lang,
            "lines": fi.lines,
            "size": fi.size,
        }
        for fi in files
    ]

    edges_set: Set[Tuple[str, str]] = set()
    external: Set[str] = set()
    structure: Dict[str, dict] = {}  # path -> {imports, funcs, calls, classes}

    # Pre-build Swift module map for fast import resolution
    swift_module_map: Dict[str, str] = _build_swift_module_map(known)

    # Pre-build Java package map for fast import resolution
    java_pkg_map: Dict[str, str] = _build_java_pkg_map(files, abs_by_rel)

    # Use tree-sitter if available for supported languages
    ts_parser = _get_ts_parser() if TS_AVAILABLE else None

    for fi in files:
        if fi.lang not in {"python", "javascript", "typescript", "java", "swift"}:
            continue

        src_rel = fi.path
        src_abs = abs_by_rel[src_rel]

        if ts_parser:
            # Use tree-sitter for structure extraction, but keep import resolution
            # conservative for Python where regex import parsing is currently more
            # reliable than our AST import walker.
            parsed: ParsedFile = ts_parser.parse(src_abs, fi.lang)
            if parsed.func_defs or parsed.func_calls or parsed.classes or parsed.imports:
                # Prefer regex-derived imports for Python to avoid malformed module names.
                if fi.lang == "python":
                    import_refs = _parse_py_imports(_read_text(src_abs))
                else:
                    import_refs = [imp.path for imp in parsed.imports]

                structure[src_rel] = {
                    "imports": import_refs,
                    "funcs": [(f.name, f.kind, f.receiver) for f in parsed.func_defs],
                    "calls": [(c.name, c.recv) for c in parsed.func_calls],
                    "classes": parsed.classes,
                }

                # Resolve imports to edges
                for ref in import_refs:
                    if not ref:
                        continue
                    resolved: Optional[str] = None
                    is_ext = False

                    if fi.lang == "python":
                        resolved, is_ext = _resolve_py_module(project_root, src_abs, ref)
                    elif fi.lang in ("javascript", "typescript"):
                        if ref.startswith("./") or ref.startswith("../"):
                            resolved = _resolve_js_relative(project_root, src_abs, ref)
                        else:
                            resolved = _resolve_ts_alias(project_root, ref, hints)
                    elif fi.lang == "java":
                        resolved, is_ext = _resolve_java_import(project_root, src_abs, ref, known, java_pkg_map)
                    elif fi.lang == "swift":
                        resolved, is_ext = _resolve_swift_import(project_root, ref, known, swift_module_map)

                    if resolved and resolved in known:
                        edges_set.add((src_rel, resolved))
                    elif is_ext:
                        pkg = ref.split("/")[0] if not ref.startswith("@") else "/".join(ref.split("/")[:2])
                        if pkg:
                            external.add(pkg)
                continue

        # Fallback to regex parsing for backward compatibility
        text = _read_text(src_abs)
        if not text:
            continue

        if fi.lang == "python":
            for ref in _parse_py_imports(text):
                resolved, is_ext = _resolve_py_module(project_root, src_abs, ref)
                if resolved and resolved in known:
                    edges_set.add((src_rel, resolved))
                elif is_ext:
                    external.add(ref.lstrip(".").split(".")[0])
        elif fi.lang == "swift":
            for ref in _parse_swift_imports(text):
                resolved, is_ext = _resolve_swift_import(project_root, ref, known, swift_module_map)
                if resolved and resolved in known:
                    edges_set.add((src_rel, resolved))
                elif is_ext:
                    external.add(ref)
        elif fi.lang == "java":
            for m in JAVA_IMPORT_RE.finditer(text):
                ref = m.group("pkg")
                if not ref:
                    continue
                resolved, is_ext = _resolve_java_import(project_root, src_abs, ref, known, java_pkg_map)
                if resolved and resolved in known:
                    edges_set.add((src_rel, resolved))
                elif is_ext:
                    external.add(ref)
        else:
            for ref in _parse_js_imports(text):
                resolved: Optional[str] = None
                if ref.startswith("./") or ref.startswith("../"):
                    resolved = _resolve_js_relative(project_root, src_abs, ref)
                else:
                    resolved = _resolve_ts_alias(project_root, ref, hints)

                if resolved and resolved in known:
                    edges_set.add((src_rel, resolved))
                elif not resolved:
                    pkg = ref.split("/")[0] if not ref.startswith("@") else "/".join(ref.split("/")[:2])
                    if pkg and not ref.startswith("@/"):
                        external.add(pkg)

    edges = [{"src": path_to_id[s], "tgt": path_to_id[t]} for (s, t) in sorted(edges_set)]

    out_adj: Dict[str, List[str]] = {}
    in_adj: Dict[str, List[str]] = {}
    for e in edges:
        out_adj.setdefault(e["src"], []).append(e["tgt"])
        in_adj.setdefault(e["tgt"], []).append(e["src"])

    for k in list(out_adj.keys()):
        out_adj[k] = sorted(set(out_adj[k]))
    for k in list(in_adj.keys()):
        in_adj[k] = sorted(set(in_adj[k]))

    meta = {
        "project_root": project_root,
        "files": len(files),
        "total_lines": sum(fi.lines for fi in files),
        "languages": _lang_counts(files),
        "hints": {
            "base_url": hints.get("base_url"),
            "package_name": hints.get("package_name"),
            "ts_path_aliases": sorted((hints.get("ts_paths") or {}).keys()),
        },
    }

    return {
        "meta": meta,
        "nodes": nodes,
        "edges": edges,
        "adj": {"out": out_adj, "in": in_adj},
        "external_deps": sorted(x for x in external if x),
        "structure": structure,  # AI-relevant: funcs, calls, classes per file
    }


def _lang_counts(files: List[FileInfo]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for fi in files:
        d[fi.lang] = d.get(fi.lang, 0) + 1
    return dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))
