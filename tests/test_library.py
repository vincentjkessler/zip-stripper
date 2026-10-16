"""Tests for the Zip Stripper Library (library folder layout + local web page)."""
import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path
import unittest
from unittest import mock
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import zip_stripper as zs
import zip_stripper_web as web

FAKE_KEY = "sk-" + "ant-" + "api03-" + "Q1w2E3r4T5y6U7i8O9p0" * 3


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_project(root: Path, name: str = "My Project") -> Path:
    src = root / name
    write(src / "main.py", "print('hi')\n")
    write(src / "leak.py", f"KEY = '{FAKE_KEY}'\n")
    write(src / ".gitignore", "private/\n")
    write(src / "private" / "notes.txt", "mine")
    return src


def quiet_zip(src: Path, library: Path, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return zs.strip_and_zip_project(src, library, quiet=True, library=True, **kwargs)


class LibraryLayoutTests(unittest.TestCase):
    def test_zip_alone_with_reports_tucked_into_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_project(tmp)
            library = tmp / "lib"
            zip_path, receipt, size_report = quiet_zip(src, library)
            run_dir = zip_path.parent
            self.assertEqual(run_dir.parent, library / "My_Project")
            self.assertEqual([p.name for p in run_dir.iterdir() if p.is_file()], [zip_path.name])
            self.assertEqual(receipt.parent, run_dir / "details")
            self.assertEqual(size_report.parent, run_dir / "details")
            entry = json.loads((run_dir / "details" / zs.LIBRARY_ENTRY_NAME).read_text(encoding="utf-8"))
            self.assertEqual(entry["source"], str(src.resolve()))
            self.assertEqual(entry["zip"], zip_path.name)
            self.assertEqual([s["path"] for s in entry["secrets_left_out"]], ["leak.py"])
            self.assertEqual(entry["gitignore_left_out"], 1)
            self.assertNotIn("Q1w2E3r4", json.dumps(entry))
            with zipfile.ZipFile(zip_path) as zf:
                self.assertEqual(set(zf.namelist()), {"main.py", ".gitignore"})

    def test_two_runs_same_second_get_separate_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_project(tmp)
            fixed = zs._dt.datetime(2026, 10, 15, 12, 0, 0)
            with mock.patch.object(zs._dt, "datetime", wraps=zs._dt.datetime) as dt:
                dt.now.return_value = fixed
                first, _, _ = quiet_zip(src, tmp / "lib")
                second, _, _ = quiet_zip(src, tmp / "lib")
            self.assertNotEqual(first.parent, second.parent)
            self.assertTrue(first.exists() and second.exists())

    def test_cli_defaults_to_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_project(tmp)
            library = tmp / "lib"
            with mock.patch.dict(os.environ, {"ZIPSTRIPPER_LIBRARY": str(library)}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(zs.main([str(src), "--no-open", "--quiet"]), 0)
            self.assertEqual(len(list(library.glob("*/*/details/" + zs.LIBRARY_ENTRY_NAME))), 1)

    def test_cli_output_keeps_old_flat_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_project(tmp)
            out = tmp / "flat"
            with contextlib.redirect_stdout(io.StringIO()):
                zs.main([str(src), "-o", str(out), "--no-open", "--quiet"])
            self.assertEqual(len(list(out.glob("*.zip"))), 1)
            self.assertEqual(len(list(out.glob("*RECEIPT*.md"))), 1)

    def test_scan_groups_by_project_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            a = make_project(tmp, "Alpha")
            b = make_project(tmp, "Beta")
            library = tmp / "lib"
            quiet_zip(a, library)
            time.sleep(1.1)
            quiet_zip(b, library)
            time.sleep(1.1)
            newest_a, _, _ = quiet_zip(a, library)
            data = web.scan_library(library)
            self.assertEqual([p["name"] for p in data["projects"]], ["Alpha", "Beta"])
            alpha = data["projects"][0]
            self.assertEqual(len(alpha["runs"]), 2)
            self.assertEqual(alpha["runs"][0]["zip"], newest_a.name)
            self.assertTrue(alpha["runs"][0]["zip_exists"])
            self.assertIn("Receipt.md", [d["name"] for d in alpha["runs"][0]["details"]])

    def test_redo_arguments_rebuild_switches(self):
        entry = {"source": "C:/p", "redo": {
            "profile": "source", "destination": "claude", "keep_media": True, "use_gitignore": False,
            "media_cutoff_kb": 500, "keep_paths": ["a"], "drop_paths": ["b"], "keep_secret_paths": ["c.pem"]}}
        args = web.redo_arguments(entry)
        self.assertEqual(args[0], "C:/p")
        for expected in (["--profile", "source"], ["--destination", "claude"], ["--media-cutoff-kb", "500"],
                         ["--keep-path", "a"], ["--drop-path", "b"], ["--keep-secrets-file", "c.pem"]):
            i = args.index(expected[0])
            self.assertEqual(args[i:i + 2], expected)
        self.assertIn("--keep-media", args)
        self.assertIn("--no-gitignore", args)
        self.assertEqual(web.redo_arguments({"source": "C:/p", "redo": {"profile": "smart", "use_gitignore": True}}), ["C:/p"])


class LibraryServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = make_project(self.root)
        self.library = self.root / "lib"
        self.zip_path, _, _ = quiet_zip(self.src, self.library)
        self.run_id = self.zip_path.parent.relative_to(self.library).as_posix()
        self.server = web.make_server(self.library, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, host=None, header=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if method == "POST":
            headers["Content-Type"] = "application/json"
            if header:
                headers["X-ZipStripper"] = "1"
        conn.request(method, path, body=json.dumps(body or {}) if method == "POST" else None, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_page_and_library_api(self):
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Zip Stripper", page)
        status, data = self.request("GET", "/api/library")
        library = json.loads(data)
        self.assertEqual(library["projects"][0]["runs"][0]["id"], self.run_id)

    def test_serves_reports_but_nothing_outside_the_library(self):
        status, data = self.request("GET", f"/files/{self.run_id}/details/Receipt.md")
        self.assertEqual(status, 200)
        self.assertIn(b"Receipt", data)
        status, _ = self.request("GET", "/files/../My%20Project/main.py")
        self.assertIn(status, {403, 404})
        status, _ = self.request("GET", "/files/%2E%2E/%2E%2E/Windows/win.ini")
        self.assertIn(status, {403, 404})

    def test_blocks_other_sites(self):
        status, _ = self.request("GET", "/api/library", host="evil.example:80")
        self.assertEqual(status, 403)
        status, _ = self.request("POST", "/api/redo", {"id": self.run_id}, header=False)
        self.assertEqual(status, 403)

    def test_unknown_zip_is_reported(self):
        status, data = self.request("POST", "/api/copy", {"id": "nope/never"})
        self.assertEqual(status, 404)
        status, data = self.request("POST", "/api/copy", {"id": "../.."})
        self.assertEqual(status, 404)

    def test_new_zip_from_typed_path_runs_a_job(self):
        status, data = self.request("POST", "/api/new", {"path": str(self.src)})
        self.assertEqual(status, 200, data)
        job_id = json.loads(data)["job"]
        deadline = time.time() + 90
        job = None
        while time.time() < deadline:
            jobs = json.loads(self.request("GET", "/api/jobs")[1])["jobs"]
            job = next(j for j in jobs if j["id"] == job_id)
            if job["status"] != "running":
                break
            time.sleep(0.3)
        self.assertEqual(job["status"], "done", "\n".join(job["log"]))
        self.assertTrue(job["run_id"])
        runs = web.scan_library(self.library)["projects"][0]["runs"]
        self.assertEqual(len(runs), 2)

    def test_new_zip_rejects_missing_folder(self):
        status, data = self.request("POST", "/api/new", {"path": str(self.root / "does-not-exist")})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
