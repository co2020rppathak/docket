"""Tests for the web application. They use a temporary database and upload folder,
so your real vault.db and uploads/ are never touched.

Run:  python -m unittest test_app -v
"""
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

# The app reads these two settings when it is imported, so they are set first
TEMP = tempfile.mkdtemp(prefix="idms_test_")
DB_FILE = os.path.join(TEMP, "test.db").replace("\\", "/")
os.environ["IDMS_DATABASE_URI"] = "sqlite:///" + DB_FILE
os.environ["IDMS_UPLOAD_FOLDER"] = os.path.join(TEMP, "uploads")
os.makedirs(os.environ["IDMS_UPLOAD_FOLDER"], exist_ok=True)

import pytesseract                       # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import app as appmod                     # noqa: E402
from app import app                      # noqa: E402
from models import Document, db         # noqa: E402
from ocr import tesseract_version        # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TODAY = date(2026, 11, 2)


def picture(lines=None):
    """A PNG as bytes; with `lines` the text is drawn on it so that real OCR can read it."""
    image = Image.new("RGB", (1700, 420), "white")
    if lines:
        draw = ImageDraw.Draw(image)
        for number, line in enumerate(lines):
            draw.text((40, 40 + number * 77), line, fill="black", font=ImageFont.load_default(size=48))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class AppTestCase(unittest.TestCase):
    counter = 0

    def setUp(self):
        AppTestCase.counter += 1
        self.username = f"user{AppTestCase.counter}"
        self.client = self.new_user(self.username)

    def new_user(self, name):
        client = app.test_client()
        client.post("/register", data={"username": name, "email": f"{name}@example.com", "password": "secret1"})
        client.post("/login", data={"username": name, "password": "secret1"})
        return client

    def upload(self, text, expiry="", category="Other", title="Doc", client=None):
        """Upload a picture whose OCR text is replaced by `text`. Returns the new document's id."""
        with mock.patch.object(appmod, "extract_text", return_value=text):
            (client or self.client).post(
                "/upload",
                data={"title": title, "category": category, "expiry_date": expiry,
                      "file": (io.BytesIO(picture()), "scan.png")},
                content_type="multipart/form-data",
            )
        with app.app_context():
            return Document.query.order_by(Document.id.desc()).first().id

    def recheck(self, doc_id, text, client=None):
        with mock.patch.object(appmod, "extract_text", return_value=text):
            return (client or self.client).post(f"/document/{doc_id}/expiry/recheck", follow_redirects=True)

    def expiry_action(self, doc_id, client=None, **form):
        return (client or self.client).post(f"/document/{doc_id}/expiry", data=form, follow_redirects=True)

    def fields(self, doc_id):
        with app.app_context():
            doc = db.session.get(Document, doc_id)
            # The date waiting for the user's choice (the first one, if several wait)
            waiting = [c for c in (doc.review or {}).get("candidates", []) if c.get("date")]
            return {
                "expiry": doc.expiry_date, "source": doc.expiry_source,
                "suggested": date.fromisoformat(waiting[0]["date"]) if waiting else None,
                "label": waiting[0]["label"] if waiting else None,
                "text": doc.extracted_text, "category": doc.category,
            }

    def page(self, doc_id, client=None):
        return (client or self.client).get(f"/document/{doc_id}").get_data(as_text=True)


class RecheckTests(AppTestCase):
    def test_a_different_date_is_shown_separately_and_the_saved_date_is_kept(self):
        doc = self.upload("Valid until 31/12/2030", expiry="2029-01-15")
        response = self.recheck(doc, "Policy\nValid until 31/12/2030")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2029, 1, 15), "user"))
        self.assertEqual(fields["suggested"], date(2030, 12, 31))
        page = response.get_data(as_text=True)
        self.assertIn("Your saved date has not been changed", page)
        self.assertIn("31 Dec 2030", page)
        self.assertIn("15 Jan 2029", page)
        self.assertIn("Use this date", page)
        self.assertIn("Keep my date", page)
        self.assertIn("Valid until", page)  # the words it was found next to

    def test_the_recheck_never_changes_the_text_category_or_source(self):
        doc = self.upload("old text", expiry="2029-01-15", category="Warranty")
        before = self.fields(doc)
        self.recheck(doc, "Valid until 31/12/2030")
        after = self.fields(doc)
        for name in ("expiry", "source", "text", "category"):
            self.assertEqual(before[name], after[name], name)

    def test_same_date_means_no_suggestion(self):
        doc = self.upload("x", expiry="2030-12-31")
        response = self.recheck(doc, "Valid until 31/12/2030")
        self.assertIsNone(self.fields(doc)["suggested"])
        self.assertIn("Your date matches", response.get_data(as_text=True))

    def test_nothing_found_clears_an_old_suggestion_and_says_so(self):
        doc = self.upload("x", expiry="2029-01-15")
        self.recheck(doc, "Valid until 31/12/2030")
        self.assertIsNotNone(self.fields(doc)["suggested"])
        response = self.recheck(doc, "Policy holder only, no dates")
        self.assertIsNone(self.fields(doc)["suggested"])
        self.assertIn("No expiry date was found", response.get_data(as_text=True))
        self.assertEqual(self.fields(doc)["expiry"], date(2029, 1, 15))

    def test_unreadable_image_is_reported_differently_from_no_date(self):
        doc = self.upload("x", expiry="2029-01-15")
        response = self.recheck(doc, "")
        self.assertIn("no text could be read", response.get_data(as_text=True))

    def test_a_failed_reading_changes_nothing(self):
        doc = self.upload("x", expiry="2029-01-15")
        self.recheck(doc, "Valid until 31/12/2030")
        before = self.fields(doc)
        for error in (pytesseract.TesseractNotFoundError(), RuntimeError("boom")):
            with mock.patch("pytesseract.image_to_string", side_effect=error), \
                    mock.patch.object(app.logger, "exception"):
                self.client.post(f"/document/{doc}/expiry/recheck")
            self.assertEqual(self.fields(doc), before)

    def test_an_unconfirmed_detected_date_is_not_replaced_either(self):
        doc = self.upload("Valid until 01/02/2030")
        self.assertEqual(self.fields(doc)["source"], "detected")
        self.recheck(doc, "Valid until 09/10/2031")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["suggested"]), (date(2030, 2, 1), date(2031, 10, 9)))

    def test_a_document_with_no_date_can_get_a_suggestion(self):
        doc = self.upload("nothing here")
        response = self.recheck(doc, "Valid until 31/12/2030")
        self.assertEqual(self.fields(doc)["suggested"], date(2030, 12, 31))
        page = response.get_data(as_text=True)
        self.assertIn("No expiry date is saved", page)
        self.assertIn("Ignore it", page)
        self.expiry_action(doc, action="use_suggested")
        self.assertEqual((self.fields(doc)["expiry"], self.fields(doc)["source"]), (date(2030, 12, 31), "user"))


class AcceptOrKeepTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.doc = self.upload("x", expiry="2029-01-15")
        self.recheck(self.doc, "Valid until 31/12/2030")

    def test_use_this_date_saves_it_as_the_users_date(self):
        response = self.expiry_action(self.doc, action="use_suggested")
        fields = self.fields(self.doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2030, 12, 31), "user"))
        self.assertIsNone(fields["suggested"])
        self.assertIn("Expiry date updated", response.get_data(as_text=True))
        self.assertNotIn("Found when the document was checked again", response.get_data(as_text=True))

    def test_keep_my_date_discards_the_suggestion_only(self):
        self.expiry_action(self.doc, action="keep")
        fields = self.fields(self.doc)
        self.assertEqual((fields["expiry"], fields["source"], fields["suggested"]), (date(2029, 1, 15), "user", None))

    def test_typing_the_suggested_date_by_hand_clears_the_suggestion(self):
        self.expiry_action(self.doc, action="save", expiry_date="2030-12-31")
        self.assertIsNone(self.fields(self.doc)["suggested"])

    def test_typing_another_date_keeps_the_suggestion_visible(self):
        self.expiry_action(self.doc, action="save", expiry_date="2032-02-02")
        fields = self.fields(self.doc)
        self.assertEqual((fields["expiry"], fields["suggested"]), (date(2032, 2, 2), date(2030, 12, 31)))

    def test_use_this_date_without_a_suggestion_is_refused(self):
        self.expiry_action(self.doc, action="keep")
        response = self.client.post(f"/document/{self.doc}/expiry", data={"action": "use_suggested"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.fields(self.doc)["expiry"], date(2029, 1, 15))


class StatusAfterCorrectionTests(AppTestCase):
    """The status is worked out from the saved date every time a page is shown."""

    def dashboard(self, query=""):
        with mock.patch.object(appmod, "today", return_value=TODAY):
            return self.client.get("/dashboard" + query).get_data(as_text=True)

    def document(self, doc):
        with mock.patch.object(appmod, "today", return_value=TODAY):
            return self.page(doc)

    def test_correcting_a_date_moves_the_document_in_and_out_of_needs_attention(self):
        doc = self.upload("x", expiry=(TODAY + timedelta(days=200)).isoformat(), title="Moving doc")
        self.assertNotIn("Moving doc", self.dashboard("?show=attention"))

        self.recheck(doc, f"Valid until {(TODAY + timedelta(days=30)).strftime('%d/%m/%Y')}")
        self.expiry_action(doc, action="use_suggested")
        self.assertIn("Expires in 30 days", self.document(doc))
        self.assertIn("Moving doc", self.dashboard("?show=attention"))

        self.expiry_action(doc, action="save", expiry_date=(TODAY + timedelta(days=31)).isoformat())
        self.assertNotIn("Moving doc", self.dashboard("?show=attention"))
        self.assertIn("Valid", self.document(doc))


def offset_date(days):
    """The date `days` away from the fixed test day (negative = in the past)."""
    return (TODAY + timedelta(days=days)).isoformat()


def parse_dashboard(html):
    """Read a dashboard page. Returns (numbers, rows).

    numbers: the four figures of the count strip {"total", "expired", "soon", "unchecked"}
    rows: the table, as a list of (title, badge colour, badge words); a document with no date has None for both
    """
    figures = [int(n) for n in re.findall(r'<div class="stat[^"]*"><b>(\d+)</b>', html)]
    numbers = dict(zip(("total", "expired", "soon", "unchecked"), figures))
    rows = []
    for part in re.split(r"<tr(?: [^>]*)?>", html)[2:]:   # the first one is before the table, the second is the header
        title = re.search(r"<td>(.*?)</td>", part, re.S).group(1)
        badge = re.search(r'class="status (\w+)">(.*?)</span>', part, re.S)
        rows.append((title, badge.group(1) if badge else None, badge.group(2) if badge else None))
    return numbers, rows


class NeedsAttentionTests(AppTestCase):
    """The 30-day rule, as seen on the dashboard."""

    BOUNDARIES = [31, 30, 29, 1, 0, -1, -5, -30]
    LABELS = {31: "Valid", 30: "Expires in 30 days", 29: "Expires in 29 days", 1: "Expires in 1 day",
              0: "Expires today", -1: "Expired 1 day ago", -5: "Expired 5 days ago", -30: "Expired 30 days ago"}
    NEEDS_ATTENTION = {30, 29, 1, 0, -1, -5, -30}

    def setUp(self):
        super().setUp()
        self.docs = {days: self.upload("x", expiry=offset_date(days), title=f"doc {days:+d}") for days in self.BOUNDARIES}
        self.no_date = self.upload("nothing", title="doc no date")
        self.far = self.upload("x", expiry=offset_date(400), title="doc far away")

    def dashboard(self, query="", client=None):
        with mock.patch.object(appmod, "today", return_value=TODAY):
            return (client or self.client).get("/dashboard" + query).get_data(as_text=True)

    def test_every_boundary_gets_the_right_badge_on_the_dashboard(self):
        _, rows = parse_dashboard(self.dashboard())
        by_title = {title: (colour, words) for title, colour, words in rows}
        for days in self.BOUNDARIES:
            colour, words = by_title[f"doc {days:+d}"]
            self.assertEqual(words, self.LABELS[days], days)
            self.assertEqual(colour, "expired" if days < 0 else "valid" if days > 30 else "soon", days)

    def test_documents_in_the_window_are_listed_and_the_others_are_not(self):
        _, rows = parse_dashboard(self.dashboard("?show=attention"))
        titles = {title for title, _, _ in rows}
        self.assertEqual(titles, {f"doc {days:+d}" for days in self.NEEDS_ATTENTION})
        self.assertNotIn("doc +31", titles)
        self.assertNotIn("doc no date", titles)
        self.assertNotIn("doc far away", titles)

    def test_the_attention_list_starts_with_the_most_overdue(self):
        _, rows = parse_dashboard(self.dashboard("?show=attention"))
        self.assertEqual([title for title, _, _ in rows],
                         ["doc -30", "doc -5", "doc -1", "doc +0", "doc +1", "doc +29", "doc +30"])

    def test_expired_documents_stay_in_the_full_list_with_their_overdue_days(self):
        _, rows = parse_dashboard(self.dashboard())
        shown = {title: words for title, _, words in rows}
        self.assertEqual(shown["doc -1"], "Expired 1 day ago")
        self.assertEqual(shown["doc -5"], "Expired 5 days ago")
        self.assertEqual(shown["doc -30"], "Expired 30 days ago")

    def test_upcoming_and_expired_look_different(self):
        _, rows = parse_dashboard(self.dashboard())
        colour = {title: c for title, c, _ in rows}
        self.assertEqual({colour["doc -1"], colour["doc -5"], colour["doc -30"]}, {"expired"})
        self.assertEqual({colour["doc +0"], colour["doc +1"], colour["doc +29"], colour["doc +30"]}, {"soon"})
        self.assertEqual(colour["doc +31"], "valid")
        self.assertIsNone(colour["doc no date"])

    def test_the_counts_agree_with_the_documents_shown(self):
        numbers, rows = parse_dashboard(self.dashboard())
        self.assertEqual(numbers["total"], len(rows))
        self.assertEqual(numbers["expired"], sum(1 for _, colour, _ in rows if colour == "expired"))
        self.assertEqual(numbers["soon"], sum(1 for _, colour, _ in rows if colour == "soon"))
        self.assertEqual((numbers["total"], numbers["expired"], numbers["soon"]), (10, 3, 4))

        html = self.dashboard("?show=attention")
        _, attention_rows = parse_dashboard(html)
        self.assertEqual(len(attention_rows), numbers["expired"] + numbers["soon"])
        self.assertIn(f"Needs attention ({numbers['expired'] + numbers['soon']})", html)
        self.assertIn("3 expired, 4 expiring within 30 days", re.sub(r"\s+", " ", html).replace(" ,", ","))

    def test_a_vault_with_nothing_urgent_says_so(self):
        quiet = self.new_user("quiet")
        self.upload("x", expiry=offset_date(31), title="doc safe", client=quiet)
        html = self.dashboard("?show=attention", client=quiet)
        self.assertIn("Nothing needs attention", html)
        self.assertNotIn('class="attention"', html)
        self.assertEqual(parse_dashboard(html)[0]["expired"] + parse_dashboard(html)[0]["soon"], 0)

    def test_the_real_clock_is_used_when_nothing_is_faked(self):
        # a separate user, so that no other document can add a matching badge to the page
        alone = self.new_user("real_clock_user")
        real_today = date.today()
        self.upload("x", expiry=(real_today + timedelta(days=30)).isoformat(), title="doc real clock", client=alone)
        self.upload("x", expiry=(real_today + timedelta(days=31)).isoformat(), title="doc real clock 31", client=alone)
        _, rows = parse_dashboard(alone.get("/dashboard").get_data(as_text=True))
        shown = {title: (colour, words) for title, colour, words in rows}
        self.assertEqual(shown["doc real clock"], ("soon", "Expires in 30 days"))
        self.assertEqual(shown["doc real clock 31"], ("valid", "Valid"))

    def test_the_status_is_computed_never_stored(self):
        with app.app_context():
            columns = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(document)"))]
        self.assertFalse([name for name in columns if "status" in name and name not in ("expiry_source", "category_source")])
        self.assertNotIn("days_left", columns)

    def test_the_same_document_is_overdue_by_more_days_as_time_passes(self):
        # the date is saved once; the number of days is worked out again each time the page is shown
        def overdue_label(today):
            with mock.patch.object(appmod, "today", return_value=today):
                return self.client.get(f"/document/{self.docs[-5]}").get_data(as_text=True)
        self.assertIn("Expired 5 days ago", overdue_label(TODAY))
        self.assertIn("Expired 6 days ago", overdue_label(TODAY + timedelta(days=1)))
        self.assertIn("Expired 35 days ago", overdue_label(TODAY + timedelta(days=30)))


class CorrectionMovesDocumentTests(AppTestCase):
    """Changing a date with the recheck feature moves the document in or out of Needs Attention."""

    def attention(self):
        with mock.patch.object(appmod, "today", return_value=TODAY):
            html = self.client.get("/dashboard?show=attention").get_data(as_text=True)
        numbers, rows = parse_dashboard(html)
        self.assertEqual(len(rows), numbers["expired"] + numbers["soon"])  # counts match the list every time
        return {title: words for title, _, words in rows}

    def correct_with_recheck(self, doc, new_days):
        """The document text says a different date than the saved one; the user accepts it."""
        new_date = TODAY + timedelta(days=new_days)
        self.recheck(doc, f"Valid until {new_date.strftime('%d/%m/%Y')}")
        self.expiry_action(doc, action="use_suggested")
        self.assertEqual(self.fields(doc)["expiry"], new_date)

    def start(self, days):
        return self.upload("x", expiry=offset_date(days), category="Warranty", title="doc moving")

    def test_31_days_away_to_10_days_away_enters_needs_attention(self):
        doc = self.start(31)
        self.assertNotIn("doc moving", self.attention())
        self.correct_with_recheck(doc, 10)
        self.assertEqual(self.attention()["doc moving"], "Expires in 10 days")

    def test_10_days_away_to_45_days_away_leaves_needs_attention(self):
        doc = self.start(10)
        self.assertIn("doc moving", self.attention())
        self.correct_with_recheck(doc, 45)
        self.assertNotIn("doc moving", self.attention())

    def test_an_expired_document_given_a_future_date_leaves_needs_attention(self):
        doc = self.start(-20)
        self.assertEqual(self.attention()["doc moving"], "Expired 20 days ago")
        self.correct_with_recheck(doc, 90)
        self.assertNotIn("doc moving", self.attention())

    def test_an_upcoming_document_given_a_past_date_becomes_expired(self):
        doc = self.start(10)
        self.correct_with_recheck(doc, -3)
        self.assertEqual(self.attention()["doc moving"], "Expired 3 days ago")

    def test_typing_the_correction_by_hand_works_the_same_way(self):
        doc = self.start(31)
        self.expiry_action(doc, action="save", expiry_date=offset_date(30))
        self.assertEqual(self.attention()["doc moving"], "Expires in 30 days")
        self.expiry_action(doc, action="save", expiry_date=offset_date(31))
        self.assertNotIn("doc moving", self.attention())
        self.expiry_action(doc, action="remove")
        self.assertNotIn("doc moving", self.attention())

    def test_corrections_never_change_the_category_or_the_users_ownership_of_the_date(self):
        doc = self.start(31)
        for days in (10, 45, -3, 20):
            self.correct_with_recheck(doc, days)
            fields = self.fields(doc)
            self.assertEqual((fields["category"], fields["source"]), ("Warranty", "user"))

    def test_the_result_is_the_same_after_navigating_away_and_back(self):
        doc = self.start(31)
        self.correct_with_recheck(doc, 10)
        first = self.attention()
        self.client.get("/upload")
        self.client.get(f"/document/{doc}")
        self.client.get("/logout")
        self.client.post("/login", data={"username": self.username, "password": "secret1"})
        self.assertEqual(self.attention(), first)

    def test_the_result_is_the_same_after_restarting_the_application(self):
        doc = self.start(31)
        self.correct_with_recheck(doc, 10)
        far = self.upload("x", expiry=offset_date(45), category="Medical", title="doc far")
        code = (
            "import json, re\nfrom datetime import date\nfrom unittest import mock\n"
            "import app as appmod\nfrom app import app\nfrom models import Document, db\n"
            "client = app.test_client()\n"
            f"client.post('/login', data={{'username': {self.username!r}, 'password': 'secret1'}})\n"
            "with mock.patch.object(appmod, 'today', return_value=date(2026, 11, 2)):\n"
            "    html = client.get('/dashboard?show=attention').get_data(as_text=True)\n"
            "titles = re.findall(r'<td>(doc [^<]*)</td>', html)\n"
            "with app.app_context():\n"
            f"    moved = db.session.get(Document, {doc})\n"
            f"    other = db.session.get(Document, {far})\n"
            "    kept = [str(moved.expiry_date), moved.expiry_source, moved.category, other.category]\n"
            "print(json.dumps([titles, kept]))\n"
        )
        titles, kept = RestartTests.run_fresh_process(self, code)
        self.assertEqual(titles, ["doc moving"])                  # "doc far" (45 days) is outside the window
        self.assertEqual(kept, [offset_date(10), "user", "Warranty", "Medical"])


class WorkingFeaturesStillWorkTests(AppTestCase):
    """A quick check that upload, text reading, categorization, expiry detection and rechecking work together."""

    def test_upload_reads_categorizes_and_finds_the_expiry_date(self):
        doc = self.upload("Example General Insurance\nPOLICY SCHEDULE\nPolicyholder: Asha\nSum Insured: 5,00,000\nValid until 31/12/2030",
                          category="auto")
        fields = self.fields(doc)
        self.assertEqual(fields["category"], "Insurance")
        self.assertEqual((fields["expiry"], fields["source"]), (date(2030, 12, 31), "detected"))
        self.assertIn("Policyholder", fields["text"])

    def test_a_typed_date_and_a_chosen_category_are_kept(self):
        doc = self.upload("Valid until 31/12/2030\nPolicy Sum Insured Insurance", expiry="2029-01-15", category="Warranty")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"], fields["category"]), (date(2029, 1, 15), "user", "Warranty"))
        self.recheck(doc, "Valid until 31/12/2030")
        self.assertEqual(self.fields(doc)["expiry"], date(2029, 1, 15))   # still the user's date

    @unittest.skipIf(tesseract_version() is None, "Tesseract is not installed")
    def test_upload_with_the_real_reader(self):
        self.client.post("/upload", data={"title": "Real upload", "category": "auto",
                                          "file": (io.BytesIO(picture(["Insurance policy number AB123456", "Valid until 31/12/2030"])), "p.png")},
                         content_type="multipart/form-data")
        with app.app_context():
            doc = Document.query.order_by(Document.id.desc()).first().id
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2030, 12, 31), "detected"))
        self.assertEqual(fields["category"], "Insurance")


class AccessTests(AppTestCase):
    def test_other_users_and_visitors_cannot_use_the_recheck(self):
        doc = self.upload("x", expiry="2029-01-15")
        other = self.new_user("someone_else")
        self.assertEqual(other.post(f"/document/{doc}/expiry/recheck").status_code, 404)
        self.assertEqual(other.post(f"/document/{doc}/expiry", data={"action": "keep"}).status_code, 404)
        visitor = app.test_client()
        response = visitor.post(f"/document/{doc}/expiry/recheck")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.assertEqual(self.client.get(f"/document/{doc}/expiry/recheck").status_code, 405)


@unittest.skipIf(tesseract_version() is None, "Tesseract is not installed")
class RealOcrTests(AppTestCase):
    def test_recheck_with_the_real_reader(self):
        # the picture really says 31/12/2030 and the user has saved a different date
        client = self.client
        client.post("/upload", data={"title": "Real", "category": "Other", "expiry_date": "2029-01-15",
                                     "file": (io.BytesIO(picture(["Insurance policy AB123456", "Valid until 31/12/2030"])), "p.png")},
                    content_type="multipart/form-data")
        with app.app_context():
            doc = Document.query.order_by(Document.id.desc()).first().id
        client.post(f"/document/{doc}/expiry/recheck")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["suggested"]), (date(2029, 1, 15), date(2030, 12, 31)))


class RestartTests(AppTestCase):
    """What the user saved must still be there when the application is started again."""

    def run_fresh_process(self, code, database=DB_FILE, uploads=None):
        env = dict(os.environ, IDMS_DATABASE_URI="sqlite:///" + database,
                   IDMS_UPLOAD_FOLDER=uploads or os.environ["IDMS_UPLOAD_FOLDER"])
        result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_DIR, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_corrections_and_suggestions_survive_a_restart(self):
        doc = self.upload("x", expiry="2029-01-15", category="Warranty")
        self.recheck(doc, "Valid until 31/12/2030")                       # a suggestion is stored
        self.expiry_action(doc, action="save", expiry_date="2032-02-02")  # then the user corrects the date
        code = (
            "import json\nfrom app import app\nfrom models import Document, db\n"
            f"with app.app_context():\n    d = db.session.get(Document, {doc})\n"
            "    waiting = [c for c in (d.review or {}).get('candidates', []) if c.get('date')]\n"
            "    print(json.dumps([str(d.expiry_date), d.expiry_source, waiting[0]['date'] if waiting else None, waiting[0]['label'] if waiting else None, d.category, d.category_source]))\n"
        )
        saved = self.run_fresh_process(code)
        self.assertEqual(saved[:3], ["2032-02-02", "user", "2030-12-31"])
        self.assertEqual(saved[3].lower(), "valid until")
        self.assertEqual(saved[4:], ["Warranty", "user"])

    def test_an_older_database_is_upgraded_and_keeps_its_data(self):
        old_db = os.path.join(tempfile.mkdtemp(dir=TEMP), "old.db").replace("\\", "/")
        con = sqlite3.connect(old_db)
        con.executescript(
            "CREATE TABLE user (id INTEGER NOT NULL, username VARCHAR(80) NOT NULL, email VARCHAR(120) NOT NULL,"
            " password_hash VARCHAR(256) NOT NULL, PRIMARY KEY (id));"
            "CREATE TABLE document (id INTEGER NOT NULL, title VARCHAR(150) NOT NULL, filename VARCHAR(200) NOT NULL,"
            " category VARCHAR(50), expiry_date DATE, expiry_source VARCHAR(10), category_source VARCHAR(10),"
            " extracted_text TEXT, uploaded_at DATETIME, user_id INTEGER NOT NULL, PRIMARY KEY (id));"
            "INSERT INTO user VALUES (1, 'old', 'old@example.com', 'x');"
            "INSERT INTO document (id, title, filename, category, expiry_date, expiry_source, category_source, user_id)"
            " VALUES (1, 'Old doc', 'a.png', 'Insurance', '2030-12-31', 'user', 'user', 1);"
        )
        con.commit()
        con.close()
        code = (
            "import json\nfrom app import app\nfrom models import Document, db\n"
            "with app.app_context():\n    d = db.session.get(Document, 1)\n"
            "    print(json.dumps([d.title, str(d.expiry_date), d.expiry_source, d.suggested_date, d.suggested_label]))\n"
        )
        self.assertEqual(self.run_fresh_process(code, database=old_db), ["Old doc", "2030-12-31", "user", None, None])


TWO_DATES = "Valid until 01/01/2027\nExpires on 01/01/2029"
ISSUE_AND_EXPIRY = "Date of Issue: 01/01/2020\nValid until 01/01/2030"


class ReviewTestCase(AppTestCase):
    def upload_page(self, text, client=None, **kw):
        """Upload and return (document id, the page the user lands on, with its messages)."""
        client = client or self.client
        with mock.patch.object(appmod, "extract_text", return_value=text):
            response = client.post(
                "/upload",
                data={"title": kw.pop("title", "Doc"), "category": kw.pop("category", "Other"),
                      "expiry_date": kw.pop("expiry", ""), "file": (io.BytesIO(picture()), "scan.png")},
                content_type="multipart/form-data", follow_redirects=True)
        with app.app_context():
            return Document.query.order_by(Document.id.desc()).first().id, response.get_data(as_text=True)

    def extract_again(self, doc_id, text):
        with mock.patch.object(appmod, "extract_text", return_value=text):
            return self.client.post(f"/document/{doc_id}/extract", follow_redirects=True).get_data(as_text=True)

    def review(self, doc_id):
        with app.app_context():
            return db.session.get(Document, doc_id).review

    def waiting(self, doc_id):
        """The dates waiting for a choice, as ISO strings (an impossible date shows as None)."""
        return [c["date"] for c in (self.review(doc_id) or {}).get("candidates", [])]

    def choose(self, doc_id, date_text, override=False, client=None):
        form = {"action": "use_candidate", "candidate": date_text}
        if override:
            form["override"] = "yes"
        return (client or self.client).post(f"/document/{doc_id}/expiry", data=form, follow_redirects=True)


class SeveralDatesTests(ReviewTestCase):
    def test_two_conflicting_dates_are_not_guessed(self):
        doc, landing = self.upload_page(TWO_DATES)
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (None, None))      # nothing was filled in
        self.assertEqual(sorted(self.waiting(doc)), ["2027-01-01", "2029-01-01"])
        self.assertIn("More than one possible expiry date was found", landing)
        page = self.page(doc)
        self.assertIn("1 Jan 2027", page)
        self.assertIn("1 Jan 2029", page)
        self.assertIn("Expires on", page)                                          # the words next to it
        self.assertEqual(page.count('name="candidate"'), 2)

    def test_choosing_a_candidate_saves_it_as_the_users_date_and_ends_the_review(self):
        doc, _ = self.upload_page(TWO_DATES)
        self.choose(doc, "2029-01-01")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2029, 1, 1), "user"))
        self.assertIsNone(self.review(doc))
        self.assertNotIn('name="candidate"', self.page(doc))

    def test_a_date_that_was_never_offered_cannot_be_chosen(self):
        doc, _ = self.upload_page(TWO_DATES)
        for wrong in ("2031-05-05", "", "not-a-date"):
            response = self.client.post(f"/document/{doc}/expiry", data={"action": "use_candidate", "candidate": wrong})
            self.assertEqual(response.status_code, 400, wrong)
        # with two to choose from, "the" suggestion is not defined either
        self.assertEqual(self.client.post(f"/document/{doc}/expiry", data={"action": "use_suggested"}).status_code, 400)
        self.assertIsNone(self.fields(doc)["expiry"])
        self.assertEqual(len(self.waiting(doc)), 2)

    def test_ignoring_the_dates_changes_nothing_else(self):
        doc, _ = self.upload_page(TWO_DATES, category="Warranty")
        self.expiry_action(doc, action="keep")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["category"]), (None, "Warranty"))
        self.assertIsNone(self.review(doc))

    def test_typing_one_of_the_dates_removes_only_that_one(self):
        doc, _ = self.upload_page(TWO_DATES)
        self.expiry_action(doc, action="save", expiry_date="2027-01-01")
        self.assertEqual(self.waiting(doc), ["2029-01-01"])
        self.expiry_action(doc, action="save", expiry_date="2029-01-01")
        self.assertIsNone(self.review(doc))

    def test_an_old_automatic_date_is_cleared_when_the_new_reading_is_ambiguous(self):
        doc, _ = self.upload_page("Valid until 01/02/2030")
        self.assertEqual(self.fields(doc)["source"], "detected")
        self.extract_again(doc, TWO_DATES)
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (None, None))      # the old date is no longer supported
        self.assertEqual(len(self.waiting(doc)), 2)

    def test_a_date_the_user_typed_is_never_touched_by_reading_the_text_again(self):
        doc, _ = self.upload_page(TWO_DATES, expiry="2028-06-06")
        self.extract_again(doc, TWO_DATES)
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2028, 6, 6), "user"))
        self.assertIsNone(self.review(doc))

    def test_the_same_date_printed_twice_is_filled_in_normally(self):
        doc, _ = self.upload_page("Valid until 15/03/2028\nPolicy Expiry Date: 15/03/2028")
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2028, 3, 15), "detected"))
        self.assertIsNone(self.review(doc))

    def test_a_date_range_fills_in_its_end_date(self):
        doc, _ = self.upload_page("Policy Period: From 02/12/2025 To 01/12/2026")
        self.assertEqual(self.fields(doc)["expiry"], date(2026, 12, 1))
        self.assertIsNone(self.review(doc))

    def test_other_people_cannot_choose_for_you(self):
        doc, _ = self.upload_page(TWO_DATES)
        other = self.new_user("someone_else_again")
        self.assertEqual(self.choose(doc, "2029-01-01", client=other).status_code, 404)
        self.assertIsNone(self.fields(doc)["expiry"])


class IssueDateTests(ReviewTestCase):
    def test_only_the_expiry_date_can_be_selected_not_the_issue_date(self):
        doc, _ = self.upload_page(ISSUE_AND_EXPIRY, expiry="2028-06-06")           # the user has their own date
        self.recheck(doc, ISSUE_AND_EXPIRY)
        page = self.page(doc)
        self.assertEqual(self.waiting(doc), ["2030-01-01"])
        self.assertEqual(page.count('name="candidate"'), 1)
        self.assertIn('value="2030-01-01"', page)
        self.assertNotIn('value="2020-01-01"', page)
        self.assertIn("Issue date 01 Jan 2020", page)                               # listed, but only for information
        self.assertEqual(self.choose(doc, "2020-01-01").status_code, 400)
        self.assertEqual(self.fields(doc)["expiry"], date(2028, 6, 6))
        self.choose(doc, "2030-01-01")
        self.assertEqual(self.fields(doc)["expiry"], date(2030, 1, 1))


class SuspiciousDateTests(ReviewTestCase):
    def test_a_far_future_date_is_not_filled_in_but_can_be_chosen_on_purpose(self):
        doc, landing = self.upload_page("Valid until: 15/03/2099")
        self.assertIsNone(self.fields(doc)["expiry"])
        self.assertIn("It was not filled in", landing)
        page = self.page(doc)
        self.assertIn("Use this date anyway", page)
        self.assertIn("2029 read as 2099", page)                                    # the reason is explained
        # not without the override: a plain request cannot pick it by accident
        self.assertEqual(self.choose(doc, "2099-03-15").status_code, 400)
        self.assertIsNone(self.fields(doc)["expiry"])
        self.choose(doc, "2099-03-15", override=True)
        fields = self.fields(doc)
        self.assertEqual((fields["expiry"], fields["source"]), (date(2099, 3, 15), "user"))
        self.assertIsNone(self.review(doc))

    def test_an_expiry_before_the_issue_date_is_flagged_and_can_be_chosen_on_purpose(self):
        doc, _ = self.upload_page("Date of Issue: 14/08/2027\nValid until: 14/08/2024")
        self.assertIsNone(self.fields(doc)["expiry"])
        page = self.page(doc)
        self.assertIn("earlier than another date in the document", page)
        self.assertIn("Use this date anyway", page)
        self.assertEqual(self.choose(doc, "2024-08-14").status_code, 400)
        self.choose(doc, "2024-08-14", override=True)
        self.assertEqual(self.fields(doc)["expiry"], date(2024, 8, 14))

    def test_an_invalid_date_cannot_be_selected_but_is_shown(self):
        doc, landing = self.upload_page("Valid until: 31/02/2026")
        self.assertIsNone(self.fields(doc)["expiry"])
        self.assertIsNone(self.review(doc))                                         # nothing to choose from
        page = self.page(doc)
        self.assertIn("31/02/2026", page)                                           # shown, not hidden
        self.assertIn("is not a real calendar date", page)
        self.assertNotIn('name="candidate"', page)
        self.assertEqual(self.choose(doc, "2026-02-28").status_code, 400)           # nothing offered, nothing to pick
        self.assertIsNone(self.fields(doc)["expiry"])

    def test_an_invalid_date_next_to_a_valid_one_has_no_button(self):
        doc, _ = self.upload_page("Valid until 31/02/2026\nExpires on 01/01/2028\nExpiry 01/01/2029")
        page = self.page(doc)
        self.assertEqual(page.count('name="candidate"'), 2)                         # only the two real dates
        self.assertIn("Cannot be used", page)
        self.assertIn("31/02/2026", page)
        self.assertNotIn("2026-02-31", page)

    def test_an_impossible_year_next_to_valid_dates_has_no_button_either(self):
        doc, _ = self.upload_page("Valid until 15/03/2150\nExpires on 01/01/2028\nExpiry 01/01/2029")
        page = self.page(doc)
        self.assertEqual(page.count('name="candidate"'), 2)
        self.assertIn("a year outside 2000-2100", page)
        self.assertNotIn('value="2150-03-15"', page)
        self.assertEqual(self.choose(doc, "2150-03-15").status_code, 400)

    def test_the_impossible_dates_stay_listed_after_other_actions(self):
        doc, _ = self.upload_page("Valid until 31/02/2026\nExpires on 01/01/2028\nExpiry 01/01/2029")
        self.expiry_action(doc, action="remove")                      # the user says there is no date
        page = self.page(doc)
        self.assertIn("31/02/2026", page)
        self.assertIn("Cannot be used", page)
        self.assertEqual(len(self.waiting(doc)), 3)                   # nothing was lost on the way

    def test_a_flagged_date_found_by_a_recheck_never_replaces_the_saved_date(self):
        doc, _ = self.upload_page("x", expiry="2029-01-15")
        response = self.recheck(doc, "Valid until: 15/03/2099").get_data(as_text=True)
        self.assertIn("Your saved date has not been changed", response)
        self.assertIn("is more than 30 years away", response)
        self.assertEqual(self.fields(doc)["expiry"], date(2029, 1, 15))
        self.assertEqual(self.waiting(doc), ["2099-03-15"])


class ShortTextTests(ReviewTestCase):
    def test_short_texts_with_an_expiry_date_are_not_called_unreadable(self):
        expected = {
            "EXP 10/2028": date(2028, 10, 31),
            "VALID THRU 05/27": date(2027, 5, 31),
            "Expiry Date: 10-Feb-2029": date(2029, 2, 10),
        }
        for text, wanted in expected.items():
            with self.subTest(text=text):
                doc, landing = self.upload_page(text)
                fields = self.fields(doc)
                self.assertEqual((fields["expiry"], fields["source"]), (wanted, "detected"))
                self.assertNotIn("Too little text", landing)
                self.assertNotIn("Not enough text could be read", self.page(doc))

    def test_a_month_and_year_says_that_the_last_day_was_used(self):
        doc, _ = self.upload_page("EXP 10/2028")
        self.assertIn("last day of that month", self.page(doc))

    def test_a_bare_year_is_offered_but_never_filled_in_automatically(self):
        doc, landing = self.upload_page("Expires 2028")
        self.assertIsNone(self.fields(doc)["expiry"])
        self.assertEqual(self.waiting(doc), ["2028-12-31"])
        page = self.page(doc)
        self.assertIn("only a year printed", page)
        self.assertIn("Use this date anyway", page)
        self.assertNotIn("Not enough text could be read", page)

    @unittest.skipIf(tesseract_version() is None, "Tesseract is not installed")
    def test_short_texts_through_the_real_reader(self):
        for line, wanted in (("EXP 10/2028", date(2028, 10, 31)), ("VALID THRU 05/27", date(2027, 5, 31))):
            with self.subTest(line=line):
                self.client.post("/upload", data={"title": "Short", "category": "Other",
                                                  "file": (io.BytesIO(picture([line])), "p.png")},
                                 content_type="multipart/form-data")
                with app.app_context():
                    doc = Document.query.order_by(Document.id.desc()).first().id
                self.assertEqual(self.fields(doc)["expiry"], wanted)


class OutcomeMessageTests(ReviewTestCase):
    """Each outcome has its own words, on upload and on the document page."""

    CASES = {
        "unreadable": ("Name\n\n1D No", "Too little text could be read", "Not enough text could be read"),
        "no_date": ("Certificate of Merit\nAwarded to Asha Rao\nGrade A", None, "The text was read, but no expiry date was found"),
        "uninterpretable": ("Valid until: 31/02/2026", "mentions an expiry", "An expiry is mentioned, but the date could not be understood"),
        "one": ("Valid until 31/12/2030", "Expiry date found in the text: 31 Dec 2030", None),
        "several": (TWO_DATES, "More than one possible expiry date", "More than one possible expiry date was found, so none was filled in"),
        "flagged": ("Valid until: 15/03/2099", "It was not filled in", "Check carefully"),
    }

    def test_every_outcome_has_its_own_message_and_page_note(self):
        landings, pages = {}, {}
        for kind, (text, landing_words, page_words) in self.CASES.items():
            doc, landing = self.upload_page(text)
            landings[kind], pages[kind] = landing, self.page(doc)
            if landing_words:
                self.assertIn(landing_words, landing, kind)
            if page_words:
                self.assertIn(page_words, pages[kind], kind)
        # ... and no outcome uses another outcome's words
        for kind, (_, landing_words, page_words) in self.CASES.items():
            for other in self.CASES:
                if other != kind:
                    if landing_words:
                        self.assertNotIn(landing_words, landings[other], f"{kind} words shown for {other}")
                    if page_words:
                        self.assertNotIn(page_words, pages[other], f"{kind} words shown for {other}")

    def test_a_completely_empty_reading_is_reported_once_and_as_unreadable(self):
        doc, landing = self.upload_page("")
        self.assertIn("No readable text was found in this image", landing)
        self.assertNotIn("Too little text", landing)
        self.assertIn("Not enough text could be read", self.page(doc))

    def test_the_uninterpretable_note_shows_the_line_and_the_reason(self):
        doc, _ = self.upload_page("Policy Holder: Asha Rao\nValid until: 31/02/2026\nPlan: Gold")
        page = self.page(doc)
        self.assertIn('The text says: "Valid until: 31/02/2026"', page)
        self.assertIn("&#34;31/02/2026&#34; is not a real calendar date", page.replace('"31/02/2026"', "&#34;31/02/2026&#34;"))

    def test_other_dates_are_listed_for_information_only(self):
        doc, _ = self.upload_page("Name: Asha Rao\nDate of Birth: 30/03/2003\nPolicy Holder only")
        page = self.page(doc)
        self.assertIn("Date of birth 30 Mar 2003", page)
        self.assertNotIn('name="candidate"', page)

    def test_the_note_goes_away_once_a_date_is_saved(self):
        doc, _ = self.upload_page("Name\n\n1D No")
        self.assertIn("Not enough text could be read", self.page(doc))
        self.expiry_action(doc, action="save", expiry_date="2030-01-01")
        self.assertNotIn("Not enough text could be read", self.page(doc))

    def test_text_from_the_document_is_escaped(self):
        doc, _ = self.upload_page("Valid until 01/01/2027 <script>alert(1)</script>\nExpires on 01/01/2029 <b>x</b>")
        page = self.page(doc)
        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<b>x</b>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_a_recheck_reports_each_outcome_in_its_own_words(self):
        doc, _ = self.upload_page("x", expiry="2029-01-15")
        said = {
            "several": (TWO_DATES, "more than one possible expiry date was found"),
            "flagged": ("Valid until: 15/03/2099", "but it is more than 30 years away"),
            "uninterpretable": ("Valid until: 31/02/2026", "It mentions an expiry"),
            "no_date": ("Policy holder only, no dates", "No expiry date was found next to an expiry word"),
            "unreadable": ("Name\n\n1D No", "too little text could be read"),
            "empty": ("", "no text could be read from it"),
            "match": ("Valid until 15/01/2029", "Your date matches"),
            "one": ("Valid until 31/12/2030", "a different date was found: 31 Dec 2030"),
        }
        pages = {kind: self.recheck(doc, text).get_data(as_text=True) for kind, (text, _) in said.items()}
        for kind, (_, words) in said.items():
            self.assertIn(words, pages[kind], kind)
        for kind, (_, words) in said.items():
            for other in said:
                if other != kind and kind not in ("one", "match"):
                    self.assertNotIn(words, pages[other], f"{kind} words shown for {other}")
        self.assertEqual(self.fields(doc)["expiry"], date(2029, 1, 15))             # never changed

    def test_a_recheck_that_finds_the_saved_date_among_several_is_a_match(self):
        doc, _ = self.upload_page("x", expiry="2029-01-01")
        page = self.recheck(doc, TWO_DATES).get_data(as_text=True)
        self.assertIn("Your date matches", page)
        self.assertIsNone(self.review(doc))


class NeedsAttentionReviewTests(ReviewTestCase):
    def dashboard(self, client=None):
        return (client or self.client).get("/dashboard").get_data(as_text=True)

    def test_a_document_waiting_for_a_choice_is_marked_and_counted(self):
        doc, _ = self.upload_page(TWO_DATES, title="doc choose")
        quiet, _ = self.upload_page("Certificate of Merit\nAwarded to Asha Rao\nGrade A", title="doc nothing")
        html = self.dashboard()
        numbers, rows = parse_dashboard(html)
        self.assertEqual(numbers["unchecked"], 1)                                    # "Waiting for your check"
        row = html.split("doc choose")[1].split("</tr>")[0]
        self.assertIn("Choose a date", row)
        self.assertNotIn("Choose a date", html.split("doc nothing")[1].split("</tr>")[0])
        self.choose(doc, "2027-01-01")
        html = self.dashboard()
        self.assertEqual(parse_dashboard(html)[0]["unchecked"], 0)
        self.assertNotIn("Choose a date", html)

    def test_a_document_with_a_saved_date_is_not_marked(self):
        doc, _ = self.upload_page("x", expiry="2028-06-06", title="doc saved")
        self.recheck(doc, TWO_DATES)
        self.assertEqual(len(self.waiting(doc)), 2)                                  # dates are waiting on the page
        html = self.dashboard()
        self.assertNotIn("Choose a date", html)                                      # ... but nothing is missing
        self.assertEqual(parse_dashboard(html)[0]["unchecked"], 0)

    def test_the_marker_never_changes_the_expiry_counts(self):
        self.upload_page(TWO_DATES, title="doc choose")
        numbers, rows = parse_dashboard(self.dashboard())
        self.assertEqual((numbers["total"], numbers["expired"], numbers["soon"]), (1, 0, 0))
        self.assertEqual(rows, [("doc choose", None, None)])


class LegacySuggestionTests(AppTestCase):
    """A suggestion saved by the previous version moves into the new review exactly once."""

    def make_old_database(self):
        from werkzeug.security import generate_password_hash
        path = os.path.join(tempfile.mkdtemp(dir=TEMP), "legacy.db").replace("\\", "/")
        con = sqlite3.connect(path)
        con.executescript(
            "CREATE TABLE user (id INTEGER NOT NULL, username VARCHAR(80) NOT NULL, email VARCHAR(120) NOT NULL,"
            " password_hash VARCHAR(256) NOT NULL, PRIMARY KEY (id));"
            "CREATE TABLE document (id INTEGER NOT NULL, title VARCHAR(150) NOT NULL, filename VARCHAR(200) NOT NULL,"
            " category VARCHAR(50), category_source VARCHAR(10), expiry_date DATE, expiry_source VARCHAR(10),"
            " suggested_date DATE, suggested_label VARCHAR(60),"
            " extracted_text TEXT, uploaded_at DATETIME, user_id INTEGER NOT NULL, PRIMARY KEY (id));"
        )
        con.execute("INSERT INTO user VALUES (1, 'old', 'old@example.com', ?)", (generate_password_hash("secret1"),))
        rows = [
            (1, "Has a date and a suggestion", "2029-01-15", "user", "2030-12-31", "Valid until"),
            (2, "Nothing pending", "2031-03-03", "user", None, None),
            (3, "Suggestion and no date", None, None, "2032-02-02", "Expiry"),
        ]
        for doc_id, title, expiry, source, suggested, label in rows:
            con.execute(
                "INSERT INTO document (id, title, filename, category, category_source, expiry_date, expiry_source,"
                " suggested_date, suggested_label, user_id) VALUES (?, ?, 'a.png', 'Other', 'user', ?, ?, ?, ?, 1)",
                (doc_id, title, expiry, source, suggested, label))
        con.commit()
        con.close()
        return path

    SHOW = (
        "import json, sqlite3\nfrom app import app\nfrom models import Document, db\n"
        "with app.app_context():\n"
        "    out = {}\n"
        "    for d in Document.query.order_by(Document.id):\n"
        "        waiting = [c['date'] for c in (d.review or {}).get('candidates', [])]\n"
        "        out[d.id] = [waiting, str(d.expiry_date), d.expiry_source]\n"
        "    legacy = db.session.execute(db.text('SELECT id, suggested_date, suggested_label FROM document ORDER BY id')).all()\n"
        "    out['legacy'] = [list(r[1:]) for r in legacy]\n"
        "print(json.dumps(out))\n"
    )

    def act(self, doc_id, **form):
        return (
            "import json\nfrom app import app\nfrom models import Document, db\n"
            "client = app.test_client()\n"
            "client.post('/login', data={'username': 'old', 'password': 'secret1'})\n"
            f"response = client.post('/document/{doc_id}/expiry', data={form!r})\n"
            "page = client.get('/document/%d' % " + str(doc_id) + ").get_data(as_text=True)\n"
            "print(json.dumps([response.status_code, 'Use this date' in page]))\n"
        )

    def start(self, code, database):
        return RestartTests.run_fresh_process(self, code, database=database)

    def test_an_old_suggestion_is_migrated_and_the_old_values_are_cleared(self):
        db_path = self.make_old_database()
        shown = self.start(self.SHOW, db_path)
        self.assertEqual(shown["1"], [["2030-12-31"], "2029-01-15", "user"])      # the saved date is untouched
        self.assertEqual(shown["2"], [[], "2031-03-03", "user"])
        self.assertEqual(shown["3"], [["2032-02-02"], "None", None])
        self.assertEqual(shown["legacy"], [[None, None]] * 3)                       # cleared right after the move

    def test_the_migrated_suggestion_still_offers_the_buttons(self):
        db_path = self.make_old_database()
        self.assertEqual(self.start(self.act(1, action="noop-never-used"), db_path)[1], True)

    def test_a_dismissed_suggestion_does_not_come_back_after_a_restart(self):
        db_path = self.make_old_database()
        self.start(self.SHOW, db_path)                                              # first start: migrate
        status, _ = self.start(self.act(1, action="keep"), db_path)                 # the user dismisses it
        self.assertEqual(status, 302)
        for _ in range(2):                                                          # restart, and restart again
            shown = self.start(self.SHOW, db_path)
            self.assertEqual(shown["1"], [[], "2029-01-15", "user"])
            self.assertEqual(shown["legacy"], [[None, None]] * 3)
            self.assertEqual(shown["3"][0], ["2032-02-02"])                         # the other one is still pending

    def test_an_accepted_suggestion_does_not_come_back_either(self):
        db_path = self.make_old_database()
        self.start(self.SHOW, db_path)
        status, _ = self.start(self.act(3, action="use_suggested"), db_path)
        self.assertEqual(status, 302)
        for _ in range(2):
            shown = self.start(self.SHOW, db_path)
            self.assertEqual(shown["3"], [[], "2032-02-02", "user"])
            self.assertEqual(shown["legacy"], [[None, None]] * 3)

    def test_starting_twice_before_any_action_changes_nothing(self):
        db_path = self.make_old_database()
        first = self.start(self.SHOW, db_path)
        self.assertEqual(self.start(self.SHOW, db_path), first)

    def test_a_suggestion_that_is_not_a_date_is_cleared_without_creating_a_review(self):
        db_path = self.make_old_database()
        con = sqlite3.connect(db_path)
        con.execute("UPDATE document SET suggested_date = 'garbage' WHERE id = 2")
        con.commit()
        con.close()
        shown = self.start(self.SHOW, db_path)
        self.assertEqual(shown["2"][0], [])
        self.assertEqual(shown["legacy"], [[None, None]] * 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
