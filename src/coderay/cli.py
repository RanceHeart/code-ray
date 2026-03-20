from __future__ import annotations

import argparse
import json
import os
from typing import List, Optional

from .analyzer import build_index
from .context import build_context_pack
from .entrypoints import detect_entrypoints
from .pack import build_goal_pack
from .scanner import scan_project
from .summary import summarize_index
from .symbols import find_symbol
from .tokens import chars_from_token_budget


def _cmd_xray(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.path)
    files = scan_project(
        root,
        exclude=args.exclude,
        max_files=args.max_files,
        max_bytes=args.max_bytes,
    )
    index = build_index(root, files)

    out_path = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(f"[coderay] wrote index: {out_path} ({index['meta']['files']} files)")
    return 0


def _load_index(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cmd_ctx(args: argparse.Namespace) -> int:
    index = _load_index(args.index)
    pack = build_context_pack(
        index=index,
        file=args.file,
        hops=args.hops,
        direction=args.direction,
        page=args.page,
        page_size=args.page_size,
        max_chars_per_file=args.max_chars_per_file,
        max_total_chars=args.max_total_chars,
        budget_tokens=args.budget_tokens,
    )
    print(json.dumps(pack, ensure_ascii=False, indent=2))
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    index = _load_index(args.index)
    print(json.dumps(summarize_index(index, top_n=args.top_n), ensure_ascii=False, indent=2))
    return 0


def _cmd_entrypoints(args: argparse.Namespace) -> int:
    index = _load_index(args.index)
    print(json.dumps(detect_entrypoints(index, top_n=args.top_n), ensure_ascii=False, indent=2))
    return 0


def _cmd_symbol(args: argparse.Namespace) -> int:
    index = _load_index(args.index)
    print(json.dumps(find_symbol(index, name=args.name, top_n=args.top_n), ensure_ascii=False, indent=2))
    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    index = _load_index(args.index)
    pack = build_goal_pack(
        index=index,
        goal=args.goal,
        hops=args.hops,
        page_size=args.page_size,
        page=args.page,
        max_chars_per_file=args.max_chars_per_file,
        max_total_chars=args.max_total_chars or chars_from_token_budget(args.budget_tokens),
    )
    print(json.dumps(pack, ensure_ascii=False, indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="coderay", description="code-ray: xray index + AI context packs")
    sub = p.add_subparsers(dest="cmd", required=True)

    px = sub.add_parser("xray", help="scan project and write an index JSON")
    px.add_argument("path", nargs="?", default=".")
    px.add_argument("--out", default=".coderay/index.json")
    px.add_argument("--exclude", nargs="*", default=None)
    px.add_argument("--max-files", type=int, default=None)
    px.add_argument("--max-bytes", type=int, default=300_000)
    px.add_argument("--quiet", action="store_true")
    px.set_defaults(fn=_cmd_xray)

    pc = sub.add_parser("ctx", help="fetch a context pack by file neighborhood")
    pc.add_argument("--index", required=True)
    pc.add_argument("--file", required=True, help="project-relative path")
    pc.add_argument("--hops", type=int, default=1)
    pc.add_argument("--direction", choices=["both", "out", "in"], default="both")
    pc.add_argument("--page", type=int, default=1)
    pc.add_argument("--page-size", type=int, default=20)
    pc.add_argument("--max-chars-per-file", type=int, default=20_000)
    pc.add_argument("--max-total-chars", type=int, default=None)
    pc.add_argument("--budget-tokens", type=int, default=None)
    pc.set_defaults(fn=_cmd_ctx)

    ps = sub.add_parser("summary", help="show top dependency hotspots from an index")
    ps.add_argument("--index", required=True)
    ps.add_argument("--top-n", type=int, default=20)
    ps.set_defaults(fn=_cmd_summary)

    pe = sub.add_parser("entrypoints", help="detect likely entrypoints and route maps")
    pe.add_argument("--index", required=True)
    pe.add_argument("--top-n", type=int, default=20)
    pe.set_defaults(fn=_cmd_entrypoints)

    pys = sub.add_parser("symbol", help="find likely files for a symbol/class/function name")
    pys.add_argument("--index", required=True)
    pys.add_argument("--name", required=True)
    pys.add_argument("--top-n", type=int, default=20)
    pys.set_defaults(fn=_cmd_symbol)

    pp = sub.add_parser("pack", help="build a task-oriented context pack from a goal string")
    pp.add_argument("--index", required=True)
    pp.add_argument("--goal", required=True)
    pp.add_argument("--hops", type=int, default=1)
    pp.add_argument("--page", type=int, default=1)
    pp.add_argument("--page-size", type=int, default=12)
    pp.add_argument("--max-chars-per-file", type=int, default=16_000)
    pp.add_argument("--max-total-chars", type=int, default=None)
    pp.add_argument("--budget-tokens", type=int, default=None)
    pp.set_defaults(fn=_cmd_pack)

    args = p.parse_args(argv)
    return args.fn(args)
