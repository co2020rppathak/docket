"""Tests for status.py. No database, no images.

Run:  python -m unittest test_status -v
"""
import unittest
from datetime import date, timedelta

from status import SOON_DAYS, expiry_status

TODAY = date(2026, 11, 2)


class ExpiryStatusTests(unittest.TestCase):
    def status(self, days_from_today):
        return expiry_status(TODAY + timedelta(days=days_from_today), TODAY)

    def test_the_30_day_rule_at_every_boundary(self):
        # days from today -> (state, words shown)
        expected = {
            31: ("valid", "Valid"),
            30: ("soon", "Expires in 30 days"),
            29: ("soon", "Expires in 29 days"),
            1: ("soon", "Expires in 1 day"),
            0: ("soon", "Expires today"),
            -1: ("expired", "Expired 1 day ago"),
            -5: ("expired", "Expired 5 days ago"),
            -30: ("expired", "Expired 30 days ago"),
        }
        for offset, (key, label) in expected.items():
            with self.subTest(days_from_today=offset):
                result = self.status(offset)
                self.assertEqual((result.key, result.label, result.days), (key, label, offset))

    def test_a_document_expiring_today_is_soon_and_never_expired(self):
        self.assertEqual(self.status(0).key, "soon")
        self.assertNotEqual(self.status(0).key, "expired")

    def test_the_time_of_day_never_matters(self):
        # only dates are compared, so the status cannot change during the day
        from datetime import datetime
        morning = expiry_status(TODAY, datetime(2026, 11, 2, 0, 0, 1).date())
        night = expiry_status(TODAY, datetime(2026, 11, 2, 23, 59, 59).date())
        self.assertEqual(morning, night)

    def test_no_date(self):
        result = expiry_status(None, TODAY)
        self.assertEqual((result.key, result.days), ("none", None))

    def test_expired_yesterday(self):
        result = self.status(-1)
        self.assertEqual((result.key, result.label), ("expired", "Expired 1 day ago"))

    def test_expired_long_ago(self):
        result = self.status(-400)
        self.assertEqual((result.key, result.label), ("expired", "Expired 400 days ago"))

    def test_expires_today_is_not_expired_yet(self):
        result = self.status(0)
        self.assertEqual((result.key, result.label), ("soon", "Expires today"))

    def test_tomorrow(self):
        self.assertEqual(self.status(1).label, "Expires in 1 day")

    def test_last_day_of_soon(self):
        result = self.status(SOON_DAYS)
        self.assertEqual((result.key, result.label), ("soon", "Expires in 30 days"))

    def test_first_day_of_valid(self):
        result = self.status(SOON_DAYS + 1)
        self.assertEqual((result.key, result.label), ("valid", "Valid"))

    def test_far_future(self):
        self.assertEqual(self.status(3650).key, "valid")

    def test_days_count_over_a_leap_day(self):
        # 2028 is a leap year: 28 Feb -> 1 Mar is 2 days
        result = expiry_status(date(2028, 3, 1), date(2028, 2, 28))
        self.assertEqual(result.label, "Expires in 2 days")

    def test_today_defaults_to_the_real_date(self):
        self.assertEqual(expiry_status(date.today()).key, "soon")
        self.assertEqual(expiry_status(date.today() - timedelta(days=1)).key, "expired")


if __name__ == "__main__":
    unittest.main(verbosity=2)
