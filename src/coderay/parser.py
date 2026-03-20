"""
Tree-sitter based parser for code-ray.

Extracts:
- Import/require statements (dependencies)
- Function/method definitions
- Function/method calls
- Class definitions
- Type annotations (AI struct analysis)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# Import tree-sitter and language modules
try:
    from tree_sitter import Language, Parser
    TS_AVAILABLE = True
except ImportError:
    TS_AVAILABLE = False

from .scanner import FileInfo


@dataclass
class FuncDef:
    name: str
    kind: str  # "function", "method", "class_method"
    receiver: Optional[str] = None  # for methods, the receiver type


@dataclass
class FuncCall:
    name: str
    recv: Optional[str] = None  # for method calls


@dataclass
class ImportInfo:
    path: str
    is_dynamic: bool = False


@dataclass
class ParsedFile:
    path: str
    lang: str
    imports: List[ImportInfo] = field(default_factory=list)
    func_defs: List[FuncDef] = field(default_factory=list)
    func_calls: List[FuncCall] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)  # just names for now
    types: List[str] = field(default_factory=list)  # type annotations


class TreeSitterParser:
    """Unified tree-sitter parser for multiple languages."""

    # Map our lang names to tree-sitter language names
    LANG_MAP: Dict[str, str] = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "java": "java",
        "swift": "swift",
    }

    def __init__(self):
        self._parsers: Dict[str, Parser] = {}
        self._initialized = False

    def _init(self):
        if self._initialized or not TS_AVAILABLE:
            return

        # Build language paths - tree-sitter-language packages install as tree_sitter_<lang>
        import importlib.util

        for our_lang, ts_name in self.LANG_MAP.items():
            try:
                if our_lang == "typescript":
                    # tree-sitter-typescript exposes language_typescript/language_tsx
                    from tree_sitter_typescript import language_typescript
                    capsule = language_typescript()
                    lang = Language(capsule)
                    parser = Parser(lang)
                    self._parsers[our_lang] = parser
                elif our_lang == "swift":
                    from tree_sitter_swift import language as sw_lang
                    capsule = sw_lang()
                    lang = Language(capsule)
                    parser = Parser(lang)
                    self._parsers[our_lang] = parser
                elif our_lang == "java":
                    from tree_sitter_java import language as java_lang
                    capsule = java_lang()
                    lang = Language(capsule)
                    parser = Parser(lang)
                    self._parsers[our_lang] = parser
                else:
                    # Standard pattern: tree_sitter_<lang>
                    module_name = f"tree_sitter_{ts_name}"
                    mod = importlib.import_module(module_name)
                    lang_fn = getattr(mod, "language", None)
                    if lang_fn:
                        capsule = lang_fn()
                        lang = Language(capsule)
                        parser = Parser(lang)
                        self._parsers[our_lang] = parser
            except Exception as e:
                print(f"Warning: failed to load {our_lang}: {e}")
                pass

        self._initialized = True

    def get_parser(self, lang: str) -> Optional[Parser]:
        self._init()
        return self._parsers.get(lang)

    def parse(self, abs_path: str, lang: str) -> ParsedFile:
        """Parse a file and extract structural information."""
        parser = self.get_parser(lang)
        if not parser:
            return ParsedFile(path=abs_path, lang=lang)

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return ParsedFile(path=abs_path, lang=lang)

        result = ParsedFile(path=abs_path, lang=lang)

        try:
            tree = parser.parse(bytes(text, "utf8"))
            root = tree.root_node

            if lang == "python":
                self._parse_python(root, text, result)
            elif lang in ("javascript", "typescript"):
                self._parse_js_ts(root, text, result)
            elif lang == "java":
                self._parse_java(root, text, result)
            elif lang == "swift":
                self._parse_swift(root, text, result)
        except Exception:
            pass

        return result

    # -------------------------------------------------------------------------
    # Python parsing
    # -------------------------------------------------------------------------

    def _parse_python(self, node, text: str, result: ParsedFile):
        """Extract imports, definitions, calls from Python AST."""
        for child in node.children:
            ctype = child.type

            if ctype == "import_statement":
                result.imports.extend(self._extract_py_imports(child, text))
            elif ctype == "import_from_statement":
                result.imports.extend(self._extract_py_import_from(child, text))
            elif ctype == "function_definition":
                name = self._get_text(child, text, "identifier")
                if name:
                    result.func_defs.append(FuncDef(name=name, kind="function"))
            elif ctype == "class_definition":
                name = self._get_text(child, text, "identifier")
                if name:
                    result.classes.append(name)
                    result.func_defs.append(FuncDef(name=name, kind="class"))
                    # Parse methods inside class
                    for m in child.children:
                        if m.type == "function_definition":
                            mname = self._get_text(m, text, "identifier")
                            if mname:
                                result.func_defs.append(
                                    FuncDef(name=mname, kind="method", receiver=name)
                                )
            elif ctype == "expression_statement":
                # Could be a call
                self._extract_py_calls(child, text, result)

    def _extract_py_imports(self, node, text: str) -> List[ImportInfo]:
        """Extract from 'import foo.bar' or 'import foo, bar' statement."""
        imports = []
        for child in node.children:
            if child.type == "dotted_name":
                # dotted_name: "import os" or "import json.re" — collect full path
                imports.append(ImportInfo(path=self._get_node_text(child, text)))
            elif child.type == "identifier":
                # e.g. "import os, re" — individual identifiers
                imports.append(ImportInfo(path=self._get_node_text(child, text)))
            # skip ',' and 'import' keyword
        return imports

    def _extract_py_import_from(self, node, text: str) -> List[ImportInfo]:
        """Extract from 'from foo.bar import x' statement.

        Returns the source module path (relative or absolute).
        Note: imported names (after 'import') are NOT included — they are
        symbols, not module references for edge-building.
        """
        imports = []
        seen_import_kw = False

        for child in node.children:
            if child.type == "import":
                seen_import_kw = True
            elif child.type == "relative_import":
                # e.g. "." or "..foo.bar" — extract the module path
                path_parts = []
                for sub in child.children:
                    if sub.type == "import_prefix":
                        # import_prefix contains dots (.), collect them
                        path_parts.append(sub.text.decode())
                    elif sub.type == "identifier":
                        path_parts.append(self._get_node_text(sub, text))
                    elif sub.type == "dotted_name":
                        # dotted_name inside relative_import: collect identifiers with dots
                        parts = []
                        for innermost in sub.children:
                            if innermost.type == "identifier":
                                parts.append(self._get_node_text(innermost, text))
                            elif innermost.type == ".":
                                parts.append(".")
                        path_parts.append("".join(parts))
                imports.append(ImportInfo(path="".join(path_parts)))
            elif child.type == "dotted_name" and not seen_import_kw:
                # Absolute import: "from json import ..." — dotted_name is the module
                imports.append(ImportInfo(path=self._get_node_text(child, text)))
            # NOTE: we intentionally skip dotted_name/identifier AFTER 'import'
            # keyword — those are the imported symbols, not module references

        return imports

    def _extract_py_calls(self, node, text: str, result: ParsedFile):
        """Extract function calls from an expression statement."""
        for child in node.children:
            if child.type == "call":
                func = child.children[0] if child.children else None
                if func:
                    if func.type == "identifier":
                        result.func_calls.append(
                            FuncCall(name=self._get_node_text(func, text))
                        )
                    elif func.type == "attribute":
                        # method call: obj.method
                        attr = func.children[-1] if func.children else None
                        recv = func.children[0] if len(func.children) > 1 else None
                        if attr and attr.type == "identifier":
                            name = self._get_node_text(attr, text)
                            result.func_calls.append(
                                FuncCall(name=name, recv=self._get_node_text(recv, text) if recv else None)
                            )

    # -------------------------------------------------------------------------
    # JavaScript/TypeScript parsing
    # -------------------------------------------------------------------------

    def _parse_js_ts(self, node, text: str, result: ParsedFile):
        """Extract imports, exports, definitions, calls from JS/TS."""
        for child in node.children:
            stype = child.type

            if stype in ("import_statement", "import_clause", "named_imports"):
                result.imports.extend(self._extract_js_import(child, text))
            elif stype == "export_statement":
                # Check if it's export { ... } or export default
                for sub in child.children:
                    if sub.type == "named_export":
                        self._extract_named_export(sub, text, result)
            elif stype in ("function_declaration", "function"):
                name = self._get_js_name(child, text)
                if name:
                    result.func_defs.append(FuncDef(name=name, kind="function"))
            elif stype in ("class_declaration", "class"):
                name = self._get_js_name(child, text)
                if name:
                    result.classes.append(name)
                    result.func_defs.append(FuncDef(name=name, kind="class"))
                    # Parse class methods
                    for m in child.children:
                        if m.type in ("method_definition", "property"):
                            mname = self._get_js_name(m, text)
                            if mname and mname != "constructor":
                                result.func_defs.append(
                                    FuncDef(name=mname, kind="method", receiver=name)
                                )
            elif stype == "lexical_declaration":
                # const/let/var with possible arrow functions
                for sub in child.children:
                    if sub.type == "variable_declarator":
                        vname = self._get_js_name(sub, text)
                        # Check if it's a function assignment
                        for vsub in sub.children:
                            if vsub.type in ("arrow_function", "function"):
                                fname = vname or self._get_js_name(vsub, text)
                                if fname:
                                    result.func_defs.append(
                                        FuncDef(name=fname, kind="function")
                                    )
            elif stype == "call_expression":
                self._extract_js_call(child, text, result)

    def _extract_js_import(self, node, text: str) -> List[ImportInfo]:
        imports = []
        # Look for string_literal (the import path)
        for child in node.children:
            if child.type == "string":
                path = child.text.decode()[1:-1]  # Remove quotes
                imports.append(ImportInfo(path=path))
        return imports

    def _extract_named_export(self, node, text: str, result: ParsedFile):
        # export { foo, bar }
        for child in node.children:
            if child.type == "identifier":
                name = self._get_node_text(child, text)
                result.func_defs.append(FuncDef(name=name, kind="export"))

    def _get_js_name(self, node, text: str) -> Optional[str]:
        for child in node.children:
            if child.type == "identifier":
                return self._get_node_text(child, text)
            elif child.type == "property_identifier":
                return self._get_node_text(child, text)
            elif child.type == "string":
                return self._get_node_text(child, text)[1:-1]
        return None

    def _extract_js_call(self, node, text: str, result: ParsedFile):
        """Extract function call information."""
        # call_expression: function arguments
        children = node.children
        if not children:
            return

        func = children[0]
        if func.type == "identifier":
            result.func_calls.append(FuncCall(name=self._get_node_text(func, text)))
        elif func.type == "member_expression":
            # obj.method
            parts = []
            for c in func.children:
                if c.type in ("identifier", "property_identifier"):
                    parts.append(self._get_node_text(c, text))
            if len(parts) >= 2:
                result.func_calls.append(FuncCall(name=parts[-1], recv=parts[0]))
            elif len(parts) == 1:
                result.func_calls.append(FuncCall(name=parts[0]))
        elif func.type == "import":
            # dynamic import()
            for c in children:
                if c.type == "string":
                    path = c.text.decode()[1:-1]
                    result.imports.append(ImportInfo(path=path, is_dynamic=True))

    # -------------------------------------------------------------------------
    # Java parsing
    # -------------------------------------------------------------------------

    def _parse_java(self, node, text: str, result: ParsedFile):
        """Extract imports, class/method definitions from Java."""
        for child in node.children:
            ctype = child.type

            if ctype == "import_declaration":
                self._extract_java_import(child, text, result)
            elif ctype in ("class_declaration", "interface_declaration", "enum_declaration"):
                name = self._get_java_name(child, text)
                if name:
                    result.classes.append(name)
                    kind = "class" if "class" in ctype else "interface" if "interface" in ctype else "enum"
                    result.func_defs.append(FuncDef(name=name, kind=kind))
                    # Parse members
                    for m in child.children:
                        if m.type == "method_declaration":
                            mname = self._get_java_name(m, text)
                            if mname:
                                result.func_defs.append(
                                    FuncDef(name=mname, kind="method", receiver=name)
                                )
                        elif m.type == "constructor_declaration":
                            mname = self._get_java_name(m, text)
                            if mname:
                                result.func_defs.append(
                                    FuncDef(name=mname, kind="constructor", receiver=name)
                                )
            elif ctype == "method_declaration":
                # Top-level method
                name = self._get_java_name(child, text)
                if name:
                    result.func_defs.append(FuncDef(name=name, kind="method"))
            elif ctype == "method_invocation":
                self._extract_java_call(child, text, result)

    def _extract_java_import(self, node, text: str, result: ParsedFile):
        for child in node.children:
            if child.type == "scoped_identifier":
                path = self._get_node_text(child, text)
                result.imports.append(ImportInfo(path=path))
            elif child.type == "identifier":
                path = self._get_node_text(child, text)
                result.imports.append(ImportInfo(path=path))

    def _get_java_name(self, node, text: str) -> Optional[str]:
        for child in node.children:
            if child.type == "identifier":
                return self._get_node_text(child, text)
        return None

    def _extract_java_call(self, node, text: str, result: ParsedFile):
        """Extract method invocation."""
        children = node.children
        if not children:
            return

        # method_invocation: object (.) method (arguments)
        # Find the method name (last identifier before '(')
        method_name = None
        recv = None
        for i, c in enumerate(children):
            if c.type == "identifier":
                if i > 0 and children[i-1].type == "dot":
                    recv = method_name
                    method_name = self._get_node_text(c, text)
                elif method_name is None:
                    method_name = self._get_node_text(c, text)

        if method_name:
            result.func_calls.append(FuncCall(name=method_name, recv=recv))

    # -------------------------------------------------------------------------
    # Swift parsing
    # -------------------------------------------------------------------------

    def _parse_swift(self, node, text: str, result: ParsedFile):
        """Extract imports, class/func definitions from Swift."""
        for child in node.children:
            ctype = child.type

            if ctype == "import_declaration":
                for c in child.children:
                    if c.type == "identifier":
                        result.imports.append(ImportInfo(path=self._get_node_text(c, text)))
            elif ctype in ("class_declaration", "struct_declaration", "enum_declaration", "protocol_declaration"):
                name = self._get_swift_name(child, text)
                if name:
                    result.classes.append(name)
                    kind = ctype.replace("_declaration", "")
                    result.func_defs.append(FuncDef(name=name, kind=kind))
            elif ctype == "function_declaration":
                name = self._get_swift_name(child, text)
                if name:
                    result.func_defs.append(FuncDef(name=name, kind="function"))
            elif ctype == "call_expression":
                self._extract_swift_call(child, text, result)

    def _get_swift_name(self, node, text: str) -> Optional[str]:
        for child in node.children:
            if child.type == "identifier":
                return self._get_node_text(child, text)
        return None

    def _extract_swift_call(self, node, text: str, result: ParsedFile):
        """Extract Swift function call."""
        for child in node.children:
            if child.type == "identifier":
                result.func_calls.append(FuncCall(name=self._get_node_text(child, text)))
            elif child.type == "call_expression":
                self._extract_swift_call(child, text, result)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_node_text(self, node, text: str) -> str:
        """Get text content of a node."""
        start = node.start_byte if hasattr(node, 'start_byte') else 0
        end = node.end_byte if hasattr(node, 'end_byte') else len(text)
        # Handle bytes vs string
        if isinstance(text, bytes):
            return text[start:end].decode('utf-8', errors='replace')
        elif isinstance(start, bytes):
            return text[start:end].decode('utf-8', errors='replace')
        else:
            return text[start:end]

    def _get_text(self, node, text: str, type_name: str) -> Optional[str]:
        """Get text of a child node by type."""
        for child in node.children:
            if child.type == type_name:
                return self._get_node_text(child, text)
        return None
