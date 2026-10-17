"""The finished ZIP goes on the clipboard after a run (the right-click path), ready for Ctrl+V."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zip_stripper as zs  # noqa: E402


class ClipboardAfterRunTests(unittest.TestCase):
    def run_main(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "proj"
            (src / "src").mkdir(parents=True)
            (src / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
            out = Path(tmp) / "out"
            env = {k: v for k, v in os.environ.items() if k != "ZIPSTRIPPER_NO_CLIPBOARD"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(zs, "copy_files_to_clipboard", return_value=True) as clip, \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                code = zs.main([str(src), "-o", str(out), "--no-open", "--quiet", *extra])
            return code, clip, printed.getvalue()

    def test_zip_is_copied_after_a_run(self):
        code, clip, printed = self.run_main()
        self.assertEqual(code, 0)
        clip.assert_called_once()
        files = clip.call_args[0][0]
        self.assertEqual(len(files), 1)
        self.assertTrue(str(files[0]).endswith(".zip"))
        self.assertIn("Ctrl+V", printed)

    def test_no_copy_flag_leaves_the_clipboard_alone(self):
        code, clip, _ = self.run_main("--no-copy")
        self.assertEqual(code, 0)
        clip.assert_not_called()


    def test_clipboard_helper_really_runs(self):
        # Not mocked at the zip_stripper level: catches a missing import or a broken command line.
        fake = mock.Mock(returncode=0)
        with mock.patch("subprocess.run", return_value=fake) as run, mock.patch.object(zs.os, "name", "nt"):
            self.assertTrue(zs.copy_files_to_clipboard([Path("C:/x/a.zip")]))
        cmd = run.call_args[0][0]
        self.assertIn("Set-Clipboard -LiteralPath", cmd[-1])
        self.assertEqual(run.call_args[1]["env"]["ZS_CLIP_FILE"], str(Path("C:/x/a.zip")))


if __name__ == "__main__":
    unittest.main()
