"""Unit tests for sharpen's pure logic: message extraction, target resolution, prompt hook.

Run: python3 -m unittest sharpen_prompt/test_sharpen.py
"""

import importlib.machinery
import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
_loader = importlib.machinery.SourceFileLoader("sharpen", str(HERE / "sharpen"))
_spec = importlib.util.spec_from_loader("sharpen", _loader)
sharpen = importlib.util.module_from_spec(_spec)
_loader.exec_module(sharpen)


def reply(verdict, body, fence="````"):
    return (f"Pair demo → %2 (repo, 5s ago)\n\n**▼ MESSAGE TO COPY — {verdict}**\n\n"
            f"{fence}\n{body}\n{fence}\n\n**▲ END OF MESSAGE**\n\n### What changed\n- `x`\n")


def pane(pid, pair=None, role=None, window="@1", left=0, top=0, cwd="/w/repo"):
    return {"id": pid, "session": "s", "window_id": window, "window_index": "1",
            "pane_index": "0", "left": left, "top": top, "cwd": cwd, "command": "claude",
            "pair": pair, "role": role}


def snap(pid, updated, pair=None, role=None, text="hi"):
    return {"session_id": f"sess-{pid}-{updated}", "cwd": "/w/repo", "tmux_pane": pid,
            "pair": pair, "role": role, "updated_at": updated, "last_assistant_text": text}


class ExtractMessageTest(unittest.TestCase):
    def test_ready_block(self):
        verdict, msg = sharpen.extract_message(reply("READY", "Do the thing.\n\n1. step"))
        self.assertEqual(verdict, "READY")
        self.assertEqual(msg, "Do the thing.\n\n1. step")

    def test_not_ready(self):
        verdict, msg = sharpen.extract_message(
            reply("NOT READY** (1 blocking question below)", "best guess"))
        self.assertEqual(verdict, "NOT READY")
        self.assertEqual(msg, "best guess")

    def test_nested_triple_fence_inside_four(self):
        body = "Run this:\n```bash\nmake test\n```\nThen report."
        _, msg = sharpen.extract_message(reply("READY", body))
        self.assertEqual(msg, body)

    def test_triple_fence_still_works(self):
        _, msg = sharpen.extract_message(reply("READY", "plain", fence="```"))
        self.assertEqual(msg, "plain")

    def test_fence_with_language_tag(self):
        text = "**▼ MESSAGE TO COPY — READY**\n```text\nhello\n```\n**▲ END OF MESSAGE**"
        self.assertEqual(sharpen.extract_message(text), ("READY", "hello"))

    def test_uses_last_block(self):
        text = reply("READY", "first") + "\n" + reply("READY", "second")
        self.assertEqual(sharpen.extract_message(text)[1], "second")

    def test_no_block(self):
        self.assertEqual(sharpen.extract_message("Which file did you mean?"), (None, None))

    def test_block_without_fence(self):
        text = "**▼ MESSAGE TO COPY — READY**\n\nno fence here\n\n**▲ END OF MESSAGE**"
        self.assertEqual(sharpen.extract_message(text), ("READY", None))

    def test_unterminated_fence(self):
        text = "**▼ MESSAGE TO COPY — READY**\n````\nhalf"
        self.assertEqual(sharpen.extract_message(text), ("READY", None))


class ExtractTruncationTest(unittest.TestCase):
    def test_triple_wrapped_message_with_inner_code_block(self):
        text = reply("READY", "Run this:\n```bash\nmake test\n```\nThen report back.", fence="```")
        self.assertEqual(sharpen.extract_message(text),
                         ("READY", "Run this:\n```bash\nmake test\n```\nThen report back."))

    def test_triple_wrapped_with_bare_inner_fences(self):
        body = "A\n```\ncode\n```\nB"
        self.assertEqual(sharpen.extract_message(reply("READY", body, fence="```"))[1], body)

    def test_missing_end_marker_is_not_extracted(self):
        text = "**▼ MESSAGE TO COPY — READY**\n\n````\nhello\n````\n"
        self.assertEqual(sharpen.extract_message(text), ("READY", None))


class ResolveTargetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(sharpen, "PAIRS_DIR", Path(self.tmp.name) / "pairs"),
                        mock.patch.object(sharpen, "SESSIONS_DIR", Path(self.tmp.name) / "sess")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_most_recent_working_member_wins(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working"),
                 pane("%3", "demo", "working")]
        snaps = [snap("%2", 100), snap("%3", 200), snap("%9", 999)]
        self.assertEqual(sharpen.resolve_target("demo", panes, snaps, "%1")[:1], ("%3",))
        self.assertEqual(sharpen.resolve_target("demo", panes, snaps, "%1")[2], "latest")

    def test_rollover_in_same_pane(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working")]
        old, new = snap("%2", 100, text="old"), snap("%2", 300, text="new")
        target, s, _ = sharpen.resolve_target("demo", panes, [old, new], "%1")
        self.assertEqual((target, s["last_assistant_text"]), ("%2", "new"))

    def test_pinned_overrides_recency(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working"),
                 pane("%3", "demo", "working")]
        sharpen.save_pair_state("demo", {"pinned_target": "%2"})
        target, _, how = sharpen.resolve_target("demo", panes, [snap("%2", 1), snap("%3", 9)], "%1")
        self.assertEqual((target, how), ("%2", "pinned"))

    def test_pin_to_closed_pane_is_ignored(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%3", "demo", "working")]
        sharpen.save_pair_state("demo", {"pinned_target": "%2"})
        self.assertEqual(sharpen.resolve_target("demo", panes, [snap("%3", 9)], "%1")[0], "%3")

    def test_other_pairs_are_ignored(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working"),
                 pane("%5", "other", "working")]
        snaps = [snap("%2", 100), snap("%5", 999)]
        self.assertEqual(sharpen.resolve_target("demo", panes, snaps, "%1")[0], "%2")

    def test_neighbor_fallback_only_when_unambiguous(self):
        one = [pane("%1", "demo", "sharpen"), pane("%2")]
        self.assertEqual(sharpen.resolve_target("demo", one, [snap("%2", 5)], "%1")[2], "neighbor")
        two = one + [pane("%3")]
        result = sharpen.resolve_target("demo", two, [snap("%2", 5), snap("%3", 6)], "%1")
        self.assertEqual(result, (None, None, "none"))

    def test_neighbor_in_other_window_not_used(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%2", window="@9")]
        self.assertEqual(sharpen.resolve_target("demo", panes, [snap("%2", 5)], "%1")[2], "none")

    def test_working_member_without_snapshot(self):
        panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working")]
        self.assertEqual(sharpen.resolve_target("demo", panes, [], "%1"), ("%2", None, "latest"))


class SelectorTest(unittest.TestCase):
    def test_relative_and_id_and_cwd(self):
        panes = [pane("%1", left=0), pane("%2", left=100, cwd="/w/myapp"),
                 pane("%3", window="@2", cwd="/w/other")]
        self.assertEqual(sharpen.resolve_selector("right", panes, "%1")["id"], "%2")
        self.assertEqual(sharpen.resolve_selector("left", panes, "%2")["id"], "%1")
        self.assertIsNone(sharpen.resolve_selector("left", panes, "%1"))
        self.assertEqual(sharpen.resolve_selector("%3", panes, "%1")["id"], "%3")
        self.assertEqual(sharpen.resolve_selector("myapp", panes, "%1")["id"], "%2")
        self.assertIsNone(sharpen.resolve_selector("nothing-matches", panes, "%1"))


class SlugTest(unittest.TestCase):
    def test_workbench_initiative(self):
        self.assertEqual(sharpen.slug_from_cwd("/u/ws/workbench/sharpen_prompt_tool/sub"),
                         "sharpen-prompt-tool")

    def test_plain_folder(self):
        self.assertEqual(sharpen.slug_from_cwd("/u/ws/MyApp_Auth"), "myapp-auth")


class StopHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "state"
        self.root = root
        self.notes = []
        self.copied = []
        self.panes = []
        self.patches = [
            mock.patch.object(sharpen, "STATE_DIR", root),
            mock.patch.object(sharpen, "PAIRS_DIR", root / "pairs"),
            mock.patch.object(sharpen, "SESSIONS_DIR", root / "sessions"),
            mock.patch.object(sharpen, "LOG_FILE", root / ".hook.log"),
            mock.patch.object(sharpen, "in_tmux", lambda: True),
            mock.patch.object(sharpen, "list_panes", lambda: self.panes),
            mock.patch.object(sharpen, "notify", lambda msg, pane_id=None: self.notes.append(msg)),
            mock.patch.object(sharpen, "copy_message", lambda text, pair: self.copied.append(text)),
            mock.patch.dict(os.environ, {"TMUX_PANE": "%1"}),
        ]
        for p in self.patches:
            p.start()
        os.environ.pop("SHARPEN_PAIR", None)
        os.environ.pop("SHARPEN_ROLE", None)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def stop(self, text="hello", sid="abc"):
        sharpen.hook_stop({"session_id": sid, "cwd": "/w/repo", "last_assistant_message": text})

    def snapshots(self):
        return list((self.root / "sessions").glob("*.json")) if (self.root / "sessions").exists() else []

    def test_unpaired_pane_writes_nothing(self):
        self.panes = [pane("%1")]
        self.stop()
        self.assertEqual(self.snapshots(), [])
        self.assertFalse(self.root.exists())

    def test_paired_pane_writes_snapshot(self):
        self.panes = [pane("%1", "demo", "working")]
        self.stop("the question")
        (path,) = self.snapshots()
        data = sharpen.read_json(path)
        self.assertEqual((data["pair"], data["role"], data["last_assistant_text"]),
                         ("demo", "working", "the question"))

    def test_env_paired_session_outside_tmux_writes_snapshot(self):
        with mock.patch.object(sharpen, "in_tmux", lambda: False), \
             mock.patch.dict(os.environ, {"SHARPEN_PAIR": "demo", "SHARPEN_ROLE": "working"}):
            self.stop("hi")
        self.assertEqual(len(self.snapshots()), 1)

    def test_state_is_owner_only(self):
        self.panes = [pane("%1", "demo", "sharpen")]
        self.stop(reply("READY", "Do it."))
        modes = {p: p.stat().st_mode & 0o777 for p in self.root.rglob("*")}
        self.assertTrue(modes)
        for path, mode in modes.items():
            self.assertEqual(mode, 0o700 if path.is_dir() else 0o600, path)

    def test_existing_loose_directory_is_tightened(self):
        (self.root / "sessions").mkdir(parents=True, mode=0o755)
        (self.root / "sessions").chmod(0o755)
        self.root.chmod(0o755)
        self.panes = [pane("%1", "demo", "working")]
        self.stop()
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "sessions").stat().st_mode & 0o777, 0o700)

    def test_sharpen_pane_ready_copies_and_records(self):
        self.panes = [pane("%1", "demo", "sharpen")]
        self.stop(reply("READY", "Do the thing."))
        self.assertEqual(self.copied, ["Do the thing."])
        self.assertIn("copied — READY", self.notes[0])
        self.assertEqual((self.root / "pairs" / "demo.last-message.md").read_text(), "Do the thing.\n")
        self.assertTrue(sharpen.pair_state("demo")["last_copied"]["copied"])

    def test_sharpen_pane_not_ready_does_not_copy(self):
        self.panes = [pane("%1", "demo", "sharpen")]
        self.stop(reply("NOT READY", "Maybe."))
        self.assertEqual(self.copied, [])
        self.assertIn("NOT READY", self.notes[0])

    def test_sharpen_pane_unextractable_block_notifies(self):
        self.panes = [pane("%1", "demo", "sharpen")]
        self.stop("**▼ MESSAGE TO COPY — READY**\n\n````\nno end marker\n````\n")
        self.assertEqual(self.copied, [])
        self.assertIn("couldn't extract", self.notes[0])

    def test_sharpen_pane_clarifying_reply_is_silent(self):
        self.panes = [pane("%1", "demo", "sharpen")]
        self.stop("Which branch do you mean?")
        self.assertEqual((self.copied, self.notes), ([], []))


IDLE_SCREEN = "some output\n" + "─" * 20 + "\n❯ \n" + "─" * 20 + "\n  status line\n"
TYPED_SCREEN = "some output\n" + "─" * 20 + "\n❯ half typed thought\n" + "─" * 20 + "\n"
BUSY_SCREEN = "✻ Working… (12s)\n" + "─" * 20 + "\n❯ \n" + "─" * 20 + "\n"
QUEUED_SCREEN = "✻ Working… (12s)\n" + "─" * 20 + "\n❯ Press up to edit queued messages\n" + "─" * 20 + "\n"
PASTED_PLACEHOLDER = "─" * 20 + "\n❯ [Pasted text #1 +40 lines]\n" + "─" * 20 + "\n"
DIALOG_SCREEN = "Do you want to proceed?\n❯ 1. Yes\n  2. No\n"


class SessionCommandTest(unittest.TestCase):
    def flags(self, cmd):
        return cmd[:cmd.index("--append-system-prompt")] if "--append-system-prompt" in cmd else cmd

    def test_defaults_to_bypass_permissions(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHARPEN_PERMISSION_MODE", None)
            cmd = sharpen.session_command("demo")
        self.assertEqual(self.flags(cmd), ["claude", "--name", "sharpen:demo",
                                           "--permission-mode", "bypassPermissions"])

    def test_default_opts_out(self):
        with mock.patch.dict(os.environ, {"SHARPEN_PERMISSION_MODE": "default"}):
            cmd = sharpen.session_command("demo")
        self.assertNotIn("--permission-mode", cmd)

    def test_other_modes_pass_through(self):
        with mock.patch.dict(os.environ, {"SHARPEN_PERMISSION_MODE": "acceptEdits"}):
            cmd = sharpen.session_command("demo")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")

    def test_session_prompt_is_appended_when_present(self):
        cmd = sharpen.session_command("demo")
        self.assertEqual(cmd[cmd.index("--append-system-prompt") + 1],
                         sharpen.SESSION_PROMPT.read_text())


class PromptStateTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(sharpen.prompt_state(IDLE_SCREEN)[0], "empty")
        self.assertEqual(sharpen.prompt_state(TYPED_SCREEN), ("text", "half typed thought"))
        self.assertEqual(sharpen.prompt_state(BUSY_SCREEN)[0], "empty")
        self.assertEqual(sharpen.prompt_state(QUEUED_SCREEN)[0], "empty")
        self.assertEqual(sharpen.prompt_state(DIALOG_SCREEN)[0], "text")
        self.assertEqual(sharpen.prompt_state("$ ls\n")[0], "unknown")
        self.assertEqual(sharpen.prompt_state("❯\u00a0\n")[0], "empty")


class FindSharpenPaneTest(unittest.TestCase):
    def test_pair_of_the_origin_pane_wins(self):
        panes = [pane("%1", "a", "sharpen"), pane("%2", "b", "sharpen"), pane("%3", "b", "working")]
        self.assertEqual(sharpen.find_sharpen_pane(panes, None, "%3")[0]["id"], "%2")

    def test_unpaired_pane_uses_the_one_sharpen_pane_in_its_window(self):
        panes = [pane("%1", "a", "sharpen", window="@1"), pane("%2", "b", "sharpen", window="@2"),
                 pane("%3", window="@2")]
        found, pair = sharpen.find_sharpen_pane(panes, None, "%3")
        self.assertEqual((found["id"], pair), ("%2", "b"))

    def test_two_sharpen_panes_in_the_window_is_ambiguous(self):
        panes = [pane("%1", "a", "sharpen"), pane("%2", "b", "sharpen"), pane("%3")]
        self.assertEqual(sharpen.find_sharpen_pane(panes, None, "%3"), (None, None))

    def test_unpaired_pane_with_none_in_window_falls_back_to_the_only_one_on_the_server(self):
        panes = [pane("%1", "a", "sharpen", window="@1"), pane("%3", window="@2")]
        self.assertEqual(sharpen.find_sharpen_pane(panes, None, "%3")[0]["id"], "%1")

    def test_several_sharpen_panes_elsewhere_is_ambiguous(self):
        panes = [pane("%1", "a", "sharpen", window="@1"), pane("%2", "b", "sharpen", window="@2"),
                 pane("%3", window="@3")]
        self.assertEqual(sharpen.find_sharpen_pane(panes, None, "%3"), (None, None))



class ChooseTargetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "state"
        self.saved = root / "dictations" / "x.md"
        self.shown = []
        self.delivered = []
        self.clipboard = ""
        self.panes = [pane("%1", "alpha", "sharpen"), pane("%2", "beta", "sharpen", window="@2"),
                      pane("%3", "alpha", "working")]

        def fake_deliver(text, pair, from_pane, refine, voice):
            if pair == "beta" and getattr(self, "beta_fails", False):
                raise SystemExit(3)
            self.delivered.append((text, pair, refine, voice))

        self.patches = [
            mock.patch.object(sharpen, "STATE_DIR", root),
            mock.patch.object(sharpen, "PAIRS_DIR", root / "pairs"),
            mock.patch.object(sharpen, "list_panes", lambda: self.panes),
            mock.patch.object(sharpen, "deliver", fake_deliver),
            mock.patch.object(sharpen, "in_tmux", lambda: False),
            mock.patch.object(sharpen, "read_clipboard", lambda: self.clipboard),
            mock.patch.object(sharpen, "write_clipboard", lambda text, pair=None: setattr(self, "clipboard", text)),
        ]
        for p in self.patches:
            p.start()
        sharpen.write_private(self.saved, "dictated words\n")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def choose(self, *answers, refine=False):
        it = iter(answers)
        return sharpen.choose_target(self.saved, refine, ask=lambda q: next(it), show=self.shown.append)

    def test_lists_every_sharpen_session_and_sends_to_the_one_picked(self):
        self.assertEqual(self.choose("2"), "delivered")
        listing = "\n".join(self.shown)
        self.assertIn("1) [alpha]", listing)
        self.assertIn("2) [beta]", listing)
        self.assertNotIn("working", listing)
        self.assertEqual(self.delivered, [("dictated words", "beta", False, True)])

    def test_refine_flag_is_kept(self):
        self.choose("1", refine=True)
        self.assertTrue(self.delivered[0][2])

    def test_enter_skips_and_sends_nothing(self):
        self.assertEqual(self.choose(""), "skipped")
        self.assertEqual(self.delivered, [])

    def test_c_copies_the_transcript(self):
        self.assertEqual(self.choose("c"), "copied")
        self.assertEqual(self.clipboard, "dictated words")

    def test_c_warns_about_a_pending_sharpened_message(self):
        with mock.patch.object(sharpen, "pending_pair", lambda: "alpha"):
            prompts = []
            sharpen.choose_target(self.saved, False, ask=lambda q: prompts.append(q) or "", show=lambda m: None)
        self.assertIn("replaces [alpha]'s pending message", prompts[0])

    def test_bad_input_asks_again(self):
        self.assertEqual(self.choose("9", "x", "1"), "delivered")
        self.assertEqual(self.delivered[0][1], "alpha")

    def test_a_pick_that_fails_lets_the_user_choose_again(self):
        self.beta_fails = True
        self.assertEqual(self.choose("2", "1"), "delivered")
        self.assertEqual(self.delivered[0][1], "alpha")

    def test_no_sharpen_sessions_at_all_falls_back_to_the_copy_offer(self):
        self.panes = [pane("%3", "alpha", "working")]
        self.assertEqual(self.choose("y"), "copied")
        self.assertEqual(self.clipboard, "dictated words")

    def test_failure_kind_reaches_the_pointer_file(self):
        ptr = Path(self.tmp.name) / "ptr"
        # no-pane failures record their kind so the popup knows to offer a choice
        with mock.patch.dict(os.environ, {"SHARPEN_DICTATION_PTR": str(ptr)}):
            sharpen.write_pointer(self.saved, "no-pane")
        self.assertEqual(sharpen.read_json(ptr), {"path": str(self.saved), "kind": "no-pane"})


class DeliverTest(unittest.TestCase):
    """screens is a script: each capture-pane pops the next screen, the last one repeats."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "state"
        self.tmux_calls = []
        self.screens = [IDLE_SCREEN]
        self.after_paste = None
        self.after_enter = IDLE_SCREEN
        self.in_mode = "0"
        self.paste_fails = False
        self.panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working")]

        def fake_tmux(*args, input_text=None):
            self.tmux_calls.append((args, input_text))
            if args[0] == "load-buffer":
                self.payload = input_text
                return ""
            if args[0] == "paste-buffer":
                if self.paste_fails:
                    return None
                self.screens = [self.after_paste or ("─" * 20 + "\n❯ " + self.payload + "\n" + "─" * 20)]
                return ""
            if args[0] == "send-keys":
                self.screens = [self.after_enter]
                return ""
            if args[0] == "display-message":
                return self.in_mode + "\n"
            if args[0] == "capture-pane":
                return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)
            return ""

        self.patches = [
            mock.patch.object(sharpen, "tmux", fake_tmux),
            mock.patch.object(sharpen, "in_tmux", lambda: True),
            mock.patch.object(sharpen, "list_panes", lambda: self.panes),
            mock.patch.object(sharpen, "STATE_DIR", root),
            mock.patch.object(sharpen, "PAIRS_DIR", root / "pairs"),
            mock.patch.object(sharpen, "LOG_FILE", root / ".hook.log"),
            mock.patch.object(sharpen, "IDLE_WAIT_SECONDS", 0.05),
            mock.patch.object(sharpen, "PASTE_WAIT_SECONDS", 0.05),
            mock.patch.object(sharpen, "SUBMIT_WAIT_SECONDS", 0.05),
            mock.patch.object(sharpen, "POLL_SECONDS", 0.005),
            mock.patch.dict(os.environ, {"TMUX_PANE": "%2"}),
        ]
        for p in self.patches:
            p.start()
        os.environ.pop("SHARPEN_DELIVER_ANY", None)
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def deliver(self, text="my draft", args=()):
        with mock.patch("sys.stdin", __import__("io").StringIO(text)):
            sharpen.cmd_deliver(list(args))

    def verbs(self):
        return [c[0][0] for c in self.tmux_calls]

    def fails(self, **kw):
        with self.assertRaises(SystemExit) as cm:
            self.deliver(**kw)
        self.assertEqual(cm.exception.code, 3)

    def test_delivers_checks_paste_then_enter_then_submission(self):
        self.deliver("hello\nworld", ["--voice"])
        v = self.verbs()
        self.assertLess(v.index("paste-buffer"), v.index("send-keys"))
        self.assertIn("capture-pane", v[v.index("paste-buffer"):v.index("send-keys")])
        self.assertIn("capture-pane", v[v.index("send-keys"):])
        load = next(c for c in self.tmux_calls if c[0][0] == "load-buffer")
        self.assertEqual(load[1], "new [voice]: hello\nworld")

    def test_refine_marker(self):
        self.deliver("shorter", ["--refine"])
        load = next(c for c in self.tmux_calls if c[0][0] == "load-buffer")
        self.assertEqual(load[1], "refine: shorter")

    def test_buffer_is_named_per_pair_and_process_and_removed_by_the_paste(self):
        self.deliver()
        load = next(c for c in self.tmux_calls if c[0][0] == "load-buffer")
        self.assertEqual(load[0][2], f"sharpen-deliver-demo-{os.getpid()}")
        paste = next(c for c in self.tmux_calls if c[0][0] == "paste-buffer")
        self.assertIn("-d", paste[0])

    def test_busy_pane_still_delivers_and_queues(self):
        self.screens = [BUSY_SCREEN]
        self.deliver()
        self.assertIn("send-keys", self.verbs())

    def test_pane_with_a_queued_message_still_delivers(self):
        self.screens = [QUEUED_SCREEN]
        self.deliver()
        self.assertIn("send-keys", self.verbs())

    def test_long_paste_placeholder_counts_as_visible(self):
        self.after_paste = PASTED_PLACEHOLDER
        self.deliver("x " * 400)
        self.assertIn("send-keys", self.verbs())

    def test_refuses_when_text_already_typed(self):
        self.screens = [TYPED_SCREEN]
        self.fails()
        self.assertNotIn("paste-buffer", self.verbs())
        self.assertNotIn("send-keys", self.verbs())

    def test_refuses_when_dialog_open(self):
        self.screens = [DIALOG_SCREEN]
        self.fails()
        self.assertNotIn("paste-buffer", self.verbs())

    def test_refuses_when_pane_is_a_shell(self):
        self.panes[0]["command"] = "zsh"
        self.fails()
        self.assertNotIn("paste-buffer", self.verbs())

    def test_no_enter_if_paste_never_appears(self):
        self.after_paste = IDLE_SCREEN
        self.fails()
        self.assertNotIn("send-keys", self.verbs())

    def test_failure_if_draft_stays_in_box_after_enter(self):
        self.after_enter = "─" * 20 + "\n❯ new: my draft\n" + "─" * 20
        self.fails()
        self.assertIn("send-keys", self.verbs())

    def test_paste_command_failure_exits_3_and_cleans_up_buffer(self):
        self.paste_fails = True
        self.fails()
        self.assertIn("delete-buffer", self.verbs())

    def test_scrollback_is_cancelled_before_pasting(self):
        self.in_mode = "1"
        self.deliver()
        v = self.verbs()
        self.assertIn("copy-mode", v)
        self.assertLess(v.index("copy-mode"), v.index("paste-buffer"))

    def test_live_pane_is_left_alone(self):
        self.deliver()
        self.assertNotIn("copy-mode", self.verbs())

    def test_no_sharpen_pane_exits_3(self):
        self.panes = [pane("%2", "demo", "working")]
        self.fails()

    def test_empty_stdin_is_an_error(self):
        with self.assertRaises(SystemExit):
            self.deliver("   ")

    def test_voice_delivery_saves_the_transcript_before_sending(self):
        self.screens = [DIALOG_SCREEN]
        self.fails(text="dictated words", args=["--voice"])
        saved = self.root / "pairs" / "demo.last-dictation.md"
        self.assertEqual(saved.read_text(), "dictated words\n")
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)

    def test_typed_delivery_does_not_save_a_dictation(self):
        self.deliver("typed")
        self.assertFalse((self.root / "pairs" / "demo.last-dictation.md").exists())

    def test_outcome_is_recorded_without_the_text(self):
        self.screens = [DIALOG_SCREEN]
        self.fails(text="secret words", args=["--voice"])
        state = sharpen.read_json(self.root / "pairs" / "demo.last-delivery.json")
        self.assertFalse(state["ok"])
        self.assertIn("half-typed", state["reason"])
        self.assertNotIn("secret", (self.root / ".hook.log").read_text())
        self.assertIn("FAILED", (self.root / ".hook.log").read_text())
        self.screens = [IDLE_SCREEN]
        self.deliver()
        self.assertTrue(sharpen.read_json(self.root / "pairs" / "demo.last-delivery.json")["ok"])

    def test_failed_voice_delivery_never_writes_the_clipboard(self):
        self.screens = [DIALOG_SCREEN]
        with mock.patch.object(sharpen, "write_clipboard") as wc:
            self.fails(args=["--voice"])
        wc.assert_not_called()


    def test_unpaired_pane_delivers_to_the_sharpen_pane_in_its_window(self):
        self.panes = [pane("%1", "demo", "sharpen"), pane("%9")]
        os.environ["TMUX_PANE"] = "%9"
        self.deliver("from the nvim pane")
        self.assertIn("send-keys", self.verbs())

    def test_unpaired_failures_each_get_their_own_saved_transcript(self):
        self.panes = [pane("%9")]
        os.environ["TMUX_PANE"] = "%9"
        self.fails(text="first dictation", args=["--voice"])
        self.fails(text="second dictation", args=["--voice"])
        saved = sorted((self.root / "dictations").glob("*.md"))
        self.assertEqual([p.read_text() for p in saved], ["first dictation\n", "second dictation\n"])
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in saved))

    def test_saved_path_is_reported_through_the_pointer_file(self):
        ptr = self.root.parent / "ptr"
        with mock.patch.dict(os.environ, {"SHARPEN_DICTATION_PTR": str(ptr)}):
            self.screens = [DIALOG_SCREEN]
            self.fails(text="words", args=["--voice"])
        info = sharpen.read_json(ptr)
        self.assertEqual(info["path"], str(self.root / "pairs" / "demo.last-dictation.md"))
        self.assertEqual(info["kind"], "")

    def test_no_pane_failure_marks_the_pointer_for_a_choice(self):
        self.panes = [pane("%9"), pane("%1", "a", "sharpen", window="@2"), pane("%2", "b", "sharpen", window="@3")]
        os.environ["TMUX_PANE"] = "%9"
        ptr = self.root.parent / "ptr2"
        with mock.patch.dict(os.environ, {"SHARPEN_DICTATION_PTR": str(ptr)}):
            self.fails(text="words", args=["--voice"])
        self.assertEqual(sharpen.read_json(ptr)["kind"], "no-pane")

    def test_busy_dialog_failure_does_not_ask_for_a_choice(self):
        ptr = self.root.parent / "ptr3"
        with mock.patch.dict(os.environ, {"SHARPEN_DICTATION_PTR": str(ptr)}):
            self.screens = [DIALOG_SCREEN]
            self.fails(text="words", args=["--voice"])
        self.assertEqual(sharpen.read_json(ptr)["kind"], "")

    def resend(self, args=()):
        sharpen.cmd_resend(list(args))

    def test_resend_sends_the_saved_dictation_after_a_failure(self):
        self.screens = [DIALOG_SCREEN]
        self.fails(text="first try", args=["--voice", "--refine"])
        self.screens = [IDLE_SCREEN]
        self.resend()
        load = [c for c in self.tmux_calls if c[0][0] == "load-buffer"][-1]
        self.assertEqual(load[1], "refine [voice]: first try")

    def test_resend_refuses_when_already_delivered(self):
        self.deliver("fine", ["--voice"])
        with self.assertRaises(SystemExit):
            self.resend()
        self.resend(["--force"])

    def test_resend_without_a_saved_dictation_fails(self):
        with self.assertRaises(SystemExit):
            self.resend(["--pair", "demo"])


class PromptHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(sharpen, "PAIRS_DIR", root / "pairs"),
            mock.patch.object(sharpen, "SESSIONS_DIR", root / "sess"),
            mock.patch.object(sharpen, "in_tmux", lambda: True),
            mock.patch.dict(os.environ, {"TMUX_PANE": "%1"}),
        ]
        self.panes = [pane("%1", "demo", "sharpen"), pane("%2", "demo", "working")]
        self.patches.append(mock.patch.object(sharpen, "list_panes", lambda: self.panes))
        for p in self.patches:
            p.start()
        self.t = time.time()
        sharpen.write_json(sharpen.SESSIONS_DIR / "a.json", snap("%2", self.t, text="Q: which branch?"))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def ctx(self, prompt, session_id="s1"):
        out = sharpen.hook_prompt({"prompt": prompt, "session_id": session_id})
        return out["hookSpecificOutput"]["additionalContext"] if out else None

    def test_injects_once_then_skips_until_changed(self):
        first = self.ctx("new: use main")
        self.assertIn("Q: which branch?", first)
        self.assertIn("sharpen_header: Pair demo → %2", first)
        second = self.ctx("refine: shorter")
        self.assertNotIn("Q: which branch?", second)
        self.assertIn("still current", second)
        sharpen.write_json(sharpen.SESSIONS_DIR / "a.json", snap("%2", self.t + 5, text="Q2"))
        self.assertIn("Q2", self.ctx("refine: again"))

    def test_new_sharpen_session_in_same_pane_gets_context_again(self):
        self.assertIn("Q: which branch?", self.ctx("new: one", "s1"))
        self.assertNotIn("Q: which branch?", self.ctx("refine: x", "s1"))
        fresh = self.ctx("hello", "s2")
        self.assertIn("Q: which branch?", fresh)
        self.assertNotIn("still current", fresh)

    def test_injection_state_is_pruned(self):
        for n in range(25):
            self.ctx("new: x", f"s{n}")
        self.assertEqual(len(sharpen.pair_state("demo")["injected"]), 20)

    def test_new_marker_forces_reinject(self):
        self.ctx("new: one")
        self.assertIn("Q: which branch?", self.ctx("new: two"))

    def test_non_sharpen_pane_gets_nothing(self):
        self.panes[0]["role"] = "working"
        self.assertIsNone(sharpen.hook_prompt({"prompt": "hello"}))

    def test_switch_is_announced(self):
        self.ctx("new: one")
        self.panes.append(pane("%4", "demo", "working"))
        sharpen.write_json(sharpen.SESSIONS_DIR / "b.json", snap("%4", self.t + 10, text="fresh"))
        out = self.ctx("new: two")
        self.assertIn("switched from %2", out)
        self.assertIn("fresh", out)


class ClipboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "state"
        self.clipboard = ""
        self.buffers = {}

        def fake_tmux(*args, input_text=None):
            if args[0] == "load-buffer":
                self.buffers[args[2]] = input_text
            return ""

        self.patches = [
            mock.patch.object(sharpen, "STATE_DIR", root),
            mock.patch.object(sharpen, "PAIRS_DIR", root / "pairs"),
            mock.patch.object(sharpen, "in_tmux", lambda: True),
            mock.patch.object(sharpen, "tmux", fake_tmux),
            mock.patch.object(sharpen.shutil, "which", lambda name: "/usr/bin/" + name),
            mock.patch.object(sharpen, "read_clipboard", lambda: self.clipboard),
            mock.patch.object(sharpen.subprocess, "run", self.fake_run),
        ]
        for p in self.patches:
            p.start()

    def fake_run(self, cmd, input=None, **kw):
        if cmd[0] == "pbcopy":
            self.clipboard = input
        return mock.Mock(returncode=0, stdout="")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_each_pair_gets_its_own_tmux_buffer(self):
        sharpen.copy_message("A", "alpha")
        sharpen.copy_message("B", "beta")
        self.assertEqual(self.buffers, {"sharpen-alpha": "A", "sharpen-beta": "B"})

    def test_second_pair_names_the_message_it_replaced(self):
        self.assertIsNone(sharpen.copy_message("A", "alpha"))
        self.assertEqual(sharpen.copy_message("B", "beta"), "alpha")
        self.assertEqual(self.clipboard, "B")

    def test_same_pair_overwriting_itself_is_not_a_displacement(self):
        sharpen.copy_message("A1", "alpha")
        self.assertIsNone(sharpen.copy_message("A2", "alpha"))

    def test_no_notice_if_the_user_already_copied_something_else(self):
        sharpen.copy_message("A", "alpha")
        self.clipboard = "something I copied myself"
        self.assertIsNone(sharpen.copy_message("B", "beta"))

    def test_no_notice_after_the_window_has_passed(self):
        sharpen.copy_message("A", "alpha")
        state = sharpen.read_json(sharpen.STATE_DIR / "clipboard.json")
        state["at"] -= sharpen.DISPLACE_WINDOW_SECONDS + 60
        sharpen.write_json(sharpen.STATE_DIR / "clipboard.json", state)
        self.assertIsNone(sharpen.copy_message("B", "beta"))

    def test_only_a_hash_is_remembered_not_the_text(self):
        sharpen.copy_message("a very private message", "alpha")
        stored = (sharpen.STATE_DIR / "clipboard.json").read_text()
        self.assertNotIn("private", stored)


    def test_offer_copies_only_when_the_user_says_yes(self):
        saved = sharpen.STATE_DIR / "t.md"
        sharpen.write_private(saved, "dictated words\n")
        self.clipboard = "keep"
        self.assertFalse(sharpen.offer_clipboard(saved, ask=lambda q: ""))
        self.assertFalse(sharpen.offer_clipboard(saved, ask=lambda q: "n"))
        self.assertEqual(self.clipboard, "keep")
        self.assertTrue(sharpen.offer_clipboard(saved, ask=lambda q: "y"))
        self.assertEqual(self.clipboard, "dictated words")

    def test_offer_names_the_pending_message_it_would_replace(self):
        saved = sharpen.STATE_DIR / "t.md"
        sharpen.write_private(saved, "dictated words\n")
        sharpen.copy_message("ALPHA TEXT", "alpha")
        asked = []
        sharpen.offer_clipboard(saved, ask=lambda q: asked.append(q) or "n")
        self.assertIn("replaces [alpha]'s sharpened message", asked[0])

    def test_offer_does_not_warn_when_nothing_is_pending(self):
        saved = sharpen.STATE_DIR / "t.md"
        sharpen.write_private(saved, "dictated words\n")
        asked = []
        sharpen.offer_clipboard(saved, ask=lambda q: asked.append(q) or "n")
        self.assertNotIn("replaces", asked[0])

    def test_accepted_offer_clears_the_pair_attribution(self):
        saved = sharpen.STATE_DIR / "t.md"
        sharpen.write_private(saved, "dictated words\n")
        sharpen.copy_message("ALPHA TEXT", "alpha")
        sharpen.offer_clipboard(saved, ask=lambda q: "y")
        self.assertIsNone(sharpen.copy_message("BETA TEXT", "beta"))

    def test_recall_by_pane_recopies_that_pairs_message(self):
        sharpen.write_private(sharpen.PAIRS_DIR / "alpha.last-message.md", "ALPHA TEXT\n")
        sharpen.copy_message("B", "beta")
        panes = [pane("%2", "alpha", "working")]
        with mock.patch.object(sharpen, "list_panes", lambda: panes):
            sharpen.cmd_copy(["--from-pane", "%2", "--quiet"])
        self.assertEqual(self.clipboard, "ALPHA TEXT")

    def test_recall_from_an_unpaired_pane_does_not_touch_the_clipboard(self):
        self.clipboard = "keep me"
        with mock.patch.object(sharpen, "list_panes", lambda: [pane("%9")]):
            with self.assertRaises(SystemExit):
                sharpen.cmd_copy(["--from-pane", "%9", "--quiet"])
        self.assertEqual(self.clipboard, "keep me")


if __name__ == "__main__":
    unittest.main()
