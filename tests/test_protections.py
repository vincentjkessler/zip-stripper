"""Tests for v1.5.0: secret protection, .gitignore support, duplicate/media trimming.

Fake keys are built by joining pieces so this file itself never contains a
key-shaped string (otherwise Zip Stripper would rightly leave it out).
"""
import contextlib
import io
import tempfile
from pathlib import Path
import unittest
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zip_stripper import (
    find_gitignored_paths,
    main,
    scan_text_for_secrets,
    secret_name_reason,
    strip_and_zip_project,
)

FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3
FAKE_OPENAI = "sk-" + "proj-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0Fe"
FAKE_GITHUB = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
FAKE_AWS = "AK" + "IA" + "ABCDEFGHIJ234567"
FAKE_GOOGLE = "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"
FAKE_STRIPE = "sk" + "_live_" + "a1B2c3D4e5F6g7H8i9J0"
PRIVATE_KEY_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def zip_names(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def run(src: Path, out: Path, **kwargs):
    """Run quietly and also capture anything printed (secret banner prints even when quiet)."""
    buffer = io.StringIO()
    kwargs.setdefault("quiet", True)
    with contextlib.redirect_stdout(buffer):
        result = strip_and_zip_project(src, out, **kwargs)
    return result, buffer.getvalue()


def make_secret_project(root: Path) -> Path:
    src = root / "Secret Project"
    write(src / "src" / "clean.py", "def add(a, b):\n    return a + b\n")
    write(src / "src" / "leaky.py", f'API_KEY = "{FAKE_ANTHROPIC}"\n')
    write(src / "credentials.json", '{"client_secret": "y"}')
    write(src / "secrets.toml", 'token = "abc"\n')
    write(src / "server.pem", "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    write(src / ".ssh" / "id_rsa", PRIVATE_KEY_HEADER + "\nabc\n")
    write(src / ".env", "SECRET=1\n")
    return src


class SecretProtectionTests(unittest.TestCase):
    def test_secret_folder_zip_holds_only_clean_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            (zip_path, receipt, _), printed = run(src, tmp / "out")
            self.assertEqual(zip_names(zip_path), {"src/clean.py"})
            text = receipt.read_text(encoding="utf-8")
            self.assertIn("SECRETS FOUND", text)
            for rel in ["src/leaky.py", "credentials.json", "secrets.toml", "server.pem", ".ssh/id_rsa"]:
                self.assertIn(rel, text)
                self.assertIn(rel, printed)
            self.assertIn("Anthropic API key (line 1)", text)
            # Original folder untouched.
            self.assertTrue((src / "src" / "leaky.py").exists())
            self.assertTrue((src / ".ssh" / "id_rsa").exists())

    def test_secret_value_is_never_printed_or_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            out = tmp / "out"
            (_, _, _), printed = run(src, out, quiet=False)
            self.assertNotIn(FAKE_ANTHROPIC, printed)
            self.assertNotIn("A1b2C3d4E5", printed)
            for report in out.iterdir():
                if report.suffix != ".zip":
                    self.assertNotIn("A1b2C3d4E5", report.read_text(encoding="utf-8"), report.name)

    def test_keep_secrets_file_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            (zip_path, receipt, _), printed = run(src, tmp / "out", keep_secret_paths=["server.pem"])
            self.assertEqual(zip_names(zip_path), {"src/clean.py", "server.pem"})
            self.assertIn("KEPT ON PURPOSE", receipt.read_text(encoding="utf-8"))
            self.assertIn("KEPT!", printed)

    def test_keep_secrets_file_from_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            out = tmp / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main([str(src), "-o", str(out), "--no-open", "--quiet", "--keep-secrets-file", "src/leaky.py"])
            self.assertEqual(code, 0)
            zip_path = next(out.glob("*.zip"))
            self.assertEqual(zip_names(zip_path), {"src/clean.py", "src/leaky.py"})

    def test_keep_rules_cannot_sneak_secrets_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            write(src / ".zipstripperignore", "keep: **\n")
            (zip_path, _, _), _ = run(src, tmp / "out", keep_paths=["src/leaky.py", ".ssh"])
            names = zip_names(zip_path)
            self.assertNotIn("src/leaky.py", names)
            self.assertNotIn(".ssh/id_rsa", names)
            self.assertNotIn("credentials.json", names)

    def test_keep_secret_rule_in_zipstripperignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            write(src / ".zipstripperignore", "keep-secret: secrets.toml\n")
            (zip_path, _, _), _ = run(src, tmp / "out")
            self.assertIn("secrets.toml", zip_names(zip_path))
            self.assertNotIn("credentials.json", zip_names(zip_path))

    def test_copy_then_strip_mode_also_removes_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = make_secret_project(tmp)
            (zip_path, _, _), _ = run(src, tmp / "out", copy_then_strip=True)
            self.assertEqual(zip_names(zip_path), {"src/clean.py"})

    def test_token_configs_only_dropped_when_they_hold_a_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            write(src / "main.py", "print(1)")
            write(src / "a" / ".npmrc", "//registry.npmjs.org/:_authToken=abc123\n")
            write(src / "b" / ".npmrc", "save-exact=true\n")
            write(src / ".pypirc", "[pypi]\nusername = __token__\npassword = pypi-abc\n")
            write(src / "keys" / "id_ed25519.pub", "ssh-ed25519 AAAA user@host\n")
            write(src / "secrets.example.toml", 'token = "put-yours-here"\n')
            write(src / ".env.example", "SECRET=\n")
            (zip_path, _, _), _ = run(src, tmp / "out")
            names = zip_names(zip_path)
            self.assertNotIn("a/.npmrc", names)
            self.assertNotIn(".pypirc", names)
            self.assertIn("b/.npmrc", names)
            self.assertIn("keys/id_ed25519.pub", names)
            self.assertIn("secrets.example.toml", names)
            self.assertIn(".env.example", names)

    def test_keep_env_still_keeps_env_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            write(src / "main.py", "print(1)")
            write(src / ".env", f"ANTHROPIC_API_KEY={FAKE_ANTHROPIC}\n")
            (zip_path, _, _), _ = run(src, tmp / "out", keep_env=True)
            self.assertIn(".env", zip_names(zip_path))

    def test_content_patterns_detect_each_kind(self):
        cases = {
            "Anthropic API key": FAKE_ANTHROPIC,
            "OpenAI API key": FAKE_OPENAI,
            "GitHub token": FAKE_GITHUB,
            "AWS access key": FAKE_AWS,
            "Google API key": FAKE_GOOGLE,
            "Stripe key": FAKE_STRIPE,
            "Private key": PRIVATE_KEY_HEADER,
        }
        with tempfile.TemporaryDirectory() as tmp:
            for kind, value in cases.items():
                path = write(Path(tmp) / "f.txt", f"line one\nkey = '{value}'\n")
                self.assertIn((kind, 2), scan_text_for_secrets(path), kind)

    def test_ordinary_text_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(Path(tmp) / "f.py", "import sklearn  # sk-learn\nrunner = 'task-runner-abcdefghijklmnopqrstuvwxyz'\nkey = os.environ['OPENAI_API_KEY']\n")
            self.assertEqual(scan_text_for_secrets(path), [])
            binary = Path(tmp) / "img.bin"
            binary.write_bytes(b"\x00\x01" + FAKE_ANTHROPIC.encode())
            self.assertEqual(scan_text_for_secrets(binary), [])

    def test_name_rules(self):
        for rel in ["credentials.json", "credentials-prod.json", "a/.aws/config", "certs/site.key", "x.p12", "y.pfx", "id_rsa", "deploy/id_ed25519", "service-account.json", ".git-credentials"]:
            self.assertIsNotNone(secret_name_reason(rel), rel)
        for rel in ["src/main.py", "id_rsa.pub", "keyboard.js", "credentials.example.json", "docs/secrets.md.template"]:
            self.assertIsNone(secret_name_reason(rel), rel)


class GitignoreTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        src = root / "Proj"
        write(src / "main.py", "print(1)")
        write(src / ".gitignore", "data/\n/top.txt\n*.secretlog\n!keep.secretlog\nout/\n")
        write(src / "data" / "private.json", '{"me": 1}')
        write(src / "top.txt", "root only")
        write(src / "sub" / "top.txt", "not anchored here")
        write(src / "a.secretlog", "x")
        write(src / "keep.secretlog", "x")
        write(src / "out", "a file named out, not a folder")
        write(src / "sub" / ".gitignore", "local-only.txt\n")
        write(src / "sub" / "local-only.txt", "x")
        write(src / "local-only.txt", "nested rule must not reach the root")
        write(src / "sub" / "deep" / "data" / "x.txt", "unanchored dir rule matches at any depth")
        return src

    def test_gitignore_honoured_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = self.make_project(tmp)
            (zip_path, receipt, _), _ = run(src, tmp / "out")
            names = zip_names(zip_path)
            self.assertNotIn("data/private.json", names)
            self.assertNotIn("top.txt", names)
            self.assertIn("sub/top.txt", names)
            self.assertNotIn("a.secretlog", names)
            self.assertIn("keep.secretlog", names)
            self.assertIn("out", names)
            self.assertNotIn("sub/local-only.txt", names)
            self.assertIn("local-only.txt", names)
            self.assertNotIn("sub/deep/data/x.txt", names)
            self.assertIn(".gitignore", names)
            self.assertIn("main.py", names)
            self.assertIn("Left out because the project's .gitignore", receipt.read_text(encoding="utf-8"))

    def test_no_gitignore_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = self.make_project(tmp)
            (zip_path, _, _), _ = run(src, tmp / "out", use_gitignore=False)
            names = zip_names(zip_path)
            self.assertIn("data/private.json", names)
            self.assertIn("top.txt", names)
            self.assertIn("sub/local-only.txt", names)

    def test_no_gitignore_from_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = self.make_project(tmp)
            out = tmp / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                main([str(src), "-o", str(out), "--no-open", "--quiet", "--no-gitignore"])
            self.assertIn("data/private.json", zip_names(next(out.glob("*.zip"))))

    def test_zipstripperignore_still_works_on_top(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = self.make_project(tmp)
            write(src / "notes.md", "drop me")
            write(src / ".zipstripperignore", "notes.md\nkeep: data/private.json\n")
            (zip_path, _, _), _ = run(src, tmp / "out")
            names = zip_names(zip_path)
            self.assertNotIn("notes.md", names)
            self.assertIn("data/private.json", names)  # explicit keep beats .gitignore

    def test_double_star_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "P"
            write(src / ".gitignore", "**/generated/**\nnotes/**/*.txt\n")
            write(src / "a" / "generated" / "x.js")
            write(src / "notes" / "2026" / "10" / "day.txt")
            write(src / "notes" / "keep.md")
            found = find_gitignored_paths(src)
            self.assertIn("a/generated/x.js", found)
            self.assertIn("notes/2026/10/day.txt", found)
            self.assertNotIn("notes/keep.md", found)


class DuplicateAndMediaTests(unittest.TestCase):
    def test_exact_duplicates_kept_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            body = "same content " * 200
            write(src / "art" / "hero.svg", body)
            write(src / "site" / "copy" / "hero.svg", body)
            write(src / "other.svg", body + "different")
            (zip_path, receipt, _), _ = run(src, tmp / "out")
            names = zip_names(zip_path)
            self.assertIn("art/hero.svg", names)
            self.assertNotIn("site/copy/hero.svg", names)
            self.assertIn("other.svg", names)
            self.assertIn("same as `art/hero.svg`", receipt.read_text(encoding="utf-8"))
            self.assertTrue((src / "site" / "copy" / "hero.svg").exists())

    def test_keep_duplicates_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            write(src / "a.txt", "dup " * 500)
            write(src / "b" / "a.txt", "dup " * 500)
            (zip_path, _, _), _ = run(src, tmp / "out", keep_duplicates=True)
            self.assertTrue({"a.txt", "b/a.txt"} <= zip_names(zip_path))

    def test_big_media_left_out_small_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            write(src / "main.py", "print(1)")
            (src / "shots").mkdir()
            (src / "shots" / "big.png").write_bytes(b"\x89PNG" + b"\x01" * (300 * 1024))
            (src / "icon.png").write_bytes(b"\x89PNG" + b"\x02" * (10 * 1024))
            (zip_path, receipt, _), _ = run(src, tmp / "out")
            names = zip_names(zip_path)
            self.assertNotIn("shots/big.png", names)
            self.assertIn("icon.png", names)
            self.assertIn("Big images/media left out", receipt.read_text(encoding="utf-8"))

            (zip_path, _, _), _ = run(src, tmp / "out2", keep_media=True)
            self.assertIn("shots/big.png", zip_names(zip_path))

            (zip_path, _, _), _ = run(src, tmp / "out3", media_cutoff_kb=5)
            self.assertNotIn("icon.png", zip_names(zip_path))

    def test_keep_media_from_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            (src / "shots").mkdir(parents=True)
            (src / "shots" / "big.jpg").write_bytes(b"\xff\xd8" + b"\x01" * (300 * 1024))
            out = tmp / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                main([str(src), "-o", str(out), "--no-open", "--quiet", "--keep-media"])
            self.assertIn("shots/big.jpg", zip_names(next(out.glob("*.zip"))))

    def test_plain_profile_keeps_media_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            (src / "a").mkdir(parents=True)
            (src / "a" / "big.png").write_bytes(b"\x89PNG" + b"\x01" * (300 * 1024))
            (src / "big-copy.png").write_bytes(b"\x89PNG" + b"\x01" * (300 * 1024))
            (zip_path, _, _), _ = run(src, tmp / "out", profile="plain")
            self.assertTrue({"a/big.png", "big-copy.png"} <= zip_names(zip_path))

    def test_user_keep_path_protects_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            (src / "art").mkdir(parents=True)
            (src / "art" / "cover.png").write_bytes(b"\x89PNG" + b"\x01" * (300 * 1024))
            (zip_path, _, _), _ = run(src, tmp / "out", keep_paths=["art"])
            self.assertIn("art/cover.png", zip_names(zip_path))

    def test_too_big_for_ai_chat_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            write(src / "main.py", "print(1)")
            write(src / "bigdocs" / "dump.md", "".join(f"line {i} of a very long document\n" for i in range(70000)))
            (zip_path, receipt, _), printed = run(src, tmp / "out", quiet=False)
            self.assertIn("STILL TOO BIG FOR ONE AI CHAT", printed)
            self.assertIn("bigdocs/", printed)
            self.assertIn("still too big for one AI chat", receipt.read_text(encoding="utf-8"))

    def test_no_warning_for_small_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "Proj"
            write(src / "main.py", "print(1)")
            (_, _, _), printed = run(src, tmp / "out", quiet=False)
            self.assertNotIn("STILL TOO BIG", printed)


if __name__ == "__main__":
    unittest.main()
