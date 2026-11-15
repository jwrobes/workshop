"""Unit tests for snapname's pure logic: slugs, folder mapping, placement, paste guard, processing.

Run: python3 -m unittest smart_screenshots/test_snapname.py
"""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
_loader = importlib.machinery.SourceFileLoader("snapname", str(HERE / "snapname"))
_spec = importlib.util.spec_from_loader("snapname", _loader)
snapname = importlib.util.module_from_spec(_spec)
_loader.exec_module(snapname)


class SlugifyTest(unittest.TestCase):
    def test_cleans_model_output(self):
        self.assertEqual(snapname.slugify("`Datadog Error Spike.png`\n", 6), "datadog-error-spike")

    def test_caps_word_count(self):
        self.assertEqual(snapname.slugify("a-b-c-d-e-f-g-h", 3), "a-b-c")

    def test_empty_when_nothing_usable(self):
        self.assertEqual(snapname.slugify("  \n", 6), "")
        self.assertEqual(snapname.slugify("!!!", 6), "")


class ScreenshotNameTest(unittest.TestCase):
    def test_matches_macos_names(self):
        for name in ["Screenshot 2026-10-20 at 4.40.33 PM.png",
                     "Screenshot 2026-10-20 at 4.40.33 PM (2).png",
                     "Screenshot 2026-10-20 at 16.40.33.png"]:
            self.assertIsNotNone(snapname.SCREENSHOT_RE.match(name), name)

    def test_ignores_named_files(self):
        for name in ["2026-10-20_xcode-dialog.png", "Screen Recording 2026-10-20 at 4.40.33 PM.mov",
                     ".Screenshot 2026-10-20 at 4.40.33 PM.png"]:
            self.assertIsNone(snapname.SCREENSHOT_RE.match(name), name)


class WorkingFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "proj_workspace"
        (self.ws / "workbench" / "fix_bug" / ".claude").mkdir(parents=True)
        (self.ws / "proj-fix-bug" / "app").mkdir(parents=True)
        (self.ws / "workbench" / "fix_bug" / ".claude" / "settings.json").write_text(json.dumps(
            {"permissions": {"additionalDirectories": ["../../proj-fix-bug"]}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_workbench_subdir(self):
        folder, label = snapname.working_folder(str(self.ws / "workbench" / "fix_bug"), self.root)
        self.assertEqual(folder, self.ws / "workbench" / "fix_bug")
        self.assertEqual(label, "proj_workspace / fix_bug")

    def test_worktree_maps_back_to_its_workbench(self):
        folder, _ = snapname.working_folder(str(self.ws / "proj-fix-bug" / "app"), self.root)
        self.assertEqual(folder.resolve(), (self.ws / "workbench" / "fix_bug").resolve())

    def test_unclaimed_dir_falls_back_to_workspace(self):
        (self.ws / "scratch").mkdir()
        folder, label = snapname.working_folder(str(self.ws / "scratch"), self.root)
        self.assertEqual(folder, self.ws)
        self.assertEqual(label, "proj_workspace")

    def test_completed_workbench_is_not_a_target(self):
        done = self.ws / "workbench" / "completed" / "old"
        done.mkdir(parents=True)
        folder, _ = snapname.working_folder(str(done), self.root)
        self.assertEqual(folder, self.ws)

    def test_outside_a_workspace(self):
        (self.root / "other").mkdir()
        self.assertEqual(snapname.working_folder(str(self.root / "other"), self.root), (None, None))
        self.assertEqual(snapname.working_folder("/tmp", self.root), (None, None))


class PlaceTest(unittest.TestCase):
    def test_hard_links_and_gitignores(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "shot.png"
            src.write_bytes(b"png")
            dest = snapname.place(src, tmp / "wb", "link")
            self.assertEqual(dest, tmp / "wb" / "screenshots" / "shot.png")
            self.assertTrue(src.exists())
            self.assertEqual(os.stat(src).st_ino, os.stat(dest).st_ino)
            self.assertEqual((tmp / "wb" / "screenshots" / ".gitignore").read_text(), "*\n")
            again = snapname.place(src, tmp / "wb", "link")
            self.assertEqual(again.name, "shot-2.png")

    def test_move_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "shot.png"
            src.write_bytes(b"png")
            dest = snapname.place(src, tmp / "wb", "move")
            self.assertFalse(src.exists())
            self.assertTrue(dest.exists())


class SafeToPasteTest(unittest.TestCase):
    def test_empty_prompt(self):
        self.assertTrue(snapname.safe_to_paste("some output\n\n❯ \n  ? for shortcuts\n"))

    def test_half_typed_prompt(self):
        self.assertTrue(snapname.safe_to_paste("❯ look at this \n"))

    def test_permission_dialog(self):
        screen = "Do you want to proceed?\n❯ 1. Yes\n  2. No\n"
        self.assertFalse(snapname.safe_to_paste(screen))

    def test_no_prompt_visible(self):
        self.assertFalse(snapname.safe_to_paste("$ ls\nfoo\n"))


class PendingTest(unittest.TestCase):
    def test_age_filter_skips_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "Screenshot 2026-01-01 at 1.00.00 PM.png"
            new = Path(tmp) / "Screenshot 2026-10-20 at 1.00.00 PM.png"
            old.write_bytes(b"x")
            new.write_bytes(b"x")
            (Path(tmp) / "named.png").write_bytes(b"x")
            ages = {old.name: 1000.0, new.name: 1990.0}
            with mock.patch.object(snapname, "created_at", side_effect=lambda p: ages[p.name]):
                self.assertEqual(snapname.pending(tmp), [old, new])
                self.assertEqual(snapname.pending(tmp, max_age=120, now=2000.0), [new])


class AppleScriptStringTest(unittest.TestCase):
    def test_escapes_quotes_and_backslashes(self):
        self.assertEqual(snapname.applescript_string('a "b" \\ → c'), '"a \\"b\\" \\\\ → c"')


class VisionCallTest(unittest.TestCase):
    """The vision backend is a command template; fake it with a stub script, no real model."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.img = self.dir / "shot.jpg"
        self.img.write_bytes(b"jpg")
        self.stub = self.dir / "stub.sh"
        self.stub.write_text('#!/bin/sh\necho "args: $*" > "$0.args"\necho "Terminal Build-Error!"\n')
        self.stub.chmod(0o755)
        patcher = mock.patch.object(snapname, "log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, template):
        return dict(snapname.DEFAULTS, vision_cmd=template, model="m1")

    def test_placeholders_filled_and_output_returned(self):
        cfg = self.cfg(f"{self.stub} -m {{model}} -a {{image}} -s {{system}} {{prompt}}")
        out = snapname.call_vision_model(self.img, cfg, "Name this screenshot.")
        self.assertIn("Terminal", out)
        args = (self.dir / "stub.sh.args").read_text()
        self.assertIn("-m m1 -a " + str(self.img), args)
        self.assertIn("Name this screenshot.", args)

    def test_failure_returns_none(self):
        self.assertIsNone(snapname.call_vision_model(self.img, self.cfg("false"), "p"))
        self.assertIsNone(snapname.call_vision_model(self.img, self.cfg("/no/such/cmd {image}"), "p"))

    def test_bad_template_returns_none(self):
        self.assertIsNone(snapname.call_vision_model(self.img, self.cfg("cmd {nope}"), "p"))
        self.assertIsNone(snapname.call_vision_model(self.img, self.cfg("cmd 'unterminated"), "p"))

    def test_env_overrides_config(self):
        with mock.patch.dict(os.environ, {"SNAPNAME_VISION_CMD": "echo hi", "SNAPNAME_MODEL": "zz"}):
            cfg = snapname.load_config()
        self.assertEqual((cfg["vision_cmd"], cfg["model"]), ("echo hi", "zz"))

    def test_default_template_builds(self):
        argv = snapname.build_vision_argv(
            snapname.DEFAULT_VISION_CMD, image="/t/a b.jpg", image_dir="/t", model="m",
            system="sys prompt", prompt="p")
        self.assertEqual(argv[0], "claude")
        self.assertIn("sys prompt", argv)
        self.assertTrue(any("/t/a b.jpg" in a for a in argv))

    def test_slug_from_stub_end_to_end(self):
        cfg = self.cfg(f"{self.stub} {{image}}")
        real_run = snapname.run

        def run_with_fake_sips(cmd, *a, **kw):
            if cmd[0] == "sips":
                Path(cmd[cmd.index("--out") + 1]).write_bytes(b"jpg")
                return ""
            return real_run(cmd, *a, **kw)
        with mock.patch.object(snapname, "run", side_effect=run_with_fake_sips):
            self.assertEqual(snapname.ask_model_for_slug(self.img, cfg), "terminal-build-error")


class ProcessOneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.watch = self.tmp_path / "Screenshots"
        self.watch.mkdir()
        self.shot = self.watch / "Screenshot 2026-10-20 at 4.40.33 PM.png"
        self.shot.write_bytes(b"png-bytes")
        self.wb = self.tmp_path / "wb"
        self.cfg = dict(snapname.DEFAULTS, notify=False)
        patches = [
            mock.patch.object(snapname, "wait_until_stable", return_value=True),
            mock.patch.object(snapname, "log"),
            mock.patch.object(snapname, "resolve_target", return_value=(
                self.wb, "ws / wb", {"id": "%1", "command": "claude", "cwd": "/x"}, "test")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_renames_routes_and_pastes(self):
        with mock.patch.object(snapname, "ask_model_for_slug", return_value="xcode-dialog"), \
                mock.patch.object(snapname, "paste_into_claude", return_value=True) as paste:
            final = snapname.process_one(self.shot, self.cfg)
        self.assertEqual(final, self.wb / "screenshots" / "2026-10-20_xcode-dialog.png")
        self.assertTrue((self.watch / "2026-10-20_xcode-dialog.png").exists())
        self.assertFalse(self.shot.exists())
        paste.assert_called_once()
        self.assertEqual(paste.call_args[0][1], f"{final} ")

    def test_naming_failure_keeps_original(self):
        with mock.patch.object(snapname, "ask_model_for_slug", return_value=None), \
                mock.patch.object(snapname, "paste_into_claude") as paste:
            self.assertIsNone(snapname.process_one(self.shot, self.cfg))
        self.assertTrue(self.shot.exists())
        paste.assert_not_called()

    def test_name_collision_gets_suffix(self):
        (self.watch / "2026-10-20_xcode-dialog.png").write_bytes(b"older")
        with mock.patch.object(snapname, "ask_model_for_slug", return_value="xcode-dialog"), \
                mock.patch.object(snapname, "paste_into_claude", return_value=False):
            final = snapname.process_one(self.shot, self.cfg)
        self.assertEqual(final.name, "2026-10-20_xcode-dialog-2.png")

    def test_backfill_only_renames(self):
        with mock.patch.object(snapname, "ask_model_for_slug", return_value="old-thing"), \
                mock.patch.object(snapname, "paste_into_claude") as paste, \
                mock.patch.object(snapname, "notify") as note:
            final = snapname.process_one(self.shot, self.cfg, backfill=True)
        self.assertEqual(final, self.watch / "2026-10-20_old-thing.png")
        self.assertFalse(self.wb.exists())
        paste.assert_not_called()
        note.assert_not_called()

    def test_inject_off(self):
        cfg = dict(self.cfg, inject="off")
        with mock.patch.object(snapname, "ask_model_for_slug", return_value="x"), \
                mock.patch.object(snapname, "paste_into_claude") as paste:
            snapname.process_one(self.shot, cfg)
        paste.assert_not_called()


if __name__ == "__main__":
    unittest.main()
