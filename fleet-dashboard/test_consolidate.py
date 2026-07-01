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
            {"name": "ynab", "members": [ids[2]]},  # singleton -> dropped
        ]}
        tracks = consolidate.run_llm_consolidation(cards, runner=self._runner(payload))
        names = {t["name"] for t in tracks}
        # Only the 2+ member track survives; the singleton 'ynab' is dropped.
        self.assertEqual(names, {"email-triage"})
        et = next(t for t in tracks if t["name"] == "email-triage")
        self.assertEqual(set(et["members"]), {ids[0], ids[1]})

    def test_singletons_are_dropped(self):
        cards = [card("a", pr=1), card("b", pr=2)]
        ids = [consolidate._card_id(c) for c in cards]
        payload = {"tracks": [{"name": "solo", "members": [ids[0]]},
                              {"name": "solo2", "members": [ids[1]]}]}
        tracks = consolidate.run_llm_consolidation(cards, runner=self._runner(payload))
        self.assertEqual(tracks, [])  # both singletons -> nothing

    def test_drops_unknown_member_ids(self):
        # Known id stays; ghost dropped. Needs a 2nd known member to survive the
        # singleton filter, so we can assert the ghost was filtered.
        cards = [card("a", pr=1), card("b", pr=2)]
        ids = [consolidate._card_id(c) for c in cards]
        payload = {"tracks": [{"name": "t", "members": [ids[0], ids[1], "ghost#999"]}]}
        tracks = consolidate.run_llm_consolidation(cards, runner=self._runner(payload))
        self.assertEqual(set(tracks[0]["members"]), {ids[0], ids[1]})

    def test_junk_output_returns_empty(self):
        cards = [card("a", pr=1)]
        tracks = consolidate.run_llm_consolidation(
            cards, runner=lambda p: "I cannot help with that.")
        self.assertEqual(tracks, [])

    def test_fenced_json_is_parsed(self):
        cards = [card("a", pr=1), card("b", pr=2)]
        ids = [consolidate._card_id(c) for c in cards]
        fenced = "```json\n" + json.dumps(
            {"tracks": [{"name": "t", "members": ids}]}) + "\n```"
        tracks = consolidate.run_llm_consolidation(cards, runner=lambda p: fenced)
        self.assertEqual(tracks[0]["name"], "t")

    def test_prose_then_fence_is_parsed(self):
        # The real failure: CLI prefixed "Here is the output:" before a ```json
        # fence, which produced 0 tracks. Must survive prose-THEN-fence.
        cards = [card("a", pr=1), card("b", pr=2)]
        ids = [consolidate._card_id(c) for c in cards]
        resp = ("The grouping analysis is complete. Here is the output:\n\n"
                "```json\n" + json.dumps({"tracks": [{"name": "t",
                "members": ids}]}) + "\n```\nLet me know if you need changes.")
        tracks = consolidate.run_llm_consolidation(cards, runner=lambda p: resp)
        self.assertEqual(tracks[0]["name"], "t")
        self.assertEqual(set(tracks[0]["members"]), set(ids))

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


def pr_card(number, title, state="OPEN", labels=None, branch=None,
            shipped=False, repo="claw-playbook"):
    """A card carrying a github PR object, like the collector produces."""
    return {"repo": repo, "shipped": shipped,
            "github": {"kind": "pr", "number": number, "title": title,
                       "state": state, "labels": labels or [], "branch": branch,
                       "url": f"https://gh/{repo}/pull/{number}"}}


def issue_card(number, title, state="OPEN", repo="claw-playbook"):
    return {"repo": repo,
            "github": {"kind": "issue", "number": number, "title": title,
                       "state": state, "labels": []}}


def wt_card(branch, dirty=0, flags=None, repo="claw-playbook"):
    return {"repo": repo, "kind": "worktree", "branch": branch,
            "slug": branch, "dirty_files": dirty, "flags": flags or []}


class StrandRoleTests(unittest.TestCase):
    def test_impl_pr(self):
        c = pr_card(115, "feat: Communications Hub")
        self.assertEqual(consolidate.strand_role(c), "impl-PR")

    def test_spec_pr_by_label(self):
        c = pr_card(118, "Whatever", labels=["build-spec"])
        self.assertEqual(consolidate.strand_role(c), "spec-PR")

    def test_spec_pr_by_specs_title(self):
        c = pr_card(118, "Specs: Stage 2 + Stage 3")
        self.assertEqual(consolidate.strand_role(c), "spec-PR")

    def test_issue_role(self):
        self.assertEqual(consolidate.strand_role(issue_card(112, "x")), "issue")

    def test_worktree_role(self):
        self.assertEqual(consolidate.strand_role(wt_card("build-briefing")), "worktree")

    def test_plan_role(self):
        self.assertEqual(consolidate.strand_role(card("some-plan")), "plan")


class StrandStateTests(unittest.TestCase):
    def test_merged_from_shipped(self):
        self.assertEqual(consolidate.strand_state(
            pr_card(115, "x", state="MERGED", shipped=True)), "merged")

    def test_open(self):
        self.assertEqual(consolidate.strand_state(pr_card(118, "x")), "open")

    def test_closed(self):
        self.assertEqual(consolidate.strand_state(
            pr_card(9, "x", state="CLOSED")), "closed")

    def test_worktree_dirty(self):
        self.assertEqual(consolidate.strand_state(wt_card("b", dirty=6)), "dirty")

    def test_worktree_clean(self):
        self.assertEqual(consolidate.strand_state(wt_card("b")), "clean")


class StrandSourceTests(unittest.TestCase):
    def test_web_from_claude_branch(self):
        self.assertEqual(consolidate.strand_source(
            pr_card(119, "x", branch="claude/trusting-bohr-1")), "web")

    def test_bosque_from_branch(self):
        self.assertEqual(consolidate.strand_source(
            pr_card(115, "x", branch="bosque/comms-hub")), "bosque")

    def test_bosque_from_title_when_no_branch(self):
        # Real case: #115 title is "feat(bosque): ..." and branch is absent in
        # older cached data. Title marker is the honest fallback.
        self.assertEqual(consolidate.strand_source(
            pr_card(115, "feat(bosque): Communications Hub")), "bosque")

    def test_undetectable_is_dash_not_guess(self):
        self.assertEqual(consolidate.strand_source(
            pr_card(119, "Implement briefing curation Stages 2-5")), "—")


class StrandStageTests(unittest.TestCase):
    def test_shipped(self):
        self.assertEqual(consolidate.strand_stage(
            pr_card(115, "x", state="MERGED", shipped=True)), "shipped")

    def test_open_pr_in_review(self):
        self.assertEqual(consolidate.strand_stage(pr_card(118, "x")), "review")

    def test_open_issue_specd(self):
        self.assertEqual(consolidate.strand_stage(issue_card(112, "x")), "spec")


class TrackFactsTests(unittest.TestCase):
    def _briefing_track(self):
        # The communications-hub track: 3 merged impl PRs, 1 open spec-PR, 2 issues.
        cards = [
            pr_card(115, "feat(bosque): Communications Hub", state="MERGED", shipped=True),
            pr_card(117, "Email Triage: tag Digest (Stage 1) — impl", state="MERGED", shipped=True),
            pr_card(119, "Implement briefing curation Stages 2-5", state="MERGED", shipped=True),
            pr_card(118, "Specs: Stage 2 + Stage 3", state="OPEN"),
            issue_card(111, "Communications Hub — morning briefing"),
            issue_card(112, "Communications Hub & Morning Briefing (Sprint 14)"),
        ]
        ids = [consolidate._card_id(c) for c in cards]
        track = {"name": "communications-hub-morning-briefing", "members": ids}
        return [track], cards

    def test_stamp_produces_members_detail_and_facts(self):
        tracks, cards = self._briefing_track()
        consolidate.stamp_track_facts(tracks, cards)
        t = tracks[0]
        self.assertEqual(len(t["members_detail"]), 6)
        f = t["facts"]
        self.assertEqual(f["merged"], 3)
        self.assertEqual(f["roles"]["impl-PR"], 3)
        self.assertEqual(f["roles"]["spec-PR"], 1)
        self.assertEqual(f["roles"]["issue"], 2)
        # The interesting fact: impl merged AND a spec-PR still open.
        self.assertTrue(f["impl_merged_spec_open"])
        # Furthest-along stage is shipped -> the card lands in Completed.
        self.assertEqual(f["furthest_stage"], "shipped")

    def test_detail_roles_states_present(self):
        tracks, cards = self._briefing_track()
        consolidate.stamp_track_facts(tracks, cards)
        by_id = {d["id"]: d for d in tracks[0]["members_detail"]}
        d115 = by_id["claw-playbook#115"]
        self.assertEqual((d115["role"], d115["state"], d115["stage"]),
                         ("impl-PR", "merged", "shipped"))
        self.assertEqual(d115["source"], "bosque")  # from feat(bosque) title
        d118 = by_id["claw-playbook#118"]
        self.assertEqual((d118["role"], d118["state"], d118["stage"]),
                         ("spec-PR", "open", "review"))

    def test_unknown_member_id_still_listed(self):
        tracks = [{"name": "t", "members": ["ghost#999", "x#1"]}]
        consolidate.stamp_track_facts(tracks, [pr_card(1, "x", repo="x")])
        det = {d["id"]: d for d in tracks[0]["members_detail"]}
        self.assertIn("ghost#999", det)  # not silently dropped
        self.assertEqual(det["ghost#999"]["role"], "?")


if __name__ == "__main__":
    unittest.main()
