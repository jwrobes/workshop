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

    def test_card_id_product_level_pr_uses_product_not_qmark(self):
        # A product-level PR has repo=None -> product#number, NOT ?#number.
        c = {"github": {"number": 113}, "repo": None, "product": "magic-me",
             "slug": "communications-hub-morning-briefing"}
        self.assertEqual(consolidate._card_id(c), "magic-me#113")


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
            shipped=False, repo="claw-playbook", body=""):
    """A card carrying a github PR object, like the collector produces."""
    return {"repo": repo, "shipped": shipped,
            "github": {"kind": "pr", "number": number, "title": title,
                       "state": state, "labels": labels or [], "branch": branch,
                       "body": body, "url": f"https://gh/{repo}/pull/{number}"}}


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


class StrayAttachTests(unittest.TestCase):
    def _briefing_tracks(self):
        return [{"name": "communications-hub-morning-briefing",
                 "members": ["claw-playbook#111", "claw-playbook#112",
                             "claw-playbook#115"]}]

    def test_attach_by_build_slug_branch(self):
        # The #113 case: product-level PR, build-<slug> branch == track name.
        stray = {"github": {"number": 113, "branch":
                 "build-communications-hub-morning-briefing"},
                 "repo": None, "product": "magic-me", "slug": "x"}
        tracks = self._briefing_tracks()
        consolidate.attach_strays_to_tracks([stray], tracks)
        self.assertIn("magic-me#113", tracks[0]["members"])

    def test_attach_by_closes_member(self):
        # Body 'closes #112' where #112 is a member.
        stray = {"github": {"number": 113, "branch": "claude/random-name",
                 "body": "Implements the hub. closes #112"},
                 "repo": None, "product": "magic-me", "slug": "x"}
        tracks = self._briefing_tracks()
        consolidate.attach_strays_to_tracks([stray], tracks)
        self.assertIn("magic-me#113", tracks[0]["members"])

    def test_does_not_attach_unrelated(self):
        stray = {"github": {"number": 200, "branch": "build-something-else",
                 "body": "unrelated"}, "repo": "claw-playbook", "slug": "x"}
        tracks = self._briefing_tracks()
        consolidate.attach_strays_to_tracks([stray], tracks)
        self.assertNotIn("claw-playbook#200", tracks[0]["members"])

    def test_skips_card_already_in_a_track(self):
        # #115 is already a member; must not be duplicated even if its branch
        # would match.
        member = {"github": {"number": 115,
                  "branch": "build-communications-hub-morning-briefing"},
                  "repo": "claw-playbook", "slug": "x"}
        tracks = self._briefing_tracks()
        consolidate.attach_strays_to_tracks([member], tracks)
        self.assertEqual(tracks[0]["members"].count("claw-playbook#115"), 1)

    def test_skips_already_stamped_track(self):
        stray = {"github": {"number": 113,
                 "branch": "build-communications-hub-morning-briefing"},
                 "repo": None, "product": "magic-me", "track": "somewhere"}
        tracks = self._briefing_tracks()
        consolidate.attach_strays_to_tracks([stray], tracks)
        self.assertNotIn("magic-me#113", tracks[0]["members"])

    def test_closes_parsing_variants(self):
        self.assertEqual(consolidate._closes_numbers(
            "Closes #112, fixes #90 and resolves #7"), {112, 90, 7})
        self.assertEqual(consolidate._closes_numbers("mentions #5 only"), set())

    def test_branch_slug_strips_prefix(self):
        self.assertEqual(consolidate._branch_slug(
            "build-communications-hub-morning-briefing"),
            "communications-hub-morning-briefing")
        self.assertEqual(consolidate._branch_slug("bosque/build-spec-007"), "007")


class StrandActivityTests(unittest.TestCase):
    def test_open_pr_is_active(self):
        self.assertEqual(consolidate.strand_activity(pr_card(118, "x")), "active")

    def test_open_spec_pr_is_active(self):
        self.assertEqual(consolidate.strand_activity(
            pr_card(118, "Specs: Stage 2")), "active")

    def test_open_issue_is_backlog(self):
        self.assertEqual(consolidate.strand_activity(issue_card(111, "x")), "backlog")

    def test_merged_pr_is_done(self):
        self.assertEqual(consolidate.strand_activity(
            pr_card(115, "x", state="MERGED", shipped=True)), "done")

    def test_dirty_worktree_is_active(self):
        self.assertEqual(consolidate.strand_activity(wt_card("b", dirty=3)), "active")

    def test_clean_worktree_is_done(self):
        self.assertEqual(consolidate.strand_activity(wt_card("b")), "done")


class TrackPlacementTests(unittest.TestCase):
    def _place(self, cards):
        tracks = [{"name": "t", "members": [consolidate._card_id(c) for c in cards]}]
        consolidate.stamp_track_facts(tracks, cards)
        return tracks[0]["facts"]["placement"]

    def test_all_done_is_completed(self):
        self.assertEqual(self._place([
            pr_card(1, "a", state="MERGED", shipped=True),
            pr_card(2, "b", state="MERGED", shipped=True)]), "completed")

    def test_any_active_is_active_even_with_shipped(self):
        # The briefing case: 3 merged impl + open spec-PR + open issues -> Active,
        # NOT Completed. A shipped strand does not make the whole track done.
        self.assertEqual(self._place([
            pr_card(115, "a", state="MERGED", shipped=True),
            pr_card(117, "b", state="MERGED", shipped=True),
            pr_card(119, "c", state="MERGED", shipped=True),
            pr_card(118, "Specs: Stage 2"),          # open spec-PR -> active
            issue_card(111, "d"), issue_card(112, "e")]), "active")

    def test_only_backlog_open_is_backlog(self):
        # Shipped work + only open ISSUES (queued, nobody working) -> Backlog.
        self.assertEqual(self._place([
            pr_card(1, "a", state="MERGED", shipped=True),
            issue_card(2, "b"), issue_card(3, "c")]), "backlog")

    def test_activity_counts_present(self):
        tracks = [{"name": "t", "members": ["claw-playbook#1", "claw-playbook#2"]}]
        consolidate.stamp_track_facts(tracks, [
            pr_card(1, "a"), issue_card(2, "b")])
        self.assertEqual(tracks[0]["facts"]["activity_counts"],
                         {"active": 1, "backlog": 1, "done": 0})


class TrackStageTests(unittest.TestCase):
    def _stage(self, cards):
        tracks = [{"name": "t", "members": [consolidate._card_id(c) for c in cards]}]
        consolidate.stamp_track_facts(tracks, cards)
        return tracks[0]["facts"]["pipeline_stage"]

    def test_all_specd_is_spec(self):
        self.assertEqual(self._stage([issue_card(1, "a"), issue_card(2, "b")]), "spec")

    def test_all_shipped_is_shipped(self):
        self.assertEqual(self._stage([
            pr_card(1, "a", state="MERGED", shipped=True),
            pr_card(2, "b", state="MERGED", shipped=True)]), "shipped")

    def test_middle_ignores_shipped_takes_furthest_unshipped(self):
        # Briefing: impl-PRs shipped, spec-PR #118 in-review, issues spec'd.
        # Furthest UNSHIPPED strand is the in-review spec-PR -> review, NOT shipped.
        self.assertEqual(self._stage([
            pr_card(115, "a", state="MERGED", shipped=True),
            pr_card(117, "b", state="MERGED", shipped=True),
            pr_card(119, "c", state="MERGED", shipped=True),
            pr_card(118, "Specs: Stage 2"),         # open spec-PR -> review
            issue_card(111, "d"), issue_card(112, "e")]), "review")

    def test_middle_only_specd_unshipped(self):
        # Shipped impl + only open issues left -> the leading edge is spec'd.
        self.assertEqual(self._stage([
            pr_card(1, "a", state="MERGED", shipped=True),
            issue_card(2, "b")]), "spec")


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

    def test_detail_carries_body_and_metadata(self):
        # The panel needs "what is this trying to do" — body, labels, branch.
        c = pr_card(115, "feat(bosque): Communications Hub", state="MERGED",
                    shipped=True, labels=["ready"], branch="bosque/comms",
                    body="Adds the morning-briefing pipeline: digest + calendar.")
        d = consolidate.strand_detail(c)
        self.assertIn("morning-briefing pipeline", d["body"])
        self.assertEqual(d["labels"], ["ready"])
        self.assertEqual(d["branch"], "bosque/comms")

    def test_detail_body_falls_back_to_plan_body(self):
        # A local plan strand has no github object — use its card body/goal.
        d = consolidate.strand_detail(
            {"repo": "r", "slug": "p", "title": "Plan", "body": "The plan text."})
        self.assertEqual(d["body"], "The plan text.")

    def test_detail_body_truncated(self):
        d = consolidate.strand_detail(pr_card(1, "x", body="z" * 5000))
        self.assertEqual(len(d["body"]), 2000)

    def test_unknown_member_id_still_listed(self):
        tracks = [{"name": "t", "members": ["ghost#999", "x#1"]}]
        consolidate.stamp_track_facts(tracks, [pr_card(1, "x", repo="x")])
        det = {d["id"]: d for d in tracks[0]["members_detail"]}
        self.assertIn("ghost#999", det)  # not silently dropped
        self.assertEqual(det["ghost#999"]["role"], "?")


# ---------------------------------------------------------------------------
# Pass 1 — TRIAGE. The LLM sweeps Ungrouped artifacts and proposes, per item,
# ONE of attach / create-track / archive + a confidence. HIGH-confidence
# attaches auto-apply (written into track-overrides.json as _source llm-triage);
# medium/low attaches + all create/archive are SUGGESTIONS the human resolves.
# The runner is injected so these stay offline + deterministic (never call the
# real claude CLI in a gate).
# ---------------------------------------------------------------------------
def triage_runner(proposals):
    """A fake claude runner that returns a canned triage payload."""
    return lambda prompt: json.dumps({"proposals": proposals})


class TriageTests(unittest.TestCase):
    def _ungrouped(self):
        return [pr_card(200, "Morning briefing digest tweaks", repo="claw-playbook"),
                pr_card(201, "Totally unrelated infra script", repo="claw-playbook")]

    def _tracks(self):
        return [{"name": "communications-hub",
                 "members": ["claw-playbook#115", "claw-playbook#119"]}]

    def test_no_ungrouped_no_call(self):
        called = []
        res = consolidate.run_triage(
            [], self._tracks(),
            runner=lambda p: called.append(1) or "{}")
        self.assertEqual(called, [])          # runner never invoked
        self.assertEqual(res["proposals"], [])

    def test_high_confidence_attach_is_auto(self):
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=triage_runner([
                {"id": "claw-playbook#200", "action": "attach",
                 "track": "communications-hub", "confidence": "high",
                 "reason": "same morning-briefing feature"}]))
        # An auto-attach: applied (goes into overrides), NOT a pending suggestion.
        self.assertEqual(len(res["auto"]), 1)
        self.assertEqual(res["auto"][0]["id"], "claw-playbook#200")
        self.assertEqual(res["auto"][0]["track"], "communications-hub")
        self.assertEqual(res["suggestions"], [])

    def test_medium_attach_is_a_suggestion_not_auto(self):
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=triage_runner([
                {"id": "claw-playbook#200", "action": "attach",
                 "track": "communications-hub", "confidence": "medium",
                 "reason": "maybe related"}]))
        self.assertEqual(res["auto"], [])
        self.assertEqual(len(res["suggestions"]), 1)
        self.assertEqual(res["suggestions"][0]["action"], "attach")

    def test_create_track_is_always_a_suggestion_even_high(self):
        # create/archive are higher-stakes -> never auto, regardless of confidence.
        res = consolidate.run_triage(
            self._ungrouped(), [],
            runner=triage_runner([
                {"id": "claw-playbook#200", "action": "create",
                 "track": "briefing-digest", "confidence": "high",
                 "reason": "two items form one effort"}]))
        self.assertEqual(res["auto"], [])
        self.assertEqual(len(res["suggestions"]), 1)
        self.assertEqual(res["suggestions"][0]["action"], "create")

    def test_archive_is_always_a_suggestion_even_high(self):
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=triage_runner([
                {"id": "claw-playbook#201", "action": "archive",
                 "confidence": "high", "reason": "stale, superseded"}]))
        self.assertEqual(res["auto"], [])
        self.assertEqual(len(res["suggestions"]), 1)
        self.assertEqual(res["suggestions"][0]["action"], "archive")

    def test_attach_to_unknown_track_is_dropped(self):
        # An auto-attach to a track that doesn't exist would corrupt membership.
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=triage_runner([
                {"id": "claw-playbook#200", "action": "attach",
                 "track": "nonexistent-track", "confidence": "high"}]))
        self.assertEqual(res["auto"], [])
        self.assertEqual(res["suggestions"], [])

    def test_proposal_for_unknown_id_is_dropped(self):
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=triage_runner([
                {"id": "claw-playbook#9999", "action": "attach",
                 "track": "communications-hub", "confidence": "high"}]))
        self.assertEqual(res["auto"], [])
        self.assertEqual(res["suggestions"], [])

    def test_junk_output_returns_empty_not_raise(self):
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=lambda p: "I cannot help with that.")
        self.assertEqual(res["auto"], [])
        self.assertEqual(res["suggestions"], [])

    def test_cli_failure_returns_empty_not_raise(self):
        def boom(p):
            raise OSError("claude missing")
        res = consolidate.run_triage(self._ungrouped(), self._tracks(), runner=boom)
        self.assertEqual(res["auto"], [])
        self.assertEqual(res["suggestions"], [])

    def test_prose_then_fence_parsed(self):
        resp = ('Here is the triage:\n```json\n'
                '{"proposals":[{"id":"claw-playbook#200","action":"attach",'
                '"track":"communications-hub","confidence":"high"}]}\n```')
        res = consolidate.run_triage(self._ungrouped(), self._tracks(),
                                     runner=lambda p: resp)
        self.assertEqual(len(res["auto"]), 1)

    def test_duplicate_proposals_for_one_id_collapse(self):
        # Two proposals for the same id -> only the first is kept (no double
        # auto-attach / no inflated runlog).
        res = consolidate.run_triage(
            self._ungrouped(), self._tracks(),
            runner=triage_runner([
                {"id": "claw-playbook#200", "action": "attach",
                 "track": "communications-hub", "confidence": "high"},
                {"id": "claw-playbook#200", "action": "attach",
                 "track": "communications-hub", "confidence": "high"}]))
        self.assertEqual(len(res["auto"]), 1)
        self.assertEqual(len(res["proposals"]), 1)


class ApplyTriageAutoTests(unittest.TestCase):
    """A high-confidence auto-attach writes into track-overrides.json as a real
    reassign, marked _source:'llm-triage' so it's editable like any correction."""

    def test_auto_attach_written_as_reassign_override(self):
        overrides = {}
        auto = [{"id": "claw-playbook#200", "track": "communications-hub",
                 "confidence": "high"}]
        out = consolidate.apply_triage_auto(overrides, auto)
        self.assertEqual(out["reassign"]["claw-playbook#200"], "communications-hub")
        # Marked as LLM-sourced so the UI can distinguish it from a human reassign.
        self.assertEqual(out.get("_source", {}).get("claw-playbook#200"), "llm-triage")

    def test_auto_attach_does_not_clobber_human_reassign(self):
        # A human reassign already in the file must WIN over the LLM auto-attach.
        overrides = {"reassign": {"claw-playbook#200": "human-track"}}
        auto = [{"id": "claw-playbook#200", "track": "communications-hub",
                 "confidence": "high"}]
        out = consolidate.apply_triage_auto(overrides, auto)
        self.assertEqual(out["reassign"]["claw-playbook#200"], "human-track")

    def test_human_takeover_of_llm_reassign_is_not_reverted(self):
        # A reassign the human EDITED (clearing the llm-triage _source tag, as the
        # UI does) must NOT be reverted to the LLM's proposal on the next run.
        overrides = {"reassign": {"claw-playbook#200": "human-track"},
                     "_source": {}}   # human cleared the tag
        auto = [{"id": "claw-playbook#200", "track": "communications-hub",
                 "confidence": "high"}]
        out = consolidate.apply_triage_auto(overrides, auto)
        self.assertEqual(out["reassign"]["claw-playbook#200"], "human-track")

    def test_still_llm_sourced_reassign_is_refreshed(self):
        # If it's STILL marked llm-triage (human hasn't touched it), the pass may
        # keep it pointed at the current proposal (idempotent re-assert).
        overrides = {"reassign": {"claw-playbook#200": "old-track"},
                     "_source": {"claw-playbook#200": "llm-triage"}}
        auto = [{"id": "claw-playbook#200", "track": "new-track",
                 "confidence": "high"}]
        out = consolidate.apply_triage_auto(overrides, auto)
        self.assertEqual(out["reassign"]["claw-playbook#200"], "new-track")


# ---------------------------------------------------------------------------
# ARCHIVE — a soft, reversible flag carried in track-overrides.json (an
# `archive:[id]` list, mirroring `split`). apply_overrides marks the card and
# the collector drops it from board/pipeline/Ungrouped, but it STAYS in
# status.json. Unarchiving (removing the id from the list) brings it back.
# ---------------------------------------------------------------------------
class ArchiveOverrideTests(unittest.TestCase):
    def test_apply_overrides_returns_archived_set(self):
        # apply_overrides surfaces the archive list so the collector can stamp
        # cards (archive doesn't change track grouping, so it's a passthrough).
        tracks = [{"name": "t", "members": ["a#1", "a#2"]}]
        out = consolidate.apply_overrides(tracks, {"archive": ["a#1"]})
        # Grouping is untouched by archive.
        by = {t["name"]: set(t["members"]) for t in out}
        self.assertEqual(by["t"], {"a#1", "a#2"})

    def test_stamp_archived_marks_and_is_reversible(self):
        cards = [pr_card(300, "stale thing", repo="r"),
                 pr_card(301, "live thing", repo="r")]
        consolidate.stamp_archived(cards, {"archive": ["r#300"]})
        by = {consolidate._card_id(c): c for c in cards}
        self.assertTrue(by["r#300"].get("archived"))
        self.assertFalse(by["r#301"].get("archived"))
        # Unarchive: empty archive list -> nothing marked (returns).
        consolidate.stamp_archived(cards, {"archive": []})
        self.assertFalse(by["r#300"].get("archived"))

    def test_archived_card_dropped_from_ungrouped_but_kept(self):
        # This is the collector-level behavior: an archived stray leaves the
        # Ungrouped/board surfaces (card.archived True) but persists in the data.
        cards = [pr_card(300, "stale", repo="r")]
        consolidate.stamp_archived(cards, {"archive": ["r#300"]})
        self.assertTrue(cards[0]["archived"])   # still IN the list, just flagged

    def test_archive_is_noop_for_a_track_member(self):
        # Archive only declutters STRAYS. A card that's a track member must NOT
        # get hidden (that would leave the member listed but its card gone).
        member = pr_card(400, "in a track", repo="r")
        member["track"] = "some-track"
        consolidate.stamp_archived([member], {"archive": ["r#400"]})
        self.assertFalse(member.get("archived"))  # member is not hidden


# ---------------------------------------------------------------------------
# PASS 2 — TRACK-ANALYSIS. Per track, feed members_detail + bodies + facts; the
# LLM returns a headline verdict, a completion read (BOTH its gut % AND the %
# COMPUTED from its per-strand keep/clip decisions — the cross-check), a cleanup
# list, relationships, and per-strand status. Cached to verdicts.json keyed by
# track name. Runner injected so tests stay offline.
# ---------------------------------------------------------------------------
def _briefing_track():
    """A track shaped like the real briefing track: 3 merged impl-PRs, 1 open
    spec-PR, 2 open issues (stamped with members_detail via stamp_track_facts)."""
    cards = [
        pr_card(115, "feat(bosque): Communications Hub", state="MERGED",
                shipped=True, branch="bosque/comms"),
        pr_card(117, "Email Triage: tag Digest", state="MERGED", shipped=True),
        pr_card(119, "briefing curation Stages 2-5", state="MERGED", shipped=True),
        pr_card(118, "Specs: Stage 2 + Stage 3", state="OPEN", labels=["build-spec"]),
        issue_card(111, "comms-hub issue"),
        issue_card(112, "comms-hub issue 2"),
    ]
    ids = [consolidate._card_id(c) for c in cards]
    tracks = [{"name": "briefing", "members": ids}]
    consolidate.stamp_track_facts(tracks, cards)
    return tracks[0]


def analyze_runner(payload):
    return lambda prompt: json.dumps(payload)


class AnalyzeTests(unittest.TestCase):
    def _full_payload(self, llm_pct=80, strands=None):
        t = _briefing_track()
        ids = [d["id"] for d in t["members_detail"]]
        strands = strands or {ids[0]: "keep", ids[1]: "keep", ids[2]: "keep",
                              ids[3]: "close", ids[4]: "supplanted",
                              ids[5]: "supplanted"}
        return t, {
            "headline": "SHIPPED · needs cleanup",
            "completion_pct": llm_pct,
            "completion_verbal": "shipped; close spec #118; #111/#112 supplanted",
            "cleanup": ["close spec-PR #118", "close #111/#112 (supplanted by #119)"],
            "relationships": [
                {"pair": [ids[0], ids[2]], "relation": "progressive",
                 "confidence": "high", "note": "#119 builds on #115"}],
            "strands": {sid: {"status": st, "note": st + " note",
                              "confidence": "high"} for sid, st in strands.items()},
            "confidence": "high",
        }

    def test_verdict_shape_parsed(self):
        t, payload = self._full_payload()
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        self.assertEqual(v["headline"], "SHIPPED · needs cleanup")
        self.assertEqual(v["completion"]["llm_pct"], 80)
        self.assertIn("close spec", v["completion"]["verbal"])
        self.assertEqual(len(v["cleanup"]), 2)
        self.assertEqual(v["relationships"][0]["relation"], "progressive")

    def test_per_strand_status_parsed(self):
        t, payload = self._full_payload()
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        ids = [d["id"] for d in t["members_detail"]]
        self.assertEqual(v["strands"][ids[3]]["status"], "close")
        self.assertEqual(v["strands"][ids[4]]["status"], "supplanted")

    def test_computed_pct_from_keep_clip(self):
        # keep = the 3 merged + (nothing else kept); computed % = done-kept /
        # total-kept. Here 3 kept (all merged/done) + 0 open kept -> 3/3 = 100%
        # of the KEPT work is done; the clipped strands don't count as "work left".
        t, payload = self._full_payload()
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        # 3 keeps, all done (merged). computed = 100.
        self.assertEqual(v["completion"]["computed_pct"], 100)

    def test_agreement_is_high_confidence(self):
        # LLM says ~100 and its clip list implies 100 -> agree -> high, show computed.
        t, payload = self._full_payload(llm_pct=100)
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        self.assertEqual(v["completion"]["confidence"], "high")

    def test_divergence_is_low_confidence(self):
        # LLM guts 40% but its keep/clip implies 100% done -> diverge -> LOW
        # confidence (render as a question). The free consistency check.
        t, payload = self._full_payload(llm_pct=40)
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        self.assertEqual(v["completion"]["confidence"], "low")

    def test_computed_with_open_kept_strand(self):
        # If an OPEN strand is KEPT (real remaining work), it counts against %.
        t = _briefing_track()
        ids = [d["id"] for d in t["members_detail"]]
        # keep the 3 merged AND the open spec #118 (id[3]); clip the 2 issues.
        strands = {ids[0]: "keep", ids[1]: "keep", ids[2]: "keep",
                   ids[3]: "keep", ids[4]: "supplanted", ids[5]: "outdated"}
        _, payload = self._full_payload(llm_pct=75, strands=strands)
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        # 4 kept, 3 done (merged) + 1 not-done (open spec) -> 3/4 = 75%.
        self.assertEqual(v["completion"]["computed_pct"], 75)

    def test_junk_output_returns_none(self):
        t = _briefing_track()
        v = consolidate.run_analyze(t, runner=lambda p: "no idea")
        self.assertIsNone(v)

    def test_cli_failure_returns_none(self):
        t = _briefing_track()
        def boom(p):
            raise OSError("no claude")
        self.assertIsNone(consolidate.run_analyze(t, runner=boom))

    def test_prose_then_fence(self):
        t, payload = self._full_payload()
        resp = "Here's my analysis:\n```json\n" + json.dumps(payload) + "\n```"
        v = consolidate.run_analyze(t, runner=lambda p: resp)
        self.assertIsNotNone(v)
        self.assertEqual(v["headline"], "SHIPPED · needs cleanup")

    def test_relationship_pair_string_is_coerced_to_list(self):
        # A `pair` returned as a STRING (or missing) must be coerced to a list so
        # the template's pair.map(...) can't crash the whole track-detail render.
        t = _briefing_track()
        payload = {"headline": "H", "completion_pct": 50, "cleanup": [],
                   "relationships": [
                       {"pair": "claw#1 vs claw#2", "relation": "competing"},
                       {"relation": "independent"}],  # pair missing entirely
                   "strands": {}, "confidence": "high"}
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        for r in v["relationships"]:
            self.assertIsInstance(r["pair"], list)

    def test_all_clipped_strands_is_low_confidence(self):
        # If EVERY strand is clipped (kept==0), computed % is None and the LLM's
        # gut % would contradict every strand slot -> flag LOW confidence so it
        # renders as a question, never asserted as a fact.
        t = _briefing_track()
        ids = [d["id"] for d in t["members_detail"]]
        strands = {i: "duplicate" for i in ids}   # nothing kept
        _, payload = self._full_payload(llm_pct=80, strands=strands)
        v = consolidate.run_analyze(t, runner=analyze_runner(payload))
        self.assertIsNone(v["completion"]["computed_pct"])
        self.assertEqual(v["completion"]["confidence"], "low")


class VerdictStampTests(unittest.TestCase):
    def test_stamp_verdicts_sets_t_verdict(self):
        t = _briefing_track()
        verdicts = {"briefing": {"headline": "X", "completion": {}}}
        consolidate.stamp_verdicts([t], verdicts)
        self.assertEqual(t["verdict"]["headline"], "X")

    def test_no_verdict_leaves_track_clean(self):
        # Offline-safe: a track with no cached verdict stamps nothing.
        t = _briefing_track()
        consolidate.stamp_verdicts([t], {})
        self.assertNotIn("verdict", t)


# ---------------------------------------------------------------------------
# PASS 3 — ROLLUP. Pure aggregation over the Pass-2 verdicts: bucket each track
# (near-done / mid / early / stuck) + per-track %. NEVER invokes a runner.
# ---------------------------------------------------------------------------
class RollupTests(unittest.TestCase):
    def _tracks(self):
        return [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]

    def _verdicts(self):
        return {
            "a": {"headline": "near", "completion": {"computed_pct": 90,
                  "confidence": "high"}, "cleanup": []},              # near-done
            "b": {"headline": "mid", "completion": {"computed_pct": 50,
                  "confidence": "high"}, "cleanup": []},               # mid
            "c": {"headline": "shipped msg", "completion": {"computed_pct": 95,
                  "confidence": "high"}, "cleanup": ["close #5"]},     # stuck (hi%+cleanup)
            # d: no verdict -> early
        }

    def test_bucket_distribution(self):
        r = consolidate.build_rollup(self._tracks(), self._verdicts())
        self.assertEqual(r["counts"],
                         {"near-done": 1, "mid": 1, "early": 1, "stuck": 1})

    def test_high_pct_with_cleanup_is_stuck_not_near(self):
        r = consolidate.build_rollup(self._tracks(), self._verdicts())
        c = next(t for t in r["tracks"] if t["name"] == "c")
        self.assertEqual(c["bucket"], "stuck")

    def test_no_verdict_track_is_early(self):
        r = consolidate.build_rollup(self._tracks(), self._verdicts())
        d = next(t for t in r["tracks"] if t["name"] == "d")
        self.assertEqual(d["bucket"], "early")
        self.assertIsNone(d["pct"])

    def test_low_completion_confidence_is_stuck(self):
        # A diverged (low-confidence) completion read -> the track needs a
        # decision, not more building -> stuck (even without an explicit cleanup).
        tracks = [{"name": "x"}]
        verdicts = {"x": {"completion": {"computed_pct": 85, "confidence": "low"},
                          "cleanup": []}}
        r = consolidate.build_rollup(tracks, verdicts)
        self.assertEqual(r["tracks"][0]["bucket"], "stuck")

    def test_analyzed_track_with_cleanup_but_no_pct_is_stuck_not_early(self):
        # A track that WAS analyzed (has a verdict) and flagged for cleanup, but
        # whose % couldn't be computed, must read 'stuck' (needs a decision), not
        # 'early' (which is reserved for never-analyzed tracks).
        tracks = [{"name": "z"}]
        verdicts = {"z": {"completion": {}, "cleanup": ["reconcile #1 vs #2"]}}
        r = consolidate.build_rollup(tracks, verdicts)
        self.assertEqual(r["tracks"][0]["bucket"], "stuck")

    def test_never_analyzed_track_is_still_early(self):
        # No verdict at all (even with the fallback machinery) -> early.
        r = consolidate.build_rollup([{"name": "q"}], {})
        self.assertEqual(r["tracks"][0]["bucket"], "early")

    def test_rollup_does_not_invoke_runner(self):
        # Pass 3 CONSUMES Pass-2 output; it must not call any LLM. build_rollup
        # takes no runner at all — this test documents that contract.
        self.assertFalse(hasattr(consolidate.build_rollup, "runner"))
        r = consolidate.build_rollup(self._tracks(), self._verdicts())
        self.assertIn("tracks", r)
        self.assertIn("counts", r)


if __name__ == "__main__":
    unittest.main()
