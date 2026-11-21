"""Parses real source files on disk into (file, symbol, import) data for the
knowledge graph. This only ever reads a local directory the backend host can
already see -- there is no git-clone-a-remote-URL step here, which would
otherwise turn a knowledge-graph sync into a server-side-request-forgery /
arbitrary-fetch vector.

Parsing goes through a small polyglot parser-adapter framework (P3-3):
`LanguageAdapter` is the extension point, keyed by file suffix in
`_ADAPTERS`. Today two real adapters exist -- `PythonAdapter` (the real
`ast` module: genuine function/class definitions and imports with real line
numbers) and `TypeScriptJavaScriptAdapter` (regex-based, not a full
compiler, so it can miss or misattribute unusual syntax, but every symbol
and import it does report really exists at that file and line). Only files
whose suffix has a registered adapter are scanned at all (same scope as
before this framework existed, to avoid flooding the graph with every
non-code file in a repo); a parse failure on a file that *is* in scope
degrades to "no symbols/imports for that file" rather than aborting the
whole scan. Adding a new language means adding one more `LanguageAdapter`,
registering its suffixes, and widening the suffix filter in
`scan_directory`; nothing else in this module changes.

Beyond per-file parsing, `compute_relationships()` derives the two
cross-file relationship types the engineering roadmap calls out as the next
priority after "file defines symbol": `DEPENDS_ON` (file A imports a module
resolvable to file B inside this same repo) and `TESTS` (a recognized test
file's naming convention maps it to the file it tests). Call-graph (`CALLS`)
and deep data-flow analysis remain explicitly out of scope here, as the
roadmap allows.
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import re

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".angular", ".pytest_cache", ".mypy_cache", "coverage",
}
_PYTHON_SUFFIXES = {".py"}
_TS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
_MAX_FILES = 2000

_TEST_FILE_RE = re.compile(
    r"^(test_)(?P<py_suffix_name>.+)\.py$"
    r"|^(?P<py_prefix_name>.+)(_test)\.py$"
    r"|^(?P<ts_name>.+)\.(test|spec)\.(ts|tsx|js|jsx)$"
)


@dataclass
class CodeSymbol:
    name: str
    kind: str  # "function" | "class"
    line: int


@dataclass
class CodeImport:
    """One module reference found in a file. `module` is the raw module
    name/path as written in source (dotted for Python, a string literal for
    TS/JS). `relative` means it is a same-repo relative import (Python
    `from . import x` / `from .pkg import y`, or TS/JS `./x` / `../y`) --
    only relative imports are ever resolved to a same-repo `File` for
    `DEPENDS_ON`; anything else becomes an external `Module` node via
    `IMPORTS`, matching what `knowledge_graph.py` already does for
    unresolved imports."""

    module: str
    line: int
    relative: bool


@dataclass
class CodeFile:
    relative_path: str
    language: str
    symbols: list[CodeSymbol] = field(default_factory=list)
    imports: list[CodeImport] = field(default_factory=list)
    is_test: bool = False
    test_target_name: str | None = None  # basename this test file's naming convention implies it tests


@dataclass
class IngestionError(Exception):
    message: str


@dataclass
class RelationshipGraph:
    """Cross-file relationships computed once the whole repo has been
    parsed (both endpoints must be known to resolve a relative import to a
    same-repo file)."""

    depends_on: list[tuple[str, str]] = field(default_factory=list)  # (from_path, to_path)
    tests: list[tuple[str, str]] = field(default_factory=list)  # (test_file_path, target_file_path)


class LanguageAdapter(ABC):
    """Extension point for the polyglot parser-adapter framework. Each
    adapter claims a set of file suffixes and knows how to turn that
    language's source text into real symbols/imports -- nothing here walks
    the filesystem or touches Neo4j."""

    language: str
    suffixes: frozenset[str]

    @abstractmethod
    def parse(self, source: str) -> tuple[list[CodeSymbol], list[CodeImport]]:
        ...


class PythonAdapter(LanguageAdapter):
    language = "python"
    suffixes = frozenset(_PYTHON_SUFFIXES)

    def parse(self, source: str) -> tuple[list[CodeSymbol], list[CodeImport]]:
        symbols: list[CodeSymbol] = []
        imports: list[CodeImport] = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return symbols, imports
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(CodeSymbol(name=node.name, kind="function", line=node.lineno))
            elif isinstance(node, ast.ClassDef):
                symbols.append(CodeSymbol(name=node.name, kind="class", line=node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(CodeImport(module=alias.name, line=node.lineno, relative=False))
            elif isinstance(node, ast.ImportFrom):
                level = node.level or 0
                prefix = "." * level
                if node.module:
                    imports.append(
                        CodeImport(module=f"{prefix}{node.module}", line=node.lineno, relative=level > 0)
                    )
                elif level > 0:
                    # `from . import foo[, bar]` -- each name is itself a submodule.
                    for alias in node.names:
                        imports.append(
                            CodeImport(module=f"{prefix}{alias.name}", line=node.lineno, relative=True)
                        )
        return symbols, imports


class TypeScriptJavaScriptAdapter(LanguageAdapter):
    language = "typescript"  # overridden per-file below (typescript vs javascript)
    suffixes = frozenset(_TS_SUFFIXES)

    _SYMBOL_RE = re.compile(
        r"^\s*export\s+(?:default\s+)?(class|function)\s+(\w+)"
        r"|^\s*export\s+const\s+(\w+)\s*="
        r"|^\s*(class|function)\s+(\w+)",
        re.MULTILINE,
    )
    _IMPORT_RE = re.compile(
        r"""^\s*import\s+(?:[^'"]+?\s+from\s+)?['"](?P<mod1>[^'"]+)['"]"""
        r"""|require\(\s*['"](?P<mod2>[^'"]+)['"]\s*\)"""
        r"""|^\s*export\s+(?:[^'"]+?\s+from\s+)?['"](?P<mod3>[^'"]+)['"]""",
        re.MULTILINE,
    )

    def parse(self, source: str) -> tuple[list[CodeSymbol], list[CodeImport]]:
        symbols: list[CodeSymbol] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            match = self._SYMBOL_RE.match(line)
            if not match:
                continue
            kind_a, name_a, name_const, kind_b, name_b = match.groups()
            if name_a:
                symbols.append(CodeSymbol(name=name_a, kind=kind_a, line=lineno))
            elif name_const:
                symbols.append(CodeSymbol(name=name_const, kind="const", line=lineno))
            elif name_b:
                symbols.append(CodeSymbol(name=name_b, kind=kind_b, line=lineno))

        imports: list[CodeImport] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            for match in self._IMPORT_RE.finditer(line):
                module = match.group("mod1") or match.group("mod2") or match.group("mod3")
                if not module:
                    continue
                imports.append(
                    CodeImport(module=module, line=lineno, relative=module.startswith("."))
                )
        return symbols, imports


_ADAPTERS: dict[str, LanguageAdapter] = {}
for _adapter in (PythonAdapter(), TypeScriptJavaScriptAdapter()):
    for _suffix in _adapter.suffixes:
        _ADAPTERS[_suffix] = _adapter


def _language_for_suffix(suffix: str) -> str:
    if suffix in _PYTHON_SUFFIXES:
        return "python"
    if suffix in (".ts", ".tsx"):
        return "typescript"
    if suffix in (".js", ".jsx"):
        return "javascript"
    return suffix.lstrip(".") or "unknown"


def _detect_test_file(relative_path: str) -> tuple[bool, str | None]:
    """Naming-convention test detection: `test_foo.py`, `foo_test.py`,
    `foo.spec.ts`, `foo.test.tsx`, etc. Returns (is_test, target_basename)
    where `target_basename` is the filename this test file's own naming
    convention implies it tests (without directory), or None if this isn't
    a recognized test file."""
    name = relative_path.rsplit("/", 1)[-1]
    match = _TEST_FILE_RE.match(name)
    if not match:
        return False, None
    if match.group("py_suffix_name"):
        return True, f"{match.group('py_suffix_name')}.py"
    if match.group("py_prefix_name"):
        return True, f"{match.group('py_prefix_name')}.py"
    if match.group("ts_name"):
        # The target could be any of the TS/JS suffixes; resolution tries them all.
        return True, match.group("ts_name")
    return False, None


def scan_directory(root: Path) -> list[CodeFile]:
    """Walks a real directory tree on the backend host and parses every
    real source file found, up to a sane cap. Raises IngestionError if
    the path doesn't exist or isn't a directory -- never silently returns
    an empty-but-successful scan for a bad path."""
    if not root.exists():
        raise IngestionError(f"Path does not exist on the backend host: {root}")
    if not root.is_dir():
        raise IngestionError(f"Path is not a directory: {root}")

    files: list[CodeFile] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= _MAX_FILES:
            break
        if path.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        suffix = path.suffix.lower()
        if suffix not in _PYTHON_SUFFIXES and suffix not in _TS_SUFFIXES:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        adapter = _ADAPTERS.get(suffix)
        language = _language_for_suffix(suffix)
        if adapter is not None:
            try:
                symbols, imports = adapter.parse(source)
            except Exception:  # noqa: BLE001 - a parsing failure degrades to "no symbols", never a scan abort
                symbols, imports = [], []
        else:
            symbols, imports = [], []

        relative_path = str(path.relative_to(root)).replace("\\", "/")
        is_test, test_target_name = _detect_test_file(relative_path)

        files.append(
            CodeFile(
                relative_path=relative_path,
                language=language,
                symbols=symbols,
                imports=imports,
                is_test=is_test,
                test_target_name=test_target_name,
            )
        )
    return files


def _resolve_python_module(from_path: str, module: str, all_paths: set[str]) -> str | None:
    """Resolves a Python import to a same-repo file path, or None if it
    points outside this repo (a real third-party package, most likely)."""
    if not module.startswith("."):
        candidate_base = module.replace(".", "/")
        for suffix in (".py",):
            if f"{candidate_base}{suffix}" in all_paths:
                return f"{candidate_base}{suffix}"
        if f"{candidate_base}/__init__.py" in all_paths:
            return f"{candidate_base}/__init__.py"
        return None

    level = len(module) - len(module.lstrip("."))
    remainder = module[level:]
    from_dir = from_path.rsplit("/", 1)[0] if "/" in from_path else ""
    parts = from_dir.split("/") if from_dir else []
    # level 1 ("from . import x" / "from .x import y") stays in the same package directory.
    up = max(level - 1, 0)
    base_parts = parts[: len(parts) - up] if up else parts
    candidate_base = "/".join([*base_parts, *remainder.replace(".", "/").split("/")]) if remainder else "/".join(base_parts)
    candidate_base = candidate_base.strip("/")
    for suffix in (".py",):
        if f"{candidate_base}{suffix}" in all_paths:
            return f"{candidate_base}{suffix}"
    if f"{candidate_base}/__init__.py" in all_paths:
        return f"{candidate_base}/__init__.py"
    return None


def _resolve_ts_module(from_path: str, module: str, all_paths: set[str]) -> str | None:
    if not module.startswith("."):
        return None
    from_dir = from_path.rsplit("/", 1)[0] if "/" in from_path else ""
    parts = [p for p in from_dir.split("/") if p] if from_dir else []
    for segment in module.split("/"):
        if segment == "." or segment == "":
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    candidate_base = "/".join(parts)
    for suffix in (".ts", ".tsx", ".js", ".jsx"):
        if f"{candidate_base}{suffix}" in all_paths:
            return f"{candidate_base}{suffix}"
        if f"{candidate_base}/index{suffix}" in all_paths:
            return f"{candidate_base}/index{suffix}"
    return None


def compute_relationships(files: list[CodeFile]) -> RelationshipGraph:
    """Derives `DEPENDS_ON` (same-repo import resolution) and `TESTS`
    (test-file naming convention) across the whole parsed file set. Both
    need the full file list up front, which is why this runs once after
    `scan_directory`, not per-file."""
    all_paths = {f.relative_path for f in files}
    by_basename: dict[str, list[str]] = {}
    for f in files:
        by_basename.setdefault(f.relative_path.rsplit("/", 1)[-1], []).append(f.relative_path)

    graph = RelationshipGraph()

    for f in files:
        for imp in f.imports:
            if not imp.relative:
                continue
            target = (
                _resolve_python_module(f.relative_path, imp.module, all_paths)
                if f.language == "python"
                else _resolve_ts_module(f.relative_path, imp.module, all_paths)
            )
            if target and target != f.relative_path:
                graph.depends_on.append((f.relative_path, target))

        if f.is_test and f.test_target_name:
            candidates = by_basename.get(f.test_target_name, [])
            if not candidates and not f.test_target_name.endswith(".py"):
                # TS test target name has no extension yet; try all TS/JS suffixes.
                for suffix in (".ts", ".tsx", ".js", ".jsx"):
                    candidates = by_basename.get(f"{f.test_target_name}{suffix}", [])
                    if candidates:
                        break
            if candidates:
                same_dir = f.relative_path.rsplit("/", 1)[0] if "/" in f.relative_path else ""
                best = next(
                    (c for c in candidates if (c.rsplit("/", 1)[0] if "/" in c else "") == same_dir),
                    candidates[0],
                )
                if best != f.relative_path:
                    graph.tests.append((f.relative_path, best))

    graph.depends_on = sorted(set(graph.depends_on))
    graph.tests = sorted(set(graph.tests))
    return graph
