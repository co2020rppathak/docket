"""Tests for the category guesser (categorize.py). No images, no OCR.

Run:  python -m unittest test_categorize -v
"""
import unittest

from categorize import MIN_LEAD, MIN_SCORE, guess_category, score_categories


class GuessCategoryTests(unittest.TestCase):
    def category(self, text):
        guess = guess_category(text)
        return guess.category if guess else None

    def test_insurance_policy(self):
        text = "Example General Insurance\nPOLICY SCHEDULE\nPolicyholder: Asha\nSum Insured: Rs. 5,00,000\nPremium Paid: Rs. 9,000"
        self.assertEqual(self.category(text), "Insurance")

    def test_warranty_card(self):
        text = "Acme Electronics\nWARRANTY CARD\nProduct: Laptop\nModel No: LP-120\nSerial No: SN123\nDate of Purchase: 01/01/2025"
        self.assertEqual(self.category(text), "Warranty")

    def test_course_certificate(self):
        text = "Institute of Technology\nCERTIFICATE OF COMPLETION\nThis is to certify that Asha has successfully completed the course\nGrade: A"
        self.assertEqual(self.category(text), "Certificate")

    def test_id_card(self):
        self.assertEqual(self.category("STUDENT ID CARD\nName: Asha\nID No: SMP-2024-1234\nDepartment: Library\nDate of Birth: 01/01/2003"), "ID Proof")

    def test_government_id_words(self):
        self.assertEqual(self.category("Passport No: A1234567 Identity document"), "ID Proof")

    def test_health_card(self):
        text = "Sample Health Plan\nHEALTH INSURANCE CARD\nMember ID: HLT-123456\nPlan: Family Floater"
        self.assertEqual(self.category(text), "Medical")

    def test_medical_report(self):
        self.assertEqual(self.category("City Hospital\nPatient: Asha\nDiagnosis: fever\nPrescription attached"), "Medical")

    def test_membership_is_other(self):
        text = "Demo Fitness Club\nMEMBERSHIP CERTIFICATE\nMember: Asha\nMember Since: 01/01/2024"
        self.assertEqual(self.category(text), "Other")

    # ---- documents whose title uses another category's word ----

    def test_certificate_of_insurance_is_insurance(self):
        self.assertEqual(self.category("CERTIFICATE OF INSURANCE\nPolicy No: 123\nSum Insured: 5,00,000"), "Insurance")

    def test_warranty_certificate_is_warranty(self):
        self.assertEqual(self.category("PRODUCT WARRANTY CERTIFICATE\nModel No: AC-1\nSerial No: 77\nDealer: Mart"), "Warranty")

    def test_member_id_card_is_id_proof(self):
        self.assertEqual(self.category("MEMBER ID CARD\nID No: 123\nDepartment: Accounts"), "ID Proof")

    # ---- when it must say "not sure" ----

    def test_nothing_useful(self):
        for text in ["", "   ", None, "Hello world", "Thank you for your order", "12/05/2026 Total 400"]:
            with self.subTest(text=text):
                self.assertIsNone(guess_category(text))

    def test_one_weak_word_is_not_enough(self):
        self.assertLess(score_categories("date of birth")["ID Proof"][0], MIN_SCORE)
        self.assertIsNone(guess_category("Date of Birth: 01/01/2003"))

    def test_a_clear_but_weak_signal_is_not_enough(self):
        # "ID No" scores 3 and nothing else matches: far ahead of the rest, but below MIN_SCORE
        self.assertEqual(score_categories("ID No: 5")["ID Proof"][0], 3)
        self.assertIsNone(guess_category("ID No: 5"))

    def test_two_close_categories_give_no_answer(self):
        # "warranty" (Warranty, 5) against "insurance" and "policy" (Insurance, 6): too close to call
        text = "extended warranty insurance policy"
        scores = score_categories(text)
        self.assertLess(abs(scores["Warranty"][0] - scores["Insurance"][0]), MIN_LEAD)
        self.assertIsNone(guess_category(text))

    # ---- details ----

    def test_capital_letters_do_not_matter(self):
        self.assertEqual(self.category("WARRANTY CARD SERIAL NO 5 MODEL NO 6"), "Warranty")

    def test_a_word_counts_once_however_often_it_appears(self):
        once = score_categories("warranty")["Warranty"][0]
        many = score_categories("warranty " * 50)["Warranty"][0]
        self.assertEqual(once, many)

    def test_words_are_not_matched_inside_other_words(self):
        self.assertEqual(score_categories("subpolicyx")["Insurance"][0], 0)
        self.assertEqual(score_categories("badge")["Certificate"][0], 0)

    def test_result_lists_the_words_that_decided_it(self):
        guess = guess_category("Policy No 5\nSum Insured 3\nInsurance Co")
        self.assertEqual(guess.category, "Insurance")
        self.assertIn("policy", guess.words)
        self.assertGreaterEqual(guess.score, MIN_SCORE)

    def test_every_category_is_one_the_app_offers(self):
        from categorize import RULES
        self.assertEqual(set(RULES), {"ID Proof", "Insurance", "Warranty", "Certificate", "Medical", "Other"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
