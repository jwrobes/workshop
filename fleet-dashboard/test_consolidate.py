#!/usr/bin/env python3
"""Tests for work-track consolidation (Phase 5).

The LLM call is injected (a fake runner) so tests are fast + deterministic — we
never shell out to the real `claude` CLI here. Covers: grouping from LLM output,
robustness to junk output, overrides winning, and card stamping.
"""

import json
import unittest

import consolidate


def card(slug, title=None, source="remote-only", repo="claw-playbook",
         product="magic-me", pr=None):
    c = {"slug": slug, "title": title or slug, "source": source,
         "repo": repo, "product": product}
    if pr is not None:
        c["github"] = {"number": pr}
    return c


class LooseAndIdTests(unittest.TestCase):
    def test_only_loose_sources_grouped(self):
        cards = [card("a", source="remote-only"), card("b", source="workbench-only"),
                 card("c", source="local")]
        loose = consolidate.loose_cards(cards)
        self.assertEqual({c["slug"] for c in loose}, {"a", "b"})

    def test_card_id_prefers_github_ref(self):
        self.assertEqual(consolidate._card_id(card("x", pr=113)), "claw-playbook#113")
        self.assertEqual(consolidate._card_id(card("y")), "claw-playbook/y")


class LLMConsolidationTests(unittest.TestCase):
    def _runner(self, payload):
        return lambda prompt: json.dumps(payload)

    def test_groups_from_llm_output(self):
        cards = [card("email-triage-v2", pr=88), card("email-triage-feedback"),
                 card("ynab-tools", pr=90)]
        ids = [consolidate._card_id(c) for c in cards]
        payload = {"tracks": [
            {"name": "email-triage", "members": [ids[0], ids[1]]},
            {"name": "ynab", "members": [ids[2]]},
        ]}
        tracks = consolidate.run_llm_consolidation(cards, runner=self._runner(payload))
        names = {t["name"] for t in tracks}
        self.assertEqual(names, {"email-triage", "ynab"})
        et = next(t for t in tracks if t["name"] == "email-triage")
        self.assertEqual(set(et["members"]), {ids[0], ids[1]})

    def test_drops_unknown_member_ids(self):
        cards = [card("a", pr=1)]
        payload = {"tracks": [{"name": "t", "members":
                              [consolidate._card_id(cards[0]), "ghost#999"]}]}
        tracks = consolidate.run_llm_consolidation(cards, runner=self._runner(payload))
        self.assertEqual(tracks[0]["members"], ["claw-playbook#1"])

    def test_junk_output_returns_empty(self):
        cards = [card("a", pr=1)]
        tracks = consolidate.run_llm_consolidation(
            cards, runner=lambda p: "I cannot help with that.")
        self.assertEqual(tracks, [])

    def test_fenced_json_is_parsed(self):
        cards = [card("a", pr=1)]
        cid = consolidate._card_id(cards[0])
        fenced = "```json\n" + json.dumps(
            {"tracks": [{"name": "t", "members": [cid]}]}) + "\n```"
        tracks = consolidate.run_llm_consolidation(cards, runner=lambda p: fenced)
        self.assertEqual(tracks[0]["name"], "t")

    def test_cli_failure_returns_empty_not_raise(self):
        cards = [card("a", pr=1)]
        def boom(prompt):
            raise OSError("claude not found")
        self.assertEqual(consolidate.run_llm_consolidation(cards, runner=boom), [])

    def test_no_loose_cards_no_call(self):
        called = []
        consolidate.run_llm_consolidation(
            [card("a", source="local")], runner=lambda p: called.append(1) or "{}")
        self.assertEqual(called, [])  # runner never invoked


class OverrideTests(unittest.TestCase):
    def test_reassign_moves_card_and_wins(self):
        tracks = [{"name": "wrong", "members": ["x#1", "x#2"]}]
        out = consolidate.apply_overrides(tracks, {"reassign": {"x#2": "right"}})
        by = {t["name"]: set(t["members"]) for t in out}
        self.assertEqual(by["wrong"], {"x#1"})
        self.assertEqual(by["right"], {"x#2"})

    def test_reassign_into_new_track(self):
        tracks = [{"name": "a", "members": ["i#1"]}]
        out = consolidate.apply_overrides(tracks, {"reassign": {"i#1": "brandnew"}})
        names = {t["name"] for t in out}
        self.assertIn("brandnew", names)
        self.assertNotIn("a", names)  # 'a' emptied -> dropped

    def test_split_pulls_card_into_singleton(self):
        tracks = [{"name": "grp", "members": ["m#1", "m#2"]}]
        out = consolidate.apply_overrides(tracks, {"split": ["m#2"]})
        by = {t["name"]: set(t["members"]) for t in out}
        self.assertEqual(by["grp"], {"m#1"})
        self.assertEqual(by["track:m#2"], {"m#2"})

    def test_empty_overrides_passthrough(self):
        tracks = [{"name": "t", "members": ["a#1", "a#2"]}]
        out = consolidate.apply_overrides(tracks, {})
        self.assertEqual(out[0]["members"], ["a#1", "a#2"])


class AttachTests(unittest.TestCase):
    def test_only_multi_member_tracks_stamp_cards(self):
        cards = [card("a", pr=1), card("b", pr=2), card("c", pr=3)]
        ids = [consolidate._card_id(c) for c in cards]
        tracks = [{"name": "pair", "members": [ids[0], ids[1]]},
                  {"name": "solo", "members": [ids[2]]}]
        consolidate.attach_tracks_to_cards(cards, tracks)
        self.assertEqual(cards[0].get("track"), "pair")
        self.assertEqual(cards[1].get("track"), "pair")
        self.assertIsNone(cards[2].get("track"))  # singleton not stamped


if __name__ == "__main__":
    unittest.main()
