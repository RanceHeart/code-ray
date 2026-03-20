from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional


def load_project_hints(project_root: str) -> dict:
    project_root = os.path.abspath(project_root)
    tsconfig_path = os.path.join(project_root, "tsconfig.json")
    package_json_path = os.path.join(project_root, "package.json")

    base_url = project_root
    paths: Dict[str, List[str]] = {}
    package_name: Optional[str] = None

    if os.path.isfile(tsconfig_path):
        try:
            with open(tsconfig_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
            # tolerate trailing commas in tsconfig
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            data = json.loads(raw)
            compiler = (data or {}).get("compilerOptions") or {}
            ts_base = compiler.get("baseUrl")
            if isinstance(ts_base, str) and ts_base.strip():
                base_url = os.path.abspath(os.path.join(project_root, ts_base))
            if isinstance(compiler.get("paths"), dict):
                for k, v in compiler["paths"].items():
                    if isinstance(v, list):
                        paths[str(k)] = [str(x) for x in v]
        except Exception:
            pass

    if os.path.isfile(package_json_path):
        try:
            with open(package_json_path, "r", encoding="utf-8", errors="replace") as f:
                pkg = json.load(f)
            if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
                package_name = pkg["name"]
        except Exception:
            pass

    return {
        "project_root": project_root,
        "base_url": base_url,
        "ts_paths": paths,
        "package_name": package_name,
    }
