import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeChunk:
    file_path: str   # relative to repo root
    symbol: str
    start_line: int
    end_line: int
    source: str
    repo: str = ""   # nazwa repozytorium (puste dla sample)


# Directories never worth indexing (build output, VCS, deps).
_SKIP_DIRS = {".git", ".gradle", "build", "target", "node_modules", ".venv",
              "dist", ".idea", "bin", "__pycache__"}


# ── Python (AST) ────────────────────────────────────────────────────────────
def parse_python_file(filepath: Path, repo_root: Path) -> list[CodeChunk]:
    try:
        source_text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []

    lines = source_text.splitlines()
    rel_path = str(filepath.relative_to(repo_root))
    chunks = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno
        end = node.end_lineno if hasattr(node, "end_lineno") else node.lineno
        chunk_source = "\n".join(lines[start - 1 : end])
        chunks.append(CodeChunk(
            file_path=rel_path,
            symbol=node.name,
            start_line=start,
            end_line=end,
            source=chunk_source,
        ))

    return chunks


# ── Java (lightweight regex + brace matching) ───────────────────────────────
# No external parser dependency: we detect top-level types and their members
# using the brace depth at the start of each line (so method *calls*, which live
# at depth >= 2, are not mistaken for declarations).
_TYPE_DECL = re.compile(r"\b(class|interface|enum|record)\s+(\w+)")
_METHOD_SIG = re.compile(
    r"^\s*"
    r"(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|strictfp)\s+)+"
    r"(?:<[^>]+>\s*)?"          # optional generic type params
    r"[\w.<>\[\],?&\s]+?\s+"    # return type
    r"(\w+)\s*\("               # method name + (
)
_CTOR_SIG = re.compile(r"^\s*(?:public|private|protected)\s+(\w+)\s*\(")
_CTRL = {"if", "for", "while", "switch", "catch", "synchronized", "return",
         "new", "try", "else", "do", "throw", "assert"}


def _line_start_depths(lines: list[str]) -> list[int]:
    """Brace depth at the START of each line (best-effort; ignores strings)."""
    depths, d = [], 0
    for ln in lines:
        depths.append(d)
        d += ln.count("{") - ln.count("}")
    return depths


def _find_open_brace(lines: list[str], decl_idx: int, lookahead: int = 8) -> int | None:
    """Index of the line holding the body's opening '{', or None (abstract / ';')."""
    for i in range(decl_idx, min(decl_idx + lookahead, len(lines))):
        if "{" in lines[i]:
            return i
        if ";" in lines[i]:
            return None
    return None


def _find_block_end(lines: list[str], open_idx: int) -> int:
    """From the line with the body '{', return the line index of the matching '}'."""
    depth, started = 0, False
    for i in range(open_idx, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    return i
    return len(lines) - 1


def _extend_up(lines: list[str], idx: int) -> int:
    """Include contiguous annotations / javadoc above the declaration line."""
    j = idx
    while j > 0:
        prev = lines[j - 1].strip()
        if prev.startswith(("@", "//", "*", "/*")) or prev.endswith("*/"):
            j -= 1
        else:
            break
    return j


def parse_java_file(filepath: Path, repo_root: Path) -> list[CodeChunk]:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    rel_path = str(filepath.relative_to(repo_root))
    depths = _line_start_depths(lines)
    chunks: list[CodeChunk] = []

    for idx, ln in enumerate(lines):
        sd = depths[idx]
        stripped = ln.strip()
        if not stripped or stripped.startswith(("*", "//", "/*", "@", "}")):
            continue

        # Top-level (or nested) type declaration → whole type as one chunk.
        mtype = _TYPE_DECL.search(ln)
        if mtype and sd <= 1:
            name = mtype.group(2)
            open_i = _find_open_brace(lines, idx)
            if open_i is not None:
                end_i = _find_block_end(lines, open_i)
                start = _extend_up(lines, idx)
                chunks.append(CodeChunk(rel_path, name, start + 1, end_i + 1,
                                        "\n".join(lines[start:end_i + 1])))
            continue

        # Method / constructor declaration (only at class-body depth).
        if sd != 1 or "(" not in stripped:
            continue
        before_paren = stripped.split("(", 1)[0]
        if "=" in before_paren:           # field initializer like `X = Map.of(` — not a method
            continue
        m = _METHOD_SIG.match(ln) or _CTOR_SIG.match(ln)
        if not m:
            continue
        name = m.group(1)
        if name in _CTRL:
            continue
        start = _extend_up(lines, idx)
        open_i = _find_open_brace(lines, idx)
        if open_i is not None:
            end_i = _find_block_end(lines, open_i)
        else:
            # abstract / interface method ending with ';'
            end_i = idx
            for i in range(idx, min(idx + 8, len(lines))):
                if ";" in lines[i]:
                    end_i = i
                    break
        chunks.append(CodeChunk(rel_path, name, start + 1, end_i + 1,
                                "\n".join(lines[start:end_i + 1])))

    return chunks


# ── JavaScript / TypeScript / JSX / TSX (lightweight, top-level segmentation) ──
# JSX, template literals and `{}` in expressions make brace-depth matching
# unreliable, so we segment the file by TOP-LEVEL declarations (column 0 — typical
# for formatted modules): each declaration owns the lines from itself up to (but
# excluding) the next top-level declaration. Good enough for retrieval + the
# full-file change flow (the whole file is sent to the LLM anyway).
_JS_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"   # function NAME
    r"|^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*="                 # const/let/var NAME =
    r"|^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"                 # class NAME
    r"|^(?:export\s+)?(?:interface|enum)\s+(\w+)"                    # interface/enum NAME (TS)
    r"|^(?:export\s+)?type\s+(\w+)\s*="                             # type NAME = (TS)
    r"|^(?:export\s+)?default\s+function\b"                          # anonymous default function
)


def parse_js_file(filepath: Path, repo_root: Path) -> list[CodeChunk]:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    rel_path = str(filepath.relative_to(repo_root))

    # Top-level declarations only (no leading whitespace).
    decls: list[tuple[int, str]] = []
    for idx, ln in enumerate(lines):
        if not ln or ln[:1].isspace():
            continue
        m = _JS_DECL.match(ln)
        if not m:
            continue
        name = next((g for g in m.groups() if g), "default")
        decls.append((idx, name))

    if not decls:
        # Whole-file fallback so the file is still retrievable (e.g. pure JSX/markup).
        if not lines:
            return []
        return [CodeChunk(rel_path, filepath.stem, 1, len(lines), text)]

    starts = [_extend_up(lines, idx) for idx, _ in decls]
    chunks: list[CodeChunk] = []
    for i, (_, name) in enumerate(decls):
        s = starts[i]
        e = (starts[i + 1] - 1) if i + 1 < len(decls) else (len(lines) - 1)
        if e < s:
            e = s
        chunks.append(CodeChunk(rel_path, name, s + 1, e + 1, "\n".join(lines[s:e + 1])))
    return chunks


# ── Dispatcher ──────────────────────────────────────────────────────────────
_PARSERS = {
    ".py": parse_python_file,
    ".java": parse_java_file,
    ".js": parse_js_file,
    ".jsx": parse_js_file,
    ".ts": parse_js_file,
    ".tsx": parse_js_file,
    ".mjs": parse_js_file,
}


def ingest_repo(repo_path: str, repo_name: str = "") -> list[CodeChunk]:
    root = Path(repo_path).resolve()
    chunks: list[CodeChunk] = []
    for suffix, parser in _PARSERS.items():
        for f in root.rglob(f"*{suffix}"):
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            for chunk in parser(f, root):
                chunk.repo = repo_name
                chunks.append(chunk)
    return chunks


def ingest_app(repos: list[dict]) -> list[CodeChunk]:
    """Indeksuje wiele repozytoriów naraz i taguje każdy chunk nazwą repo.

    Każdy element `repos` to słownik z kluczami `name` (str) i `path` (str).
    Pomija repo, których katalog nie istnieje.
    """
    chunks: list[CodeChunk] = []
    for repo in repos:
        name, path = repo["name"], repo["path"]
        if not Path(path).is_dir():
            continue
        chunks.extend(ingest_repo(path, repo_name=name))
    return chunks
