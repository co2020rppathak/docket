"""Tests for the expiry-date detector (expiry.py). They need no images and no OCR.

Run:  python -m unittest test_expiry -v
"""
import unittest

from datetime import date, timedelta

from expiry import (
    FAR_FUTURE_DAYS, MIN_SCORE, Candidate, analyse, find_expiry, has_expiry_date,
)


class FindExpiryTests(unittest.TestCase):
    def expiry(self, text):
        """The detected date as 'YYYY-MM-DD', or None."""
        found = find_expiry(text)
        return found.date.isoformat() if found else None

    # ---------- what it should find ----------

    def test_common_expiry_labels(self):
        for label in [
            "Valid until:", "Valid Upto", "Valid Thru:", "Valid till", "Expiry Date:",
            "Date of Expiry:", "Expires on", "Expiry:", "Exp:", "Warranty expires on",
            "Policy Expiry Date", "DATE OF EXPIRY", "Validity (NT):", "Good thru",
            "Cover ends on", "Policy ends on:", "Ending on", "Membership valid until",
        ]:
            with self.subTest(label=label):
                self.assertEqual(self.expiry(f"{label} 15/03/2028"), "2028-03-15")

    def test_all_supported_date_formats(self):
        for written in [
            "15/03/2028", "15-03-2028", "15.03.2028", "15 Mar 2028", "15 March 2028",
            "March 15, 2028", "2028-03-15", "15-Mar-2028", "15th March, 2028", "Mar 15 2028",
            "15 MARCH 2028", "2028/03/15",
        ]:
            with self.subTest(written=written):
                self.assertEqual(self.expiry(f"Valid until: {written}"), "2028-03-15")

    def test_numeric_dates_are_read_day_first(self):
        self.assertEqual(self.expiry("Valid until 05/06/2027"), "2027-06-05")  # 5 June, not 6 May
        # 25 cannot be a month, so this can only be month-first
        self.assertEqual(self.expiry("Valid until 11/25/2027"), "2027-11-25")

    def test_label_on_the_line_above(self):
        self.assertEqual(self.expiry("Valid Thru:\n15.03.2028"), "2028-03-15")

    def test_realistic_page_with_other_dates(self):
        page = (
            "Demo Care Insurance (SAMPLE)\n\n"
            "HEALTH INSURANCE CARD\n"
            "Member: Rohan Joshi\n"
            "Member ID: HLT-176672\n"
            "Plan: Family Floater\n"
            "Date of Birth: 30 Aug 1985\n"
            "Valid Thru: 11 May 2031\n"
            "SAMPLE CARD - FOR SOFTWARE TESTING ONLY\n"
        )
        self.assertEqual(self.expiry(page), "2031-05-11")

    def test_expiry_found_whatever_its_position(self):
        issue, expiry = "Date of Issue: 14-08-2024", "Valid Upto: 14-08-2027"
        self.assertEqual(self.expiry(f"Grade: A\n{issue}\n{expiry}"), "2027-08-14")
        self.assertEqual(self.expiry(f"Grade: A\n{expiry}\n{issue}"), "2027-08-14")

    # ---------- two dates on one line, and ranges ----------

    def test_two_dates_on_one_line(self):
        self.assertEqual(self.expiry("Date of issue 12 JAN 2021 Date of expiry 11 JAN 2031"), "2031-01-11")
        self.assertEqual(self.expiry("Expiry: 08.11.2026 Issued: 08.11.2025"), "2026-11-08")

    def test_ranges_use_the_end_date(self):
        for text in [
            "Policy Period: 2025-12-02 to 2026-12-01",
            "Period of Insurance: From 02/12/2025 To 01/12/2026",
            "Valid from 02/12/2025 till 01/12/2026",
            "From 00:00 hrs on 02/12/2025 to midnight of 01/12/2026",
            "Valid: 02/12/2025 - 01/12/2026",
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.expiry(text), "2026-12-01")

    # ---------- what it must NOT suggest ----------

    def test_other_kinds_of_dates_are_ignored(self):
        for text in [
            "Date of Issue: 14/08/2024",
            "Date of Birth: 30/03/2003",
            "DOB: 30/03/2003",
            "Date of Purchase: 23/01/2026",
            "Member Since: 12/11/2025",
            "Printed on 10/12/2025",
            "Valid from 02/12/2025",
            "Valid since 02/12/2025",
            "Validity start date: 02/12/2025",
            "Effective date: 02/12/2025",
            "Dividends paid on 02/12/2025",   # "ends" inside another word is not an expiry word
            "Weekends: 02/12/2025",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(self.expiry(text))

    def test_a_date_with_no_label_is_not_enough(self):
        self.assertIsNone(self.expiry("08/11/2026"))
        self.assertIsNone(self.expiry("Total 12/05/2026"))

    def test_label_on_the_line_above_must_be_an_expiry_label(self):
        self.assertIsNone(self.expiry("Date of Issue:\n15.03.2028"))

    def test_no_text_or_no_dates(self):
        self.assertIsNone(self.expiry(""))
        self.assertIsNone(self.expiry("   \n\n  "))
        self.assertIsNone(self.expiry("Certificate No: CERT-12345\nGrade: A"))
        self.assertIsNone(self.expiry("Valid until further notice"))

    def test_numbers_that_look_like_dates_are_not_dates(self):
        text = (
            "Policy No: POL/SMP/2026/423466\n"
            "Certificate No: CERT-17952\n"
            "ID No: SMP-2020-2186\n"
            "Serial No: SN116266656\n"
            "Sum Insured: Rs. 1,000,000\n"
            "Expiry in 2 years"
        )
        self.assertIsNone(self.expiry(text))

    def test_impossible_dates_are_rejected(self):
        self.assertIsNone(self.expiry("Valid until 31/02/2026"))  # no 31st of February
        self.assertIsNone(self.expiry("Valid until 15/13/2026"))  # no month 13
        self.assertIsNone(self.expiry("Valid until 15/03/1979"))  # far too old: probably misread
        self.assertIsNone(self.expiry("Valid until 15/03/2150"))  # far too new

    def test_a_date_that_follows_a_stray_digit_is_not_trusted(self):
        # OCR broke "19/09/2031" into "1 9/09/2031": reading "9/09/2031" would give the wrong day
        self.assertIsNone(self.expiry("Expiry; 1 9/09/2031"))
        self.assertIsNone(self.expiry("Valid until 2 5.12.2027"))
        # but a normal label, even one ending in a number, is fine
        self.assertEqual(self.expiry("Policy 2 expiry 19/09/2031"), "2031-09-19")
        self.assertEqual(self.expiry("Expiry: 08.11.2026 Issued: 08.11.2025"), "2026-11-08")

    def test_a_date_is_never_joined_across_lines(self):
        self.assertIsNone(self.expiry("Valid until: 15\n03/2028"))
        self.assertIsNone(self.expiry("Valid until: 15/03\n2028"))

    # ---------- OCR mistakes ----------

    def test_common_ocr_misreads_are_repaired(self):
        self.assertEqual(self.expiry("Expiry: 23/0] /2027"), "2027-01-23")   # 1 read as ]
        self.assertEqual(self.expiry("Exp: 3O/O6/2O27"), "2027-06-30")       # 0 read as O
        self.assertEqual(self.expiry("Valid till l5-O3-2028"), "2028-03-15")  # 1 read as l
        self.assertEqual(self.expiry("Expiry: 15 / 03 / 2028"), "2028-03-15")  # extra spaces

    # ---------- choosing between several candidates ----------

    def test_two_expiry_dates_the_later_one_wins(self):
        self.assertEqual(self.expiry("Valid until 01/01/2027\nExpires on 01/01/2029"), "2029-01-01")

    def test_result_carries_the_label_and_score(self):
        found = find_expiry("Policy No: 12\nValid until: 15/03/2028")
        self.assertEqual(found.date.isoformat(), "2028-03-15")
        self.assertEqual(found.label.lower(), "valid until:")
        self.assertGreaterEqual(found.score, MIN_SCORE)


TODAY = date(2026, 11, 3)


class AnalyseTests(unittest.TestCase):
    """analyse(): what kind of result the text gives, and which dates are offered."""

    def kind(self, text):
        return analyse(text, TODAY).kind

    def selectable(self, text):
        return [c.date.isoformat() for c in analyse(text, TODAY).candidates if c.selectable]

    # ---------- short texts: a few words can still hold a readable expiry date ----------

    def test_short_texts_with_an_expiry_date_are_never_unreadable(self):
        cases = {
            "EXP 10/2028": ("one", "2028-10-31"),                 # last day of the month
            "VALID THRU 05/27": ("one", "2027-05-31"),            # MM/YY as printed on cards
            "Expiry Date: 10-Feb-2029": ("one", "2029-02-10"),
            "Expires 2028": ("flagged", "2028-12-31"),            # only a year: needs a deliberate choice
        }
        for text, (kind, expected) in cases.items():
            with self.subTest(text=text):
                result = analyse(text, TODAY)
                self.assertNotEqual(result.kind, "unreadable")
                self.assertEqual(result.kind, kind)
                self.assertEqual(self.selectable(text), [expected])
                self.assertTrue(has_expiry_date(text))

    def test_partial_dates_say_what_was_assumed(self):
        month = analyse("EXP 10/2028", TODAY).candidates[0]
        self.assertEqual((month.notes, month.flags), (["month_only"], []))
        year = analyse("Expires 2028", TODAY).candidates[0]
        self.assertEqual(year.flags, ["year_only"])
        self.assertTrue(year.needs_override)

    def test_partial_dates_are_only_believed_right_after_an_expiry_word(self):
        for text in ["Ref 10/2028", "Date 05/27", "Total 2028", "Policy 2028 renewal", "Phone 98/27"]:
            with self.subTest(text=text):
                self.assertEqual(self.selectable(text), [])
        # broken full dates must not be read as month/year or a bare year
        for text in ["Valid Thru; 06/07 2029", "Exp: 0907, 2028", "Valid Upto 14 Noy 2026"]:
            with self.subTest(text=text):
                self.assertEqual(self.selectable(text), [])
                self.assertEqual(self.kind(text), "uninterpretable")

    def test_the_three_word_rule_only_applies_when_nothing_else_is_there(self):
        self.assertEqual(self.kind("Name\n\n1D No"), "unreadable")
        self.assertEqual(self.kind("abc def"), "unreadable")
        self.assertEqual(self.kind("abc def ghi"), "no_date")          # exactly three words
        self.assertEqual(self.kind("EXP"), "uninterpretable")          # one word, but an expiry word
        self.assertEqual(self.kind("10/12/2020"), "no_date")           # one date and no words

    # ---------- the four kinds of "no usable date" ----------

    def test_unreadable_text(self):
        for text in ["", "   \n\n ", "~~ |", "Name\n\n1D No"]:
            with self.subTest(text=text):
                result = analyse(text, TODAY)
                self.assertEqual((result.kind, result.candidates), ("unreadable", []))

    def test_readable_text_with_no_expiry_date(self):
        result = analyse("Certificate of Achievement\nAwarded to Asha Rao\nGrade A", TODAY)
        self.assertEqual((result.kind, result.candidates, result.wording), ("no_date", [], []))

    def test_a_birth_date_alone_is_listed_but_is_not_an_expiry_date(self):
        result = analyse("Name: Asha Rao\nDate of Birth: 30/03/2003", TODAY)
        self.assertEqual(result.kind, "no_date")
        self.assertEqual([(o.role, o.date.isoformat()) for o in result.others], [("birth", "2003-03-30")])

    def test_expiry_wording_without_a_usable_date(self):
        for text in ["Valid until further notice", "Expiry: 22/02! 2028", "Valid until: 31/02/2026"]:
            with self.subTest(text=text):
                result = analyse(text, TODAY)
                self.assertEqual(result.kind, "uninterpretable")
                self.assertTrue(result.wording)           # the line is kept so it can be shown

    # ---------- several candidates ----------

    def test_two_conflicting_expiry_dates_give_no_winner(self):
        result = analyse("Valid until 01/01/2027\nExpires on 01/01/2029", TODAY)
        self.assertEqual(result.kind, "several")
        self.assertEqual(sorted(c.date.isoformat() for c in result.candidates), ["2027-01-01", "2029-01-01"])
        self.assertTrue(all(c.selectable and not c.flags for c in result.candidates))

    def test_a_clearly_stronger_label_wins_over_a_weaker_one(self):
        result = analyse("Validity 01/01/2027\nExpires on 01/01/2029", TODAY)
        self.assertEqual(result.kind, "one")
        self.assertEqual(result.candidates[0].date.isoformat(), "2029-01-01")

    def test_a_label_only_slightly_stronger_is_not_a_clear_winner(self):
        # 4 points against 3 points (the end of a range): too close to choose for the user
        text = "Expiry: 01/01/2029\nPolicy Period 02/12/2025 to 01/12/2026"
        result = analyse(text, TODAY)
        self.assertEqual(result.kind, "several")
        self.assertEqual(sorted(self.selectable(text)), ["2026-12-01", "2029-01-01"])

    def test_issue_date_and_expiry_date_only_the_expiry_date_is_selectable(self):
        result = analyse("Date of Issue: 01/01/2020\nExpiry: 01/01/2030", TODAY)
        self.assertEqual(result.kind, "one")
        self.assertEqual(self.selectable("Date of Issue: 01/01/2020\nExpiry: 01/01/2030"), ["2030-01-01"])
        self.assertEqual([(o.role, o.date.isoformat()) for o in result.others], [("issue", "2020-01-01")])
        self.assertFalse(any(c.date.isoformat() == "2020-01-01" for c in result.candidates))

    def test_the_other_kinds_of_dates_are_named(self):
        text = ("Date of Birth: 01/02/1990\nPurchased on 03/04/2025\nMember Since: 05/06/2024\n"
                "Printed on 07/08/2025\nExpiry: 01/01/2031")
        roles = {o.role for o in analyse(text, TODAY).others}
        self.assertEqual(roles, {"birth", "purchase", "start", "printed"})

    def test_the_same_expiry_date_printed_several_times_is_one_candidate(self):
        text = "Valid until 15/03/2028\nPolicy Expiry Date: 15/03/2028\nExp 15 Mar 2028"
        result = analyse(text, TODAY)
        self.assertEqual((result.kind, len(result.candidates)), ("one", 1))

    def test_a_date_range_gives_its_end_date_and_lists_the_start(self):
        for text in ["Policy Period: 02/12/2025 to 01/12/2026", "From 02/12/2025 To 01/12/2026",
                     "Valid: 02/12/2025 - 01/12/2026", "Valid from 02/12/2025 till 01/12/2026"]:
            with self.subTest(text=text):
                result = analyse(text, TODAY)
                self.assertEqual((result.kind, self.selectable(text)), ("one", ["2026-12-01"]))
                self.assertEqual([(o.role, o.date.isoformat()) for o in result.others], [("start", "2025-12-02")])

    def test_each_candidate_carries_its_label_and_line(self):
        c = analyse("Policy No: 12\nPolicy Expiry Date: 15/03/2028 (renewal due)", TODAY).candidates[0]
        self.assertEqual((c.raw, c.label.lower()), ("15/03/2028", "policy expiry date:"))
        self.assertEqual(c.context, "Policy Expiry Date: 15/03/2028 (renewal due)")

    # ---------- suspicious dates ----------

    def test_a_far_future_date_is_flagged_but_can_be_chosen(self):
        result = analyse("Valid until: 15/03/2099", TODAY)      # 2029 misread as 2099
        c = result.candidates[0]
        self.assertEqual((result.kind, c.flags), ("flagged", ["far_future"]))
        self.assertTrue(c.selectable and c.needs_override)

    def test_the_far_future_limit_is_30_years(self):
        edge = TODAY + timedelta(days=FAR_FUTURE_DAYS)
        for when, flagged in ((edge, False), (edge + timedelta(days=1), True)):
            with self.subTest(when=when):
                result = analyse(f"Valid until {when.strftime('%d/%m/%Y')}", TODAY)
                self.assertEqual(bool(result.candidates[0].flags), flagged)
                self.assertEqual(result.kind, "flagged" if flagged else "one")

    def test_an_expiry_before_the_issue_date_is_flagged_but_can_be_chosen(self):
        for anchor in ["Date of Issue: 14/08/2027", "Date of Birth: 14/08/2027", "Purchased on 14/08/2027",
                       "Effective date: 14/08/2027"]:
            with self.subTest(anchor=anchor):
                result = analyse(f"{anchor}\nValid until: 14/08/2024", TODAY)
                c = result.candidates[0]
                self.assertEqual((result.kind, c.flags), ("flagged", ["before_issue"]))
                self.assertTrue(c.selectable and c.needs_override)

    def test_the_expiry_is_compared_with_the_latest_of_the_earlier_dates(self):
        # after the birth date, but before the issue date: still wrong
        text = "Date of Birth: 01/01/1985\nDate of Issue: 01/01/2020\nValid until: 01/01/2018"
        self.assertEqual(analyse(text, TODAY).candidates[0].flags, ["before_issue"])

    def test_an_expiry_after_the_issue_date_is_not_flagged(self):
        self.assertEqual(self.kind("Date of Issue: 14/08/2024\nValid until: 14/08/2027"), "one")

    def test_an_expiry_in_the_past_is_not_suspicious(self):
        self.assertEqual(self.kind("Valid until: 01/01/2020"), "one")

    def test_a_genuinely_invalid_date_is_listed_but_cannot_be_selected(self):
        for text, flag in [("Valid until 31/02/2026", "not_a_date"), ("Expiry: 15/13/2026", "not_a_date"),
                           ("Valid until 15/03/1979", "implausible_year"), ("Valid until 15/03/2150", "implausible_year")]:
            with self.subTest(text=text):
                result = analyse(text, TODAY)
                self.assertEqual(result.kind, "uninterpretable")
                c = result.candidates[0]
                self.assertEqual(c.flags, [flag])
                self.assertFalse(c.selectable)
                self.assertFalse(has_expiry_date(text))
        self.assertEqual(analyse("Valid until 31/02/2026", TODAY).candidates[0].raw, "31/02/2026")

    def test_a_valid_date_next_to_an_invalid_one_is_still_offered(self):
        result = analyse("Valid until 31/02/2026\nExpires on 01/01/2028", TODAY)
        self.assertEqual(self.selectable("Valid until 31/02/2026\nExpires on 01/01/2028"), ["2028-01-01"])
        self.assertEqual([c.raw for c in result.candidates if not c.selectable], ["31/02/2026"])

    def test_letters_read_as_digits_are_noted_but_do_not_block(self):
        c = analyse("Exp: 3O/O6/2O27", TODAY).candidates[0]
        self.assertEqual((c.date.isoformat(), c.flags, c.notes), ("2027-06-30", [], ["repaired"]))

    def test_nothing_that_looks_like_an_expiry_date_is_silently_dropped(self):
        text = "Valid until 31/02/2026\nExpires 15/03/2099\nExpiry: 01/01/2028\nValid until 15/03/2150"
        raws = {c.raw for c in analyse(text, TODAY).candidates}
        self.assertEqual(raws, {"31/02/2026", "15/03/2099", "01/01/2028", "15/03/2150"})

    # ---------- agreement with find_expiry, and storing ----------

    def test_a_single_clear_full_date_is_the_same_as_find_expiry(self):
        for text in ["Valid until: 15/03/2028", "Valid Thru:\n15.03.2028", "Policy Period: 2025-12-02 to 2026-12-01",
                     "Demo Care\nDate of Birth: 30 Aug 1985\nValid Thru: 11 May 2031\nSAMPLE",
                     "Expiry: 08.11.2026 Issued: 08.11.2025", "Exp: 3O/O6/2O27"]:
            with self.subTest(text=text):
                result = analyse(text, TODAY)
                self.assertEqual(result.kind, "one")
                self.assertEqual(result.candidates[0].date, find_expiry(text).date)

    def test_a_candidate_survives_being_stored_and_read_back(self):
        for text in ["Valid until: 15/03/2099", "Valid until 31/02/2026", "EXP 10/2028"]:
            c = analyse(text, TODAY).candidates[0]
            self.assertEqual(Candidate.from_dict(c.to_dict()), c)


if __name__ == "__main__":
    unittest.main(verbosity=2)
