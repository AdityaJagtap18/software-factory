import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
}


@dataclass
class NormalizedNode:
    id: str
    label: str
    type: str  # Repository, Directory, File, Class, Function, Method, Module, API, Test, External
    file_path: Optional[str] = None
    location: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedEdge:
    source: str
    target: str
    type: str  # CONTAINS, IMPORTS, CALLS, DEFINES, INHERITS, IMPLEMENTS, DEPENDS_ON, TESTS, REFERENCES
    provenance: str = "EXTRACTED"  # EXTRACTED or INFERRED
    weight: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ManifestDependency:
    name: str
    version: str
    manifest_file: str
    scope: str = "production"  # production or dev


@dataclass
class GraphifyExtractionResult:
    nodes: list[NormalizedNode]
    edges: list[NormalizedEdge]
    manifest_dependencies: list[ManifestDependency]
    languages: dict[str, int]
    total_files: int
    total_directories: int
    total_classes: int
    total_functions: int
    lines_of_code: int
    log_output: str
    graphify_version: str = "0.9.113"


def find_graphify_cli() -> Optional[str]:
    cli = shutil.which("graphify")
    if cli:
        return cli
    venv_dir = Path(sys.executable).parent
    candidate = venv_dir / ("graphify.exe" if sys.platform == "win32" else "graphify")
    if candidate.exists():
        return str(candidate)
    return None


def extract_manifest_dependencies(repo_path: Path) -> list[ManifestDependency]:
    dependencies: list[ManifestDependency] = []
    
    # 1. package.json
    for pkg_json in repo_path.rglob("package.json"):
        if any(ignored in pkg_json.parts for ignored in ["node_modules", ".git", "dist", "build"]):
            continue
        try:
            rel = str(pkg_json.relative_to(repo_path)).replace("\\", "/")
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            prod_deps = data.get("dependencies", {})
            if isinstance(prod_deps, dict):
                for name, ver in prod_deps.items():
                    dependencies.append(ManifestDependency(name=name, version=str(ver), manifest_file=rel, scope="production"))
            dev_deps = data.get("devDependencies", {})
            if isinstance(dev_deps, dict):
                for name, ver in dev_deps.items():
                    dependencies.append(ManifestDependency(name=name, version=str(ver), manifest_file=rel, scope="dev"))
        except Exception as exc:
            logger.debug(f"Error parsing package.json {pkg_json}: {exc}")

    # 2. requirements.txt
    for req_file in repo_path.rglob("requirements*.txt"):
        if any(ignored in req_file.parts for ignored in ["node_modules", ".git", "venv", ".venv"]):
            continue
        try:
            rel = str(req_file.relative_to(repo_path)).replace("\\", "/")
            lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                match = re.match(r"^([a-zA-Z0-9_\-\.]+)([=<>!~]+.*)?", line)
                if match:
                    pkg_name = match.group(1)
                    ver = match.group(2) or ""
                    dependencies.append(ManifestDependency(name=pkg_name, version=ver.strip(), manifest_file=rel, scope="production"))
        except Exception as exc:
            logger.debug(f"Error parsing requirements {req_file}: {exc}")

    # 3. pyproject.toml
    for pyproject in repo_path.rglob("pyproject.toml"):
        if any(ignored in pyproject.parts for ignored in ["node_modules", ".git", "venv", ".venv"]):
            continue
        try:
            rel = str(pyproject.relative_to(repo_path)).replace("\\", "/")
            content = pyproject.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'["\']([a-zA-Z0-9_\-\.]+)(([=<>!~]+[^"\']+)?)["\']', content):
                name, ver = m.group(1), m.group(2) or ""
                if name.lower() not in ["build-system", "poetry", "tool", "setuptools", "wheel"]:
                    dependencies.append(ManifestDependency(name=name, version=ver, manifest_file=rel, scope="production"))
        except Exception as exc:
            logger.debug(f"Error parsing pyproject.toml {pyproject}: {exc}")

    return dependencies


def run_graphify_extraction(
    repo_path: Path,
    excluded_paths: Optional[list[str]] = None,
    max_file_size_kb: int = 500,
) -> GraphifyExtractionResult:
    logs: list[str] = []
    logs.append(f"Starting repository intelligence analysis in {repo_path}")

    cli = find_graphify_cli()
    graph_json_path = repo_path / "graphify-out" / "graph.json"

    if cli:
        logs.append(f"Found Graphify CLI at {cli}")
        cmd = [cli, "update", str(repo_path), "--no-cluster", "--force"]
        try:
            logs.append(f"Executing: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.stdout:
                logs.append(f"[Graphify stdout]\n{proc.stdout}")
            if proc.stderr:
                logs.append(f"[Graphify stderr]\n{proc.stderr}")
        except Exception as exc:
            logs.append(f"Warning: Graphify CLI execution encountered error: {exc}")
    else:
        logs.append("Graphify CLI not found in PATH or venv; using internal code extraction engine.")

    # Parse graph.json or fallback
    nodes: list[NormalizedNode] = []
    edges: list[NormalizedEdge] = []
    seen_nodes: set[str] = set()

    if graph_json_path.exists():
        try:
            logs.append(f"Reading structured graph from {graph_json_path}")
            raw = json.loads(graph_json_path.read_text(encoding="utf-8", errors="ignore"))
            raw_nodes = raw.get("nodes", [])
            raw_links = raw.get("links", [])
            logs.append(f"Loaded {len(raw_nodes)} raw nodes and {len(raw_links)} raw links from Graphify output.")

            for rn in raw_nodes:
                nid = rn.get("id")
                if not nid or nid in seen_nodes:
                    continue
                seen_nodes.add(nid)
                label = rn.get("label", nid)
                source_file = rn.get("source_file", "")
                source_loc = rn.get("source_location", "")
                is_external = rn.get("external", False) or rn.get("type") == "external"
                is_callable = rn.get("_callable", False) or label.endswith("()")

                # Classify type
                if is_external:
                    ntype = "External"
                elif "test" in label.lower() or "test" in source_file.lower():
                    ntype = "Test"
                elif is_callable:
                    ntype = "Function"
                elif label.startswith("class ") or "class" in rn.get("file_type", ""):
                    ntype = "Class"
                elif any(label.endswith(ext) or source_file.endswith(ext) for ext in _LANGUAGE_EXTENSIONS):
                    ntype = "File"
                elif rn.get("file_type") == "directory":
                    ntype = "Directory"
                else:
                    ntype = "Module"

                # Check if API endpoint
                if ntype in ("Function", "Module") and any(api_marker in label.lower() for api_marker in ["api", "router", "endpoint", "get_", "post_", "put_", "delete_"]):
                    ntype = "API"

                nodes.append(
                    NormalizedNode(
                        id=nid,
                        label=label,
                        type=ntype,
                        file_path=source_file or None,
                        location=source_loc or None,
                        properties={"raw": rn},
                    )
                )

            for rl in raw_links:
                src = rl.get("source")
                tgt = rl.get("target")
                if not src or not tgt:
                    continue
                rel = rl.get("relation", "references").upper()
                # Map relation to canonical types
                if "IMPORT" in rel:
                    rel_type = "IMPORTS"
                elif "CALL" in rel:
                    rel_type = "CALLS"
                elif "CONTAIN" in rel:
                    rel_type = "CONTAINS"
                elif "DEFINE" in rel:
                    rel_type = "DEFINES"
                elif "INHERIT" in rel:
                    rel_type = "INHERITS"
                elif "IMPLEMENT" in rel:
                    rel_type = "IMPLEMENTS"
                elif "DEPEND" in rel:
                    rel_type = "DEPENDS_ON"
                elif "TEST" in rel:
                    rel_type = "TESTS"
                else:
                    rel_type = "REFERENCES"

                raw_conf = str(rl.get("confidence", "EXTRACTED")).upper()
                provenance = "EXTRACTED" if "EXTRACT" in raw_conf else "INFERRED"
                weight = float(rl.get("weight", 1.0))

                edges.append(
                    NormalizedEdge(
                        source=src,
                        target=tgt,
                        type=rel_type,
                        provenance=provenance,
                        weight=weight,
                        properties={"context": rl.get("context", "")},
                    )
                )
        except Exception as exc:
            logs.append(f"Failed parsing graphify graph.json: {exc}")

    # Fallback / Enrichment with filesystem scan for files, dirs, LOC and languages
    logs.append("Analyzing filesystem for directories, files, LOC, and language distribution...")
    total_loc = 0
    languages: dict[str, int] = {}
    total_files = 0
    total_dirs = 0

    excluded = set(excluded_paths or ["node_modules", "dist", ".git", "__pycache__", "venv", ".venv", "build", "graphify-out"])

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
        rel_dir = os.path.relpath(root, repo_path).replace("\\", "/")
        if rel_dir != ".":
            total_dirs += 1
            dir_id = f"dir:{rel_dir}"
            if dir_id not in seen_nodes:
                seen_nodes.add(dir_id)
                nodes.append(
                    NormalizedNode(
                        id=dir_id,
                        label=os.path.basename(rel_dir),
                        type="Directory",
                        file_path=rel_dir,
                    )
                )

        for f in files:
            file_path = Path(root) / f
            rel_file = os.path.relpath(file_path, repo_path).replace("\\", "/")
            ext = file_path.suffix.lower()

            # Max file size check
            try:
                size_kb = file_path.stat().st_size / 1024
                if size_kb > max_file_size_kb:
                    continue
            except OSError:
                continue

            total_files += 1
            file_id = f"file:{rel_file}"
            if file_id not in seen_nodes:
                seen_nodes.add(file_id)
                is_test = "test" in f.lower() or f.endswith("_test.py") or f.endswith(".spec.ts")
                nodes.append(
                    NormalizedNode(
                        id=file_id,
                        label=f,
                        type="Test" if is_test else "File",
                        file_path=rel_file,
                    )
                )
                # Link directory to file
                parent_dir = os.path.dirname(rel_file)
                parent_dir_id = f"dir:{parent_dir}" if parent_dir and parent_dir != "." else "dir:root"
                edges.append(
                    NormalizedEdge(
                        source=parent_dir_id,
                        target=file_id,
                        type="CONTAINS",
                        provenance="EXTRACTED",
                    )
                )

            # Count lines of code and languages
            lang = _LANGUAGE_EXTENSIONS.get(ext)
            if lang:
                try:
                    line_count = len(file_path.read_text(encoding="utf-8", errors="ignore").splitlines())
                    total_loc += line_count
                    languages[lang] = languages.get(lang, 0) + line_count
                except Exception:
                    pass

    # External manifest dependencies
    logs.append("Extracting package manifest dependencies...")
    manifest_deps = extract_manifest_dependencies(repo_path)
    logs.append(f"Found {len(manifest_deps)} manifest dependencies.")

    for dep in manifest_deps:
        ext_id = f"ext:{dep.name}"
        if ext_id not in seen_nodes:
            seen_nodes.add(ext_id)
            nodes.append(
                NormalizedNode(
                    id=ext_id,
                    label=dep.name,
                    type="External",
                    properties={"version": dep.version, "manifest": dep.manifest_file, "scope": dep.scope},
                )
            )
        manifest_file_id = f"file:{dep.manifest_file}"
        edges.append(
            NormalizedEdge(
                source=manifest_file_id,
                target=ext_id,
                type="DEPENDS_ON",
                provenance="EXTRACTED",
                properties={"version": dep.version},
            )
        )

    # Class & Function counts
    total_classes = sum(1 for n in nodes if n.type == "Class")
    total_functions = sum(1 for n in nodes if n.type in ("Function", "Method", "API"))

    logs.append(
        f"Extraction complete: {len(nodes)} nodes, {len(edges)} edges, {total_files} files, "
        f"{total_classes} classes, {total_functions} functions, {total_loc} LOC."
    )

    return GraphifyExtractionResult(
        nodes=nodes,
        edges=edges,
        manifest_dependencies=manifest_deps,
        languages=languages,
        total_files=total_files,
        total_directories=total_dirs,
        total_classes=total_classes,
        total_functions=total_functions,
        lines_of_code=total_loc,
        log_output="\n".join(logs),
    )
