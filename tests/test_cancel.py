"""Cancel stops a running job on the Library page (e.g. "Only what changed") and tidies up after it."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import zip_stripper_web as web  # noqa: E402

SLOW_JOB = (
    "import sys, time, pathlib\n"
    "run = pathlib.Path(sys.argv[1])\n"
    "(run / 'details').mkdir(parents=True)\n"
    "(run / 'half.zip').write_bytes(b'x' * 1000)\n"
    "print('[Zip Stripper] Working folder: ' + str(run), flush=True)\n"
    "time.sleep(60)\n"
)


class CancelJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.library = Path(self.tmp.name) / "lib"
        self.finished = self.library / "proj" / "2026-01-01_000000"
        (self.finished / "details").mkdir(parents=True)
        (self.finished / "details" / web.zs.LIBRARY_ENTRY_NAME).write_text("{}", encoding="utf-8")
        self.server = web.make_server(self.library, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", path, body=json.dumps(body), headers={
            "Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", "X-ZipStripper": "1"})
        data = json.loads(conn.getresponse().read())
        conn.close()
        return data

    def wait_for(self, check, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(0.1)
        return False

    def start_slow_job(self, run_dir):
        return web.start_command_job([sys.executable, "-c", SLOW_JOB, str(run_dir)],
                                     "Only what changed: proj", root=self.library)

    def test_cancel_stops_the_job_and_removes_the_half_made_folder(self):
        run_dir = self.library / "proj" / "2026-01-02_000000"
        job = self.start_slow_job(run_dir)
        self.assertTrue(self.wait_for(lambda: run_dir.exists() and str(job["id"]) in web.WORK_DIRS))
        started = time.time()
        self.assertEqual(self.post("/api/cancel-job", {"job": job["id"]}), {"ok": True})
        self.assertTrue(self.wait_for(lambda: job["status"] != "running"))
        self.assertLess(time.time() - started, 15, "Cancel should not wait for the job to finish")
        self.assertEqual(job["status"], "cancelled")
        self.assertTrue(self.wait_for(lambda: not run_dir.exists()), "half-made folder should be gone")
        self.assertTrue(self.finished.exists(), "finished ZIPs must never be touched")

    def test_cancel_after_finishing_changes_nothing(self):
        job = web.start_command_job([sys.executable, "-c", "print('done')"], "Redo: proj", root=self.library)
        self.assertTrue(self.wait_for(lambda: job["status"] != "running"))
        self.assertEqual(self.post("/api/cancel-job", {"job": job["id"]}), {"ok": False})
        self.assertEqual(job["status"], "done")
        self.assertEqual(self.post("/api/cancel-job", {"job": "nope"}), {"ok": False})

    def test_cleanup_never_removes_a_finished_run_or_anything_outside_the_library(self):
        web.remove_unfinished_run(self.library, self.finished)
        self.assertTrue(self.finished.exists())
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        web.remove_unfinished_run(self.library, outside)
        self.assertTrue(outside.exists())
        web.remove_unfinished_run(self.library, self.library)
        self.assertTrue(self.library.exists())

    def test_page_has_a_cancel_button_for_running_jobs(self):
        self.assertIn('data-act="cancel-job"', web.PAGE_HTML)
        self.assertIn("/api/cancel-job", web.PAGE_HTML)


if __name__ == "__main__":
    unittest.main()
