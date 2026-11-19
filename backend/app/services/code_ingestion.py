"""Parses real source files on disk into (file, symbol) pairs for the
knowledge graph. This only ever reads a local directory the backend host
can already see -- there is no git-clone-a-remote-URL step here, which
would otherwise turn a knowledge-graph sync into a server-side-request-
forgery / arbitrary-fetch vector. Python files are parsed with the real
`ast` module (genuine function/class definitions with real line numbers);
TypeScript/JavaScript files are scanned with a lightweight regex for
top-level `class`/`function`/`export const` declarations -- not a full
compiler, so it can miss or misattribute unusual syntax, but every symbol
it does report really exists at that file and line.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".angular", ".pytest_cache", ".mypy_cache", "coverage",
}
_PYTHON_SUFFIXES = {".py"}
_TS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
_MAX_FILES = 2000

_TS_SYMBOL_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(class|function)\s+(\w+)"
    r"|^\s*export\s+const\s+(\w+)\s*="
    r"|^\s*(class|function)\s+(\w+)",
    re.MULTILINE,
)


@dataclass
class CodeSymbol:
    name: str
    kind: str  # "function" | "class"
    line: int


@dataclass
class CodeFile:
    relative_path: str
    language: str
    symbols: list[CodeSymbol] = field(default_factory=list)


@dataclass
class IngestionError(Exception):
    message: str


def _parse_python(source: str) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return symbols
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(CodeSymbol(name=node.name, kind="function", line=node.lineno))
        elif isinstance(node, ast.ClassDef):
            symbols.append(CodeSymbol(name=node.name, kind="class", line=node.lineno))
    return symbols


def _parse_ts_js(source: str) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        match = _TS_SYMBOL_RE.match(line)
        if not match:
            continue
        kind_a, name_a, name_const, kind_b, name_b = match.groups()
        if name_a:
            symbols.append(CodeSymbol(name=name_a, kind=kind_a, line=lineno))
        elif name_const:
            symbols.append(CodeSymbol(name=name_const, kind="const", line=lineno))
        elif name_b:
            symbols.append(CodeSymbol(name=name_b, kind=kind_b, line=lineno))
    return symbols


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

        if suffix in _PYTHON_SUFFIXES:
            symbols = _parse_python(source)
            language = "python"
        else:
            symbols = _parse_ts_js(source)
            language = "typescript" if suffix in (".ts", ".tsx") else "javascript"

        files.append(
            CodeFile(
                relative_path=str(path.relative_to(root)).replace("\\", "/"),
                language=language,
                symbols=symbols,
            )
        )
    return files
