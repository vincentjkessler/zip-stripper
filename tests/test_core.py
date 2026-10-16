import csv
import tempfile
from pathlib import Path
import unittest
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zip_stripper import (
    strip_and_zip_project,
    default_output_dir,
    clean_copy_project,
    scan_project,
)


class ZipStripperTests(unittest.TestCase):
    def zip_names(self, zip_path):
        with zipfile.ZipFile(zip_path) as zf:
            return set(zf.namelist())

    def test_default_output_dir_has_zip_stripper_folder(self):
        self.assertEqual(default_output_dir().name, "ZipStripper_Output")

    def test_strips_heavy_dirs_and_env_from_copy_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "MyProject"
            src.mkdir()
            (src / "src").mkdir()
            (src / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
            (src / "node_modules").mkdir()
            (src / "node_modules" / "big.js").write_text("x" * 1000, encoding="utf-8")
            (src / ".git").mkdir()
            (src / ".git" / "config").write_text("[core]", encoding="utf-8")
            (src / ".env").write_text("SECRET=1", encoding="utf-8")
            (src / ".env.example").write_text("SECRET=", encoding="utf-8")

            out = tmp / "out"
            zip_path, receipt, size_report = strip_and_zip_project(src, out, quiet=True, copy_then_strip=True)

            self.assertTrue(zip_path.exists())
            self.assertTrue(receipt.exists())
            self.assertTrue(size_report.exists())
            self.assertTrue((src / "node_modules" / "big.js").exists())
            self.assertTrue((src / ".git" / "config").exists())

            names = self.zip_names(zip_path)
            self.assertIn("src/app.py", names)
            self.assertIn(".env.example", names)
            self.assertNotIn("node_modules/big.js", names)
            self.assertNotIn(".git/config", names)
            self.assertNotIn(".env", names)

    def test_fast_clean_copy_strips_pycache_and_pytest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "__pycache__").mkdir()
            (src / "__pycache__" / "a.pyc").write_bytes(b"x")
            (src / ".pytest_cache").mkdir()
            (src / ".pytest_cache" / "README.md").write_text("cache", encoding="utf-8")
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            out = tmp / "out"

            zip_path, _, _ = strip_and_zip_project(src, out, quiet=True)
            names = self.zip_names(zip_path)
            self.assertIn("main.py", names)
            self.assertNotIn("__pycache__/a.pyc", names)
            self.assertNotIn(".pytest_cache/README.md", names)

    def test_keep_selected_archive_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            (src / "important.zip").write_bytes(b"important")
            (src / "junk.zip").write_bytes(b"junk")
            out = tmp / "out"

            zip_path, receipt, _ = strip_and_zip_project(src, out, quiet=True, keep_paths=["important.zip"])
            names = self.zip_names(zip_path)
            self.assertIn("important.zip", names)
            self.assertNotIn("junk.zip", names)
            self.assertIn("important.zip", receipt.read_text(encoding="utf-8"))

    def test_drop_selected_kept_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "src").mkdir()
            (src / "src" / "app.py").write_text("print(1)", encoding="utf-8")
            (src / "docs").mkdir()
            (src / "docs" / "huge.txt").write_text("x" * 1000, encoding="utf-8")
            out = tmp / "out"

            zip_path, _, _ = strip_and_zip_project(src, out, quiet=True, drop_paths=["docs"])
            names = self.zip_names(zip_path)
            self.assertIn("src/app.py", names)
            self.assertNotIn("docs/huge.txt", names)

    def test_size_reports_are_written_with_all_kept_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "a.txt").write_text("a", encoding="utf-8")
            (src / "b.txt").write_text("bb", encoding="utf-8")
            out = tmp / "out"

            zip_path, receipt, size_report = strip_and_zip_project(src, out, quiet=True)
            self.assertTrue(zip_path.exists())
            self.assertTrue(size_report.exists())
            receipt_text = receipt.read_text(encoding="utf-8")
            self.assertIn("Final contents CSV", receipt_text)
            csv_paths = list(out.glob("*_ZIP_CONTENTS_SIZE_REPORT_*.csv"))
            self.assertEqual(len(csv_paths), 1)
            with csv_paths[0].open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual({r["path"] for r in rows}, {"a.txt", "b.txt"})
            self.assertTrue(all("size_bytes" in r for r in rows))

    def test_scan_project_reports_removed_and_kept_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "a.txt").write_text("a", encoding="utf-8")
            (src / "data.zip").write_bytes(b"zip")
            scan = scan_project(src)
            removed = {item["path"] for item in scan["removed"]}
            kept = {item["path"] for item in scan["kept_files"]}
            self.assertIn("data.zip", removed)
            self.assertIn("a.txt", kept)


if __name__ == "__main__":
    unittest.main()

class ZipStripperSmartTests(unittest.TestCase):
    def zip_names(self, zip_path):
        with zipfile.ZipFile(zip_path) as zf:
            return set(zf.namelist())

    def test_smart_keeps_evidence_packet_but_drops_regular_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            (src / "PROJECT_EXTERNAL_AUDIT_BUNDLE.zip").write_bytes(b"audit")
            (src / "random_download.zip").write_bytes(b"junk")
            out = tmp / "out"

            zip_path, receipt, _ = strip_and_zip_project(src, out, quiet=True)
            names = self.zip_names(zip_path)
            self.assertIn("PROJECT_EXTERNAL_AUDIT_BUNDLE.zip", names)
            self.assertNotIn("random_download.zip", names)
            self.assertIn("Smart mode: yes", receipt.read_text(encoding="utf-8"))

    def test_smart_drops_duplicate_nested_evidence_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "state").mkdir()
            packet = b"same-packet"
            (src / "state" / "PROJECT_AUDIT_CONTEXT_PACKET.zip").write_bytes(packet)
            nested = src / "state" / "deep" / "packet" / "artifacts" / "reviewer_packet_related" / "state"
            nested.mkdir(parents=True)
            (nested / "PROJECT_AUDIT_CONTEXT_PACKET.zip").write_bytes(packet)
            out = tmp / "out"

            zip_path, _, _ = strip_and_zip_project(src, out, quiet=True)
            names = self.zip_names(zip_path)
            self.assertIn("state/PROJECT_AUDIT_CONTEXT_PACKET.zip", names)
            self.assertNotIn("state/deep/packet/artifacts/reviewer_packet_related/state/PROJECT_AUDIT_CONTEXT_PACKET.zip", names)

    def test_smart_drops_large_raw_download_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            raw = src / "state" / "run" / "downloads"
            raw.mkdir(parents=True)
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            (raw / "huge.evt").write_bytes(b"x" * (2 * 1024 * 1024))
            out = tmp / "out"

            zip_path, _, _ = strip_and_zip_project(src, out, quiet=True)
            names = self.zip_names(zip_path)
            self.assertIn("main.py", names)
            self.assertNotIn("state/run/downloads/huge.evt", names)

    def test_user_keep_path_overrides_smart_drop(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            (src / "random_download.zip").write_bytes(b"keep me")
            out = tmp / "out"

            zip_path, _, _ = strip_and_zip_project(src, out, quiet=True, keep_paths=["random_download.zip"])
            names = self.zip_names(zip_path)
            self.assertIn("random_download.zip", names)

class ZipStripperSourceProfileTests(unittest.TestCase):
    def zip_names(self, zip_path):
        with zipfile.ZipFile(zip_path) as zf:
            return set(zf.namelist())

    def test_source_profile_keeps_source_but_drops_state_and_domain_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "BigProject"
            src.mkdir()
            (src / "main.py").write_text("print('project')", encoding="utf-8")
            (src / "core").mkdir()
            (src / "core" / "engine.py").write_text("x=1", encoding="utf-8")
            (src / "project_core").mkdir()
            (src / "project_core" / "governance.py").write_text("RULE=True", encoding="utf-8")
            (src / "docs").mkdir()
            (src / "docs" / "README.md").write_text("docs", encoding="utf-8")
            (src / "tests").mkdir()
            (src / "tests" / "test_engine.py").write_text("def test_x(): pass", encoding="utf-8")
            (src / "state" / "physics_data" / "solar_wind").mkdir(parents=True)
            (src / "state" / "physics_data" / "solar_wind" / "omni2_all_years.dat").write_bytes(b"x" * 1024)
            (src / "state" / "PROJECT_AUDIT_CONTEXT_PACKET.zip").write_bytes(b"packet")
            (src / "domains" / "data" / "jena_climate").mkdir(parents=True)
            (src / "domains" / "data" / "jena_climate" / "jena.csv").write_text("date,temp", encoding="utf-8")
            out = tmp / "out"

            zip_path, receipt, size_report = strip_and_zip_project(src, out, quiet=True, profile="source")
            names = self.zip_names(zip_path)
            self.assertIn("main.py", names)
            self.assertIn("core/engine.py", names)
            self.assertIn("project_core/governance.py", names)
            self.assertIn("docs/README.md", names)
            self.assertIn("tests/test_engine.py", names)
            self.assertIn("_ZIP_STRIPPER/SOURCE_SELECTION_REPORT.md", names)
            self.assertNotIn("state/physics_data/solar_wind/omni2_all_years.dat", names)
            self.assertNotIn("state/PROJECT_AUDIT_CONTEXT_PACKET.zip", names)
            self.assertNotIn("domains/data/jena_climate/jena.csv", names)
            self.assertIn("Profile: source", receipt.read_text(encoding="utf-8"))
            self.assertTrue(size_report.exists())
            reports = list(out.glob("*_ZIP_STRIPPER_SOURCE_SELECTION_*.md"))
            self.assertEqual(len(reports), 1)

    def test_source_keep_path_can_restore_specific_file_under_dropped_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "BigProject"
            (src / "state").mkdir(parents=True)
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            (src / "state" / "needed_fixture.json").write_text("{}", encoding="utf-8")
            out = tmp / "out"

            zip_path, _, _ = strip_and_zip_project(src, out, quiet=True, profile="source", keep_paths=["state/needed_fixture.json"])
            names = self.zip_names(zip_path)
            self.assertIn("main.py", names)
            self.assertIn("state/needed_fixture.json", names)

class ZipStripperProductizationTests(unittest.TestCase):
    def zip_names(self, zip_path):
        with zipfile.ZipFile(zip_path) as zf:
            return set(zf.namelist())

    def test_zipstripperignore_drop_and_keep_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "main.py").write_text("print(1)", encoding="utf-8")
            (src / "docs").mkdir()
            (src / "docs" / "drop_me.md").write_text("drop", encoding="utf-8")
            (src / "state").mkdir()
            (src / "state" / "needed_fixture.json").write_text("{}", encoding="utf-8")
            (src / ".zipstripperignore").write_text("drop: docs/drop_me.md\nkeep: state/needed_fixture.json\n", encoding="utf-8")
            out = tmp / "out"

            zip_path, receipt, _ = strip_and_zip_project(src, out, quiet=True, profile="source")
            names = self.zip_names(zip_path)
            self.assertIn("main.py", names)
            self.assertNotIn("docs/drop_me.md", names)
            self.assertIn("state/needed_fixture.json", names)
            self.assertIn(".zipstripperignore loaded: yes", receipt.read_text(encoding="utf-8"))

    def test_html_and_token_reports_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            src.mkdir()
            (src / "main.py").write_text("print('hello')\n" * 20, encoding="utf-8")
            out = tmp / "out"

            zip_path, receipt, _ = strip_and_zip_project(src, out, quiet=True, destination="chatgpt")
            self.assertTrue(zip_path.exists())
            token_reports = list(out.glob("*_ZIP_STRIPPER_TOKEN_ESTIMATE_*.md"))
            html_reports = list(out.glob("*_ZIP_STRIPPER_REPORT_*.html"))
            self.assertEqual(len(token_reports), 1)
            self.assertEqual(len(html_reports), 1)
            self.assertIn("Estimated text/code tokens", token_reports[0].read_text(encoding="utf-8"))
            receipt_text = receipt.read_text(encoding="utf-8")
            self.assertIn("Destination preset: chatgpt", receipt_text)
            self.assertIn("Token estimate report", receipt_text)
            self.assertIn("HTML report", receipt_text)

class ZipStripperGuiPackagingTests(unittest.TestCase):
    def test_gui_flag_is_present_in_help(self):
        import subprocess
        import sys
        script = Path(__file__).resolve().parents[1] / "zip_stripper.py"
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=True)
        self.assertIn("--gui", result.stdout)

    def test_gui_wrapper_exists(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "ZipStripper-GUI.cmd").exists())
        self.assertIn("--gui", (root / "ZipStripper-GUI.cmd").read_text(encoding="utf-8"))

    def test_public_repo_keeps_only_simple_windows_launchers(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "ZipStripper.cmd").exists())
        self.assertTrue((root / "ZipStripper-GUI.cmd").exists())
        self.assertFalse((root / "Build-Standalone.ps1").exists())
        self.assertFalse((root / "Install-ContextMenu.ps1").exists())
        self.assertFalse((root / "ZipStripper.spec").exists())
