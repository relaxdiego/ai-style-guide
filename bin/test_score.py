#!/usr/bin/env python3
"""Self-test for bin/score.py.

    python3 bin/test_score.py

Plain unittest, no dependencies and no captured samples: every fixture is
written inline into a temporary tree, so the suite runs in a checkout with an
empty samples/ and cannot be quietly satisfied by the real data.

The cases here are the defects the metrics actually had, kept as regressions:
a bold lead-in counted as a heading and dropped from the prose count, a bash
comment inside a fence counted as a heading, an inline list cut apart at the
first comma inside a quoted regex, a metric that could regress from a zero
baseline and be reported as having no headroom, a guard row that vanished
because its baseline was zero, and an owned metric graded on the sign of a
difference of means with no test of whether ten samples could see it.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score  # noqa: E402


PROBE = "unit-probe"        # no prompts/unit-probe.md: no tokens, no coverage


def doc(words=10, bullets=0, sections=0, extra=""):
    """A synthetic response with a known word/bullet/section count."""
    L = [f"## Heading {i}" for i in range(sections)]
    L += [f"- bullet {i}" for i in range(bullets)]
    L += [" ".join(f"w{i}" for i in range(words))]
    return "\n\n".join(L) + ("\n" + extra if extra else "") + "\n"


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def score_text(self, text, tokens=(), coverage=()):
        p = self.root / "r1.md"
        p.write_text(text)
        return score.score_file(p, list(tokens), coverage)

    def arm(self, probe, arm, texts):
        d = self.root / "samples" / probe / arm
        d.mkdir(parents=True)
        for i, t in enumerate(texts, 1):
            (d / f"r{i}.md").write_text(t)
        return d

    def claims(self, **kw):
        c = {"id": "styled", "baseline": "control",
             "owns": [], "probes": [], "guards": [], "banned": []}
        c.update(kw)
        return c

    def rows(self, **kw):
        return score._rows(self.root, self.claims(**kw), "styled")

    def find(self, rows, metric, probe=PROBE):
        hits = [r for r in rows if r["metric"] == metric and r["probe"] == probe]
        self.assertEqual(len(hits), 1, f"expected one {metric} row, got {hits}")
        return hits[0]


class TestElaborationRatio(Harness):
    """F1: a linear transform of first_verdict_pct, and in LOWER_IS_BETTER,
    where minimising it maximised first_verdict_pct — it paid for burying the
    verdict."""

    def test_gone_from_everywhere(self):
        row = self.score_text("SQLite is the answer.", tokens=["SQLite"])
        self.assertNotIn("elaboration_ratio", row)
        self.assertNotIn("elaboration_ratio", score.NUMERIC)
        self.assertNotIn("elaboration_ratio", score.LOWER_IS_BETTER)

    def test_first_verdict_pct_survives_untouched(self):
        row = self.score_text("SQLite is the answer.", tokens=["SQLite"])
        self.assertEqual(row["first_verdict_pct"], 0.0)
        self.assertIn("first_verdict_pct", score.NUMERIC)
        self.assertNotIn("first_verdict_pct", score.LOWER_IS_BETTER)


class TestSections(Harness):
    """F2: the heading regex counted bold lead-ins and fenced comments."""

    def test_bold_lead_in_is_not_a_section(self):
        text = ("**It has no history.** Code you write carries the shape of "
                "the decisions behind it.\n")
        self.assertEqual(self.score_text(text)["sections"], 0)

    def test_standalone_bold_heading_still_counts(self):
        text = "**The tradeoff**\n\nSQLite wins on operations.\n"
        self.assertEqual(self.score_text(text)["sections"], 1)

    def test_trailing_whitespace_after_bold_heading_still_counts(self):
        self.assertEqual(self.score_text("**The tradeoff**  \n\nbody\n")["sections"], 1)

    def test_markdown_headings_still_count(self):
        text = "# One\n\nbody\n\n#### Four\n\nbody\n"
        self.assertEqual(self.score_text(text)["sections"], 2)

    def test_comment_inside_a_fence_is_not_a_section(self):
        text = ("Run this:\n\n```bash\n# make it executable\nchmod +x go.sh\n"
                "# then commit\ngit add go.sh\n```\n\nThat is the whole fix.\n")
        self.assertEqual(self.score_text(text)["sections"], 0)


class TestProseParagraphs(Harness):
    """F3: `*` in the marker class matched `**Bold.**`, and a fence with a
    blank line in it was split into a chunk that looked like prose."""

    def test_bold_lead_in_paragraph_counts_as_prose(self):
        text = ("**It has no history.** Code you write carries the shape of "
                "the decisions behind it.\n")
        self.assertEqual(self.score_text(text)["prose_paragraphs"], 1)

    def test_standalone_bold_heading_is_not_prose(self):
        """A bold span alone on its line is a heading, so it must not be
        counted as a paragraph as well as a section. Excluding `**` wholesale
        dropped the lead-ins; excluding nothing double-counted the headings."""
        text = "**What counts as a congestion signal**\n\nThe prose body.\n"
        row = self.score_text(text)
        self.assertEqual(row["sections"], 1)
        self.assertEqual(row["prose_paragraphs"], 1)

    def test_heading_and_lead_in_are_told_apart(self):
        text = ("**A heading**\n\n"
                "**A lead-in.** Followed by prose on the same line.\n")
        row = self.score_text(text)
        self.assertEqual(row["sections"], 1)
        self.assertEqual(row["prose_paragraphs"], 1)

    def test_real_bullets_are_still_not_prose(self):
        text = "Intro line.\n\n- one\n- two\n\n* star\n\n+ plus\n\n1. numbered\n"
        self.assertEqual(self.score_text(text)["prose_paragraphs"], 1)

    def test_fence_with_a_blank_line_adds_no_prose(self):
        text = ("Intro line.\n\n```bash\nchmod +x go.sh\n\ngit add go.sh\n```\n\n"
                "Closing line.\n")
        self.assertEqual(self.score_text(text)["prose_paragraphs"], 2)

    def test_headings_and_tables_are_still_not_prose(self):
        text = "## Heading\n\n| a | b |\n\nOne paragraph.\n"
        self.assertEqual(self.score_text(text)["prose_paragraphs"], 1)


class TestCodeBlocks(Harness):
    """F4: the metric counted blocks, not lines, and was named for lines."""

    def test_renamed_and_counts_blocks(self):
        text = "```\na\nb\nc\n```\n\ntext\n\n```py\nd\n```\n"
        row = self.score_text(text)
        self.assertEqual(row["code_blocks"], 2)
        self.assertNotIn("code_fence_lines", row)
        self.assertIn("code_blocks", score.NUMERIC)
        self.assertNotIn("code_fence_lines", score.NUMERIC)


class TestListKey(Harness):
    """F5: `\\[(.*?)\\]` plus split(",") cut quoted items apart. Coverage
    markers are regexes, so both characters are legal inside one."""

    def test_quoted_comma_and_bracket_survive(self):
        self.assertEqual(
            score._list_key('coverage: ["a,b", "c[x]d"]', "coverage"),
            ["a,b", "c[x]d"])

    def test_bare_items_behave_as_before(self):
        self.assertEqual(score._list_key("owns: [words, prose_paragraphs]", "owns"),
                         ["words", "prose_paragraphs"])

    def test_single_quotes_and_inner_spaces(self):
        self.assertEqual(score._list_key("banned: ['worth noting', frankly]", "banned"),
                         ["worth noting", "frankly"])

    def test_multi_line_list(self):
        text = 'banned: ["load-bearing", "worth noting",\n  "seam", "seams"]\n'
        self.assertEqual(score._list_key(text, "banned"),
                         ["load-bearing", "worth noting", "seam", "seams"])

    def test_empty_and_missing(self):
        self.assertEqual(score._list_key("verdict_tokens: []", "verdict_tokens"), [])
        self.assertEqual(score._list_key("id: x", "verdict_tokens"), [])

    def test_real_coverage_marker_with_a_regex_alternation(self):
        text = 'coverage: ["log|output|error", "\\bnam(e|es|ing)\\b"]'
        self.assertEqual(score._list_key(text, "coverage"),
                         ["log|output|error", "\\bnam(e|es|ing)\\b"])


class TestSummarise(Harness):
    """F11: scores.json recorded mean/min/max but not spread."""

    def test_sd_present_and_none_at_n_of_one(self):
        rows = [self.score_text(doc(words=n)) for n in (10, 20)]
        self.assertAlmostEqual(score.summarise(rows)["words"]["sd"], 7.07, places=2)
        self.assertIsNone(score.summarise(rows[:1])["words"]["sd"])


class TestPermP(unittest.TestCase):
    """F9: the noise floor an owned metric now has to clear."""

    def test_known_noise_pair_is_not_significant(self):
        a = [10, 12, 9, 11, 13, 8, 12, 10, 11, 9]
        b = [11, 9, 12, 10, 8, 13, 9, 12, 10, 11]
        self.assertGreater(score.perm_p(a, b), 0.05)

    def test_known_separated_pair_is_significant(self):
        a = [10, 12, 9, 11, 13, 8, 12, 10, 11, 9]
        b = [40, 42, 39, 41, 43, 38, 42, 40, 41, 39]
        self.assertLess(score.perm_p(a, b), 0.05)

    def test_identical_arms_are_p_one(self):
        self.assertEqual(score.perm_p([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)

    def test_deterministic_and_symmetric(self):
        a = [10, 12, 9, 11, 13, 8, 12, 10, 11, 9]
        b = [12, 14, 11, 13, 15, 10, 14, 12, 13, 11]
        self.assertEqual(score.perm_p(a, b), score.perm_p(a, b))
        self.assertEqual(score.perm_p(a, b), score.perm_p(b, a))

    def test_exact_when_the_split_count_allows_it(self):
        # C(20,10) = 184,756, under PERM_EXACT_MAX, so the shipped 10-vs-10
        # cells are enumerated rather than sampled.
        self.assertLessEqual(184756, score.PERM_EXACT_MAX)
        # Maximal separation: only the two extreme splits are as extreme.
        self.assertEqual(score.perm_p(list(range(10)), list(range(100, 110))),
                         round(2 / 184756, 4))

    def test_sampled_fallback_is_deterministic(self):
        a, b = list(range(30)), [x + 1 for x in range(30)]
        self.assertGreater(score.perm_p(a, b), 0.05)
        self.assertEqual(score.perm_p(a, b), score.perm_p(a, b))

    def test_too_few_samples_has_no_p(self):
        self.assertIsNone(score.perm_p([1], [2]))


class TestTargets(Harness):
    """F6 and F9: what an owned metric now has to do to be credited."""

    def test_zero_baseline_regression_is_a_failure(self):
        # sections 0.0 -> 0.3: three of ten responses grew a heading.
        self.arm(PROBE, "control", [doc(words=20) for _ in range(10)])
        self.arm(PROBE, "styled",
                 [doc(words=20, sections=1) for _ in range(3)]
                 + [doc(words=20) for _ in range(7)])
        targets, _, failures = self.rows(owns=["sections"], probes=[PROBE])
        row = self.find(targets, "sections")
        self.assertEqual((row["baseline"], row["style"]), (0, 0.3))
        self.assertEqual(row["status"], "REGRESSED FROM ZERO")
        self.assertTrue(any("rose from a zero baseline" in f for f in failures),
                        failures)

    def test_zero_on_both_sides_is_no_headroom(self):
        self.arm(PROBE, "control", [doc(words=20) for _ in range(6)])
        self.arm(PROBE, "styled", [doc(words=20) for _ in range(6)])
        targets, _, failures = self.rows(owns=["sections"], probes=[PROBE])
        self.assertEqual(self.find(targets, "sections")["status"], "no headroom")
        self.assertTrue(any("no headroom on any probe" in f for f in failures),
                        failures)

    def test_separated_improvement_is_ok(self):
        self.arm(PROBE, "control", [doc(words=n) for n in range(60, 66)])
        self.arm(PROBE, "styled", [doc(words=n) for n in range(20, 26)])
        targets, _, failures = self.rows(owns=["words"], probes=[PROBE])
        row = self.find(targets, "words")
        self.assertEqual(row["status"], "ok")
        self.assertLess(row["p"], score.PERM_ALPHA)
        self.assertEqual(failures, [])

    def test_right_direction_but_noise_is_a_failure(self):
        # Means differ by one word; the arms interleave completely.
        self.arm(PROBE, "control", [doc(words=n) for n in (40, 42, 44, 46, 48, 50)])
        self.arm(PROBE, "styled", [doc(words=n) for n in (39, 41, 43, 45, 47, 49)])
        targets, _, failures = self.rows(owns=["words"], probes=[PROBE])
        row = self.find(targets, "words")
        self.assertEqual(row["status"], "NOT SIGNIFICANT")
        self.assertGreater(row["p"], score.PERM_ALPHA)
        self.assertTrue(any("not past noise" in f and "permutation p=" in f
                            for f in failures), failures)

    def test_wrong_direction_is_still_a_failure(self):
        self.arm(PROBE, "control", [doc(words=n) for n in range(20, 26)])
        self.arm(PROBE, "styled", [doc(words=n) for n in range(60, 66)])
        targets, _, failures = self.rows(owns=["words"], probes=[PROBE])
        self.assertEqual(self.find(targets, "words")["status"], "NO MOVEMENT")
        self.assertTrue(any("did not improve" in f for f in failures), failures)

    def test_banned_terms_gets_a_p_of_its_own(self):
        # banned_terms has no summary entry; its vector comes from the files.
        self.arm(PROBE, "control", ["honestly, " + doc(words=20) for _ in range(6)])
        self.arm(PROBE, "styled", [doc(words=20) for _ in range(6)])
        targets, _, failures = self.rows(owns=["banned_terms"], probes=[PROBE],
                                         banned=["honestly"])
        row = self.find(targets, "banned_terms")
        self.assertEqual((row["baseline"], row["style"]), (1.0, 0.0))
        self.assertEqual(row["status"], "ok")
        self.assertLess(row["p"], score.PERM_ALPHA)
        self.assertEqual(failures, [])


class TestGuards(Harness):
    """F7 and F9: guard rows at a zero baseline, and p as commentary only."""

    def test_zero_baseline_guard_row_is_emitted(self):
        self.arm(PROBE, "control", [doc(words=40) for _ in range(10)])
        self.arm(PROBE, "styled",
                 [doc(words=40, sections=1) for _ in range(3)]
                 + [doc(words=40) for _ in range(7)])
        _, guards, _ = self.rows(guards=[PROBE])
        row = self.find(guards, "sections")
        self.assertEqual((row["baseline"], row["style"]), (0, 0.3))
        self.assertIsNone(row["delta_pct"])
        self.assertEqual(row["delta"], 0.3)
        self.assertEqual(score._delta(row), "+0.30")

    def test_movement_off_a_zero_baseline_on_a_guarded_metric_is_collateral(self):
        self.arm(PROBE, "control", ["" for _ in range(6)])
        self.arm(PROBE, "styled", [doc(words=40) for _ in range(6)])
        _, guards, failures = self.rows(guards=[PROBE])
        row = self.find(guards, "words")
        self.assertTrue(row["guarded"])
        self.assertEqual(row["status"], "COLLATERAL")
        self.assertTrue(any("off a zero baseline" in f for f in failures), failures)

    def test_small_but_significant_guard_movement_still_passes(self):
        # 5% is inside GUARD_TOLERANCE, and the arms do not overlap at all, so
        # p is tiny. The guard is a point-estimate alarm and must not care.
        self.arm(PROBE, "control", [doc(words=100) for _ in range(6)])
        self.arm(PROBE, "styled", [doc(words=105) for _ in range(6)])
        _, guards, failures = self.rows(guards=[PROBE])
        row = self.find(guards, "words")
        self.assertEqual(row["status"], "ok")
        self.assertLess(row["p"], score.PERM_ALPHA)
        self.assertEqual(failures, [])

    def test_guard_beyond_tolerance_still_fails(self):
        self.arm(PROBE, "control", [doc(words=100) for _ in range(6)])
        self.arm(PROBE, "styled", [doc(words=60) for _ in range(6)])
        _, guards, failures = self.rows(guards=[PROBE])
        self.assertEqual(self.find(guards, "words")["status"], "COLLATERAL")
        self.assertTrue(any("guard metric 'words' moved" in f for f in failures),
                        failures)


class TestDirections(Harness):
    """F10: bullets has no universal direction, so a style declares its own."""

    def write_claims(self, body):
        d = self.root / "style"
        d.mkdir(exist_ok=True)
        (d / "claims.yaml").write_text(body)
        return score.load_claims(d)

    def test_absent_when_unset(self):
        c = self.write_claims("id: s\nowns:   [words]\nprobes: [p]\n"
                              "guards: []\nbanned: []\n")
        self.assertNotIn("directions", c)
        self.assertTrue(score.wants_lower(c, "bullets"))

    def test_parsed_and_applied(self):
        c = self.write_claims("id: s\nowns:   [bullets]\nprobes: [p]\n"
                              "guards: []\nbanned: []\n"
                              "directions:\n  bullets: higher\n")
        self.assertEqual(c["directions"], {"bullets": "higher"})
        self.assertFalse(score.wants_lower(c, "bullets"))
        self.assertTrue(score.wants_lower(c, "words"))

    def test_more_bullets_fails_by_default_and_passes_when_declared(self):
        self.arm(PROBE, "control", [doc(words=40, bullets=1) for _ in range(6)])
        self.arm(PROBE, "styled", [doc(words=40, bullets=5) for _ in range(6)])
        targets, _, failures = self.rows(owns=["bullets"], probes=[PROBE])
        self.assertEqual(self.find(targets, "bullets")["status"], "NO MOVEMENT")
        self.assertTrue(failures)

        targets, _, failures = self.rows(owns=["bullets"], probes=[PROBE],
                                         directions={"bullets": "higher"})
        row = self.find(targets, "bullets")
        self.assertEqual(row["status"], "ok")
        self.assertLess(row["p"], score.PERM_ALPHA)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
