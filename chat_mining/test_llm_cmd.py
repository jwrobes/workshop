import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import chat_analyze


class LlmCmdTest(unittest.TestCase):
    def test_default_is_claude(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHAT_MINING_LLM_CMD", None)
            argv, _, prepend = chat_analyze.build_llm_command("sys", "m")
        self.assertEqual(argv, ["claude", "-p"])
        self.assertTrue(prepend)

    def test_llm_alias(self):
        with mock.patch.dict(os.environ, {"CHAT_MINING_LLM_CMD": "llm"}):
            argv, _, prepend = chat_analyze.build_llm_command("sys", "gpt")
        self.assertEqual(argv, ["llm", "-m", "gpt", "-s", "sys"])
        self.assertFalse(prepend)

    def test_custom_stub_script(self):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / "stub.sh"
            stub.write_text('#!/bin/sh\ncat >/dev/null\necho "sys=$CHAT_MINING_SYSTEM_PROMPT"\n')
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            with mock.patch.dict(os.environ, {"CHAT_MINING_LLM_CMD": str(stub)}):
                out = chat_analyze.run_llm("hello", "hi", "m", verbose=False)
        self.assertEqual(out, "sys=hello")

    def test_missing_command_returns_none(self):
        with mock.patch.dict(os.environ, {"CHAT_MINING_LLM_CMD": "/nonexistent/cmd"}):
            self.assertIsNone(chat_analyze.run_llm("s", "u", "m", verbose=False))


if __name__ == "__main__":
    unittest.main()
