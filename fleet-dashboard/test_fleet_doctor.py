#!/usr/bin/env python3
"""Tests for fleet-doctor's duplicate-card detection (report-only health check).

Run: python3 test_fleet_doctor.py   (stdlib unittest, no deps)
fleet-doctor.py has a hyphen, so load it via importlib.
"""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "fleet_doctor", str(Path(__file__).parent / "fleet-doctor.py"))
fd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fd)


def card(title, source="repo-plan", slug=None, product="magic-me", repo="claw-playbook", github=None):
    c = {"title": title, "source": source, "product": product, "repo": repo,
         "slug": slug if slug is not None else title.lower().replace(" ", "-")}
    if github:
        c["github"] = github
    return c


class DuplicateDetectionTests(unittest.TestCase):
    def test_same_initiative_across_sources_flagged(self):
        cards = [
            card("ynab-2026-api-tools", source="repo-plan", slug="ynab-2026-api-tools"),
            card("YNAB 2026 API tools — parent tracker", source="remote-only",
                 slug="ynab-parent", github={"number": 90}),
        ]
        pairs = fd.find_duplicate_cards(cards)
        self.assertEqual(len(pairs), 1)
        a, b, score, shared = pairs[0]
        self.assertGreaterEqual(score, 0.5)
        self.assertIn("ynab", shared)

    def test_same_source_not_paired(self):
        # two repo-plans, even if similar, aren't a cross-source duplicate
        cards = [card("venmo enrichment", source="repo-plan", slug="venmo-enrichment-a"),
                 card("venmo enrichment two", source="repo-plan", slug="venmo-enrichment-b")]
        self.assertEqual(fd.find_duplicate_cards(cards), [])

    def test_exact_slug_match_not_flagged(self):
        # identical normalized slug would have auto-merged in the collector
        cards = [card("Venmo", source="repo-plan", slug="venmo_enrichment"),
                 card("Venmo", source="workbench-only", slug="venmo-enrichment")]
        self.assertEqual(fd.find_duplicate_cards(cards), [])

    def test_different_product_not_paired(self):
        cards = [card("shared tool", source="repo-plan", slug="a", product="magic-me"),
                 card("shared tool", source="workbench-only", slug="b", product="build-tooling")]
        self.assertEqual(fd.find_duplicate_cards(cards), [])

    def test_different_repo_not_paired(self):
        cards = [card("auth", source="repo-plan", slug="a", repo="claw-playbook"),
                 card("auth", source="workbench-only", slug="b", repo="wizard")]
        self.assertEqual(fd.find_duplicate_cards(cards), [])

    def test_unrelated_titles_below_threshold(self):
        cards = [card("amazon venmo categorizer", source="repo-plan", slug="amazon-venmo"),
                 card("dangerclaw cron ecosystem", source="workbench-only", slug="dangerclaw-cron")]
        self.assertEqual(fd.find_duplicate_cards(cards), [])

    def test_align_suggestion_targets_repo_plan_slug(self):
        plan = card("YNAB tools", source="repo-plan", slug="ynab-2026-api-tools")
        wb = card("ynab tools", source="workbench-only", slug="ynab_tools")
        wb["path"] = "/ws/workbench/ynab_tools"
        s = fd._align_suggestion(plan, wb)
        self.assertIn("ynab-2026-api-tools", s)
        self.assertIn("workbench", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
