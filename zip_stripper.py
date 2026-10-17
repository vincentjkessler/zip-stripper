#!/usr/bin/env python3
"""
Zip Stripper v2.0.1
Copy a project, strip heavy/generated/private folders, zip the clean copy.
Standard-library only. Windows-first, cross-platform enough for tests.

v2.0.1 copies the finished ZIP to the clipboard after a right-click run.
v2.0.0 is the first release as plain "Zip Stripper" (with an optional paid
Zip Stripper Pro add-on, see load_pro()).
v1.6.0 added the Zip Stripper Library: zips go to Documents/Zip Stripper Library
and a local web page (zip_stripper_web.py) lists them all.
v1.5.0 leaves out secret files and files containing API/private keys,
honours the project's .gitignore, and drops exact duplicates and big media.
v1.4.0 added a standard-library GUI launcher and cleaner source/package profiles.
The original project is never modified.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import fnmatch
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

VERSION = "2.0.1"
APP_NAME = "Zip Stripper"

DEFAULT_STRIP_DIRS = {
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", "ENV", "virtualenv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".pyre", ".tox", ".nox",
    ".hypothesis", ".ipynb_checkpoints", "htmlcov", ".eggs", "pip-wheel-metadata",
    "node_modules", "bower_components", ".npm", ".pnpm-store", ".yarn-cache",
    ".parcel-cache", ".turbo", ".vite", ".next", ".nuxt", ".svelte-kit",
    ".astro", ".angular", ".cache-loader", ".webpack", ".rollup.cache",
    "storybook-static",
    ".cache", "cache", "caches", ".coverage_cache", "coverage", ".nyc_output",
    "logs", "log", "tmp", "temp", ".tmp", ".temp",
    "dist", "build", "out", "output", "outputs", "release", "releases",
    "Debug", "Release", "x64", "x86",
    "target", "bin", "obj", ".gradle", ".idea_modules", ".dart_tool",
    ".pub-cache", ".packages", ".stack-work", "cmake-build-debug",
    "cmake-build-release", "CMakeFiles",
    "Pods", "DerivedData", ".expo", ".expo-shared", ".serverless",
    ".terraform", ".aws-sam",
    "dist_electron", "electron-dist", "app.asar.unpacked",
    "vendor",
}

DEFAULT_STRIP_DIR_SUFFIXES = {".egg-info", ".dist-info", ".cache", ".bak"}

DEFAULT_STRIP_FILES = {
    "Thumbs.db", "ehthumbs.db", "Desktop.ini", ".DS_Store", "._.DS_Store",
    ".coverage", "coverage.xml", "npm-debug.log", "yarn-error.log",
    "pnpm-debug.log", "package-lock.json.tmp",
}

DEFAULT_STRIP_FILE_PREFIXES = {".env"}

ENV_TEMPLATE_NAMES = {
    ".env.example", ".env.sample", ".env.template", ".env.defaults", ".env.dist",
    ".env.example.local", ".env.sample.local", ".env.template.local",
}

DEFAULT_STRIP_SUFFIXES = {
    ".log", ".tmp", ".temp", ".bak", ".old", ".orig", ".swp", ".swo",
    ".pyc", ".pyo", ".class", ".o", ".obj", ".pdb", ".ilk", ".idb",
    ".dSYM", ".coverage", ".tsbuildinfo",
}

DEFAULT_STRIP_ARCHIVE_SUFFIXES = {
    ".zip", ".7z", ".rar", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz",
    ".gz", ".bz2", ".xz", ".iso", ".dmg", ".pkg", ".msi", ".exe", ".dll",
    ".so", ".dylib", ".asar",
}

# Smart mode is intentionally simple and auditable. It does not try to infer
# science value; it preserves evidence-shaped handoff packets and removes
# obvious upload bloat: raw downloads, giant datasets, duplicate nested packet
# copies, dependency/build/cache folders, logs, and non-evidence archives.
SMART_EVIDENCE_KEYWORDS = {
    "audit", "reviewer", "packet", "bundle", "prereg", "preregister",
    "preregistration", "freeze", "frozen", "claim", "adjudication",
    "results", "registry", "blind_input", "clarification", "reproduction",
    "external", "handoff", "receipt", "manifest",
}

SMART_RAW_PATH_MARKERS = {
    "/downloads/", "/download/", "/raw/", "/raw_data/", "/physics_data/",
    "domains/data/", "/data/raw/", "/cache/", "/tmp/",
}

SMART_LARGE_DATA_SUFFIXES = {
    ".csv", ".dat", ".evt", ".evt.gz", ".sf", ".fits", ".fit",
    ".h5", ".hdf5", ".npy", ".npz", ".parquet", ".feather",
}

SMART_SOURCE_SUFFIXES = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".json", ".jsonl", ".md", ".rst", ".txt", ".toml", ".yaml",
    ".yml", ".ini", ".cfg", ".ps1", ".bat", ".cmd", ".sh",
    ".html", ".css", ".scss", ".sql", ".lock", ".gitignore",
}

SMART_DEFAULT_TARGET_MB = 250
SMART_ALWAYS_KEEP_MAX_MB = 300
CHATGPT_SAFE_ZIP_MB = 450


DESTINATION_PRESETS = {
    "generic": {"target_mb": SMART_DEFAULT_TARGET_MB, "max_zip_mb": CHATGPT_SAFE_ZIP_MB, "label": "Generic AI upload"},
    "chatgpt": {"target_mb": 250, "max_zip_mb": 450, "label": "ChatGPT upload-safe preset"},
    "claude": {"target_mb": 25, "max_zip_mb": 30, "label": "Claude conservative upload preset"},
    "gemini": {"target_mb": 250, "max_zip_mb": 450, "label": "Gemini app/API conservative preset"},
    "cursor": {"target_mb": 80, "max_zip_mb": 100, "label": "Cursor/dev-agent compact context preset"},
}

ZIPSTRIPPERIGNORE_NAME = ".zipstripperignore"
TEXT_TOKEN_SUFFIXES = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".md", ".rst", ".txt", ".json", ".jsonl", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".ps1", ".bat", ".cmd", ".sh", ".html", ".css", ".scss",
    ".sql", ".csv", ".xml", ".lock", ".gitignore",
}

SOURCE_DROP_TOP_LEVELS = {
    "state", "context_logs", "runs", "run_outputs", "executions",
    "output", "outputs", "artifacts", "artifact", "archives", "archive",
    "backups", "backup", "datasets", "data", "downloads", "download",
    "raw", "raw_data", "physics_data", "scratch", "sandbox", "tmp", "temp",
}

SOURCE_DROP_PREFIXES = {
    "domains/data/",
}

SOURCE_DROP_MARKERS = {
    "/downloads/", "/download/", "/raw/", "/raw_data/", "/physics_data/",
    "/audit_results/", "/packet/artifacts/", "/debug_logs/", "/logs/",
    "/cache/", "/tmp/", "/temp/", "/output/", "/outputs/",
}

SOURCE_KEEP_FILENAMES = {
    "readme", "readme.md", "license", "license.md", "makefile", "dockerfile",
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "tox.ini", "pytest.ini", "mypy.ini", "ruff.toml",
    ".gitignore", ".env.example", ".env.sample", ".env.template",
}

SOURCE_PROFILE_SUFFIXES = {
    ".py", ".pyw", ".ps1", ".bat", ".cmd", ".sh",
    ".md", ".rst", ".txt", ".json", ".jsonl", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".sql", ".html", ".css", ".js", ".ts",
}

# --- Secret protection (v1.5.0) ---------------------------------------------
# Folders that only ever hold keys/credentials.
SECRET_DIR_NAMES = {".ssh", ".aws", ".gnupg", ".azure", ".kube"}

# File names (case-insensitive globs) that are credentials by convention.
SECRET_FILE_GLOBS = (
    "credentials", "credentials*.json", "credentials*.yml", "credentials*.yaml",
    "client_secret*.json", "service-account*.json", "service_account*.json",
    "*serviceaccount*.json", "*-sa-key*.json",
    "secrets.*", "secret.*", "*.secrets", "*.secret",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "*.ppk",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk",
    ".netrc", "_netrc", ".pgpass", ".htpasswd", ".git-credentials",
)

# Names that look like templates are not dropped by name (their contents are still scanned).
SECRET_TEMPLATE_MARKERS = (".example", ".sample", ".template", ".dist", "-example", "_example")

# Config files that are only a problem when they actually contain a token/password.
SECRET_TOKEN_CONFIGS = {
    ".npmrc": r"(?im)(_authtoken|_auth|_password)\s*=\s*(?!<REDACTED)\S+",
    ".yarnrc": r"(?im)(npmauthtoken|_authtoken)\s*[=:]\s*(?!<REDACTED)\S+",
    ".yarnrc.yml": r"(?im)(npmauthtoken|_authtoken)\s*[=:]\s*(?!<REDACTED)\S+",
    ".pypirc": r"(?im)^\s*(password)\s*[=:]\s*(?!<REDACTED)\S+",
}

# Text patterns that identify real API keys / private keys. Only the kind and
# line number are ever reported; the matched value itself is never printed.
SECRET_CONTENT_PATTERNS = (
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI API key", r"(?<![A-Za-z0-9_\-])sk-(?!ant-)(?:proj-|svcacct-|admin-)?(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"),
    ("GitHub token", r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("AWS secret key", r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{30,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}"),
    ("Google OAuth secret", r"\bGOCSPX-[A-Za-z0-9_\-]{20,}"),
    ("Stripe key", r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("Hugging Face token", r"\bhf_[A-Za-z0-9]{30,}"),
    ("Private key", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
)

SECRET_SCAN_MAX_BYTES = 5 * 1024 * 1024

# --- Upload size trimming (v1.5.0) ------------------------------------------
MEDIA_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".psd", ".heic", ".heif", ".avif", ".ico", ".icns", ".tga", ".exr", ".hdr",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus",
    ".glb", ".gltf", ".fbx", ".blend", ".usdz",
    ".pdf",
}
DEFAULT_MEDIA_CUTOFF_KB = 250
DUPLICATE_MIN_BYTES = 1024

# Rough number of text tokens most AI chats can read at once.
AI_CHAT_COMFORT_TOKENS = 200_000
AI_CHAT_FAR_BEYOND_TOKENS = 400_000


def log(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(f"[{APP_NAME}] {message}", flush=True)


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_name(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in "-_ .":
            keep.append(ch)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip().replace(" ", "_")
    return cleaned or "project"


def human_bytes(n: int | None) -> str:
    if n is None:
        return "not measured"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{n} B"



def destination_defaults(destination: str) -> dict[str, object]:
    return dict(DESTINATION_PRESETS.get((destination or "generic").lower(), DESTINATION_PRESETS["generic"]))


def is_glob_pattern(value: str) -> bool:
    return any(ch in value for ch in "*?[")


def path_matches_pattern(rel: str, pattern: str) -> bool:
    rel = norm_rel_path(rel)
    pattern = norm_rel_path(pattern)
    if not pattern:
        return False
    if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel.lower(), pattern.lower()):
        return True
    if rel == pattern or rel.startswith(pattern + "/"):
        return True
    # Bare directory/file name convenience: "node_modules" matches anywhere.
    if "/" not in pattern and (rel.rsplit("/", 1)[-1].lower() == pattern.lower()):
        return True
    return False


def expand_path_patterns(src: Path, patterns: list[str]) -> set[str]:
    """Expand .zipstripperignore-style glob/literal patterns to project-relative paths."""
    selected: set[str] = set()
    cleaned_patterns = [norm_rel_path(p) for p in patterns if norm_rel_path(p)]
    if not cleaned_patterns:
        return selected
    for pattern in cleaned_patterns:
        if not is_glob_pattern(pattern):
            selected.add(pattern.rstrip("/"))
    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        names = list(dirs) + list(files)
        for name in names:
            rel = rel_from(root_path / name, src)
            for pattern in cleaned_patterns:
                if path_matches_pattern(rel, pattern):
                    selected.add(rel)
                    break
    return selected


def load_zipstripperignore(src: Path, ignore_file: Path | None = None) -> dict[str, object]:
    """Read per-project strip rules.

    Supported syntax:
      # comment
      drop: state/**
      keep: state/needed_fixture.json
      !state/needed_fixture.json
      keep-secret: config/public_test_key.pem
      target-mb: 100
      max-zip-mb: 450
      profile: source
      destination: chatgpt

    Bare lines are treated as drop patterns. This deliberately mirrors the
    simple mental model of .gitignore while keeping explicit keep/drop support.
    """
    path = ignore_file or (src / ZIPSTRIPPERIGNORE_NAME)
    result = {"path": path, "exists": False, "drop_patterns": [], "keep_patterns": [], "keep_secret_patterns": [], "settings": {}}
    try:
        if not path.exists() or not path.is_file():
            return result
        result["exists"] = True
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            lower = line.lower()
            if lower.startswith("keep-secret:"):
                result["keep_secret_patterns"].append(line.split(":", 1)[1].strip())
            elif lower.startswith("keep:"):
                result["keep_patterns"].append(line.split(":", 1)[1].strip())
            elif lower.startswith("drop:"):
                result["drop_patterns"].append(line.split(":", 1)[1].strip())
            elif line.startswith("!"):
                result["keep_patterns"].append(line[1:].strip())
            elif ":" in line and lower.split(":", 1)[0] in {"target-mb", "max-zip-mb", "profile", "destination"}:
                key, value = line.split(":", 1)
                result["settings"][key.strip().lower()] = value.strip()
            else:
                result["drop_patterns"].append(line)
    except OSError:
        return result
    return result


def estimate_tokens_from_stage_files(stage_files: list[dict[str, str | int]]) -> dict[str, object]:
    rows = []
    total = 0
    for item in stage_files:
        rel = str(item["path"])
        size = int(item["size_bytes"])
        lower = rel.lower()
        textish = any(lower.endswith(suffix) for suffix in TEXT_TOKEN_SUFFIXES) or "." not in rel.rsplit("/", 1)[-1]
        tokens = max(1, int(size / 4)) if textish and size else 0
        if tokens:
            rows.append({"path": rel, "size_bytes": size, "estimated_tokens": tokens})
            total += tokens
    rows.sort(key=lambda r: int(r["estimated_tokens"]), reverse=True)
    return {"estimated_total_tokens": total, "rows": rows}


def write_token_report(report_path: Path, src: Path, zip_path: Path, estimate: dict[str, object], destination: str) -> None:
    rows = list(estimate.get("rows", []))
    total = int(estimate.get("estimated_total_tokens", 0))
    lines = [
        f"# {APP_NAME} Token Estimate",
        "",
        f"Version: {VERSION}",
        f"Source project: `{src}`",
        f"Output zip: `{zip_path}`",
        f"Destination preset: `{destination}`",
        f"Created: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Estimated text/code tokens: ~{total:,}",
        "- Method: rough local estimate using approximately 4 bytes/chars per token for text-like files.",
        "- This is a sizing aid, not an exact model tokenizer.",
        "",
        "## Largest token contributors",
        "",
    ]
    if not rows:
        lines.append("- none")
    else:
        for row in rows[:200]:
            lines.append(f"- `{row['path']}` — ~{int(row['estimated_tokens']):,} tokens — {human_bytes(int(row['size_bytes']))}")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def write_html_report(html_path: Path, src: Path, zip_path: Path, stage_files: list[dict[str, str | int]], removed: list[dict[str, str | int]], token_estimate: dict[str, object], destination: str) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    kept_total = sum(int(item["size_bytes"]) for item in stage_files)
    removed_total = sum(int(item["size_bytes"]) for item in removed)
    top_kept = stage_files[:100]
    top_removed = removed[:100]
    token_total = int(token_estimate.get("estimated_total_tokens", 0))
    def rows(items):
        out = []
        for item in items:
            out.append(f"<tr><td>{html.escape(str(item.get('path','')))}</td><td>{html.escape(str(item.get('type','file')))}</td><td>{html.escape(human_bytes(int(item.get('size_bytes',0))))}</td></tr>")
        return "\n".join(out) or "<tr><td colspan='3'>none</td></tr>"
    html_text = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Zip Stripper Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;line-height:1.45}}code{{background:#f4f4f4;padding:2px 4px}}table{{border-collapse:collapse;width:100%;margin:12px 0}}td,th{{border:1px solid #ddd;padding:6px 8px;text-align:left}}th{{background:#f7f7f7}}.card{{border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0}}</style>
</head><body>
<h1>Zip Stripper Report</h1>
<div class='card'><p><b>Version:</b> {html.escape(VERSION)}</p><p><b>Source:</b> <code>{html.escape(str(src))}</code></p><p><b>Zip:</b> <code>{html.escape(str(zip_path))}</code></p><p><b>Destination:</b> {html.escape(destination)}</p></div>
<div class='card'><h2>Summary</h2><ul><li>Files kept: {len(stage_files)}</li><li>Kept source size before compression: {html.escape(human_bytes(kept_total))}</li><li>Removed/skipped items: {len(removed)}</li><li>Measured removed/skipped bytes: {html.escape(human_bytes(removed_total))}</li><li>Estimated text/code tokens: ~{token_total:,}</li></ul></div>
<h2>Largest kept files</h2><table><tr><th>Path</th><th>Type</th><th>Size</th></tr>{rows(top_kept)}</table>
<h2>Largest removed/skipped items</h2><table><tr><th>Path</th><th>Type</th><th>Size</th></tr>{rows(top_removed)}</table>
</body></html>"""
    html_path.write_text(html_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Secret protection
# ---------------------------------------------------------------------------
_SECRET_CONTENT_RES = [(kind, re.compile(rx)) for kind, rx in SECRET_CONTENT_PATTERNS]
_SECRET_TOKEN_CONFIG_RES = {name: re.compile(rx) for name, rx in SECRET_TOKEN_CONFIGS.items()}


def is_private_env_name(name: str) -> bool:
    return name not in ENV_TEMPLATE_NAMES and (name == ".env" or name.startswith(".env."))


def secret_name_reason(rel: str) -> str | None:
    """Return why a file is a secret going by its path alone, or None."""
    parts = norm_rel_path(rel).split("/")
    for part in parts[:-1]:
        if part.lower() in SECRET_DIR_NAMES:
            return f"inside a {part} folder (keys/credentials)"
    name = parts[-1].lower()
    if any(marker in name for marker in SECRET_TEMPLATE_MARKERS):
        return None
    for pattern in SECRET_FILE_GLOBS:
        if fnmatch.fnmatchcase(name, pattern):
            return "file name says key/credentials"
    return None


def scan_text_for_secrets(path: Path) -> list[tuple[str, int]]:
    """Return (kind, line number) for each key-shaped string in a text file.

    The matched text itself is never returned, so it cannot be printed.
    Binary files and files over SECRET_SCAN_MAX_BYTES are skipped.
    """
    try:
        if path.stat().st_size > SECRET_SCAN_MAX_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in data[:8192]:
        return []
    text = data.decode("utf-8", errors="ignore")
    hits: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

    def add(kind: str, start: int) -> None:
        key = (kind, text.count("\n", 0, start) + 1)
        if key not in seen:
            seen.add(key)
            hits.append(key)

    for kind, rx in _SECRET_CONTENT_RES:
        for match in rx.finditer(text):
            add(kind, match.start())
    config_rx = _SECRET_TOKEN_CONFIG_RES.get(path.name.lower())
    if config_rx:
        for match in config_rx.finditer(text):
            add(f"{path.name} login token/password", match.start())
    hits.sort(key=lambda hit: hit[1])
    return hits


def describe_secret_hits(hits: list[tuple[str, int]]) -> str:
    by_kind: dict[str, list[int]] = {}
    for kind, line in hits:
        by_kind.setdefault(kind, []).append(line)
    parts = []
    for kind, lines in by_kind.items():
        shown = ", ".join(str(n) for n in lines[:5]) + (" ..." if len(lines) > 5 else "")
        parts.append(f"{kind} (line {shown})")
    return "; ".join(parts)


def remove_secrets_from_stage(
    stage: Path,
    keep_secret_paths: set[str] | None = None,
    keep_env: bool = False,
    redactor=None,
) -> list[dict[str, object]]:
    """Find secret files in the staged copy and delete them from the copy.

    Runs after every other rule, so nothing (keep-paths, .zipstripperignore
    keep rules, smart keeps) can sneak a secret through. Only paths named in
    keep_secret_paths survive; those are still listed.

    redactor (Zip Stripper Pro): for files flagged only by their contents, a
    callable(path) -> bool that blanks the keys out in place and returns True
    when the file is now clean; such files stay in the zip, marked redacted.
    Files that are secrets by name are always left out.
    """
    keep_secret_paths = keep_secret_paths or set()
    findings: list[dict[str, object]] = []
    for root, dirs, files in os.walk(stage):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not (root_path / d).is_symlink()]
        for filename in files:
            target = root_path / filename
            rel = target.relative_to(stage).as_posix()
            if keep_env and is_private_env_name(filename):
                continue
            reason = secret_name_reason(rel)
            by_content = False
            if reason is None:
                hits = scan_text_for_secrets(target)
                if hits:
                    reason = describe_secret_hits(hits)
                    by_content = True
            if reason is None:
                continue
            try:
                size = target.stat().st_size
            except OSError:
                size = 0
            kept = path_is_exact_or_under(rel, keep_secret_paths)
            if not kept and by_content and redactor is not None:
                try:
                    cleaned = bool(redactor(target)) and not scan_text_for_secrets(target)
                except Exception:  # noqa: BLE001 - a failed redaction must fall back to leaving the file out
                    cleaned = False
                if cleaned:
                    findings.append({"type": "secret", "path": rel, "size_bytes": size, "reason": reason, "kept": False, "redacted": True})
                    continue
            if not kept:
                try:
                    target.unlink()
                except OSError:
                    pass
            findings.append({"type": "secret", "path": rel, "size_bytes": size, "reason": reason, "kept": kept})
    findings.sort(key=lambda item: str(item["path"]))
    return findings


def print_secret_banner(findings: list[dict[str, object]]) -> None:
    if not findings:
        return
    redacted = [f for f in findings if f.get("redacted")]
    removed = [f for f in findings if not f["kept"] and not f.get("redacted")]
    kept = [f for f in findings if f["kept"]]
    print("", flush=True)
    print("!" * 64)
    print("  SECRETS FOUND - LEFT OUT OF THE ZIP" if removed else ("  SECRETS FOUND - KEYS BLANKED OUT" if redacted else "  SECRETS FOUND - KEPT BECAUSE YOU ASKED"))
    print("!" * 64)
    if removed:
        print("These files look like passwords, keys or login tokens. They were NOT put")
        print("in the ZIP. (The secret itself is never shown here.)")
        for item in removed:
            print(f"  LEFT OUT  {item['path']}  ->  {item['reason']}")
    if redacted:
        print("Keys were blanked out of these files (Pro), so the files are in the ZIP without them:")
        for item in redacted:
            print(f"  BLANKED   {item['path']}  ->  {item['reason']}")
    if kept:
        print("These look like secrets but you asked to keep them (--keep-secrets-file):")
        for item in kept:
            print(f"  KEPT!     {item['path']}  ->  {item['reason']}")
    print("If one of these is safe to share, re-run with --keep-secrets-file PATH.")
    print("If a real key was in a source file, consider replacing that key with a new one.")
    print("!" * 64, flush=True)


# ---------------------------------------------------------------------------
# .gitignore support
# ---------------------------------------------------------------------------
def _gitignore_glob_to_regex(pattern: str) -> str:
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1:end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = end + 1
                continue
        elif c == "\\" and i + 1 < n:
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def parse_gitignore_line(raw_line: str):
    """Return (regex, negate, dir_only) for one .gitignore line, or None."""
    line = raw_line.rstrip("\r\n")
    stripped = line.rstrip(" ")
    if stripped.endswith("\\") and len(stripped) < len(line):
        stripped += " "
    line = stripped
    if not line or line.startswith("#"):
        return None
    negate = line.startswith("!")
    if negate:
        line = line[1:]
    dir_only = line.endswith("/")
    line = line.rstrip("/")
    if not line:
        return None
    anchored = "/" in line
    body = _gitignore_glob_to_regex(line.lstrip("/"))
    if not anchored:
        body = "(?:.*/)?" + body
    flags = re.IGNORECASE if os.name == "nt" else 0
    try:
        return re.compile(body, flags), negate, dir_only
    except re.error:
        return None


def load_gitignore_rules(gitignore_path: Path, base_rel: str) -> list[tuple[str, object, bool, bool]]:
    rules = []
    try:
        text = gitignore_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return rules
    for raw_line in text.splitlines():
        parsed = parse_gitignore_line(raw_line)
        if parsed:
            regex, negate, dir_only = parsed
            rules.append((base_rel, regex, negate, dir_only))
    return rules


def gitignore_ignored(rules: list[tuple[str, object, bool, bool]], rel: str, is_dir: bool) -> bool:
    """Apply rules in order (root file first, deeper files later); last match wins."""
    ignored = False
    for base, regex, negate, dir_only in rules:
        if dir_only and not is_dir:
            continue
        if base:
            if not rel.startswith(base + "/"):
                continue
            sub = rel[len(base) + 1:]
        else:
            sub = rel
        if regex.fullmatch(sub):  # type: ignore[attr-defined]
            ignored = not negate
    return ignored


def find_gitignored_paths(src: Path) -> dict[str, str]:
    """Return {relative path: "dir" | "file"} for everything the project's
    .gitignore files (root and nested) say to leave out. An ignored folder is
    returned once and not walked into, just like git."""
    found: dict[str, str] = {}
    inherited: dict[str, list] = {"": []}
    for root, dirs, files in os.walk(src, topdown=True):
        root_path = Path(root)
        rel_root = "" if root_path == src else rel_from(root_path, src)
        rules = list(inherited.pop(rel_root, []))
        gitignore = root_path / ".gitignore"
        if gitignore.is_file():
            rules.extend(load_gitignore_rules(gitignore, rel_root))
        next_dirs = []
        for dirname in dirs:
            rel = f"{rel_root}/{dirname}" if rel_root else dirname
            if (root_path / dirname).is_symlink():
                continue
            if rules and gitignore_ignored(rules, rel, True):
                found[rel] = "dir"
                continue
            if dirname in DEFAULT_STRIP_DIRS:
                continue  # stripped anyway; no need to walk it
            inherited[rel] = rules
            next_dirs.append(dirname)
        dirs[:] = next_dirs
        if rules:
            for filename in files:
                rel = f"{rel_root}/{filename}" if rel_root else filename
                if gitignore_ignored(rules, rel, False):
                    found[rel] = "file"
    return found


# ---------------------------------------------------------------------------
# Duplicate files and big media
# ---------------------------------------------------------------------------
def file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def is_media_file(rel: str) -> bool:
    return Path(rel).suffix.lower() in MEDIA_SUFFIXES


def find_duplicate_and_media_drops(
    src: Path,
    candidates: list[dict[str, str | int]],
    protected: set[str],
    keep_media: bool = False,
    keep_duplicates: bool = False,
    media_cutoff_kb: int = DEFAULT_MEDIA_CUTOFF_KB,
) -> dict[str, list[dict[str, object]]]:
    """Pick big images/media and exact duplicate files to leave out.

    protected paths (user keep rules, smart keeps) are never picked. For each
    set of identical files the shortest/shallowest copy is kept.
    """
    media: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []
    cutoff = max(0, int(media_cutoff_kb)) * 1024
    media_paths: set[str] = set()
    if not keep_media:
        for item in candidates:
            rel = str(item["path"])
            size = int(item["size_bytes"])
            if size > cutoff and is_media_file(rel) and not path_is_exact_or_under(rel, protected):
                media.append({"type": "big-media", "path": rel, "size_bytes": size})
                media_paths.add(rel)
    if not keep_duplicates:
        by_size: dict[int, list[dict[str, str | int]]] = {}
        for item in candidates:
            size = int(item["size_bytes"])
            if size >= DUPLICATE_MIN_BYTES and str(item["path"]) not in media_paths:
                by_size.setdefault(size, []).append(item)
        for size, group in by_size.items():
            if len(group) < 2:
                continue
            by_hash: dict[str, list[str]] = {}
            for item in group:
                rel = str(item["path"])
                digest = file_sha256(src / rel)
                if digest:
                    by_hash.setdefault(digest, []).append(rel)
            for rels in by_hash.values():
                if len(rels) < 2:
                    continue
                ordered = sorted(rels, key=duplicate_preference_score)
                protected_copies = [r for r in ordered if path_is_exact_or_under(r, protected)]
                keeper = protected_copies[0] if protected_copies else ordered[0]
                for rel in ordered:
                    if rel == keeper or path_is_exact_or_under(rel, protected):
                        continue
                    duplicates.append({"type": "duplicate", "path": rel, "size_bytes": size, "same_as": keeper})
    media.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    duplicates.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    return {"media": media, "duplicates": duplicates}


def biggest_token_folders(rows: list[dict[str, object]], limit: int = 8) -> list[dict[str, object]]:
    """Group the token estimate by folder (up to two levels deep)."""
    totals: dict[str, list[int]] = {}
    for row in rows:
        parts = str(row["path"]).split("/")
        folder = "/".join(parts[:-1][:2]) + "/" if len(parts) > 1 else "(files at the top)"
        entry = totals.setdefault(folder, [0, 0])
        entry[0] += int(row["estimated_tokens"])
        entry[1] += int(row["size_bytes"])
    ordered = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)
    return [{"path": k, "estimated_tokens": v[0], "size_bytes": v[1]} for k, v in ordered[:limit]]


def print_too_big_warning(token_estimate: dict[str, object]) -> None:
    total = int(token_estimate.get("estimated_total_tokens", 0))
    print("")
    print("================================================================")
    print("  HEADS UP: STILL TOO BIG FOR ONE AI CHAT")
    print("================================================================")
    print(f"The ZIP holds about {total:,} tokens of text (tokens = word pieces an AI reads).")
    print(f"Most AI chats can read roughly {AI_CHAT_COMFORT_TOKENS:,} at once, so the AI will only see part of it.")
    print("Biggest remaining folders:")
    for row in biggest_token_folders(list(token_estimate.get("rows", []))):
        print(f"  {'~' + format(int(row['estimated_tokens']), ','):>11} tokens  {human_bytes(int(row['size_bytes'])):>10}  {row['path']}")
    print("To trim: put a folder name in .zipstripperignore, or use --drop-path FOLDER, or --profile source.")


def build_rule_sets(keep_git: bool, keep_vendor: bool):
    strip_dirs = set(DEFAULT_STRIP_DIRS)
    if keep_git:
        strip_dirs.discard(".git")
    if keep_vendor:
        strip_dirs.discard("vendor")
    return (
        strip_dirs,
        set(DEFAULT_STRIP_DIR_SUFFIXES),
        set(DEFAULT_STRIP_FILES),
        set(DEFAULT_STRIP_FILE_PREFIXES),
        set(DEFAULT_STRIP_SUFFIXES),
        set(DEFAULT_STRIP_ARCHIVE_SUFFIXES),
    )


def should_strip_dir(path: Path, strip_dirs: set[str], strip_dir_suffixes: set[str]) -> bool:
    name = path.name
    if name in strip_dirs:
        return True
    return any(name.endswith(suffix) for suffix in strip_dir_suffixes)


def should_strip_file(
    path: Path,
    strip_files: set[str],
    strip_prefixes: set[str],
    strip_suffixes: set[str],
    strip_archive_suffixes: set[str],
    keep_env: bool,
    keep_archives: bool,
) -> bool:
    name = path.name
    lower_name = name.lower()

    if name in strip_files:
        return True

    if not keep_env:
        if name not in ENV_TEMPLATE_NAMES and any(name == prefix or name.startswith(prefix + ".") for prefix in strip_prefixes):
            return True

    if any(lower_name.endswith(suffix.lower()) for suffix in strip_suffixes):
        return True

    if not keep_archives and any(lower_name.endswith(suffix.lower()) for suffix in strip_archive_suffixes):
        return True

    return False


def rel_from(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def norm_rel_path(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip().strip("/")


def normalize_path_set(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    out: set[str] = set()
    for value in values or []:
        cleaned = norm_rel_path(value)
        if cleaned:
            out.add(cleaned)
    return out


def lower_rel(value: str | Path) -> str:
    return norm_rel_path(value).lower()


def has_any_archive_suffix(rel: str) -> bool:
    lower = rel.lower()
    return any(lower.endswith(suffix.lower()) for suffix in DEFAULT_STRIP_ARCHIVE_SUFFIXES)


def has_any_data_suffix(rel: str) -> bool:
    lower = rel.lower()
    return any(lower.endswith(suffix.lower()) for suffix in SMART_LARGE_DATA_SUFFIXES)


def looks_like_source_file(rel: str) -> bool:
    lower = rel.lower()
    name = lower.rsplit("/", 1)[-1]
    if name in {"readme", "license", "makefile", "dockerfile"}:
        return True
    return any(lower.endswith(suffix) for suffix in SMART_SOURCE_SUFFIXES)


def looks_like_source_profile_file(rel: str) -> bool:
    lower = lower_rel(rel)
    name = lower.rsplit("/", 1)[-1]
    if name in SOURCE_KEEP_FILENAMES:
        return True
    if any(lower.endswith(suffix) for suffix in SOURCE_PROFILE_SUFFIXES):
        return True
    return False


def source_drop_reason(rel: str, size_bytes: int) -> str | None:
    """Return a Source Only drop reason, or None to keep.

    The Source Only profile is for ChatGPT/Claude/Gemini code review of the
    actual project system. It keeps source/config/docs/tests, and removes historical
    run state, raw datasets, archives, and bulky generated artifacts.
    """
    lower = lower_rel(rel)
    parts = lower.split("/") if lower else []
    if not parts:
        return None

    if parts[0] in SOURCE_DROP_TOP_LEVELS:
        return "source profile: top-level run/data/artifact area"

    if any(lower == prefix.rstrip("/") or lower.startswith(prefix) for prefix in SOURCE_DROP_PREFIXES):
        return "source profile: domain data folder"

    marker_path = "/" + lower
    if any(marker in marker_path for marker in SOURCE_DROP_MARKERS):
        return "source profile: raw/download/state artifact path"

    if has_any_archive_suffix(lower):
        return "source profile: archive/binary artifact"

    if has_any_data_suffix(lower) and size_bytes >= 128 * 1024:
        return "source profile: dataset/raw data artifact"

    binary_suffixes = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".docx",
        ".pptx", ".xlsx", ".db", ".sqlite", ".sqlite3", ".pkl", ".pickle",
    }
    if any(lower.endswith(suffix) for suffix in binary_suffixes):
        return "source profile: binary/document artifact"

    if size_bytes >= 2 * 1024 * 1024 and not looks_like_source_profile_file(lower):
        return "source profile: large non-source file"

    return None


def build_source_plan(src: Path, target_mb: int | None, exclude_paths: set[str] | None = None) -> dict[str, object]:
    """Build an automatic source/system-file selection plan.

    This intentionally drops huge state/data/artifact trees. It is meant for
    handing source/system files to an AI, not for reproducing a full historical
    run with all artifacts included.
    """
    scan = scan_project(src, keep_git=False, keep_env=False, keep_archives=True, keep_vendor=False)
    all_files = [item for item in scan["kept_files"] if not path_is_exact_or_under(str(item["path"]), exclude_paths or set())]

    drop_paths: set[str] = set()
    reasons: dict[str, str] = {}

    # Drop known bulky directories even before file-level evaluation. This lets
    # clean-copy mode skip whole trees such as state/ instead of walking/copying them.
    for top in sorted(SOURCE_DROP_TOP_LEVELS):
        if (src / top).exists():
            drop_paths.add(top)
            reasons[top] = "source profile: top-level run/data/artifact area"
    for prefix in sorted(SOURCE_DROP_PREFIXES):
        prefix_clean = prefix.rstrip("/")
        if (src / prefix_clean).exists():
            drop_paths.add(prefix_clean)
            reasons[prefix_clean] = "source profile: domain data folder"

    for item in all_files:
        rel = str(item["path"])
        if path_is_exact_or_under(rel, drop_paths):
            continue
        reason = source_drop_reason(rel, int(item["size_bytes"]))
        if reason:
            drop_paths.add(rel)
            reasons[rel] = reason

    # If the source selection is still too large, trim non-source large files first.
    target_bytes = None if not target_mb or target_mb <= 0 else int(target_mb) * 1024 * 1024
    budget_drops: list[dict[str, str | int]] = []
    if target_bytes is not None:
        estimated = sum(int(item["size_bytes"]) for item in all_files if not path_is_exact_or_under(str(item["path"]), drop_paths))
        if estimated > target_bytes:
            candidates = []
            for item in all_files:
                rel = str(item["path"])
                size = int(item["size_bytes"])
                if path_is_exact_or_under(rel, drop_paths):
                    continue
                if looks_like_source_profile_file(rel) and size < 5 * 1024 * 1024:
                    continue
                if size < 512 * 1024:
                    continue
                candidates.append(item)
            candidates.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
            for item in candidates:
                if estimated <= target_bytes:
                    break
                rel = str(item["path"])
                size = int(item["size_bytes"])
                drop_paths.add(rel)
                reasons[rel] = "source profile: automatic size-budget reduction"
                budget_drops.append(item)
                estimated -= size

    kept_files = [item for item in all_files if not path_is_exact_or_under(str(item["path"]), drop_paths)]
    dropped_files = [item for item in all_files if path_is_exact_or_under(str(item["path"]), drop_paths)]
    kept_total = sum(int(item["size_bytes"]) for item in kept_files)
    dropped_total = sum(int(item["size_bytes"]) for item in dropped_files)

    return {
        "drop_paths": drop_paths,
        "reasons": reasons,
        "kept_files": sorted(kept_files, key=lambda item: int(item["size_bytes"]), reverse=True),
        "dropped_files": sorted(dropped_files, key=lambda item: int(item["size_bytes"]), reverse=True),
        "budget_drops": budget_drops,
        "kept_total": kept_total,
        "dropped_total": dropped_total,
        "target_mb": target_mb,
    }


def print_source_summary(plan: dict[str, object], quiet: bool = False) -> None:
    if quiet:
        return
    kept_files = list(plan.get("kept_files", []))
    dropped_files = list(plan.get("dropped_files", []))
    print("")
    print("================================================================")
    print("  SOURCE ONLY PACKAGING PLAN")
    print("================================================================")
    print("Automatic mode is on. It keeps source/config/docs/tests and removes")
    print("historical state, raw datasets, downloads, duplicate packets, and binaries.")
    print(f"Target rough source size: {plan.get('target_mb')} MB")
    print(f"Estimated kept source/system files: {len(kept_files)} | {human_bytes(int(plan.get('kept_total', 0)))}")
    print(f"Estimated omitted data/artifact files: {len(dropped_files)} | {human_bytes(int(plan.get('dropped_total', 0)))}")
    print("Largest kept files:")
    for item in kept_files[:10]:
        print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")
    print("Largest omitted files:")
    for item in dropped_files[:10]:
        print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")


def write_source_plan_report(report_path: Path, src: Path, plan: dict[str, object]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    reasons = dict(plan.get("reasons", {}))
    kept_files = list(plan.get("kept_files", []))
    dropped_files = list(plan.get("dropped_files", []))
    lines = [
        f"# {APP_NAME} Source Selection Report",
        "",
        f"Version: {VERSION}",
        f"Source project: `{src}`",
        f"Created: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Purpose",
        "",
        "This package is intended to contain project source/system files for AI review, not the full historical run state, raw datasets, dependency folders, build artifacts, or bulky generated outputs.",
        "",
        "## Summary",
        "",
        f"- Target rough source size: {plan.get('target_mb')} MB",
        f"- Kept files: {len(kept_files)}",
        f"- Estimated kept bytes before compression: {human_bytes(int(plan.get('kept_total', 0)))}",
        f"- Omitted files: {len(dropped_files)}",
        f"- Estimated omitted bytes: {human_bytes(int(plan.get('dropped_total', 0)))}",
        "",
        "## What this mode keeps",
        "",
        "- Python/source files",
        "- PowerShell/batch/shell scripts",
        "- README/docs/config files",
        "- tests and small fixtures",
        "- project metadata such as requirements and pyproject files",
        "",
        "## What this mode omits",
        "",
        "- `state/` historical run outputs and packets",
        "- `domains/data/` and raw dataset folders",
        "- download/raw/physics-data folders",
        "- archive/binary artifacts such as `.zip`, `.gz`, `.evt`, `.dat`, `.sf`, `.pkl`",
        "- caches, virtual environments, dependency folders, build outputs, logs",
        "",
        "## Largest kept files",
        "",
    ]
    for item in kept_files[:250]:
        lines.append(f"- `{item['path']}` — {human_bytes(int(item['size_bytes']))}")
    if not kept_files:
        lines.append("- none")
    lines.extend(["", "## Largest omitted files", ""])
    for item in dropped_files[:500]:
        rel = str(item["path"])
        lines.append(f"- `{rel}` — {human_bytes(int(item['size_bytes']))} — {reasons.get(rel, 'covered by dropped parent path')}")
    if not dropped_files:
        lines.append("- none")
    lines.extend(["", "## Omitted paths / rules", ""])
    for rel, reason in sorted(reasons.items()):
        lines.append(f"- `{rel}` — {reason}")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def looks_like_evidence_packet(rel: str) -> bool:
    lower = lower_rel(rel)
    name = lower.rsplit("/", 1)[-1]
    if not has_any_archive_suffix(lower):
        return False
    return any(keyword in lower or keyword in name for keyword in SMART_EVIDENCE_KEYWORDS)


def is_raw_or_download_path(rel: str) -> bool:
    lower = "/" + lower_rel(rel)
    return any(marker in lower for marker in SMART_RAW_PATH_MARKERS)


def duplicate_preference_score(rel: str) -> tuple[int, int, int, str]:
    """Lower score is better for keeping one duplicate packet copy."""
    lower = lower_rel(rel)
    nested_penalty = 0
    if "/packet/artifacts/" in ("/" + lower):
        nested_penalty += 4
    if "/audit_context_packet/" in ("/" + lower):
        nested_penalty += 3
    if "/reviewer_packet_related/" in ("/" + lower):
        nested_penalty += 2
    depth = lower.count("/")
    length = len(lower)
    return (nested_penalty, depth, length, lower)


def classify_smart_drop(rel: str, size_bytes: int, target_pressure: bool = False) -> str | None:
    """Return a smart-drop reason, or None to keep.

    The rule favors source and audit trail visibility over raw data hoarding.
    Evidence-shaped zip packets are preserved separately by build_smart_plan().
    """
    lower = lower_rel(rel)
    archive_like = has_any_archive_suffix(lower)
    evidence_like = looks_like_evidence_packet(lower)

    if evidence_like:
        return None

    if archive_like:
        return "non-evidence archive/binary"

    if is_raw_or_download_path(lower) and size_bytes >= 1024 * 1024:
        return "large raw/download/dataset file"

    if has_any_data_suffix(lower) and size_bytes >= 25 * 1024 * 1024 and not looks_like_source_file(lower):
        return "large data artifact"

    if target_pressure and size_bytes >= 5 * 1024 * 1024 and not looks_like_source_file(lower):
        return "auto size-budget reduction"

    return None


def build_smart_plan(
    src: Path,
    keep_git: bool,
    keep_env: bool,
    keep_archives: bool,
    keep_vendor: bool,
    target_mb: int | None,
    exclude_paths: set[str] | None = None,
) -> dict[str, object]:
    """Return keep/drop path choices and a readable explanation.

    This is the default intelligence layer: it keeps one best copy of each
    evidence-shaped archive packet, removes non-evidence archives/binaries,
    removes raw datasets/downloads, and then trims non-source large files until
    the rough pre-compression size target is satisfied.
    """
    scan = scan_project(src, keep_git=keep_git, keep_env=keep_env, keep_archives=True, keep_vendor=keep_vendor)
    # exclude_paths (e.g. .gitignore'd files) are already out; don't plan around them.
    all_files = [item for item in scan["kept_files"] if not path_is_exact_or_under(str(item["path"]), exclude_paths or set())]

    keep_paths: set[str] = set()
    drop_paths: set[str] = set()
    reasons: dict[str, str] = {}
    kept_evidence: list[dict[str, str | int]] = []
    duplicate_drops: list[dict[str, str | int]] = []

    evidence_groups: dict[tuple[str, int], list[dict[str, str | int]]] = {}
    for item in all_files:
        rel = str(item["path"])
        size = int(item["size_bytes"])
        if looks_like_evidence_packet(rel):
            key = (Path(rel).name.lower(), size)
            evidence_groups.setdefault(key, []).append(item)

    for group in evidence_groups.values():
        ordered = sorted(group, key=lambda item: duplicate_preference_score(str(item["path"])))
        keeper = ordered[0]
        keep_paths.add(str(keeper["path"]))
        kept_evidence.append(keeper)
        for duplicate in ordered[1:]:
            rel = str(duplicate["path"])
            drop_paths.add(rel)
            reasons[rel] = "duplicate evidence packet copy; kept shortest/best copy"
            duplicate_drops.append(duplicate)

    for item in all_files:
        rel = str(item["path"])
        if rel in keep_paths or rel in drop_paths:
            continue
        reason = classify_smart_drop(rel, int(item["size_bytes"]))
        if reason:
            drop_paths.add(rel)
            reasons[rel] = reason

    # Estimate and trim if a rough pre-compression budget was provided.
    target_bytes = None if not target_mb or target_mb <= 0 else int(target_mb) * 1024 * 1024
    def estimated_kept_size() -> int:
        total = 0
        for item in all_files:
            rel = str(item["path"])
            if rel in drop_paths:
                continue
            # Without keep_paths, archive/binary files would be stripped later.
            if has_any_archive_suffix(rel) and not keep_archives and rel not in keep_paths:
                continue
            total += int(item["size_bytes"])
        return total

    size_budget_drops: list[dict[str, str | int]] = []
    if target_bytes is not None:
        estimated = estimated_kept_size()
        if estimated > target_bytes:
            candidates = []
            for item in all_files:
                rel = str(item["path"])
                size = int(item["size_bytes"])
                if rel in keep_paths or rel in drop_paths:
                    continue
                if looks_like_source_file(rel):
                    continue
                if size < 5 * 1024 * 1024:
                    continue
                candidates.append(item)
            candidates.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
            for item in candidates:
                if estimated <= target_bytes:
                    break
                rel = str(item["path"])
                size = int(item["size_bytes"])
                drop_paths.add(rel)
                reasons[rel] = "auto size-budget reduction"
                size_budget_drops.append(item)
                estimated -= size

    return {
        "keep_paths": keep_paths,
        "drop_paths": drop_paths,
        "reasons": reasons,
        "kept_evidence": sorted(kept_evidence, key=lambda item: int(item["size_bytes"]), reverse=True),
        "duplicate_drops": sorted(duplicate_drops, key=lambda item: int(item["size_bytes"]), reverse=True),
        "size_budget_drops": sorted(size_budget_drops, key=lambda item: int(item["size_bytes"]), reverse=True),
        "estimated_kept_size": sum(int(item["size_bytes"]) for item in all_files if str(item["path"]) not in drop_paths),
        "target_mb": target_mb,
    }


def print_smart_summary(plan: dict[str, object], quiet: bool = False) -> None:
    if quiet:
        return
    kept_evidence = list(plan.get("kept_evidence", []))
    duplicate_drops = list(plan.get("duplicate_drops", []))
    size_budget_drops = list(plan.get("size_budget_drops", []))
    drop_paths = set(plan.get("drop_paths", set()))
    print("")
    print("================================================================")
    print("  SMART PACKAGING PLAN")
    print("================================================================")
    print("Automatic mode is on. It keeps source and one best copy of evidence-shaped packets,")
    print("then removes dependency/build/cache junk, duplicate nested packets, raw downloads,")
    print("large datasets, and non-evidence archives/binaries.")
    print(f"Target rough source size: {plan.get('target_mb')} MB")
    print(f"Evidence packets kept: {len(kept_evidence)}")
    print(f"Smart extra drops: {len(drop_paths)}")
    if kept_evidence:
        print("Largest evidence packets kept:")
        for item in kept_evidence[:8]:
            print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")
    if duplicate_drops:
        print("Duplicate packet copies auto-dropped:")
        for item in duplicate_drops[:8]:
            print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")
    if size_budget_drops:
        print("Largest size-budget drops:")
        for item in size_budget_drops[:8]:
            print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")


def write_smart_plan_report(report_path: Path, plan: dict[str, object]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {APP_NAME} Smart Plan",
        "",
        f"Version: {VERSION}",
        f"Created: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Target rough source size: {plan.get('target_mb')} MB",
        f"- Evidence packets kept: {len(list(plan.get('kept_evidence', [])))}",
        f"- Duplicate packet copies dropped: {len(list(plan.get('duplicate_drops', [])))}",
        f"- Size-budget drops: {len(list(plan.get('size_budget_drops', [])))}",
        f"- Total smart extra drop paths: {len(set(plan.get('drop_paths', set())))}",
        "",
        "## Evidence-shaped archives kept",
        "",
    ]
    for item in list(plan.get("kept_evidence", []))[:300]:
        lines.append(f"- `{item['path']}` — {human_bytes(int(item['size_bytes']))}")
    if not list(plan.get("kept_evidence", [])):
        lines.append("- none")
    lines.extend(["", "## Duplicate evidence packet copies dropped", ""])
    for item in list(plan.get("duplicate_drops", []))[:300]:
        lines.append(f"- `{item['path']}` — {human_bytes(int(item['size_bytes']))}")
    if not list(plan.get("duplicate_drops", [])):
        lines.append("- none")
    lines.extend(["", "## Smart drop paths and reasons", ""])
    reasons = dict(plan.get("reasons", {}))
    if not reasons:
        lines.append("- none")
    else:
        for rel, reason in sorted(reasons.items()):
            lines.append(f"- `{rel}` — {reason}")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def path_is_exact_or_under(rel: str, selected: set[str]) -> bool:
    if not selected:
        return False
    rel = norm_rel_path(rel)
    if rel in selected:
        return True
    # Check each parent folder ("a", "a/b", ...) with a set lookup instead of
    # scanning every selected path; selected paths can number in the thousands.
    index = rel.find("/")
    while index != -1:
        if rel[:index] in selected:
            return True
        index = rel.find("/", index + 1)
    return False


def path_is_ancestor_of_selected(rel: str, selected: set[str]) -> bool:
    rel = norm_rel_path(rel)
    for item in selected:
        if item.startswith(rel + "/"):
            return True
    return False


def folder_size_bytes(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for filename in files:
            p = Path(root) / filename
            try:
                if not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
    return total


def top_level_sizes_from_files(file_items: list[dict[str, str | int]]) -> list[dict[str, str | int]]:
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for item in file_items:
        rel = str(item["path"])
        top = rel.split("/", 1)[0]
        totals[top] = totals.get(top, 0) + int(item["size_bytes"])
        counts[top] = counts.get(top, 0) + 1
    rows = [{"path": k, "type": "top-level", "size_bytes": v, "file_count": counts[k]} for k, v in totals.items()]
    rows.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    return rows


def scan_project(
    src: Path,
    keep_git: bool = False,
    keep_env: bool = False,
    keep_archives: bool = False,
    keep_vendor: bool = False,
) -> dict[str, list[dict[str, str | int]]]:
    """Classify default-removed and default-kept items before copying.

    This provides the user a visible preflight size map. It is intentionally
    conservative: once a removable directory is found, it is listed as one item
    and its children are not listed separately.
    """
    strip_dirs, strip_dir_suffixes, strip_files, strip_prefixes, strip_suffixes, strip_archive_suffixes = build_rule_sets(keep_git, keep_vendor)
    removed: list[dict[str, str | int]] = []
    kept_files: list[dict[str, str | int]] = []
    symlinks: list[dict[str, str | int]] = []

    for root, dirs, files in os.walk(src, topdown=True):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for dirname in list(dirs):
            target = root_path / dirname
            rel = rel_from(target, src)
            try:
                if target.is_symlink():
                    symlinks.append({"type": "symlink", "path": rel, "size_bytes": 0})
                    continue
                if should_strip_dir(target, strip_dirs, strip_dir_suffixes):
                    removed.append({"type": "dir", "path": rel, "size_bytes": folder_size_bytes(target)})
                    continue
                kept_dirs.append(dirname)
            except OSError:
                removed.append({"type": "unreadable", "path": rel, "size_bytes": 0})
        dirs[:] = kept_dirs

        for filename in files:
            target = root_path / filename
            rel = rel_from(target, src)
            try:
                if target.is_symlink():
                    symlinks.append({"type": "symlink", "path": rel, "size_bytes": 0})
                    continue
                size = target.stat().st_size
                if should_strip_file(target, strip_files, strip_prefixes, strip_suffixes, strip_archive_suffixes, keep_env, keep_archives):
                    removed.append({"type": "file", "path": rel, "size_bytes": size})
                else:
                    kept_files.append({"type": "file", "path": rel, "size_bytes": size})
            except OSError:
                removed.append({"type": "unreadable", "path": rel, "size_bytes": 0})

    removed.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    kept_files.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    top_levels = top_level_sizes_from_files(kept_files)
    return {"removed": removed, "kept_files": kept_files, "top_levels": top_levels, "symlinks": symlinks}


def print_numbered_items(title: str, prefix: str, items: list[dict[str, str | int]], limit: int = 40) -> None:
    print("")
    print(title)
    print("-" * min(72, max(10, len(title))))
    if not items:
        print("  none")
        return
    for index, item in enumerate(items[:limit], 1):
        print(f"  {prefix}{index:<3} {human_bytes(int(item['size_bytes'])):>10}  {item['type']:<9} {item['path']}")
    if len(items) > limit:
        print(f"  ...and {len(items) - limit} more. Full lists will be written to CSV reports.")


def preflight_review(
    src: Path,
    keep_git: bool,
    keep_env: bool,
    keep_archives: bool,
    keep_vendor: bool,
    quiet: bool = False,
) -> tuple[set[str], set[str], bool]:
    """Return keep_paths, drop_paths, keep_archives from an interactive preflight."""
    if quiet:
        return set(), set(), keep_archives

    print("")
    print("================================================================")
    print("  PREFLIGHT SIZE REVIEW")
    print("================================================================")
    print("Scanning project so you can see what is being removed and what remains.")
    print("This may take a moment on very large folders.")

    scan = scan_project(src, keep_git=keep_git, keep_env=keep_env, keep_archives=keep_archives, keep_vendor=keep_vendor)
    removed = scan["removed"]
    kept_files = scan["kept_files"]
    top_levels = scan["top_levels"]
    removed_total = sum(int(item["size_bytes"]) for item in removed)
    kept_total = sum(int(item["size_bytes"]) for item in kept_files)

    print("")
    print(f"Default removed/skipped: {len(removed)} items | {human_bytes(removed_total)}")
    print(f"Default kept for zip:    {len(kept_files)} files | {human_bytes(kept_total)} before zip compression")

    print_numbered_items("Largest default-removed items. Type R numbers to KEEP them.", "R", removed, limit=40)
    print_numbered_items("Largest top-level areas still kept in the soon-to-be zip. Type K numbers to EXCLUDE them.", "K", top_levels, limit=25)
    print_numbered_items("Largest individual files still kept in the soon-to-be zip. Type F numbers to EXCLUDE them.", "F", kept_files, limit=25)

    print("")
    print("Choices:")
    print("  Enter      continue with defaults")
    print("  R1,R2      keep removed/skipped items R1 and R2")
    print("  K1,F3      additionally exclude kept top-level item K1 and kept file F3")
    print("  AZ         keep all archives/binaries such as .zip, .gz, .exe, .dll")
    print("  Q          cancel")
    print("")
    raw = input("Selection: ").strip()
    if raw.lower() in {"q", "quit", "cancel", "exit"}:
        raise KeyboardInterrupt("User cancelled")

    keep_paths: set[str] = set()
    drop_paths: set[str] = set()
    keep_archives_now = keep_archives
    tokens = [tok.strip().upper() for tok in raw.replace(";", ",").replace(" ", ",").split(",") if tok.strip()]
    for token in tokens:
        if token == "AZ":
            keep_archives_now = True
            continue
        if len(token) < 2:
            continue
        prefix = token[0]
        try:
            index = int(token[1:]) - 1
        except ValueError:
            continue
        if prefix == "R" and 0 <= index < min(40, len(removed)):
            keep_paths.add(str(removed[index]["path"]))
        elif prefix == "K" and 0 <= index < min(25, len(top_levels)):
            drop_paths.add(str(top_levels[index]["path"]))
        elif prefix == "F" and 0 <= index < min(25, len(kept_files)):
            drop_paths.add(str(kept_files[index]["path"]))

    if keep_paths:
        print("")
        print("Will keep these otherwise-removed items:")
        for p in sorted(keep_paths):
            print(f"  + {p}")
    if drop_paths:
        print("")
        print("Will additionally exclude these kept items:")
        for p in sorted(drop_paths):
            print(f"  - {p}")
    if keep_archives_now and not keep_archives:
        print("")
        print("Will keep all archive/binary artifacts for this run.")

    return keep_paths, drop_paths, keep_archives_now


def clean_copy_project(
    src: Path,
    stage: Path,
    keep_git: bool = False,
    keep_env: bool = False,
    keep_archives: bool = False,
    keep_vendor: bool = False,
    quiet: bool = False,
    keep_paths: set[str] | None = None,
    drop_paths: set[str] | None = None,
    drop_kinds: dict[str, str] | None = None,
) -> list[dict[str, str | int]]:
    """Copy src to stage while skipping heavy/private/generated items.

    keep_paths are relative paths that override default strip rules.
    drop_paths are relative paths to exclude even if they would normally be kept.
    """
    keep_paths = keep_paths or set()
    drop_paths = drop_paths or set()
    drop_kinds = drop_kinds or {}
    strip_dirs, strip_dir_suffixes, strip_files, strip_prefixes, strip_suffixes, strip_archive_suffixes = build_rule_sets(keep_git, keep_vendor)
    skipped: list[dict[str, str | int]] = []
    shown_skip_count = 0

    def record(kind: str, p: Path, size: int = 0) -> None:
        nonlocal shown_skip_count
        item = {"type": kind, "path": rel_from(p, src), "size_bytes": size}
        skipped.append(item)
        if shown_skip_count < 20:
            log(f"Skipping {kind}: {item['path']}", quiet)
        elif shown_skip_count == 20:
            log("Skipping more generated/heavy items...", quiet)
        shown_skip_count += 1

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        root_path = Path(directory)
        for name in names:
            p = root_path / name
            rel = rel_from(p, src)
            try:
                if path_is_exact_or_under(rel, drop_paths) and not path_is_exact_or_under(rel, keep_paths) and not path_is_ancestor_of_selected(rel, keep_paths):
                    ignored.add(name)
                    size = folder_size_bytes(p) if p.is_dir() else (p.stat().st_size if p.exists() else 0)
                    record(drop_kinds.get(rel) or ("extra-drop-dir" if p.is_dir() else "extra-drop-file"), p, size)
                    continue
                if p.is_symlink():
                    ignored.add(name)
                    record("symlink", p, 0)
                    continue
                if p.is_dir():
                    if should_strip_dir(p, strip_dirs, strip_dir_suffixes) and not path_is_exact_or_under(rel, keep_paths) and not path_is_ancestor_of_selected(rel, keep_paths):
                        ignored.add(name)
                        record("dir", p, folder_size_bytes(p))
                        continue
                if p.is_file():
                    if should_strip_file(p, strip_files, strip_prefixes, strip_suffixes, strip_archive_suffixes, keep_env, keep_archives) and not path_is_exact_or_under(rel, keep_paths):
                        ignored.add(name)
                        try:
                            size = p.stat().st_size
                        except OSError:
                            size = 0
                        record("file", p, size)
            except OSError:
                ignored.add(name)
                record("unreadable", p, 0)
        return ignored

    shutil.copytree(src, stage, ignore=ignore)
    skipped.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    return skipped


def copy_project_strict(src: Path, stage: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            p = Path(_directory) / name
            if p.is_symlink():
                ignored.add(name)
        return ignored
    shutil.copytree(src, stage, ignore=ignore)


def strip_project(
    stage: Path,
    keep_git: bool = False,
    keep_env: bool = False,
    keep_archives: bool = False,
    keep_vendor: bool = False,
    keep_paths: set[str] | None = None,
    drop_paths: set[str] | None = None,
    drop_kinds: dict[str, str] | None = None,
) -> list[dict[str, str | int]]:
    keep_paths = keep_paths or set()
    drop_paths = drop_paths or set()
    drop_kinds = drop_kinds or {}
    strip_dirs, strip_dir_suffixes, strip_files, strip_prefixes, strip_suffixes, strip_archive_suffixes = build_rule_sets(keep_git, keep_vendor)
    removed: list[dict[str, str | int]] = []

    for root, dirs, files in os.walk(stage, topdown=True):
        root_path = Path(root)
        for dirname in list(dirs):
            target = root_path / dirname
            rel = target.relative_to(stage).as_posix()
            should_drop = path_is_exact_or_under(rel, drop_paths) and not path_is_exact_or_under(rel, keep_paths) and not path_is_ancestor_of_selected(rel, keep_paths)
            should_strip = should_strip_dir(target, strip_dirs, strip_dir_suffixes) and not path_is_exact_or_under(rel, keep_paths) and not path_is_ancestor_of_selected(rel, keep_paths)
            if should_drop or should_strip:
                size = folder_size_bytes(target)
                shutil.rmtree(target, ignore_errors=True)
                removed.append({"type": (drop_kinds.get(rel) or "extra-drop-dir") if should_drop else "dir", "path": rel, "size_bytes": size})
                dirs.remove(dirname)
        for filename in files:
            target = root_path / filename
            rel = target.relative_to(stage).as_posix()
            should_drop = path_is_exact_or_under(rel, drop_paths) and not path_is_exact_or_under(rel, keep_paths)
            should_strip = should_strip_file(target, strip_files, strip_prefixes, strip_suffixes, strip_archive_suffixes, keep_env, keep_archives) and not path_is_exact_or_under(rel, keep_paths)
            if should_drop or should_strip:
                try:
                    size = target.stat().st_size
                except OSError:
                    size = 0
                try:
                    target.unlink()
                except OSError:
                    pass
                removed.append({"type": (drop_kinds.get(rel) or "extra-drop-file") if should_drop else "file", "path": rel, "size_bytes": size})
    removed.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    return removed


def list_stage_files(stage: Path) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for root, dirs, files in os.walk(stage):
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for filename in files:
            p = Path(root) / filename
            if p.is_symlink():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            rows.append({"type": "file", "path": p.relative_to(stage).as_posix(), "size_bytes": size})
    rows.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
    return rows


def make_zip(stage: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(stage):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for filename in files:
                p = Path(root) / filename
                if p.is_symlink():
                    continue
                zf.write(p, p.relative_to(stage))


def write_csv_report(csv_path: Path, rows: list[dict[str, str | int]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "type", "size_bytes", "size_human"])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "path": row.get("path", ""),
                "type": row.get("type", ""),
                "size_bytes": int(row.get("size_bytes", 0)),
                "size_human": human_bytes(int(row.get("size_bytes", 0))),
            })


def write_size_report(
    report_path: Path,
    src: Path,
    zip_path: Path,
    stage_files: list[dict[str, str | int]],
    removed: list[dict[str, str | int]],
    zip_size: int,
    keep_paths: set[str],
    drop_paths: set[str],
    contents_csv: Path,
    removed_csv: Path,
) -> None:
    kept_total = sum(int(item["size_bytes"]) for item in stage_files)
    removed_total = sum(int(item["size_bytes"]) for item in removed)
    top_levels = top_level_sizes_from_files(stage_files)
    lines = [
        f"# {APP_NAME} Size Report",
        "",
        f"Version: {VERSION}",
        f"Source project: `{src}`",
        f"Output zip: `{zip_path}`",
        f"Created: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Files in final zip: {len(stage_files)}",
        f"- Final zip source size before compression: {human_bytes(kept_total)}",
        f"- Final compressed zip size: {human_bytes(zip_size)}",
        f"- Removed/skipped items: {len(removed)}",
        f"- Removed/skipped measured bytes: {human_bytes(removed_total)}",
        f"- Full final-contents CSV: `{contents_csv.name}`",
        f"- Full removed/skipped CSV: `{removed_csv.name}`",
        "",
        "## Largest top-level areas in final zip source",
        "",
    ]
    for item in top_levels[:100]:
        lines.append(f"- `{item['path']}` — {human_bytes(int(item['size_bytes']))} across {item.get('file_count', '?')} files")
    lines.extend(["", "## Largest individual files in final zip source", ""])
    if not stage_files:
        lines.append("No files were kept.")
    else:
        for item in stage_files[:200]:
            lines.append(f"- `{item['path']}` — {human_bytes(int(item['size_bytes']))}")
    lines.extend(["", "## Largest removed/skipped items", ""])
    if not removed:
        lines.append("No matching heavy/private/generated items were removed or skipped.")
    else:
        for item in removed[:200]:
            lines.append(f"- `{item['path']}` ({item['type']}) — {human_bytes(int(item['size_bytes']))}")
    lines.extend(["", "## User choices", ""])
    lines.append("### Kept otherwise-removed items")
    if keep_paths:
        for p in sorted(keep_paths):
            lines.append(f"- `{p}`")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("### Additionally excluded kept items")
    if drop_paths:
        for p in sorted(drop_paths):
            lines.append(f"- `{p}`")
    else:
        lines.append("- none")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def write_receipt(
    receipt_path: Path,
    src: Path,
    zip_path: Path,
    before: int | None,
    after: int,
    zip_size: int,
    removed: list[dict[str, str | int]],
    keep_git: bool,
    keep_env: bool,
    keep_archives: bool,
    keep_vendor: bool,
    copy_then_strip: bool,
    size_report: Path,
    contents_csv: Path,
    removed_csv: Path,
    keep_paths: set[str],
    drop_paths: set[str],
    smart: bool = False,
    target_mb: int | None = None,
    smart_plan: Path | None = None,
    profile: str = "smart",
    source_plan: Path | None = None,
    max_zip_mb: int | None = None,
    destination: str = "generic",
    token_report: Path | None = None,
    html_report: Path | None = None,
    ignore_info: dict[str, object] | None = None,
    secret_findings: list[dict[str, object]] | None = None,
    gitignore_drops: set[str] | None = None,
    use_gitignore: bool = True,
    trim: dict[str, list[dict[str, object]]] | None = None,
    keep_media: bool = False,
    media_cutoff_kb: int = DEFAULT_MEDIA_CUTOFF_KB,
    token_estimate: dict[str, object] | None = None,
) -> None:
    removed_total = sum(int(item["size_bytes"]) for item in removed)
    action_word = "Removed" if copy_then_strip else "Skipped during clean copy / removed"
    secret_findings = secret_findings or []
    gitignore_drops = gitignore_drops or set()
    trim = trim or {"media": [], "duplicates": []}
    secrets_out = [f for f in secret_findings if not f["kept"] and not f.get("redacted")]
    secrets_redacted = [f for f in secret_findings if f.get("redacted")]
    secrets_kept = [f for f in secret_findings if f["kept"]]
    total_tokens = int((token_estimate or {}).get("estimated_total_tokens", 0))
    lines = [
        f"# {APP_NAME} Receipt",
        "",
        f"Version: {VERSION}",
        f"Source project: `{src}`",
        f"Output zip: `{zip_path}`",
        f"Created: {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"Mode: {'copy-then-strip strict mode' if copy_then_strip else 'fast clean-copy mode'}",
        f"Profile: {profile}",
        "",
    ]
    if secret_findings:
        lines.extend([
            "## !!! SECRETS FOUND !!!",
            "",
            "These files look like passwords, keys or login tokens. The secret text itself is never written here.",
            "",
        ])
        for item in secrets_out:
            lines.append(f"- LEFT OUT: `{item['path']}` — {item['reason']}")
        for item in secrets_redacted:
            lines.append(f"- KEYS BLANKED OUT, file kept (Pro): `{item['path']}` — {item['reason']}")
        for item in secrets_kept:
            lines.append(f"- KEPT ON PURPOSE (--keep-secrets-file): `{item['path']}` — {item['reason']}")
        lines.extend([
            "",
            "If one of these is safe to share, re-run with `--keep-secrets-file PATH` (or `keep-secret: PATH` in .zipstripperignore).",
            "",
        ])
    if total_tokens > AI_CHAT_FAR_BEYOND_TOKENS:
        lines.extend([
            "## Heads up: still too big for one AI chat",
            "",
            f"About {total_tokens:,} tokens of text. Most AI chats read roughly {AI_CHAT_COMFORT_TOKENS:,} at once, so the AI will only see part of it. Biggest remaining folders:",
            "",
        ])
        for row in biggest_token_folders(list((token_estimate or {}).get("rows", []))):
            lines.append(f"- `{row['path']}` — ~{int(row['estimated_tokens']):,} tokens — {human_bytes(int(row['size_bytes']))}")
        lines.append("")
    lines.extend([
        "## Summary",
        "",
        f"- Original copied size: {human_bytes(before)}",
        f"- Clean staged size before compression: {human_bytes(after)}",
        f"- Final zip size: {human_bytes(zip_size)}",
        f"- {action_word} item count: {len(removed)}",
        f"- Measured removed/skipped bytes: {human_bytes(removed_total)}",
        f"- Kept .git: {'yes' if keep_git else 'no'}",
        f"- Kept .env files: {'yes' if keep_env else 'no'}",
        f"- Kept archives/binaries: {'yes' if keep_archives else 'no'}",
        f"- Kept vendor folders: {'yes' if keep_vendor else 'no'}",
        f"- Secret files left out: {len(secrets_out)}" + (f" (kept on purpose: {len(secrets_kept)})" if secrets_kept else ""),
        f"- Files kept with keys blanked out (Pro): {len(secrets_redacted)}",
        f"- Big pictures shrunk instead of left out (Pro): {len(trim.get('shrunk', []))}",
        f"- .gitignore honoured: {'yes' if use_gitignore else 'no (--no-gitignore)'} — {len(gitignore_drops)} item(s) left out",
        f"- Exact duplicate files left out: {len(trim['duplicates'])}",
        f"- Big images/media left out: {'none (--keep-media)' if keep_media else str(len(trim['media'])) + f' (over {media_cutoff_kb} KB)'}",
        f"- Estimated text tokens in zip: ~{total_tokens:,}",
        f"- Smart mode: {'yes' if smart else 'no'}",
        f"- Smart target MB: {target_mb if target_mb else 'none'}",
        f"- Smart plan: `{smart_plan.name}`" if smart_plan else "- Smart plan: none",
        f"- Source selection report: `{source_plan.name}`" if source_plan else "- Source selection report: none",
        f"- Destination preset: {destination}",
        f"- Max zip MB warning threshold: {max_zip_mb if max_zip_mb else 'none'}",
        f"- Upload size status: {'OK under threshold' if (max_zip_mb and zip_size <= max_zip_mb * 1024 * 1024) else ('WARNING above threshold' if max_zip_mb else 'not checked')}",
        f"- .zipstripperignore loaded: {'yes' if (ignore_info and ignore_info.get('exists')) else 'no'}",
        f"- .zipstripperignore path: `{Path(ignore_info.get('path')).name}`" if (ignore_info and ignore_info.get('exists')) else "- .zipstripperignore path: none",
        f"- Token estimate report: `{token_report.name}`" if token_report else "- Token estimate report: none",
        f"- HTML report: `{html_report.name}`" if html_report else "- HTML report: none",
        f"- Size report: `{size_report.name}`",
        f"- Final contents CSV: `{contents_csv.name}`",
        f"- Removed/skipped CSV: `{removed_csv.name}`",
        "",
        "## User-selected keep paths",
        "",
    ])
    if keep_paths:
        for p in sorted(keep_paths):
            lines.append(f"- `{p}`")
    else:
        lines.append("- none")
    lines.extend(["", "## User-selected extra drop paths", ""])
    if drop_paths:
        for p in sorted(drop_paths):
            lines.append(f"- `{p}`")
    else:
        lines.append("- none")
    if gitignore_drops:
        lines.extend(["", "## Left out because the project's .gitignore lists them", ""])
        for rel in sorted(gitignore_drops)[:500]:
            lines.append(f"- `{rel}`")
        if len(gitignore_drops) > 500:
            lines.append(f"- ...and {len(gitignore_drops) - 500} more")
    if trim["duplicates"]:
        lines.extend(["", "## Exact duplicate copies left out (one copy kept)", ""])
        for item in trim["duplicates"][:500]:
            lines.append(f"- `{item['path']}` — same as `{item['same_as']}` — {human_bytes(int(item['size_bytes']))}")
        if len(trim["duplicates"]) > 500:
            lines.append(f"- ...and {len(trim['duplicates']) - 500} more")
    if trim["media"]:
        lines.extend(["", f"## Big images/media left out (over {media_cutoff_kb} KB; use --keep-media to keep)", ""])
        for item in trim["media"][:500]:
            lines.append(f"- `{item['path']}` — {human_bytes(int(item['size_bytes']))}")
        if len(trim["media"]) > 500:
            lines.append(f"- ...and {len(trim['media']) - 500} more")
    lines.extend(["", f"## {action_word} items", ""])
    if not removed:
        lines.append("No matching heavy/private/generated items were found.")
    else:
        for item in removed[:1000]:
            size = int(item["size_bytes"])
            size_text = human_bytes(size) if size else "size not measured"
            lines.append(f"- `{item['path']}` ({item['type']}, {size_text})")
        if len(removed) > 1000:
            lines.append(f"- ...and {len(removed) - 1000} more items")
    lines.extend([
        "",
        "## Notes",
        "",
        "The original project was not modified.",
        "Fast clean-copy mode skips folders such as `node_modules`, `.venv`, `venv`, `.git`, `__pycache__`, and `.pytest_cache` while copying instead of copying them first and deleting them later.",
        "Public env templates such as `.env.example` are preserved by default; private `.env*` files are removed unless `--keep-env` is used.",
        "Archive files such as `.zip`/`.gz` are removable by default. Use Manual Review, `--keep-path`, or `--keep-archives` when a specific artifact must be included.",
        "Every file is checked for passwords, API keys and private keys before zipping; files with a hit are left out unless named with `--keep-secrets-file`.",
        "The project's `.gitignore` files are honoured unless `--no-gitignore` is used.",
        "In smart/source mode exact duplicate files are kept once (`--keep-duplicates` to keep all) and big images/media are left out (`--keep-media` to keep them).",
    ])
    receipt_path.write_text("\n".join(lines), encoding="utf-8")


def strip_and_zip_project(
    src: Path,
    output_dir: Path,
    keep_git: bool = False,
    keep_env: bool = False,
    keep_archives: bool = False,
    keep_vendor: bool = False,
    copy_then_strip: bool = False,
    quiet: bool = False,
    review: bool = False,
    smart: bool = True,
    target_mb: int | None = SMART_DEFAULT_TARGET_MB,
    keep_paths: list[str] | set[str] | None = None,
    drop_paths: list[str] | set[str] | None = None,
    profile: str = "smart",
    max_zip_mb: int | None = CHATGPT_SAFE_ZIP_MB,
    destination: str = "generic",
    use_zipstripperignore: bool = True,
    zipstripperignore_path: Path | None = None,
    write_html: bool = True,
    write_token_estimate: bool = True,
    use_gitignore: bool = True,
    keep_media: bool = False,
    keep_duplicates: bool = False,
    media_cutoff_kb: int = DEFAULT_MEDIA_CUTOFF_KB,
    keep_secret_paths: list[str] | set[str] | None = None,
    library: bool = False,
    shrink_media: bool = False,
    changes_only: bool = False,
    redact_secrets: bool = False,
    fit_for: str | None = None,
) -> tuple[Path, Path, Path]:
    """Package one project.

    library=False writes the zip and every report side by side in output_dir
    (the original layout). library=True treats output_dir as the Zip Stripper
    Library: <library>/<Project>/<date_time>/ holds just the zip, with all
    reports tucked into a details/ folder plus zipstripper.json for the
    library web page.
    """
    redo_settings = {
        "profile": profile, "destination": destination, "keep_git": keep_git,
        "keep_env": keep_env, "keep_archives": keep_archives, "keep_vendor": keep_vendor,
        "use_gitignore": use_gitignore, "keep_media": keep_media,
        "keep_duplicates": keep_duplicates, "media_cutoff_kb": media_cutoff_kb,
        "keep_paths": sorted(normalize_path_set(keep_paths)),
        "drop_paths": sorted(normalize_path_set(drop_paths)),
        "keep_secret_paths": sorted(normalize_path_set(keep_secret_paths)),
        "shrink_media": shrink_media, "redact_secrets": redact_secrets,
        "fit_for": fit_for or None,
    }
    pro = None
    if shrink_media or changes_only or redact_secrets or fit_for:
        wanted = [name for flag, name in ((shrink_media, "Shrinking pictures"), (changes_only, "Only-what-changed ZIPs"),
                                          (redact_secrets, "Blanking out keys"), (fit_for, "Fit-to-AI packing")) if flag]
        pro = require_pro(" and ".join(wanted))
    if fit_for and str(fit_for).lower() not in FIT_PRESETS:
        raise ValueError(f"Unknown --fit-for value: {fit_for}. Use one of: {', '.join(sorted(FIT_PRESETS))}")
    if changes_only and not library:
        raise ValueError("Only-what-changed ZIPs need the Zip Stripper Library (don't use --output).")
    src = src.expanduser().resolve()
    if not src.exists() or not src.is_dir():
        raise ValueError(f"Project folder not found: {src}")

    keep_path_set = normalize_path_set(keep_paths)
    drop_path_set = normalize_path_set(drop_paths)
    keep_secret_set = normalize_path_set(keep_secret_paths)
    drop_kinds: dict[str, str] = {}
    destination = (destination or "generic").lower().strip()

    ignore_info: dict[str, object] | None = None
    if use_zipstripperignore:
        ignore_info = load_zipstripperignore(src, zipstripperignore_path)
        if ignore_info.get("exists"):
            settings = dict(ignore_info.get("settings", {}))
            if settings.get("profile") and profile == "smart":
                profile = str(settings["profile"]).lower().strip()
            if settings.get("destination") and destination == "generic":
                destination = str(settings["destination"]).lower().strip()
            if settings.get("target-mb") and target_mb == SMART_DEFAULT_TARGET_MB:
                try:
                    target_mb = int(str(settings["target-mb"]))
                except ValueError:
                    pass
            if settings.get("max-zip-mb") and max_zip_mb == CHATGPT_SAFE_ZIP_MB:
                try:
                    max_zip_mb = int(str(settings["max-zip-mb"]))
                except ValueError:
                    pass
            keep_path_set.update(expand_path_patterns(src, list(ignore_info.get("keep_patterns", []))))
            keep_secret_set.update(expand_path_patterns(src, list(ignore_info.get("keep_secret_patterns", []))))
            drop_path_set.update(expand_path_patterns(src, list(ignore_info.get("drop_patterns", []))))
            drop_path_set.difference_update(keep_path_set)
            log(f"Loaded {ZIPSTRIPPERIGNORE_NAME}: {ignore_info.get('path')}", quiet)

    preset = destination_defaults(destination)
    if target_mb == SMART_DEFAULT_TARGET_MB and destination != "generic":
        target_mb = int(preset["target_mb"])
    if max_zip_mb == CHATGPT_SAFE_ZIP_MB and destination != "generic":
        max_zip_mb = int(preset["max_zip_mb"])

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base = safe_name(src.name)
    stamp = now_stamp()
    if library:
        run_dir = output_dir / base / _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = run_dir.with_name(run_dir.name.split("~")[0] + f"~{suffix}")
        details_dir = run_dir / "details"
        details_dir.mkdir(parents=True)
        zip_path = run_dir / f"{base}_{stamp}.zip"
        receipt_path = details_dir / "Receipt.md"
        size_report_path = details_dir / "Size report.md"
        contents_csv = details_dir / "Files in the zip.csv"
        removed_csv = details_dir / "Left out.csv"
        smart_plan_path = details_dir / "Smart plan.md"
        source_plan_path = details_dir / "Source selection.md"
        token_report_path = details_dir / "Token estimate.md"
        html_report_path = details_dir / "Report.html"
        too_large_path = details_dir / "Too large - how to fix.md"
    else:
        zip_path = output_dir / f"{base}_AI_HANDOFF_{stamp}.zip"
        receipt_path = output_dir / f"{base}_ZIP_STRIPPER_RECEIPT_{stamp}.md"
        size_report_path = output_dir / f"{base}_ZIP_STRIPPER_SIZE_REPORT_{stamp}.md"
        contents_csv = output_dir / f"{base}_ZIP_CONTENTS_SIZE_REPORT_{stamp}.csv"
        removed_csv = output_dir / f"{base}_ZIP_REMOVED_SKIPPED_SIZE_REPORT_{stamp}.csv"
        smart_plan_path = output_dir / f"{base}_ZIP_STRIPPER_SMART_PLAN_{stamp}.md"
        source_plan_path = output_dir / f"{base}_ZIP_STRIPPER_SOURCE_SELECTION_{stamp}.md"
        token_report_path = output_dir / f"{base}_ZIP_STRIPPER_TOKEN_ESTIMATE_{stamp}.md"
        html_report_path = output_dir / f"{base}_ZIP_STRIPPER_REPORT_{stamp}.html"
        too_large_path = output_dir / f"{base}_ZIP_STRIPPER_TOO_LARGE_FIX_{stamp}.md"

    profile = (profile or "smart").lower().strip()
    if profile == "instrument":
        # Backward-compatible alias retained for older wrappers and user habits.
        profile = "source"
    if profile not in {"smart", "source", "plain"}:
        raise ValueError(f"Unknown profile: {profile}. Use smart, source, or plain.")
    if profile == "plain":
        smart = False
    if profile == "source":
        smart = False

    # Honour the project's own .gitignore files (root and nested). Explicit
    # keep rules (--keep-path, .zipstripperignore keep:) still win.
    gitignore_drops: set[str] = set()
    if use_gitignore:
        gitignore_drops = {rel for rel in find_gitignored_paths(src) if rel not in keep_path_set}
        for rel in gitignore_drops:
            drop_kinds[rel] = "gitignore"
        drop_path_set.update(gitignore_drops)
        if gitignore_drops:
            log(f".gitignore: leaving out {len(gitignore_drops)} item(s) the project's .gitignore lists.", quiet)

    smart_plan: dict[str, object] | None = None
    source_plan: dict[str, object] | None = None
    if profile == "source":
        log("Building Source Only selection plan...", quiet)
        source_plan = build_source_plan(src, target_mb=target_mb, exclude_paths=gitignore_drops)
        drop_path_set.update(set(source_plan.get("drop_paths", set())))
        # User keep selections win over source-profile drops, including dropped parent directories.
        drop_path_set.difference_update(keep_path_set)
        print_source_summary(source_plan, quiet=quiet)
        write_source_plan_report(source_plan_path, src, source_plan)

    if smart:
        log("Building smart packaging plan...", quiet)
        smart_plan = build_smart_plan(
            src,
            keep_git=keep_git,
            keep_env=keep_env,
            keep_archives=keep_archives,
            keep_vendor=keep_vendor,
            target_mb=target_mb,
            exclude_paths=gitignore_drops,
        )
        keep_path_set.update(set(smart_plan.get("keep_paths", set())))
        drop_path_set.update(set(smart_plan.get("drop_paths", set())))
        # Explicit keep selections always win over smart drops.
        drop_path_set.difference_update(keep_path_set)
        print_smart_summary(smart_plan, quiet=quiet)
        write_smart_plan_report(smart_plan_path, smart_plan)

    if review:
        chosen_keep, chosen_drop, chosen_keep_archives = preflight_review(
            src,
            keep_git=keep_git,
            keep_env=keep_env,
            keep_archives=keep_archives,
            keep_vendor=keep_vendor,
            quiet=quiet,
        )
        keep_path_set.update(chosen_keep)
        drop_path_set.update(chosen_drop)
        # Manual keep selections always win over drops.
        drop_path_set.difference_update(keep_path_set)
        keep_archives = chosen_keep_archives

    # AI-upload trimming: exact duplicate files and big images/media.
    trim: dict[str, list[dict[str, object]]] = {"media": [], "duplicates": []}
    if profile in {"smart", "source"} and not (keep_media and keep_duplicates):
        candidates = [
            item for item in scan_project(src, keep_git=keep_git, keep_env=keep_env, keep_archives=keep_archives, keep_vendor=keep_vendor)["kept_files"]
            if not path_is_exact_or_under(str(item["path"]), drop_path_set) or path_is_exact_or_under(str(item["path"]), keep_path_set)
        ]
        trim = find_duplicate_and_media_drops(
            src, candidates, keep_path_set,
            keep_media=keep_media, keep_duplicates=keep_duplicates, media_cutoff_kb=media_cutoff_kb,
        )
        if shrink_media and pro is not None and trim["media"]:
            # Pro: keep pictures that can be made smaller; shrink them in the copy below.
            shrinkable = [item for item in trim["media"] if pro.can_shrink(str(item["path"]))]
            shrink_paths = {str(item["path"]) for item in shrinkable}
            trim["media"] = [item for item in trim["media"] if str(item["path"]) not in shrink_paths]
            trim["to_shrink"] = shrinkable
        for item in trim["media"] + trim["duplicates"]:
            drop_path_set.add(str(item["path"]))
            drop_kinds[str(item["path"])] = str(item["type"])
        if trim["duplicates"]:
            log(f"Leaving out {len(trim['duplicates'])} exact duplicate file(s); one copy of each is kept.", quiet)
        if trim["media"]:
            log(f"Leaving out {len(trim['media'])} big image/media file(s) over {media_cutoff_kb} KB (use --keep-media to keep them).", quiet)

    log(f"Source: {src}", quiet)
    log(f"Output: {output_dir}", quiet)

    with tempfile.TemporaryDirectory(prefix="zip_stripper_") as tmp:
        stage = Path(tmp) / base
        before: int | None = None
        if copy_then_strip:
            log("Strict mode: measuring original size...", quiet)
            before = folder_size_bytes(src)
            log("Copying project first...", quiet)
            copy_project_strict(src, stage)
            log("Stripping copied project...", quiet)
            removed = strip_project(stage, keep_git=keep_git, keep_env=keep_env, keep_archives=keep_archives, keep_vendor=keep_vendor, keep_paths=keep_path_set, drop_paths=drop_path_set, drop_kinds=drop_kinds)
        else:
            log("Copying clean project. Heavy/generated/private folders are skipped during copy...", quiet)
            removed = clean_copy_project(
                src,
                stage,
                keep_git=keep_git,
                keep_env=keep_env,
                keep_archives=keep_archives,
                keep_vendor=keep_vendor,
                quiet=quiet,
                keep_paths=keep_path_set,
                drop_paths=drop_path_set,
                drop_kinds=drop_kinds,
            )
            # Defensive second pass; normally finds nothing, but catches edge cases.
            removed.extend(strip_project(stage, keep_git=keep_git, keep_env=keep_env, keep_archives=keep_archives, keep_vendor=keep_vendor, keep_paths=keep_path_set, drop_paths=drop_path_set, drop_kinds=drop_kinds))
            removed.sort(key=lambda item: int(item["size_bytes"]), reverse=True)

        # Secret sweep runs last, on the exact files that would go in the zip,
        # so no keep rule can let a key through. Only --keep-secrets-file can.
        log("Checking every file for passwords, keys and login tokens...", quiet)
        if pro is not None and trim.get("to_shrink"):
            log(f"Pro: shrinking {len(trim['to_shrink'])} big picture(s)...", quiet)
            shrunk, still_big = pro.shrink_images(stage, [str(i["path"]) for i in trim["to_shrink"]], media_cutoff_kb)
            trim["shrunk"] = shrunk
            for rel in still_big:
                (stage / rel).unlink(missing_ok=True)
                trim["media"].append({"type": "big-media", "path": rel, "size_bytes": next((int(i["size_bytes"]) for i in trim["to_shrink"] if i["path"] == rel), 0)})
        secret_findings = remove_secrets_from_stage(
            stage, keep_secret_set, keep_env=keep_env,
            redactor=pro.redact_file if (pro is not None and redact_secrets) else None,
        )
        print_secret_banner(secret_findings)
        removed.extend(
            {"type": "secret", "path": item["path"], "size_bytes": item["size_bytes"]}
            for item in secret_findings if not item["kept"]
        )
        removed.sort(key=lambda item: int(item["size_bytes"]), reverse=True)

        if profile == "source" and source_plan_path.exists():
            internal_report = stage / "_ZIP_STRIPPER" / "SOURCE_SELECTION_REPORT.md"
            internal_report.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_plan_path, internal_report)

        # The file list is taken from the full clean copy, so the next
        # "only what changed" ZIP can compare against everything.
        manifest = stage_manifest(stage) if library else {}
        changes: dict[str, object] | None = None
        if changes_only and pro is not None:
            previous = find_previous_entry(output_dir, src, exclude=zip_path.parent)
            changes = pro.keep_only_changes(stage, manifest, previous)
            log(f"Pro: only what changed - {changes['summary']}", quiet)

        log("Measuring cleaned copy and building final size report...", quiet)
        stage_files = list_stage_files(stage)
        after = sum(int(item["size_bytes"]) for item in stage_files)
        write_csv_report(contents_csv, stage_files)
        write_csv_report(removed_csv, removed)
        token_estimate = estimate_tokens_from_stage_files(stage_files)
        if write_token_estimate:
            write_token_report(token_report_path, src, zip_path, token_estimate, destination)
        too_big = int(token_estimate.get("estimated_total_tokens", 0)) > AI_CHAT_FAR_BEYOND_TOKENS

        # Visible major-size summary before compression.
        if not quiet:
            top_levels = top_level_sizes_from_files(stage_files)
            print("")
            print("================================================================")
            print("  FINAL ZIP SOURCE SIZE PREVIEW")
            print("================================================================")
            print(f"Files to zip: {len(stage_files)} | Source size before compression: {human_bytes(after)}")
            print(f"Estimated text/code tokens: ~{int(token_estimate.get('estimated_total_tokens', 0)):,}")
            print(f"Destination preset: {destination}")
            print("Largest top-level areas kept:")
            for item in top_levels[:15]:
                print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")
            print("Largest individual files kept:")
            for item in stage_files[:15]:
                print(f"  {human_bytes(int(item['size_bytes'])):>10}  {item['path']}")
            if too_big:
                print_too_big_warning(token_estimate)

        log("Creating zip...", quiet)
        parts: list[Path] = [zip_path]
        if fit_for and pro is not None:
            preset = FIT_PRESETS[str(fit_for).lower()]
            parts = pro.pack_parts(stage, zip_path, int(preset["tokens"]), int(preset["bytes"]), str(preset["label"]))
            if len(parts) > 1:
                log(f"Pro: split into {len(parts)} parts that each fit {preset['label']}.", quiet)
        else:
            make_zip(stage, zip_path)
        zip_size = sum(p.stat().st_size for p in parts if p.exists())
        if write_html:
            write_html_report(html_report_path, src, zip_path, stage_files, removed, token_estimate, destination)
        if max_zip_mb and zip_size > max_zip_mb * 1024 * 1024:
            log(f"WARNING: zip is {human_bytes(zip_size)}, above the {max_zip_mb} MB safety threshold.", quiet)
            warning_path = too_large_path
            warning_path.write_text("\n".join([
                f"# {APP_NAME} Too Large Warning",
                "",
                f"Output zip: `{zip_path}`",
                f"Zip size: {human_bytes(zip_size)}",
                f"Configured safety threshold: {max_zip_mb} MB",
                "",
                "Use `--profile source` for code/system-file review, or rerun with `--drop-path` for the largest paths listed in the size report.",
            ]), encoding="utf-8")
        log("Writing receipt and size reports...", quiet)
        write_size_report(size_report_path, src, zip_path, stage_files, removed, zip_size, keep_path_set, drop_path_set, contents_csv, removed_csv)
        write_receipt(receipt_path, src, zip_path, before, after, zip_size, removed, keep_git, keep_env, keep_archives, keep_vendor, copy_then_strip, size_report_path, contents_csv, removed_csv, keep_path_set, drop_path_set, smart=smart, target_mb=target_mb, smart_plan=smart_plan_path if smart else None, profile=profile, source_plan=source_plan_path if profile == "source" else None, max_zip_mb=max_zip_mb, destination=destination, token_report=token_report_path if write_token_estimate else None, html_report=html_report_path if write_html else None, ignore_info=ignore_info, secret_findings=secret_findings, gitignore_drops=gitignore_drops, use_gitignore=use_gitignore, trim=trim, keep_media=keep_media, media_cutoff_kb=media_cutoff_kb, token_estimate=token_estimate)

    if library:
        write_library_entry(
            details_dir / LIBRARY_ENTRY_NAME,
            src=src, zip_path=zip_path, zip_size=zip_size, stage_files=stage_files,
            token_estimate=token_estimate, secret_findings=secret_findings,
            gitignore_count=len(gitignore_drops), trim=trim, profile=profile,
            destination=destination, max_zip_mb=max_zip_mb, redo_settings=redo_settings,
            manifest=manifest, parts=parts, changes=changes,
        )

    log(f"Created zip: {zip_path}", quiet)
    log(f"Final zip size: {human_bytes(zip_path.stat().st_size if zip_path.exists() else 0)}", quiet)
    log(f"Receipt: {receipt_path}", quiet)
    log(f"Size report: {size_report_path}", quiet)
    if write_token_estimate:
        log(f"Token estimate: {token_report_path}", quiet)
    if write_html:
        log(f"HTML report: {html_report_path}", quiet)
    if smart:
        log(f"Smart plan: {smart_plan_path}", quiet)
    if profile == "source":
        log(f"Source selection report: {source_plan_path}", quiet)
    log(f"Full contents CSV: {contents_csv}", quiet)
    return zip_path, receipt_path, size_report_path


PRO_URL = "https://vincentjkessler.github.io/zip-stripper/#pro"
FIT_PRESETS = {
    # Rough per-part budgets so each part is something that AI can take in.
    "claude": {"tokens": 150_000, "bytes": 25 * 1024 * 1024, "label": "Claude"},
    "chatgpt": {"tokens": 100_000, "bytes": 400 * 1024 * 1024, "label": "ChatGPT"},
    "gemini": {"tokens": 700_000, "bytes": 90 * 1024 * 1024, "label": "Gemini"},
}


class ProRequired(RuntimeError):
    """Raised when a Zip Stripper Pro feature is asked for without Pro installed."""


def load_pro_addon():
    """Return the Zip Stripper Pro add-on module if its file is present (activated or not), else None.

    Pro is a separate paid add-on: zip_stripper_pro.py next to this file (or in
    a pro/ folder beside it). Without it everything here works as the free tool.
    """
    here = Path(__file__).resolve().parent
    for folder in (here, here / "pro"):
        if (folder / "zip_stripper_pro.py").is_file():
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            try:
                import zip_stripper_pro  # type: ignore[import-not-found]
                return zip_stripper_pro
            except Exception:  # noqa: BLE001 - a broken add-on must not break the free tool
                return None
    return None


def load_pro():
    """Return Zip Stripper Pro if it is installed AND activated with a licence key, else None."""
    pro = load_pro_addon()
    if pro is None:
        return None
    licensed = getattr(pro, "licensed", None)
    try:
        return pro if (licensed is None or licensed()) else None
    except Exception:  # noqa: BLE001
        return None


def pro_missing_message(feature: str) -> str:
    """Plain words for why a Pro feature can't run: not installed, or installed but not activated."""
    pro = load_pro_addon()
    if pro is not None and hasattr(pro, "licensed"):
        reason = str(pro.licence_status().get("reason") or "")
        why = "it isn't activated yet." if (not reason or "isn't activated" in reason) else f"its licence key was refused: {reason}"
        return (f"{feature} is a Zip Stripper Pro feature. Pro is installed here, but {why} "
                f"Double-click 'Activate Pro' in the Zip Stripper Pro folder and paste your licence key.")
    return f"{feature} is a Zip Stripper Pro feature. Get Pro at {PRO_URL}"


def require_pro(feature: str):
    pro = load_pro()
    if pro is None:
        raise ProRequired(pro_missing_message(feature))
    return pro


def licence_command(activate_key: str | None) -> int:
    """--activate KEY / --licence: activate Pro on this computer, or say what licence is active."""
    pro = load_pro_addon()
    if pro is None or not hasattr(pro, "activate"):
        print(f"Zip Stripper Pro isn't installed here. Get Pro at {PRO_URL}")
        return 1
    if activate_key is not None:
        result = pro.activate(activate_key)
        if not result.get("ok"):
            print(f"Not activated: {result.get('reason')}")
            return 1
        print(f"Zip Stripper Pro is activated. Licensed to {result.get('name')} <{result.get('email')}>. Thank you!")
        return 0
    status = pro.licence_status()
    if status.get("ok"):
        print(f"Zip Stripper Pro {getattr(pro, 'PRO_VERSION', '')}: licensed to {status.get('name')} <{status.get('email')}> (key {status.get('id')}).")
        return 0
    print(f"Zip Stripper Pro is installed but not activated: {status.get('reason')}")
    return 1


def library_settings(root: Path | None = None) -> dict[str, object]:
    """Default options saved from the library page (library/settings.json)."""
    path = (root or library_root()) / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_library_settings(settings: dict[str, object], root: Path | None = None) -> None:
    path = (root or library_root()) / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def find_previous_entry(root: Path, src: Path, exclude: Path | None = None) -> dict[str, object] | None:
    """Newest earlier library entry for the same source folder (with a file list)."""
    best: dict[str, object] | None = None
    if not root.is_dir():
        return None
    target = str(src.resolve()).lower()
    for meta in root.glob(f"*/*/details/{LIBRARY_ENTRY_NAME}"):
        if exclude is not None and meta.parent.parent == exclude:
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(data.get("source", "")).lower() != target or not data.get("files"):
            continue
        if best is None or str(data.get("created", "")) > str(best.get("created", "")):
            best = data
    return best


def stage_manifest(stage: Path) -> dict[str, list[object]]:
    """{relative path: [size, sha256]} for every staged file."""
    manifest: dict[str, list[object]] = {}
    for item in list_stage_files(stage):
        rel = str(item["path"])
        manifest[rel] = [int(item["size_bytes"]), file_sha256(stage / rel)]
    return manifest


LIBRARY_ENTRY_NAME = "zipstripper.json"
LIBRARY_PORT = 47811


def library_root() -> Path:
    """Where library-mode zips live: ZIPSTRIPPER_LIBRARY, else Documents/Zip Stripper Library."""
    configured = os.environ.get("ZIPSTRIPPER_LIBRARY")
    if configured:
        return Path(configured).expanduser()
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    documents = home / "Documents"
    return (documents if documents.is_dir() else home) / "Zip Stripper Library"


def library_port() -> int:
    try:
        return int(os.environ.get("ZIPSTRIPPER_PORT", LIBRARY_PORT))
    except ValueError:
        return LIBRARY_PORT


def write_library_entry(
    entry_path: Path,
    src: Path,
    zip_path: Path,
    zip_size: int,
    stage_files: list[dict[str, str | int]],
    token_estimate: dict[str, object],
    secret_findings: list[dict[str, object]],
    gitignore_count: int,
    trim: dict[str, list[dict[str, object]]],
    profile: str,
    destination: str,
    max_zip_mb: int | None,
    redo_settings: dict[str, object],
    manifest: dict[str, list[object]] | None = None,
    parts: list[Path] | None = None,
    changes: dict[str, object] | None = None,
) -> None:
    """Small summary the library web page reads. Never contains secret values."""
    tokens = int(token_estimate.get("estimated_total_tokens", 0))
    entry = {
        "app": APP_NAME,
        "version": VERSION,
        "project": src.name,
        "source": str(src),
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "zip": zip_path.name,
        "zip_bytes": zip_size,
        "file_count": len(stage_files),
        "source_bytes": sum(int(item["size_bytes"]) for item in stage_files),
        "estimated_tokens": tokens,
        "too_big_for_chat": tokens > AI_CHAT_FAR_BEYOND_TOKENS,
        "over_zip_limit": bool(max_zip_mb and zip_size > max_zip_mb * 1024 * 1024),
        "secrets_left_out": [{"path": f["path"], "reason": f["reason"]} for f in secret_findings if not f["kept"] and not f.get("redacted")],
        "secrets_redacted": [{"path": f["path"], "reason": f["reason"]} for f in secret_findings if f.get("redacted")],
        "shrunk_media": len(trim.get("shrunk", [])),
        "parts": [p.name for p in (parts or [])] if parts and len(parts) > 1 else [],
        "changes": changes,
        "secrets_kept": [{"path": f["path"], "reason": f["reason"]} for f in secret_findings if f["kept"]],
        "gitignore_left_out": gitignore_count,
        "duplicates_left_out": len(trim.get("duplicates", [])),
        "media_left_out": len(trim.get("media", [])),
        "biggest_folders": biggest_token_folders(list(token_estimate.get("rows", [])), limit=5),
        "profile": profile,
        "destination": destination,
        "redo": redo_settings,
        "files": manifest or {},
    }
    entry_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


def downloads_root() -> Path:
    """Return a portable default Downloads folder.

    ZIPSTRIPPER_OUTPUT_ROOT may be set to override the default without editing
    the source. Otherwise the current user's Downloads folder is preferred.
    """
    configured = os.environ.get("ZIPSTRIPPER_OUTPUT_ROOT")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidates.append(Path(userprofile) / "Downloads")
    candidates.append(Path.home() / "Downloads")
    candidates.append(Path.cwd())

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except OSError:
            pass
    return candidates[0]


def default_output_dir() -> Path:
    return downloads_root() / "ZipStripper_Output"


def pick_folder_with_dialog() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Select project folder to strip and zip")
        root.destroy()
        if selected:
            return Path(selected)
    except Exception:
        return None
    return None


def open_folder(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass



class _GuiTextWriter:
    def __init__(self, queue_obj):
        self.queue_obj = queue_obj

    def write(self, text: str) -> int:
        if text:
            self.queue_obj.put(("log", text))
        return len(text)

    def flush(self) -> None:
        return None


def launch_gui(initial_projects: list[str] | None = None, initial_output: str | None = None) -> int:
    """Launch the lightweight standard-library GUI.

    This is intentionally tkinter-only so Zip Stripper remains dependency-free. Native
    drag/drop inside tkinter is not dependable without third-party packages, so
    the package also includes a drag-to-GUI command wrapper that launches this
    GUI with the dropped folder prefilled.
    """
    try:
        import contextlib
        import queue
        import threading
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:
        print(f"ERROR: GUI could not start: {exc}", file=sys.stderr)
        return 2

    root = tk.Tk()
    root.title(f"{APP_NAME} v{VERSION}")
    root.geometry("960x720")
    root.minsize(820, 560)

    q: "queue.Queue[tuple[str, object]]" = queue.Queue()
    running = {"value": False}
    last_paths: dict[str, Path] = {}

    project_var = tk.StringVar(value=(initial_projects[0] if initial_projects else ""))
    output_var = tk.StringVar(value=initial_output or str(library_root()))
    profile_var = tk.StringVar(value="smart")
    destination_var = tk.StringVar(value="chatgpt")
    max_zip_var = tk.StringVar(value="450")
    target_var = tk.StringVar(value="250")
    keep_git_var = tk.BooleanVar(value=False)
    keep_env_var = tk.BooleanVar(value=False)
    keep_archives_var = tk.BooleanVar(value=False)
    keep_vendor_var = tk.BooleanVar(value=False)
    use_ignore_var = tk.BooleanVar(value=True)
    write_html_var = tk.BooleanVar(value=True)
    write_token_var = tk.BooleanVar(value=True)
    manual_review_var = tk.BooleanVar(value=False)
    use_gitignore_var = tk.BooleanVar(value=True)
    keep_media_var = tk.BooleanVar(value=False)

    main_frame = ttk.Frame(root, padding=12)
    main_frame.pack(fill="both", expand=True)

    title = ttk.Label(main_frame, text="Zip Stripper", font=("Segoe UI", 18, "bold"))
    title.pack(anchor="w")
    subtitle = ttk.Label(main_frame, text="Clean a project copy, remove upload bloat, and create an AI-ready zip. The original folder is never modified.")
    subtitle.pack(anchor="w", pady=(0, 10))

    form = ttk.LabelFrame(main_frame, text="Project")
    form.pack(fill="x", pady=(0, 10))
    form.columnconfigure(1, weight=1)

    ttk.Label(form, text="Project folder").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(form, textvariable=project_var).grid(row=0, column=1, sticky="ew", padx=8, pady=6)
    def browse_project() -> None:
        selected = filedialog.askdirectory(title="Select project folder")
        if selected:
            project_var.set(selected)
    ttk.Button(form, text="Browse...", command=browse_project).grid(row=0, column=2, padx=8, pady=6)

    ttk.Label(form, text="Output folder").grid(row=1, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(form, textvariable=output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=6)
    def browse_output() -> None:
        selected = filedialog.askdirectory(title="Select output folder")
        if selected:
            output_var.set(selected)
    ttk.Button(form, text="Browse...", command=browse_output).grid(row=1, column=2, padx=8, pady=6)

    options = ttk.LabelFrame(main_frame, text="Packaging options")
    options.pack(fill="x", pady=(0, 10))
    for i in range(6):
        options.columnconfigure(i, weight=1)

    ttk.Label(options, text="Profile").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Combobox(options, textvariable=profile_var, values=["smart", "source", "plain"], state="readonly", width=14).grid(row=0, column=1, sticky="w", padx=8, pady=6)
    ttk.Label(options, text="Destination").grid(row=0, column=2, sticky="w", padx=8, pady=6)
    ttk.Combobox(options, textvariable=destination_var, values=sorted(DESTINATION_PRESETS.keys()), state="readonly", width=14).grid(row=0, column=3, sticky="w", padx=8, pady=6)
    ttk.Label(options, text="Max zip MB").grid(row=0, column=4, sticky="w", padx=8, pady=6)
    ttk.Entry(options, textvariable=max_zip_var, width=8).grid(row=0, column=5, sticky="w", padx=8, pady=6)

    ttk.Label(options, text="Target source MB").grid(row=1, column=0, sticky="w", padx=8, pady=6)
    ttk.Entry(options, textvariable=target_var, width=8).grid(row=1, column=1, sticky="w", padx=8, pady=6)
    ttk.Checkbutton(options, text="Use .zipstripperignore", variable=use_ignore_var).grid(row=1, column=2, sticky="w", padx=8, pady=6)
    ttk.Checkbutton(options, text="HTML report", variable=write_html_var).grid(row=1, column=3, sticky="w", padx=8, pady=6)
    ttk.Checkbutton(options, text="Token estimate", variable=write_token_var).grid(row=1, column=4, sticky="w", padx=8, pady=6)
    ttk.Checkbutton(options, text="Manual review", variable=manual_review_var).grid(row=1, column=5, sticky="w", padx=8, pady=6)

    advanced = ttk.LabelFrame(main_frame, text="Advanced keep toggles")
    advanced.pack(fill="x", pady=(0, 10))
    ttk.Checkbutton(advanced, text="Keep .git", variable=keep_git_var).pack(side="left", padx=8, pady=6)
    ttk.Checkbutton(advanced, text="Keep .env files", variable=keep_env_var).pack(side="left", padx=8, pady=6)
    ttk.Checkbutton(advanced, text="Keep archives/binaries", variable=keep_archives_var).pack(side="left", padx=8, pady=6)
    ttk.Checkbutton(advanced, text="Keep vendor folders", variable=keep_vendor_var).pack(side="left", padx=8, pady=6)
    ttk.Checkbutton(advanced, text="Use .gitignore", variable=use_gitignore_var).pack(side="left", padx=8, pady=6)
    ttk.Checkbutton(advanced, text="Keep big images/media", variable=keep_media_var).pack(side="left", padx=8, pady=6)

    actions = ttk.Frame(main_frame)
    actions.pack(fill="x", pady=(0, 10))

    status_var = tk.StringVar(value="Ready.")
    ttk.Label(main_frame, textvariable=status_var).pack(anchor="w", pady=(0, 4))

    text_frame = ttk.Frame(main_frame)
    text_frame.pack(fill="both", expand=True)
    console = tk.Text(text_frame, wrap="word", height=18)
    scroll = ttk.Scrollbar(text_frame, orient="vertical", command=console.yview)
    console.configure(yscrollcommand=scroll.set)
    console.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    def append_console(text: str) -> None:
        console.configure(state="normal")
        console.insert("end", text)
        console.see("end")
        console.configure(state="disabled")

    def set_busy(is_busy: bool) -> None:
        running["value"] = is_busy
        for child in actions.winfo_children():
            try:
                child.configure(state=("disabled" if is_busy else "normal"))
            except Exception:
                pass

    def run_packaging(profile_override: str | None = None, destination_override: str | None = None) -> None:
        if running["value"]:
            return
        project_text = project_var.get().strip().strip('"')
        if not project_text:
            messagebox.showerror(APP_NAME, "Choose a project folder first.")
            return
        src = Path(project_text)
        if not src.exists() or not src.is_dir():
            messagebox.showerror(APP_NAME, f"Project folder not found:\n{src}")
            return
        try:
            target_mb = int(target_var.get().strip())
            max_zip_mb = int(max_zip_var.get().strip())
        except ValueError:
            messagebox.showerror(APP_NAME, "Target MB and Max zip MB must be whole numbers.")
            return
        console.configure(state="normal")
        console.delete("1.0", "end")
        console.configure(state="disabled")
        status_var.set("Running. The original project will not be modified.")
        set_busy(True)

        def worker() -> None:
            try:
                with contextlib.redirect_stdout(_GuiTextWriter(q)), contextlib.redirect_stderr(_GuiTextWriter(q)):
                    zip_path, receipt_path, size_report_path = strip_and_zip_project(
                        src,
                        Path(output_var.get().strip().strip('"')),
                        keep_git=keep_git_var.get(),
                        keep_env=keep_env_var.get(),
                        keep_archives=keep_archives_var.get(),
                        keep_vendor=keep_vendor_var.get(),
                        copy_then_strip=False,
                        quiet=False,
                        review=manual_review_var.get(),
                        smart=True,
                        target_mb=target_mb,
                        keep_paths=[],
                        drop_paths=[],
                        profile=profile_override or profile_var.get(),
                        max_zip_mb=max_zip_mb,
                        destination=destination_override or destination_var.get(),
                        use_zipstripperignore=use_ignore_var.get(),
                        zipstripperignore_path=None,
                        write_html=write_html_var.get(),
                        write_token_estimate=write_token_var.get(),
                        library=Path(output_var.get().strip().strip('"')).expanduser().resolve() == library_root().expanduser().resolve(),
                        use_gitignore=use_gitignore_var.get(),
                        keep_media=keep_media_var.get(),
                    )
                q.put(("done", (zip_path, receipt_path, size_report_path)))
            except Exception as exc:
                q.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll_queue() -> None:
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "log":
                    append_console(str(payload))
                elif kind == "done":
                    zip_path, receipt_path, size_report_path = payload  # type: ignore[misc]
                    last_paths["zip"] = Path(zip_path)
                    last_paths["receipt"] = Path(receipt_path)
                    last_paths["size_report"] = Path(size_report_path)
                    status_var.set(f"Done: {zip_path}")
                    append_console("\nDONE\n")
                    append_console(f"Zip: {zip_path}\nReceipt: {receipt_path}\nSize report: {size_report_path}\n")
                    set_busy(False)
                elif kind == "error":
                    status_var.set("Error. See details below.")
                    append_console(f"\nERROR: {payload}\n")
                    set_busy(False)
        except queue.Empty:
            pass
        root.after(100, poll_queue)

    def open_output_folder() -> None:
        open_folder(Path(output_var.get().strip().strip('"')))

    def copy_results() -> None:
        if not last_paths:
            root.clipboard_clear()
            root.clipboard_append(console.get("1.0", "end").strip())
            status_var.set("Copied console text.")
            return
        text = "\n".join(f"{k}: {v}" for k, v in last_paths.items())
        root.clipboard_clear()
        root.clipboard_append(text)
        status_var.set("Copied latest result paths.")

    ttk.Button(actions, text="Strip & Zip", command=lambda: run_packaging()).pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Source Only for ChatGPT", command=lambda: run_packaging("source", "chatgpt")).pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Open Output", command=open_output_folder).pack(side="left", padx=(0, 8))
    ttk.Button(actions, text="Copy Results", command=copy_results).pack(side="left", padx=(0, 8))

    append_console(
        "Tips:\n"
        "- Smart profile is the normal one-click mode.\n"
        "- Source profile keeps source/config/docs/tests and drops state/data/artifacts.\n"
        "- For drag/drop, drop a folder onto ZipStripper-GUI.cmd in Explorer.\n\n"
    )
    poll_queue()
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy, strip, and zip a project for AI upload.")
    parser.add_argument("projects", nargs="*", help="Project folder path(s) to package.")
    parser.add_argument("--output", "-o", default=None, help="Write the zip and reports side by side into this folder (the old layout). Default: the Zip Stripper Library (Documents\\Zip Stripper Library, or ZIPSTRIPPER_LIBRARY), shown at the library web page.")
    parser.add_argument("--keep-git", action="store_true", help="Do not remove .git from the copied project.")
    parser.add_argument("--keep-env", action="store_true", help="Do not remove .env* files from the copied project.")
    parser.add_argument("--keep-archives", action="store_true", help="Do not remove existing zip/exe/dll/binary/archive artifacts from the copied project.")
    parser.add_argument("--keep-vendor", action="store_true", help="Do not remove vendor folders from the copied project.")
    parser.add_argument("--keep-path", action="append", default=[], help="Relative path to keep even if Zip Stripper would normally remove it. Can be used multiple times.")
    parser.add_argument("--drop-path", action="append", default=[], help="Relative path to additionally exclude even if Zip Stripper would normally keep it. Can be used multiple times.")
    parser.add_argument("--review", action="store_true", help="Show advanced interactive preflight size review before copying/zipping.")
    parser.add_argument("--no-review", action="store_true", help="Skip interactive preflight review. This is now the default unless --review is used.")
    parser.add_argument("--profile", choices=["smart", "source", "instrument", "plain"], default="smart", help="Packaging profile. smart keeps one best evidence packet; source keeps source/system files only; instrument is a backward-compatible alias; plain uses raw strip rules. Default: smart.")
    parser.add_argument("--instrument", action="store_true", help="Backward-compatible shortcut for --profile source. Best for source/system-file handoff.")
    parser.add_argument("--smart", dest="smart", action="store_true", default=True, help="Use smart default packaging. Default: on unless --profile source/plain is used.")
    parser.add_argument("--no-smart", dest="smart", action="store_false", help="Disable smart packaging and use only the raw strip rules.")
    parser.add_argument("--destination", choices=sorted(DESTINATION_PRESETS.keys()), default="generic", help="AI destination preset. Adjusts conservative target/max zip sizes. Default: generic.")
    parser.add_argument("--target-mb", type=int, default=SMART_DEFAULT_TARGET_MB, help=f"Smart/source rough source-size target before zip compression. Default: {SMART_DEFAULT_TARGET_MB} MB.")
    parser.add_argument("--max-zip-mb", type=int, default=CHATGPT_SAFE_ZIP_MB, help=f"Warn if the finished zip is above this size. Default: {CHATGPT_SAFE_ZIP_MB} MB.")
    parser.add_argument("--no-zipstripperignore", action="store_true", help="Ignore per-project .zipstripperignore rules.")
    parser.add_argument("--no-gitignore", action="store_true", help="Do not honour the project's .gitignore files (they are honoured by default).")
    parser.add_argument("--keep-secrets-file", action="append", default=[], metavar="PATH", help="Relative path of a file to keep even though it looks like it holds a password/key. Can be used multiple times. Everything else that looks secret is left out.")
    parser.add_argument("--keep-media", action="store_true", help="Keep big images/video/audio/PDFs (by default files over the media cutoff are left out in smart/source mode).")
    parser.add_argument("--media-cutoff-kb", type=int, default=DEFAULT_MEDIA_CUTOFF_KB, help=f"Images/media bigger than this are left out unless --keep-media. Default: {DEFAULT_MEDIA_CUTOFF_KB} KB.")
    parser.add_argument("--keep-duplicates", action="store_true", help="Keep every copy of identical files (by default only one copy is kept in smart/source mode).")
    pro_group = parser.add_argument_group("Zip Stripper Pro", f"Paid add-on features. Get Pro: {PRO_URL}")
    pro_group.add_argument("--shrink-media", action="store_true", help="Pro: put smaller copies of big pictures in the ZIP instead of leaving them out.")
    pro_group.add_argument("--changes-only", action="store_true", help="Pro: ZIP only the files that changed since your last ZIP of this project, plus a CHANGES note.")
    pro_group.add_argument("--redact-secrets", action="store_true", help="Pro: blank out API keys inside files instead of leaving the whole file out.")
    pro_group.add_argument("--fit-for", choices=sorted(FIT_PRESETS), default=None, help="Pro: pack the most important files first so each ZIP part fits this AI; split into parts if needed.")
    pro_group.add_argument("--no-pro-defaults", action="store_true", help="Ignore the Pro options saved on the library page.")
    pro_group.add_argument("--activate", metavar="KEY", default=None, help="Activate Zip Stripper Pro on this computer with your licence key.")
    pro_group.add_argument("--licence", "--license", dest="licence", action="store_true", help="Show which Zip Stripper Pro licence is active here.")
    parser.add_argument("--zipstripperignore", default=None, help="Use a specific .zipstripperignore-style rules file.")
    parser.add_argument("--no-html", action="store_true", help="Do not write the HTML summary report.")
    parser.add_argument("--no-token-estimate", action="store_true", help="Do not write the rough token estimate report.")
    parser.add_argument("--copy-then-strip", action="store_true", help="Strict legacy mode: copy the whole project first, then strip the copy. Slower for large projects.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the output folder when finished.")
    parser.add_argument("--no-copy", action="store_true", help="Do not copy the finished ZIP to the clipboard (by default it is copied, ready for Ctrl+V in an AI chat).")
    parser.add_argument("--quiet", action="store_true", help="Only print final result/error lines.")
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    parser.add_argument("--gui", action="store_true", help="Open the lightweight graphical interface instead of running CLI packaging.")

    args = parser.parse_args(argv)
    if args.version:
        print(f"{APP_NAME} v{VERSION}")
        return 0
    if args.activate is not None or args.licence:
        return licence_command(args.activate)

    projects = list(args.projects)
    if args.gui:
        return launch_gui(projects, args.output)
    use_library = args.output is None
    if use_library and not args.no_pro_defaults and load_pro() is not None:
        saved = library_settings()
        args.shrink_media = args.shrink_media or bool(saved.get("shrink_media"))
        args.redact_secrets = args.redact_secrets or bool(saved.get("redact_secrets"))
        if args.fit_for is None and saved.get("fit_for") in FIT_PRESETS:
            args.fit_for = str(saved["fit_for"])

    if not projects:
        log("No project path was provided. Opening folder picker...", args.quiet)
        selected = pick_folder_with_dialog()
        if selected is None:
            parser.print_help()
            return 2
        projects = [str(selected)]

    # v1.0.6 default: intelligent no-touch mode. Manual review is available with --review.
    review = bool(args.review and not args.no_review)

    profile = "source" if args.instrument else args.profile
    if not args.smart and profile == "smart":
        profile = "plain"

    output_dir = library_root() if use_library else Path(args.output)
    ok = True
    last_zip: Path | None = None
    for project in projects:
        try:
            zip_path, receipt_path, size_report_path = strip_and_zip_project(
                Path(project),
                output_dir,
                keep_git=args.keep_git,
                keep_env=args.keep_env,
                keep_archives=args.keep_archives,
                keep_vendor=args.keep_vendor,
                copy_then_strip=args.copy_then_strip,
                quiet=args.quiet,
                review=review,
                smart=args.smart,
                target_mb=args.target_mb,
                keep_paths=args.keep_path,
                drop_paths=args.drop_path,
                profile=profile,
                max_zip_mb=args.max_zip_mb,
                destination=args.destination,
                use_zipstripperignore=not args.no_zipstripperignore,
                zipstripperignore_path=Path(args.zipstripperignore) if args.zipstripperignore else None,
                write_html=not args.no_html,
                write_token_estimate=not args.no_token_estimate,
                use_gitignore=not args.no_gitignore,
                keep_media=args.keep_media,
                keep_duplicates=args.keep_duplicates,
                media_cutoff_kb=args.media_cutoff_kb,
                keep_secret_paths=args.keep_secrets_file,
                library=use_library,
                shrink_media=args.shrink_media,
                changes_only=args.changes_only,
                redact_secrets=args.redact_secrets,
                fit_for=args.fit_for,
            )
            last_zip = zip_path
            if args.quiet:
                print(f"Created: {zip_path}")
                print(f"Receipt: {receipt_path}")
                print(f"Size report: {size_report_path}")
        except ProRequired as exc:
            ok = False
            print(f"PRO FEATURE: {exc}", file=sys.stderr, flush=True)
        except KeyboardInterrupt as exc:
            ok = False
            print(f"CANCELLED: {project}: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:
            ok = False
            print(f"ERROR: {project}: {exc}", file=sys.stderr, flush=True)
    if ok and last_zip is not None and not args.no_copy and not os.environ.get("ZIPSTRIPPER_NO_CLIPBOARD"):
        clip = sorted(last_zip.parent.glob("*.zip")) if use_library else [last_zip]
        if copy_files_to_clipboard(clip or [last_zip]):
            what = "ZIP is" if len(clip) <= 1 else f"{len(clip)} ZIP parts are"
            print(f"Your {what} on the clipboard: press Ctrl+V in ChatGPT, Claude or Gemini to attach it.", flush=True)
    if not args.no_open:
        if use_library and last_zip is not None:
            open_library_page(last_zip, output_dir)
        elif ok:
            open_folder(output_dir.expanduser().resolve())
    return 0 if ok else 1


def copy_files_to_clipboard(paths) -> bool:
    """Put the ZIP file(s) themselves on the Windows clipboard, so Ctrl+V attaches them in an AI chat."""
    import subprocess
    if os.name != "nt":
        return False
    paths = paths if isinstance(paths, (list, tuple)) else [paths]
    env = dict(os.environ, ZS_CLIP_FILE="\n".join(str(p) for p in paths))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command",
             "Set-Clipboard -LiteralPath ($env:ZS_CLIP_FILE -split \"`n\")"],
            env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), capture_output=True, timeout=30,
        )
    except Exception:  # noqa: BLE001 - a clipboard hiccup must never fail the ZIP
        return False
    return result.returncode == 0


def open_library_page(zip_path: Path | None = None, root: Path | None = None) -> None:
    """Make sure the library web page is running, then open it in the browser."""
    try:
        import zip_stripper_web
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import zip_stripper_web
    anchor = ""
    if zip_path is not None and root is not None:
        try:
            anchor = "#" + zip_path.parent.resolve().relative_to(root.expanduser().resolve()).as_posix()
        except ValueError:
            anchor = ""
    zip_stripper_web.ensure_server_and_open(anchor)


if __name__ == "__main__":
    raise SystemExit(main())
