#!/usr/bin/env python3
"""
Zip Stripper Library: a small web page on this computer that lists every ZIP
Zip Stripper has made, newest first, with the reports tucked behind Details.

    py -3 zip_stripper_web.py            start it if needed and open the page
    py -3 zip_stripper_web.py --serve    run the page server in this window
    py -3 zip_stripper_web.py --install-autostart / --remove-autostart

The page lives at http://127.0.0.1:47811/ (bookmark it). It only listens on
this computer. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
import tempfile
import urllib.request
import uuid
import webbrowser
import zipfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import zip_stripper as zs  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
AUTOSTART_NAME = "Zip Stripper Library.lnk"


def page_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or zs.library_port()}/"


def console_python() -> str:
    """python.exe (not pythonw) for child jobs, so their output can be read."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def windowless_python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").exists():
        return str(exe.with_name("pythonw.exe"))
    return str(exe)


# ---------------------------------------------------------------------------
# Library contents
# ---------------------------------------------------------------------------
def scan_library(root: Path) -> dict[str, object]:
    runs: list[dict[str, object]] = []
    if root.is_dir():
        for meta in root.glob(f"*/*/details/{zs.LIBRARY_ENTRY_NAME}"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            run_dir = meta.parent.parent
            data["id"] = run_dir.relative_to(root).as_posix()
            data["zip_exists"] = (run_dir / str(data.get("zip", ""))).is_file()
            details = []
            for item in sorted(meta.parent.iterdir(), key=lambda p: p.name.lower()):
                if item.is_file() and item.name != zs.LIBRARY_ENTRY_NAME:
                    details.append({"name": item.name, "bytes": item.stat().st_size})
            data["details"] = details
            runs.append(data)
    runs.sort(key=lambda r: str(r.get("created", "")), reverse=True)
    projects: dict[str, dict[str, object]] = {}
    for run in runs:
        run.pop("files", None)  # the full file list is only needed on disk
        key = str(run.get("source") or str(run["id"]).split("/")[0]).lower()
        project = projects.setdefault(key, {"name": run.get("project"), "source": run.get("source"),
                                            "folder": str(run["id"]).split("/")[0], "runs": [], "returns": []})
        project["runs"].append(run)  # type: ignore[union-attr]
    for project in projects.values():
        returns_root = root / str(project["folder"]) / "_returns"
        for review_file in sorted(returns_root.glob("*/review.json"), reverse=True)[:10]:
            try:
                review = json.loads(review_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            project["returns"].append({  # type: ignore[union-attr]
                "id": review_file.parent.relative_to(root).as_posix(), "created": review.get("created"),
                "status": review.get("status"), "changed": len(review.get("changed", [])),
                "added": len(review.get("added", [])), "archive_name": review.get("archive_name"),
            })
    pro = zs.load_pro()
    return {
        "root": str(root),
        "projects": list(projects.values()),
        "limits": {"comfort_tokens": zs.AI_CHAT_COMFORT_TOKENS, "far_tokens": zs.AI_CHAT_FAR_BEYOND_TOKENS},
        "version": zs.VERSION,
        "pro": pro is not None,
        "pro_version": getattr(pro, "PRO_VERSION", None),
        "pro_url": zs.PRO_URL,
        "settings": zs.library_settings(root),
        "fit_presets": {k: v["label"] for k, v in zs.FIT_PRESETS.items()},
    }


def run_dir_for(root: Path, run_id: str) -> Path | None:
    target = (root / run_id).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target if (target / "details" / zs.LIBRARY_ENTRY_NAME).is_file() else None


def read_entry(run_dir: Path) -> dict[str, object]:
    return json.loads((run_dir / "details" / zs.LIBRARY_ENTRY_NAME).read_text(encoding="utf-8"))


def redo_arguments(entry: dict[str, object]) -> list[str]:
    """Rebuild the command-line switches that made this ZIP."""
    redo = dict(entry.get("redo") or {})
    args = [str(entry["source"])]
    if redo.get("profile") and redo["profile"] != "smart":
        args += ["--profile", str(redo["profile"])]
    if redo.get("destination") and redo["destination"] != "generic":
        args += ["--destination", str(redo["destination"])]
    for key, flag in (("keep_git", "--keep-git"), ("keep_env", "--keep-env"), ("keep_archives", "--keep-archives"),
                      ("keep_vendor", "--keep-vendor"), ("keep_media", "--keep-media"), ("keep_duplicates", "--keep-duplicates")):
        if redo.get(key):
            args.append(flag)
    if redo.get("use_gitignore") is False:
        args.append("--no-gitignore")
    if redo.get("shrink_media"):
        args.append("--shrink-media")
    if redo.get("redact_secrets"):
        args.append("--redact-secrets")
    if redo.get("fit_for") in zs.FIT_PRESETS:
        args += ["--fit-for", str(redo["fit_for"])]
    if redo.get("media_cutoff_kb") and int(redo["media_cutoff_kb"]) != zs.DEFAULT_MEDIA_CUTOFF_KB:
        args += ["--media-cutoff-kb", str(int(redo["media_cutoff_kb"]))]
    for key, flag in (("keep_paths", "--keep-path"), ("drop_paths", "--drop-path"), ("keep_secret_paths", "--keep-secrets-file")):
        for value in redo.get(key) or []:
            args += [flag, str(value)]
    return args


# ---------------------------------------------------------------------------
# Jobs (new ZIPs made from the page run as separate processes)
# ---------------------------------------------------------------------------
JOBS: dict[str, dict[str, object]] = {}
JOBS_LOCK = threading.Lock()
PROCS: dict[str, subprocess.Popen] = {}  # running job id -> its process, so Cancel can stop it
WORK_DIRS: dict[str, Path] = {}  # job id -> the library folder it is filling, so Cancel can tidy it


def start_job(root: Path, args: list[str], label: str) -> dict[str, object]:
    cmd = [console_python(), str(HERE / "zip_stripper.py"), *args, "--no-open"]
    return start_command_job(cmd, label, root=root)


def start_command_job(cmd: list[str], label: str, root: Path | None = None, cwd: Path | None = None) -> dict[str, object]:
    job: dict[str, object] = {"id": uuid.uuid4().hex[:8], "label": label, "status": "running",
                              "log": [], "started": time.time(), "run_id": None}
    with JOBS_LOCK:
        JOBS[str(job["id"])] = job

    def worker() -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        if root is not None:
            env["ZIPSTRIPPER_LIBRARY"] = str(root)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    env=env, cwd=str(cwd) if cwd else None, creationflags=NO_WINDOW,
                                    text=True, encoding="utf-8", errors="replace")
            with JOBS_LOCK:
                PROCS[str(job["id"])] = proc
                cancelled_early = bool(job.get("cancel_requested"))
            if cancelled_early:
                stop_process_tree(proc)
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if root is not None and "Working folder:" in line:
                    WORK_DIRS[str(job["id"])] = Path(line.split("Working folder:", 1)[1].strip())
                with JOBS_LOCK:
                    log = job["log"]  # type: ignore[assignment]
                    log.append(line)  # type: ignore[union-attr]
                    del log[:-400]  # type: ignore[union-attr]
                if root is not None and "Created zip:" in line:
                    try:
                        zip_file = Path(line.split("Created zip:", 1)[1].strip())
                        job["run_id"] = zip_file.parent.resolve().relative_to(root.resolve()).as_posix()
                    except ValueError:
                        pass
            code = proc.wait()
            if job.get("cancel_requested") and code != 0:
                job["status"] = "cancelled"
                if root is not None:
                    remove_unfinished_run(root, WORK_DIRS.get(str(job["id"])))
            else:
                job["status"] = "done" if code == 0 else "failed"
        except Exception as exc:  # noqa: BLE001 - shown to the user on the page
            if os.name == "nt" and cwd is not None and len(str(cwd)) > 240:
                exc = RuntimeError("this folder's path is too long for Windows to run programs in "
                                   "(over 240 characters). Set ZIPSTRIPPER_LIBRARY to a shorter folder.")
            job["log"].append(f"ERROR: {exc}")  # type: ignore[union-attr]
            job["status"] = "failed"
        with JOBS_LOCK:
            PROCS.pop(str(job["id"]), None)
            WORK_DIRS.pop(str(job["id"]), None)
        job["finished"] = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return job


def stop_process_tree(proc: subprocess.Popen) -> None:
    """Stop a job's program and anything it started."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        proc.kill()


def cancel_job(job_id: str) -> bool:
    """Stop a running job. Returns False if there is no such running job."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None or job.get("status") != "running":
            return False
        job["cancel_requested"] = True
        proc = PROCS.get(job_id)
    if proc is not None:
        stop_process_tree(proc)
    return True


def remove_unfinished_run(root: Path, run_dir: Path | None) -> None:
    """Delete the half-made folder a cancelled job left in the library (never a finished ZIP)."""
    if run_dir is None:
        return
    try:
        run_dir = run_dir.resolve()
        run_dir.relative_to(root.resolve())
    except (OSError, ValueError):
        return
    if run_dir == root.resolve() or (run_dir / "details" / zs.LIBRARY_ENTRY_NAME).is_file():
        return
    for _ in range(10):  # Windows may hold the files for a moment after the program stops
        shutil.rmtree(run_dir, ignore_errors=True)
        if not run_dir.exists():
            break
        time.sleep(0.3)
    project_dir = run_dir.parent
    try:
        if project_dir != root.resolve() and not any(project_dir.iterdir()):
            project_dir.rmdir()
    except OSError:
        pass


def jobs_snapshot() -> list[dict[str, object]]:
    with JOBS_LOCK:
        jobs = sorted(JOBS.values(), key=lambda j: float(j["started"]), reverse=True)[:8]  # type: ignore[arg-type]
        return [dict(j, log=list(j["log"])[-60:]) for j in jobs]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Windows helpers
# ---------------------------------------------------------------------------
def copy_file_to_clipboard(path: Path | list[Path]) -> bool:
    """Put the file(s) themselves on the clipboard so Ctrl+V attaches them in a chat."""
    return zs.copy_files_to_clipboard(path if isinstance(path, list) else [path])


def reveal_in_explorer(path: Path) -> None:
    if os.name != "nt":
        return
    if path.is_file():
        subprocess.Popen(f'explorer /select,"{path}"')
    else:
        os.startfile(str(path))  # type: ignore[attr-defined]


def pick_folder() -> str | None:
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = filedialog.askdirectory(title='Pick a project folder to Strip & Zip', parent=r)\n"
        "print(p or '')\n"
    )
    result = subprocess.run([console_python(), "-c", code], capture_output=True, text=True,
                            creationflags=NO_WINDOW, timeout=1800)
    chosen = result.stdout.strip()
    return chosen or None


def pick_zip_file() -> str | None:
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = filedialog.askopenfilename(title=\"Pick the ZIP the AI gave you\", filetypes=[('ZIP files', '*.zip')], parent=r)\n"
        "print(p or '')\n"
    )
    result = subprocess.run([console_python(), "-c", code], capture_output=True, text=True,
                            creationflags=NO_WINDOW, timeout=1800)
    return result.stdout.strip() or None


def pro_options_to_args(options: dict[str, object]) -> list[str]:
    args: list[str] = []
    if options.get("shrink_media"):
        args.append("--shrink-media")
    if options.get("redact_secrets"):
        args.append("--redact-secrets")
    if options.get("fit_for") in zs.FIT_PRESETS:
        args += ["--fit-for", str(options["fit_for"])]
    if options.get("changes_only"):
        args.append("--changes-only")
    return args


def review_dir_for(root: Path, review_id: str) -> Path | None:
    target = (root / review_id).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target if (target / "review.json").is_file() and target.parent.name == "_returns" else None


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------
TEXT_TYPES = {".md": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
              ".txt": "text/plain; charset=utf-8", ".json": "application/json; charset=utf-8",
              ".html": "text/html; charset=utf-8"}


class LibraryHandler(BaseHTTPRequestHandler):
    server_version = "ZipStripperLibrary"
    root: Path = zs.library_root()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - silence default logging
        return

    # --- safety: only this computer's own page may use it --------------------
    def host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]  # type: ignore[attr-defined]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, content_type: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self.host_ok():
            self.send_text("Forbidden", "text/plain", 403)
            return
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self.send_text(PAGE_HTML, "text/html; charset=utf-8")
        elif path == "/api/ping":
            self.send_json({"ok": True, "app": "zipstripper", "version": zs.VERSION})
        elif path == "/api/library":
            self.send_json(scan_library(self.root))
        elif path == "/api/jobs":
            self.send_json({"jobs": jobs_snapshot()})
        elif path in {"/api/review", "/api/review/diff"}:
            self.get_review(path)
        elif path.startswith("/files/"):
            self.serve_file(unquote(path[len("/files/"):]))
        elif path == "/favicon.svg":
            self.send_text(FAVICON_SVG, "image/svg+xml")
        else:
            self.send_text("Not found", "text/plain", 404)

    def get_review(self, path: str) -> None:
        from urllib.parse import parse_qs
        query = parse_qs(urlparse(self.path).query)
        review_dir = review_dir_for(self.root, (query.get("id") or [""])[0])
        pro = zs.load_pro()
        if review_dir is None or pro is None:
            self.send_json({"ok": False, "error": "Not found"}, 404)
            return
        review = pro.read_review(review_dir)
        if path == "/api/review":
            trial = review_dir / "trial"
            review["id"] = review_dir.relative_to(self.root).as_posix()
            review["test_command"] = " ".join(pro.detect_test_command(trial, console_python()) or []) if trial.is_dir() else ""
            self.send_json(review)
        else:
            rel = (query.get("path") or [""])[0]
            try:
                text = pro.file_diff(review_dir / "reply", Path(str(review["source"])), rel)
            except ValueError:
                text = "(not allowed)"
            self.send_text(text, "text/plain; charset=utf-8")

    def serve_file(self, rel: str) -> None:
        target = (self.root / rel).resolve()
        try:
            target.relative_to(self.root.resolve())
        except ValueError:
            self.send_text("Forbidden", "text/plain", 403)
            return
        if not target.is_file():
            self.send_text("Not found", "text/plain", 404)
            return
        suffix = target.suffix.lower()
        content_type = TEXT_TYPES.get(suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        if suffix == ".zip":
            self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.end_headers()
        with target.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def do_POST(self) -> None:  # noqa: N802
        # A custom header can't be sent by other websites without permission we
        # never grant, so only this page can trigger actions.
        if not self.host_ok() or self.headers.get("X-ZipStripper") != "1":
            self.send_text("Forbidden", "text/plain", 403)
            return
        path = urlparse(self.path).path
        if path == "/api/receive" and (self.headers.get("Content-Type") or "").startswith("application/zip"):
            self.action_receive_upload()
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except (ValueError, OSError):
            self.send_json({"ok": False, "error": "Bad request"}, 400)
            return
        try:
            if path == "/api/new":
                self.action_new(data)
            elif path == "/api/cancel-job":
                self.send_json({"ok": cancel_job(str(data.get("job", "")))})
            elif path == "/api/open-library":
                reveal_in_explorer(self.root)
                self.send_json({"ok": True})
            elif path == "/api/settings":
                if zs.load_pro() is None:
                    self.send_json({"ok": False, "error": zs.pro_missing_message("That"), "pro_url": zs.PRO_URL}, 402)
                    return
                settings = {"shrink_media": bool(data.get("shrink_media")), "redact_secrets": bool(data.get("redact_secrets")),
                            "fit_for": data.get("fit_for") if data.get("fit_for") in zs.FIT_PRESETS else None}
                zs.save_library_settings(settings, self.root)
                self.send_json({"ok": True, "settings": settings})
            elif path == "/api/receive":
                self.action_receive_pick(data)
            elif path.startswith("/api/review/"):
                self.action_review(path, data)
            elif path in {"/api/copy", "/api/reveal", "/api/redo", "/api/details-folder", "/api/changes-only"}:
                run_dir = run_dir_for(self.root, str(data.get("id", "")))
                if run_dir is None:
                    self.send_json({"ok": False, "error": "That ZIP is no longer in the library."}, 404)
                    return
                entry = read_entry(run_dir)
                zip_file = run_dir / str(entry.get("zip", ""))
                if path == "/api/copy":
                    parts = [run_dir / name for name in entry.get("parts") or []]  # type: ignore[union-attr]
                    files = [p for p in parts if p.is_file()] if parts else ([zip_file] if zip_file.is_file() else [])
                    ok = bool(files) and copy_file_to_clipboard(files)
                    self.send_json({"ok": ok, "count": len(files)})
                elif path == "/api/reveal":
                    reveal_in_explorer(zip_file if zip_file.is_file() else run_dir)
                    self.send_json({"ok": True})
                elif path == "/api/details-folder":
                    reveal_in_explorer(run_dir / "details")
                    self.send_json({"ok": True})
                else:
                    if not Path(str(entry.get("source", ""))).is_dir():
                        self.send_json({"ok": False, "error": "The original project folder is gone or moved."}, 404)
                        return
                    if path == "/api/changes-only":
                        if zs.load_pro() is None:
                            self.send_json({"ok": False, "error": zs.pro_missing_message("That"), "pro_url": zs.PRO_URL}, 402)
                            return
                        job = start_job(self.root, redo_arguments(entry) + ["--changes-only", "--no-pro-defaults"],
                                        f"Only what changed: {entry.get('project')}")
                    else:
                        job = start_job(self.root, redo_arguments(entry) + ["--no-pro-defaults"], f"Redo: {entry.get('project')}")
                    self.send_json({"ok": True, "job": job["id"]})
            else:
                self.send_json({"ok": False, "error": "Unknown action"}, 404)
        except Exception as exc:  # noqa: BLE001 - report instead of crashing the server
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def action_new(self, data: dict[str, object]) -> None:
        folder = str(data.get("path") or "").strip().strip('"')
        if not folder:
            folder = pick_folder() or ""
            if not folder:
                self.send_json({"ok": False, "cancelled": True})
                return
        src = Path(folder).expanduser()
        if not src.is_dir():
            self.send_json({"ok": False, "error": f"Folder not found: {folder}"}, 404)
            return
        options = dict(data.get("options") or {})
        extra = pro_options_to_args(options) if zs.load_pro() is not None else []
        job = start_job(self.root, [str(src), *extra, "--no-pro-defaults"] if extra else [str(src)], f"New ZIP: {src.name}")
        self.send_json({"ok": True, "job": job["id"]})

    # --- Pro: bring back AI changes -------------------------------------------
    def _project_for_run(self, run_id: str):
        run_dir = run_dir_for(self.root, run_id)
        if run_dir is None:
            return None, None
        entry = read_entry(run_dir)
        return run_dir.parent, entry

    def _receive(self, archive: Path, run_id: str) -> None:
        pro = zs.load_pro()
        if pro is None:
            self.send_json({"ok": False, "error": zs.pro_missing_message("Bringing back AI changes"), "pro_url": zs.PRO_URL}, 402)
            return
        project_folder, entry = self._project_for_run(run_id)
        if project_folder is None or entry is None:
            self.send_json({"ok": False, "error": "That project is no longer in the library."}, 404)
            return
        source = Path(str(entry.get("source", "")))
        if not source.is_dir():
            self.send_json({"ok": False, "error": "The original project folder is gone or moved."}, 404)
            return
        try:
            review_dir = pro.receive_reply(archive, source, project_folder / "_returns", str(entry.get("project")))
        except zipfile.BadZipFile:
            self.send_json({"ok": False, "error": "That file isn't a ZIP the AI made (it couldn't be opened)."}, 400)
            return
        self.send_json({"ok": True, "review": review_dir.relative_to(self.root).as_posix()})

    def action_receive_upload(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 500 * 1024 * 1024:
            self.send_json({"ok": False, "error": "The ZIP is empty or bigger than 500 MB."}, 400)
            return
        run_id = unquote(self.headers.get("X-Run-Id") or "")
        name = Path(unquote(self.headers.get("X-File-Name") or "ai-reply.zip")).name
        with tempfile.TemporaryDirectory(prefix="zs_reply_") as tmp:
            archive = Path(tmp) / name
            remaining = length
            with archive.open("wb") as out:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            self._receive(archive, run_id)

    def action_receive_pick(self, data: dict[str, object]) -> None:
        if zs.load_pro() is None:
            self.send_json({"ok": False, "error": zs.pro_missing_message("Bringing back AI changes"), "pro_url": zs.PRO_URL}, 402)
            return
        chosen = pick_zip_file()
        if not chosen:
            self.send_json({"ok": False, "cancelled": True})
            return
        self._receive(Path(chosen), str(data.get("id", "")))

    def action_review(self, path: str, data: dict[str, object]) -> None:
        pro = zs.load_pro()
        review_dir = review_dir_for(self.root, str(data.get("id", "")))
        if pro is None or review_dir is None:
            self.send_json({"ok": False, "error": "Not found"}, 404)
            return
        action = path.rsplit("/", 1)[-1]
        if action == "trial":
            trial = pro.make_trial(review_dir)
            command = pro.detect_test_command(trial, console_python())
            self.send_json({"ok": True, "trial": str(trial), "test_command": " ".join(command or [])})
        elif action == "test":
            trial = review_dir / "trial"
            command = pro.detect_test_command(trial, console_python()) if trial.is_dir() else None
            if not command:
                self.send_json({"ok": False, "error": "No automatic tests found in this project."}, 400)
                return
            job = start_command_job(command, f"Testing the AI's changes: {pro.read_review(review_dir).get('project')}", cwd=trial)
            self.send_json({"ok": True, "job": job["id"]})
        elif action == "apply":
            self.send_json({"ok": True, **pro.apply_reply(review_dir)})
        elif action == "undo":
            self.send_json({"ok": True, **pro.undo_apply(review_dir)})
        elif action == "open":
            what = str(data.get("what") or "trial")
            target = review_dir / ("trial" if what == "trial" else "reply")
            if what == "project":
                target = Path(str(pro.read_review(review_dir).get("source")))
            reveal_in_explorer(target if target.exists() else review_dir)
            self.send_json({"ok": True})
        else:
            self.send_json({"ok": False, "error": "Unknown action"}, 404)


def make_server(root: Path, port: int) -> ThreadingHTTPServer:
    root.mkdir(parents=True, exist_ok=True)
    handler = type("BoundLibraryHandler", (LibraryHandler,), {"root": root})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def server_alive(port: int, timeout: float = 0.8) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as response:
            return b"zipstripper" in response.read()
    except Exception:  # noqa: BLE001
        return False


def start_background_server() -> None:
    kwargs: dict[str, object] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                                 "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = DETACHED | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([windowless_python(), str(HERE / "zip_stripper_web.py"), "--serve"], **kwargs)  # type: ignore[arg-type]


def ensure_server_and_open(anchor: str = "") -> None:
    port = zs.library_port()
    if not server_alive(port):
        start_background_server()
        deadline = time.time() + 8
        while time.time() < deadline and not server_alive(port, timeout=0.5):
            time.sleep(0.25)
    webbrowser.open(page_url(port) + anchor)


def startup_folder() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def install_autostart() -> Path:
    link = startup_folder() / AUTOSTART_NAME
    env = dict(os.environ, ZS_LNK=str(link), ZS_EXE=windowless_python(),
               ZS_ARGS=f'"{HERE / "zip_stripper_web.py"}" --serve', ZS_DIR=str(HERE))
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ZS_LNK); "
              "$s.TargetPath = $env:ZS_EXE; $s.Arguments = $env:ZS_ARGS; $s.WorkingDirectory = $env:ZS_DIR; "
              "$s.Description = 'Zip Stripper Library page (http://127.0.0.1:47811/)'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True,
                   creationflags=NO_WINDOW, capture_output=True)
    return link


def remove_autostart() -> bool:
    link = startup_folder() / AUTOSTART_NAME
    if link.exists():
        link.unlink()
        return True
    return False


MENU_KEY = r"Software\Classes\Directory\shell\ZipStripper"
OLD_MENU_KEYS = (r"Software\Classes\Directory\shell\ZipStripperLite",)


def _delete_key_tree(winreg, root, path: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_key_tree(winreg, root, path + "\\" + child)
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


def install_context_menu() -> str:
    """Add "Strip & Zip for AI Upload" to the folder right-click menu (this user only)."""
    import winreg
    for old in OLD_MENU_KEYS:
        _delete_key_tree(winreg, winreg.HKEY_CURRENT_USER, old)
    command = f'cmd.exe /d /c ""{HERE / "ZipStripper.cmd"}" "%1" || pause"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY) as key:
        winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Strip & Zip for AI Upload")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "shell32.dll,86")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY + r"\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    return command


def remove_context_menu() -> None:
    import winreg
    for path in (MENU_KEY, *OLD_MENU_KEYS):
        _delete_key_tree(winreg, winreg.HKEY_CURRENT_USER, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zip Stripper Library web page.")
    parser.add_argument("--serve", action="store_true", help="Run the page server (blocks).")
    parser.add_argument("--open", action="store_true", help="Start the server if needed and open the page (default).")
    parser.add_argument("--install", action="store_true", help="Add the right-click menu item, start the page with Windows, and open it.")
    parser.add_argument("--uninstall", action="store_true", help="Remove the right-click menu item and the Windows autostart.")
    parser.add_argument("--install-autostart", action="store_true", help="Start the page server when Windows starts.")
    parser.add_argument("--remove-autostart", action="store_true", help="Stop starting it with Windows.")
    args = parser.parse_args(argv)
    port = zs.library_port()
    if args.install:
        if os.name != "nt":
            print("The right-click menu and autostart are Windows-only. Use: zip-stripper <folder>")
            return 1
        install_context_menu()
        print('Added "Strip & Zip for AI Upload" to the folder right-click menu.')
        print(f"The Library page will start with Windows: {install_autostart()}")
        ensure_server_and_open()
        print(f"Library page: {page_url(port)}  (bookmark it)")
        return 0
    if args.uninstall:
        if os.name == "nt":
            remove_context_menu()
            remove_autostart()
        print("Removed the right-click menu item and the autostart. Your ZIPs were not touched.")
        return 0
    if args.install_autostart:
        print(f"Autostart shortcut created: {install_autostart()}")
        return 0
    if args.remove_autostart:
        print("Autostart removed." if remove_autostart() else "Autostart was not installed.")
        return 0
    if args.serve:
        if server_alive(port):
            return 0  # already running
        try:
            server = make_server(zs.library_root(), port)
        except OSError:
            return 0  # port taken (probably by another copy starting at the same time)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    ensure_server_and_open()
    return 0


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="10" y="4" width="44" height="56" rx="8" fill="#2f6fed"/><path d="M30 4h6v6h-6zm-6 6h6v6h-6zm6 6h6v6h-6zm-6 6h6v6h-6zm6 6h6v6h-6z" fill="#fff"/><rect x="24" y="40" width="16" height="12" rx="3" fill="#fff"/></svg>"""

PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zip Stripper Library</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<style>
:root {
  --bg: #f5f6f8; --card: #ffffff; --ink: #1c2230; --muted: #667085; --line: #e3e6ec;
  --accent: #2f6fed; --accent-ink: #ffffff; --soft: #eef3ff;
  --ok: #157f3c; --ok-bg: #e5f5ea; --warn: #9a5b00; --warn-bg: #fff3dc; --bad: #b42318; --bad-bg: #fde8e6;
  --shadow: 0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151c; --card: #1b1f29; --ink: #e8ebf2; --muted: #9aa3b5; --line: #2b3140;
    --accent: #5b8cff; --accent-ink: #0d1220; --soft: #1f2a44;
    --ok: #63d48c; --ok-bg: #173323; --warn: #f5c060; --warn-bg: #3a2c12; --bad: #ff8a80; --bad-bg: #3d1a18;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.45 "Segoe UI", system-ui, -apple-system, sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 10px; font-size: 22px; font-weight: 650; margin-right: auto; }
.brand img { width: 30px; height: 30px; }
.brand small { font-weight: 400; color: var(--muted); font-size: 15px; }
button { font: inherit; border: 1px solid var(--line); background: var(--card); color: var(--ink); border-radius: 8px; padding: 7px 12px; cursor: pointer; }
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); font-weight: 600; }
button:disabled { opacity: .55; cursor: default; }
.newbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.newbar .tip { color: var(--muted); font-size: 12.5px; flex-basis: 100%; text-align: right; }
.newbar input { font: inherit; padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--ink); width: 300px; max-width: 100%; }
.where { color: var(--muted); font-size: 13px; margin: 10px 0 18px; word-break: break-all; }
.where a, .link { color: var(--accent); cursor: pointer; text-decoration: none; }
.where a:hover, .link:hover { text-decoration: underline; }
.filter { width: 100%; font: inherit; padding: 9px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--card); color: var(--ink); margin-bottom: 16px; }
.job { background: var(--soft); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
.job .top { display: flex; gap: 10px; align-items: center; font-weight: 600; }
.job .cancel { margin-left: auto; font: inherit; font-weight: 600; padding: 4px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--ink); cursor: pointer; }
.job .cancel:hover { border-color: currentColor; }
.job pre { margin: 8px 0 0; max-height: 130px; overflow: auto; font: 12px/1.4 Consolas, monospace; color: var(--muted); white-space: pre-wrap; word-break: break-all; }
.spin { width: 14px; height: 14px; border: 2px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.project { background: var(--card); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); padding: 16px 18px; margin-bottom: 14px; }
.phead { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin-bottom: 10px; }
.phead h2 { margin: 0; font-size: 18px; }
.src { color: var(--muted); font-size: 12.5px; word-break: break-all; }
.zip { display: grid; grid-template-columns: 44px 1fr; gap: 6px 12px; align-items: center; }
.zip .actions { grid-column: 1 / -1; justify-content: flex-start; margin-top: 6px; }
.zip.flash { animation: flash 2.4s ease-out; border-radius: 10px; }
@keyframes flash { 0% { background: var(--soft); box-shadow: 0 0 0 6px var(--soft); } 100% { background: transparent; box-shadow: 0 0 0 6px transparent; } }
.zipicon { width: 44px; height: 52px; border-radius: 8px; background: var(--accent); color: var(--accent-ink); display: grid; place-items: center; font-weight: 700; font-size: 12px; letter-spacing: .5px; }
.zipname { font-weight: 600; word-break: break-all; }
.meta { color: var(--muted); font-size: 13px; }
.badges { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 5px; }
.badge { font-size: 12px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.badge.ok { color: var(--ok); background: var(--ok-bg); }
.badge.warn { color: var(--warn); background: var(--warn-bg); }
.badge.bad { color: var(--bad); background: var(--bad-bg); cursor: pointer; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.details { border-top: 1px dashed var(--line); margin-top: 12px; padding-top: 10px; font-size: 13.5px; }
.details h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .4px; color: var(--muted); margin: 10px 0 6px; }
.details ul { margin: 0; padding-left: 18px; }
.details .files a { display: inline-block; margin: 2px 12px 2px 0; color: var(--accent); }
.secretlist li { color: var(--bad); }
.older { margin-top: 12px; }
.older summary { cursor: pointer; color: var(--muted); font-size: 13.5px; }
.oldrow { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 7px 0; border-top: 1px solid var(--line); font-size: 13.5px; }
.oldrow .grow { flex: 1; min-width: 200px; }
.oldrow button { padding: 4px 9px; font-size: 13px; }
.empty { text-align: center; color: var(--muted); padding: 56px 16px; background: var(--card); border: 1px dashed var(--line); border-radius: 14px; }
.missing { color: var(--muted); font-style: italic; }
#toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); background: var(--ink); color: var(--bg); padding: 10px 16px; border-radius: 10px; max-width: calc(100% - 32px); box-shadow: 0 6px 24px rgba(0,0,0,.25); opacity: 0; pointer-events: none; transition: opacity .2s; z-index: 10; }
#toast.show { opacity: 1; }
.credit { text-align: center; color: var(--muted); font-size: 12.5px; margin-top: 28px; }
#offline { display: none; background: var(--bad-bg); color: var(--bad); padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; }
.protag { font-size: 11px; font-weight: 700; letter-spacing: .5px; padding: 2px 7px; border-radius: 999px; background: linear-gradient(135deg, #f6b73c, #e8590c); color: #fff; vertical-align: middle; }
.getpro { text-decoration: none; font-size: 13px; font-weight: 600; padding: 6px 11px; border-radius: 8px; background: linear-gradient(135deg, #f6b73c, #e8590c); color: #fff; }
.probar { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; margin-bottom: 14px; font-size: 13.5px; }
.probar label { display: inline-flex; gap: 6px; align-items: center; cursor: pointer; }
.probar select { font: inherit; padding: 3px 6px; border-radius: 6px; border: 1px solid var(--line); background: var(--card); color: var(--ink); }
.probar.locked { opacity: .75; }
.probar .hint { color: var(--muted); font-size: 12.5px; }
button.locked { color: var(--muted); }
button.locked::after { content: " PRO"; font-size: 10px; font-weight: 700; color: #e8590c; }
.project.drop { outline: 3px dashed var(--accent); outline-offset: 3px; }
.returns { margin-top: 10px; font-size: 13.5px; }
.retrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 6px 0; border-top: 1px solid var(--line); }
.retrow .grow { flex: 1; min-width: 200px; }
.status { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.status.received { color: var(--warn); background: var(--warn-bg); }
.status.applied { color: var(--ok); background: var(--ok-bg); }
.status.undone { color: var(--muted); background: var(--line); }
.droptip { color: var(--muted); font-size: 12.5px; margin-top: 8px; }
#overlay { position: fixed; inset: 0; background: rgba(10,14,22,.55); display: flex; align-items: flex-start; justify-content: center; padding: 32px 16px; overflow: auto; z-index: 20; }
#overlay[hidden] { display: none; }
.panel { background: var(--card); color: var(--ink); width: 100%; max-width: 900px; border-radius: 16px; padding: 20px 22px; box-shadow: 0 20px 60px rgba(0,0,0,.35); }
.panel h2 { margin: 0 0 4px; font-size: 20px; }
.panel .sub { color: var(--muted); font-size: 13px; margin-bottom: 12px; }
.panel h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .4px; color: var(--muted); margin: 16px 0 6px; }
.frow { display: flex; gap: 10px; align-items: center; padding: 6px 0; border-top: 1px solid var(--line); font-size: 13.5px; flex-wrap: wrap; }
.frow .grow { flex: 1; min-width: 200px; word-break: break-all; }
.plus { color: var(--ok); font-weight: 600; } .minus { color: var(--bad); font-weight: 600; }
pre.diff { width: 100%; margin: 6px 0 4px; max-height: 360px; overflow: auto; background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font: 12px/1.45 Consolas, monospace; white-space: pre; }
pre.diff .a { color: var(--ok); } pre.diff .d { color: var(--bad); } pre.diff .h { color: var(--accent); }
.panel .bar { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); align-items: center; }
.panel .note { color: var(--muted); font-size: 12.5px; flex-basis: 100%; }
.warnbox { background: var(--warn-bg); color: var(--warn); border-radius: 10px; padding: 8px 12px; margin: 8px 0; font-size: 13px; }
@media (max-width: 680px) {
  .zip { grid-template-columns: 40px 1fr; }
  .actions { grid-column: 1 / -1; justify-content: flex-start; }
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand"><img src="/favicon.svg" alt=""> Zip Stripper <span id="protag"></span> <small>Library</small></div>
    <div class="newbar">
      <input id="pathbox" placeholder="…or paste a folder path and press Enter" aria-label="Project folder path">
      <button class="primary" id="newbtn">+ Make a new ZIP</button>
      <span class="tip">Tip: right-click any folder → <b>Strip &amp; Zip for AI Upload</b>. The ZIP lands here and is copied, ready for Ctrl+V.</span>
    </div>
  </header>
  <div class="where" id="where"></div>
  <div class="probar" id="probar"></div>
  <div id="offline">The Zip Stripper page program isn't running. To start it again, double-click <b>ZipStripper-Library.cmd</b> in your Zip Stripper folder (or type <b>zip-stripper-library</b> if you installed it with pip). It also starts by itself when Windows starts.</div>
  <div id="jobs"></div>
  <input class="filter" id="filter" placeholder="Find a project…" aria-label="Find a project">
  <main id="list"></main>
  <div class="credit">Zip Stripper · a Vincent J. Kessler production</div>
</div>
<div id="toast" role="status"></div>
<div id="overlay" hidden><div class="panel" id="panel"></div></div>
<input type="file" id="replyfile" accept=".zip,application/zip" hidden>
<script>
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const openDetails = new Set(), openOlder = new Set();
let lastLibrary = "", lastJobs = "", library = null, flashId = decodeURIComponent(location.hash.slice(1) || "");
let jobsRunning = false;

function bytes(n) {
  n = Number(n || 0);
  const u = ["B", "KB", "MB", "GB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + " " + u[i];
}
function when(iso) {
  const d = new Date(iso); if (isNaN(d)) return iso || "";
  const now = new Date(), y = new Date(now); y.setDate(now.getDate() - 1);
  const t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return "today " + t;
  if (d.toDateString() === y.toDateString()) return "yesterday " + t;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" }) + " " + t;
}
function toast(msg, ms = 4200) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), ms);
}
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-ZipStripper": "1" }, body: JSON.stringify(body || {}) });
  let data = {}; try { data = await r.json(); } catch (e) {}
  return data;
}
function tokenBadge(run) {
  const n = Number(run.estimated_tokens || 0), lim = library.limits;
  const k = n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1000 ? Math.round(n / 1000) + "K" : String(n);
  if (n > lim.far_tokens) return `<span class="badge bad" title="Most AI chats read about ${lim.comfort_tokens.toLocaleString()} tokens at once">Too big for one AI chat · ~${k} tokens</span>`;
  if (n > lim.comfort_tokens) return `<span class="badge warn" title="Tokens are the word pieces an AI reads">Large · ~${k} tokens · may not fit every AI chat</span>`;
  return `<span class="badge ok" title="Tokens are the word pieces an AI reads">Fits in an AI chat · ~${k} tokens</span>`;
}
function secretBadge(run) {
  const n = (run.secrets_left_out || []).length, kept = (run.secrets_kept || []).length;
  let out = "";
  if (n) out += `<span class="badge bad" data-act="details" data-id="${esc(run.id)}" title="Click to see which files">${n} secret file${n > 1 ? "s" : ""} left out</span>`;
  if (kept) out += `<span class="badge bad" data-act="details" data-id="${esc(run.id)}">${kept} secret file${kept > 1 ? "s" : ""} kept on purpose</span>`;
  const red = (run.secrets_redacted || []).length;
  if (red) out += `<span class="badge ok" data-act="details" data-id="${esc(run.id)}" title="The files are in the ZIP with the keys replaced">keys blanked out in ${red} file${red > 1 ? "s" : ""}</span>`;
  return out;
}
function proBtn(act, id, label, title) {
  if (library.pro) return `<button data-act="${act}" data-id="${esc(id)}" title="${esc(title)}">${label}</button>`;
  return `<button class="locked" data-act="pro" title="${esc(title)} (Zip Stripper Pro)">${label}</button>`;
}
function renderProbar() {
  const s = library.settings || {}, pro = library.pro;
  $("#protag").innerHTML = pro ? '<span class="protag">PRO</span>' : "";
  const fits = Object.entries(library.fit_presets || {}).map(([k, v]) => `<option value="${k}" ${s.fit_for === k ? "selected" : ""}>Fit for ${esc(v)}</option>`).join("");
  $("#probar").className = "probar" + (pro ? "" : " locked");
  $("#probar").innerHTML = `
    <b>${pro ? "Pro options" : "Zip Stripper Pro"}</b>
    <label><input type="checkbox" data-opt="shrink_media" ${s.shrink_media ? "checked" : ""} ${pro ? "" : "disabled"}> Shrink big pictures instead of leaving them out</label>
    <label><input type="checkbox" data-opt="redact_secrets" ${s.redact_secrets ? "checked" : ""} ${pro ? "" : "disabled"}> Blank out keys instead of dropping the file</label>
    <select data-opt="fit_for" ${pro ? "" : "disabled"}><option value="">Any AI (one ZIP)</option>${fits}</select>
    ${pro ? '<span class="hint">Used for new ZIPs and right-click.</span>' : `<a class="getpro" href="${esc(library.pro_url)}" target="_blank" rel="noopener">Get Pro</a><span class="hint">Also: only-what-changed ZIPs and bringing the AI's changes back safely.</span>`}`;
}
function fileUrl(run, name) { return "/files/" + run.id.split("/").map(encodeURIComponent).join("/") + "/details/" + encodeURIComponent(name); }
function detailsHtml(run) {
  const left = [];
  if (run.gitignore_left_out) left.push(`${run.gitignore_left_out} item${run.gitignore_left_out > 1 ? "s" : ""} the project's .gitignore lists`);
  if (run.duplicates_left_out) left.push(`${run.duplicates_left_out} duplicate cop${run.duplicates_left_out > 1 ? "ies" : "y"}`);
  if (run.media_left_out) left.push(`${run.media_left_out} big image/media file${run.media_left_out > 1 ? "s" : ""}`);
  const secrets = (run.secrets_left_out || []).map((s) => `<li><b>${esc(s.path)}</b> — ${esc(s.reason)}</li>`).join("")
    + (run.secrets_kept || []).map((s) => `<li><b>${esc(s.path)}</b> — kept on purpose — ${esc(s.reason)}</li>`).join("");
  const nice = { "Receipt.md": "Receipt (start here)", "Report.html": "Report (web page)" };
  const order = ["Receipt.md", "Report.html"];
  const files = [...(run.details || [])].sort((a, b) => (order.indexOf(a.name) + 1 || 99) - (order.indexOf(b.name) + 1 || 99) || a.name.localeCompare(b.name))
    .map((f) => `<a href="${fileUrl(run, f.name)}" target="_blank" rel="noopener">${esc(nice[f.name] || f.name)}</a>`).join("");
  if (run.shrunk_media) left.push(`${run.shrunk_media} big picture${run.shrunk_media > 1 ? "s" : ""} shrunk (kept, smaller)`);
  const redacted = (run.secrets_redacted || []).map((s) => `<li><b>${esc(s.path)}</b> — keys blanked out, file kept — ${esc(s.reason)}</li>`).join("");
  const changes = run.changes ? `<h3>Only what changed</h3><div>${esc(run.changes.summary)}${run.changes.since ? " (since " + esc(when(run.changes.since)) + ")" : ""}</div>` : "";
  const parts = (run.parts || []).length ? `<h3>Parts</h3><div>${run.parts.map(esc).join("<br>")}<br><span style="color:var(--muted)">Upload part 1 first. “Copy for upload” copies all parts.</span></div>` : "";
  const folders = (run.biggest_folders || []).slice(0, 5).map((f) => `<li>${esc(f.path)} — ~${Number(f.estimated_tokens).toLocaleString()} tokens</li>`).join("");
  return `<div class="details">
    ${secrets ? `<h3>Secrets (the secret itself is never shown)</h3><ul class="secretlist">${secrets}</ul>` : ""}
    ${redacted ? `<h3>Keys blanked out (Pro)</h3><ul>${redacted}</ul>` : ""}
    ${changes}${parts}
    <h3>Left out to keep it small</h3><div>${left.length ? esc(left.join(" · ")) : "Nothing extra (only the usual junk like caches and installed packages)."}</div>
    ${folders ? `<h3>Biggest folders inside</h3><ul>${folders}</ul>` : ""}
    <h3>Reports made with this ZIP</h3><div class="files">${files || "none"}</div>
    <div style="margin-top:8px"><a class="link" data-act="details-folder" data-id="${esc(run.id)}">Open the details folder</a></div>
  </div>`;
}
function mainZip(run) {
  const open = openDetails.has(run.id);
  return `<div class="zip" id="${esc(run.id)}">
    <div class="zipicon">ZIP</div>
    <div>
      <div class="zipname">${esc(run.zip)}${run.zip_exists ? "" : ' <span class="missing">(file was moved or deleted)</span>'}</div>
      <div class="meta">${bytes(run.zip_bytes)} · ${Number(run.file_count || 0).toLocaleString()} files${(run.parts || []).length ? ` · <b>${run.parts.length} parts</b>` : ""}${run.changes ? " · only what changed" : ""} · ${esc(when(run.created))}</div>
      <div class="badges">${tokenBadge(run)}${secretBadge(run)}</div>
    </div>
    <div class="actions">
      <button class="primary" data-act="copy" data-id="${esc(run.id)}" ${run.zip_exists ? "" : "disabled"} title="Copies the ZIP file. Then press Ctrl+V in ChatGPT or Claude.">Copy for upload</button>
      <button data-act="reveal" data-id="${esc(run.id)}">Show in folder</button>
      <button data-act="redo" data-id="${esc(run.id)}" title="Make a fresh ZIP of this project with the same settings">Redo</button>
      ${proBtn("changes", run.id, "Only what changed", "A small ZIP with just the files changed since this ZIP")}
      ${proBtn("receive", run.id, "Bring back AI changes", "Load the ZIP the AI gave back, check it, then apply it safely")}
      <button data-act="details" data-id="${esc(run.id)}">${open ? "Hide details" : "Details"}</button>
    </div>
  </div>${open ? detailsHtml(run) : ""}`;
}
function olderRow(run) {
  const open = openDetails.has(run.id);
  const secrets = (run.secrets_left_out || []).length;
  return `<div class="oldrow" id="${esc(run.id)}">
      <div class="grow"><b>${esc(when(run.created))}</b> · ${bytes(run.zip_bytes)}${secrets ? ` · <span style="color:var(--bad)">${secrets} secret${secrets > 1 ? "s" : ""} left out</span>` : ""}${run.zip_exists ? "" : ' · <span class="missing">moved or deleted</span>'}</div>
      <button data-act="copy" data-id="${esc(run.id)}" ${run.zip_exists ? "" : "disabled"}>Copy</button>
      <button data-act="reveal" data-id="${esc(run.id)}">Show</button>
      <button data-act="details" data-id="${esc(run.id)}">${open ? "Hide" : "Details"}</button>
    </div>${open ? detailsHtml(run) : ""}`;
}
function render() {
  if (!library) return;
  renderProbar();
  $("#where").innerHTML = `Your ZIPs are kept in <code>${esc(library.root)}</code> · <a data-act="root">open that folder</a> · bookmark this page: <code>${esc(location.origin)}</code>`;
  const q = $("#filter").value.trim().toLowerCase();
  const projects = library.projects.filter((p) => !q || String(p.name).toLowerCase().includes(q) || String(p.source).toLowerCase().includes(q));
  if (!library.projects.length) {
    $("#list").innerHTML = `<div class="empty"><b>No ZIPs yet.</b><br><br>Right-click any folder → <b>Strip &amp; Zip for AI Upload</b>,<br>or press <b>+ Make a new ZIP</b> above.</div>`;
    return;
  }
  $("#list").innerHTML = projects.map((p) => {
    const [first, ...rest] = p.runs;
    const rets = (p.returns || []).slice(0, 3).map((r) => `<div class="retrow">
        <div class="grow">AI changes from <b>${esc(when(r.created))}</b> · ${r.changed} changed, ${r.added} new${r.archive_name ? " · " + esc(r.archive_name) : ""}</div>
        <span class="status ${esc(r.status)}">${r.status === "applied" ? "applied" : r.status === "undone" ? "undone" : "waiting for you"}</span>
        <button data-act="review" data-id="${esc(r.id)}">Review</button></div>`).join("");
    return `<article class="project" data-run="${esc(first.id)}">
      <div class="phead"><h2>${esc(p.name)}</h2><span class="src">${esc(p.source)}</span></div>
      ${mainZip(first)}
      ${rets ? `<div class="returns">${rets}</div>` : ""}
      ${rest.length ? `<details class="older" data-key="${esc(p.source)}" ${openOlder.has(p.source) || rest.some((r) => openDetails.has(r.id) || r.id === flashId) ? "open" : ""}><summary>${rest.length} older ZIP${rest.length > 1 ? "s" : ""}</summary>${rest.map(olderRow).join("")}</details>` : ""}
    </article>`;
  }).join("") || `<div class="empty">No project matches “${esc(q)}”.</div>`;
  if (flashId) {
    const el = document.getElementById(flashId);
    if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); flashId = ""; history.replaceState(null, "", location.pathname); }
  }
}
function jobLines(j) {
  const lines = (j.log || []).map((l) => l.replace(/^\[Zip Stripper\] /, "")).filter((l) => l.trim());
  if (j.status === "done") return lines.filter((l) => /Final zip size|LEFT OUT|KEPT!|BLANKED|Pro:|passed|failed|error/i.test(l)).slice(-8);
  return lines.slice(j.status === "failed" ? -14 : -5);
}
function renderJobs(jobs) {
  jobsRunning = jobs.some((j) => j.status === "running");
  const recent = jobs.filter((j) => j.status === "running" || Date.now() / 1000 - (j.finished || 0) < 120);
  $("#jobs").innerHTML = recent.map((j) => `<div class="job">
      <div class="top">${j.status === "running" ? '<div class="spin"></div>' : j.status === "done" ? "✓" : j.status === "cancelled" ? "–" : "✕"} ${esc(j.label)}
        <span style="font-weight:400;color:var(--muted)">${j.status === "running" ? (j.cancel_requested ? "stopping…" : "working…") : j.status === "done" ? (j.run_id ? "done — it's at the top of the list" : "done") : j.status === "cancelled" ? "cancelled — nothing was saved" : "failed — read the last lines below"}</span>
        ${j.status === "running" && !j.cancel_requested ? `<button class="cancel" data-act="cancel-job" data-job="${esc(j.id)}">Cancel</button>` : ""}</div>
      <pre>${esc(jobLines(j).join("\n"))}</pre>
    </div>`).join("");
}
async function refresh() {
  try {
    const [lib, jobs] = await Promise.all([fetch("/api/library").then((r) => r.text()), fetch("/api/jobs").then((r) => r.json())]);
    $("#offline").style.display = "none";
    const jobText = JSON.stringify(jobs.jobs);
    if (jobText !== lastJobs) {
      const before = lastJobs ? JSON.parse(lastJobs) : [];
      lastJobs = jobText; renderJobs(jobs.jobs);
      for (const j of jobs.jobs) {
        const prev = before.find((b) => b.id === j.id);
        if (prev && prev.status === "running" && j.status === "done" && j.run_id) flashId = j.run_id;
      }
    }
    if (lib !== lastLibrary || flashId) { lastLibrary = lib; library = JSON.parse(lib); render(); }
  } catch (e) {
    $("#offline").style.display = "block";
  }
  clearTimeout(refresh.timer);
  refresh.timer = setTimeout(refresh, jobsRunning ? 1200 : 6000);
}
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-act]"); if (!el) return;
  const act = el.dataset.act, id = el.dataset.id;
  if (act === "details") { openDetails.has(id) ? openDetails.delete(id) : openDetails.add(id); render(); return; }
  if (act === "root") { await post("/api/open-library"); return; }
  if (act === "copy") {
    el.disabled = true;
    const r = await post("/api/copy", { id });
    el.disabled = false;
    toast(r.ok ? "Copied! Click in the ChatGPT or Claude message box and press Ctrl+V to attach it."
               : "Couldn't copy it. Use “Show in folder” and drag the ZIP into the chat instead.", 6500);
    return;
  }
  if (act === "reveal") { await post("/api/reveal", { id }); return; }
  if (act === "details-folder") { await post("/api/details-folder", { id }); return; }
  if (act === "redo") {
    const r = await post("/api/redo", { id });
    toast(r.ok ? "Making a fresh ZIP with the same settings…" : (r.error || "Couldn't start it."));
    refresh(); return;
  }
  if (act === "pro") { window.open(library.pro_url, "_blank", "noopener"); return; }
  if (act === "cancel-job") {
    el.disabled = true; el.textContent = "Stopping…";
    const r = await post("/api/cancel-job", { job: el.dataset.job });
    toast(r.ok ? "Cancelled. Nothing was saved." : "It had already finished.");
    refresh(); return;
  }
  if (act === "changes") {
    const r = await post("/api/changes-only", { id });
    toast(r.ok ? "Making a ZIP of only what changed…" : (r.error || "Couldn't start it."));
    refresh(); return;
  }
  if (act === "receive") { receiveFor = id; $("#replyfile").value = ""; $("#replyfile").click(); return; }
  if (act === "review") { openReview(id); return; }
  if (act === "close-review") { closeReview(); return; }
  if (act === "diff") { toggleDiff(el); return; }
  if (act === "trial" || act === "test" || act === "apply" || act === "undo" || act === "open") {
    if (act === "apply" && !confirm("Copy the AI's changed and new files into your real project folder?\n\nA backup is made first, and Undo puts everything back.")) return;
    if (act === "undo" && !confirm("Put your project back the way it was before these changes?")) return;
    el.disabled = true;
    const r = await post("/api/review/" + act, { id: currentReview, what: el.dataset.what });
    el.disabled = false;
    if (!r.ok) { toast(r.error || "That didn't work."); return; }
    if (act === "trial") toast("Test copy made. Your real folder is untouched.");
    if (act === "test") toast("Running its tests… the result shows at the top of the page.", 6000);
    if (act === "apply") toast(`Applied: ${r.changed} changed, ${r.added} new. A backup was made first.`, 6500);
    if (act === "undo") toast(`Undone: ${r.restored} put back, ${r.removed} new files removed${r.kept_edited.length ? `, ${r.kept_edited.length} kept because you edited them` : ""}.`, 7000);
    if (act !== "open") openReview(currentReview);
    refresh();
  }
});
document.addEventListener("change", async (ev) => {
  const el = ev.target;
  if (el.dataset && el.dataset.opt && library && library.pro) {
    const s = Object.assign({}, library.settings || {});
    s[el.dataset.opt] = el.type === "checkbox" ? el.checked : (el.value || null);
    const r = await post("/api/settings", s);
    if (r.ok) { library.settings = r.settings; toast("Saved. New ZIPs and right-click will use this."); }
  }
});
let receiveFor = null, currentReview = null;
async function uploadReply(file, runId) {
  if (!library.pro) { window.open(library.pro_url, "_blank", "noopener"); return; }
  if (!file || !/\.zip$/i.test(file.name)) { toast("Please use the ZIP file the AI gave you."); return; }
  toast("Reading the AI's ZIP…");
  const r = await fetch("/api/receive", { method: "POST", headers: { "Content-Type": "application/zip", "X-ZipStripper": "1",
    "X-Run-Id": encodeURIComponent(runId), "X-File-Name": encodeURIComponent(file.name) }, body: file });
  let data = {}; try { data = await r.json(); } catch (e) {}
  if (!data.ok) { toast(data.error || "Couldn't read that ZIP."); return; }
  refresh(); openReview(data.review);
}
$("#replyfile").addEventListener("change", (e) => { if (e.target.files[0]) uploadReply(e.target.files[0], receiveFor); });
document.addEventListener("dragover", (e) => {
  const card = e.target.closest && e.target.closest(".project");
  if (!card || ![...(e.dataTransfer.types || [])].includes("Files")) return;
  e.preventDefault(); document.querySelectorAll(".project.drop").forEach((c) => c !== card && c.classList.remove("drop")); card.classList.add("drop");
});
document.addEventListener("dragleave", (e) => { const card = e.target.closest && e.target.closest(".project"); if (card && !card.contains(e.relatedTarget)) card.classList.remove("drop"); });
document.addEventListener("drop", (e) => {
  const card = e.target.closest && e.target.closest(".project");
  if (!card) return;
  e.preventDefault(); card.classList.remove("drop");
  uploadReply(e.dataTransfer.files[0], card.dataset.run);
});
function diffHtml(text) {
  return text.split("\n").map((l) => {
    const c = l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@") ? "h" : l.startsWith("+") ? "a" : l.startsWith("-") ? "d" : "";
    return c ? `<span class="${c}">${esc(l)}</span>` : esc(l);
  }).join("\n");
}
async function toggleDiff(el) {
  const row = el.closest(".frow"), next = row.nextElementSibling;
  if (next && next.classList.contains("diff")) { next.remove(); el.textContent = "View"; return; }
  const text = await fetch(`/api/review/diff?id=${encodeURIComponent(currentReview)}&path=${encodeURIComponent(el.dataset.path)}`).then((r) => r.text());
  const pre = document.createElement("pre"); pre.className = "diff"; pre.innerHTML = diffHtml(text);
  row.after(pre); el.textContent = "Hide";
}
function closeReview() { $("#overlay").hidden = true; currentReview = null; }
async function openReview(id) {
  currentReview = id;
  const r = await fetch("/api/review?id=" + encodeURIComponent(id)).then((x) => x.json()).catch(() => ({}));
  if (!r.source) { toast("Couldn't open that review."); return; }
  const warn = (r.changed.concat(r.added)).filter((f) => f.secret_warning);
  const rows = (items, kind) => items.map((f) => `<div class="frow"><div class="grow">${esc(f.path)}</div>
      ${kind === "changed" ? (f.binary ? '<span style="color:var(--muted)">changed (not text)</span>' : `<span class="plus">+${f.plus}</span><span class="minus">−${f.minus}</span>`) : `<span style="color:var(--muted)">new · ${bytes(f.bytes)}</span>`}
      ${f.secret_warning ? '<span class="status received">looks like a key inside</span>' : ""}
      <button data-act="diff" data-path="${esc(f.path)}">View</button></div>`).join("") || '<div class="frow"><div class="grow" style="color:var(--muted)">none</div></div>';
  const applied = r.status === "applied";
  $("#panel").innerHTML = `
    <h2>Changes from the AI · ${esc(r.project)}</h2>
    <div class="sub">From <b>${esc(r.archive_name)}</b>, received ${esc(when(r.created))} · <span class="status ${esc(r.status)}">${applied ? "applied to your folder" : r.status === "undone" ? "undone" : "not applied yet"}</span></div>
    ${r.unwrapped_folder ? `<div class="sub">The AI put everything inside a folder called “${esc(r.unwrapped_folder)}”; Zip Stripper took the files out of it so they line up with your project.</div>` : ""}
    ${warn.length ? `<div class="warnbox">${warn.length} file(s) from the AI look like they contain a key or password. Check them before applying.</div>` : ""}
    ${(r.skipped || []).length ? `<div class="warnbox">Ignored ${r.skipped.length} file(s) from the AI's ZIP: ${r.skipped.slice(0, 6).map((s) => esc(s.path) + " (" + esc(s.why) + ")").join(", ")}</div>` : ""}
    <h3>Files the AI changed (${r.changed.length})</h3>${rows(r.changed, "changed")}
    <h3>New files from the AI (${r.added.length})</h3>${rows(r.added, "added")}
    <div class="sub" style="margin-top:12px">${r.same} file(s) in the AI's ZIP are exactly the same as yours. Files the AI didn't send stay as they are.</div>
    <div class="bar">
      ${applied ? `<button data-act="undo">Undo (put my folder back)</button>` : `<button class="primary" data-act="apply" ${r.changed.length + r.added.length ? "" : "disabled"}>Apply to my real folder</button>`}
      <button data-act="trial">${r.trial ? "Remake test copy" : "Make a test copy first"}</button>
      ${r.trial ? `<button data-act="open" data-what="trial">Open test copy</button>` : ""}
      ${r.trial && r.test_command ? `<button data-act="test" title="${esc(r.test_command)}">Run its tests</button>` : ""}
      <button data-act="open" data-what="project">Open my project folder</button>
      <button data-act="close-review" style="margin-left:auto">Close</button>
      <div class="note">Nothing changes in your real folder until you press Apply. A backup of every file it replaces is made first, and Undo puts it all back.${r.trial ? " The test copy is a separate copy with the AI's changes; try it there first." : ""}</div>
    </div>`;
  $("#overlay").hidden = false;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#overlay").hidden) closeReview(); });
$("#overlay").addEventListener("click", (e) => { if (e.target.id === "overlay") closeReview(); });
async function makeNew(path) {
  $("#newbtn").disabled = true;
  if (!path) toast("A folder picker opened. If you don't see it, check the taskbar.", 6000);
  const r = await post("/api/new", path ? { path } : {});
  $("#newbtn").disabled = false;
  if (r.ok) { toast("Working on it…"); $("#pathbox").value = ""; }
  else if (!r.cancelled) toast(r.error || "Couldn't start it.");
  refresh();
}
$("#newbtn").addEventListener("click", () => makeNew($("#pathbox").value.trim()));
$("#pathbox").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.value.trim()) makeNew(e.target.value.trim()); });
$("#filter").addEventListener("input", render);
document.addEventListener("toggle", (e) => {
  const d = e.target; if (!d.matches || !d.matches("details.older")) return;
  d.open ? openOlder.add(d.dataset.key) : openOlder.delete(d.dataset.key);
}, true);
window.addEventListener("focus", refresh);
if (location.hash.startsWith("#review=")) { const rid = decodeURIComponent(location.hash.slice(8)); flashId = ""; refresh().then(() => openReview(rid)); }
else refresh();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
