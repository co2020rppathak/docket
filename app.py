import json
import os
import uuid
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    send_from_directory, abort
)
from PIL import Image
import sqlalchemy as sa
from werkzeug.security import generate_password_hash, check_password_hash

from categorize import guess_category
from expiry import (
    Candidate, FLAG_TEXT, MIN_YEAR, MAX_YEAR, NOTE_TEXT, ROLE_NAMES, UNSELECTABLE,
    analyse, has_expiry_date,
)
from models import db, User, Document
from ocr import extract_text, OCRUnavailable
from status import expiry_status, SOON_DAYS

app = Flask(__name__)
app.config["SECRET_KEY"] = "k9Xv2mQpL7sT4wZr8bNf3HjD6yUc1AeG"
# The environment variables let the tests use a temporary database instead of your real one
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("IDMS_DATABASE_URI", "sqlite:///vault.db")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit
# The login cookie is not sent along with forms that other websites post to this app
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.environ.get("IDMS_UPLOAD_FOLDER") or os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_IMAGE_PIXELS = 40_000_000  # width x height; blocks absurdly large images
CATEGORIES = ["ID Proof", "Insurance", "Warranty", "Certificate", "Medical", "Other"]
SITE_NAME = "Docket"
PROJECT_TITLE = "Intelligent Document Management System for Automated Categorization and Expiry Detection"
AUTO_CATEGORY = "auto"  # the upload form's "Detect automatically" choice

# What the user is told after text extraction: outcome -> (message, colour)
OCR_MESSAGES = {
    "ok": ("Text extracted successfully.", "success"),
    "empty": ("No readable text was found in this image.", "warning"),
    "unavailable": (
        "Text extraction is unavailable. Check that Tesseract is installed.",
        "warning",
    ),
    "failed": ("Text extraction failed for this image.", "warning"),
}

db.init_app(app)


def upgrade_database():
    """Add columns that an older vault.db does not have yet. Existing data is kept."""
    columns = [row[1] for row in db.session.execute(sa.text("PRAGMA table_info(document)"))]
    if "expiry_source" not in columns:
        db.session.execute(sa.text("ALTER TABLE document ADD COLUMN expiry_source VARCHAR(10)"))
        # Every date saved before this column existed was typed by the user
        db.session.execute(sa.text("UPDATE document SET expiry_source = 'user' WHERE expiry_date IS NOT NULL"))
    if "category_source" not in columns:
        db.session.execute(sa.text("ALTER TABLE document ADD COLUMN category_source VARCHAR(10)"))
        # Every category saved before this column existed was chosen by the user
        db.session.execute(sa.text("UPDATE document SET category_source = 'user'"))
    if "suggested_date" not in columns:
        db.session.execute(sa.text("ALTER TABLE document ADD COLUMN suggested_date DATE"))
        db.session.execute(sa.text("ALTER TABLE document ADD COLUMN suggested_label VARCHAR(60)"))
    if "review_json" not in columns:
        db.session.execute(sa.text("ALTER TABLE document ADD COLUMN review_json TEXT"))

    # A suggestion kept by an older version moves into review_json. The old columns are cleared
    # in the same step, so the suggestion can never be moved a second time: if the user accepts
    # or dismisses it, it stays gone after every restart.
    old = db.session.execute(sa.text(
        "SELECT id, suggested_date, suggested_label FROM document WHERE suggested_date IS NOT NULL"
    )).all()
    for doc_id, when, label in old:
        review = None
        try:
            when = date.fromisoformat(str(when)[:10])
            review = {
                "source": "check", "kind": "one", "others": [],
                "candidates": [Candidate(
                    raw=when.strftime("%d %b %Y"), date=when, label=(label or ""), context="",
                    role="expiry", score=0,
                ).to_dict()],
            }
        except ValueError:
            pass  # not a date: nothing worth keeping, only the old values are cleared
        db.session.execute(
            sa.text("UPDATE document SET review_json = COALESCE(review_json, :review), "
                    "suggested_date = NULL, suggested_label = NULL WHERE id = :id"),
            {"review": json.dumps(review) if review else None, "id": doc_id},
        )
    db.session.commit()


# Create the database tables if they don't exist yet, and bring an older database up to date
with app.app_context():
    db.create_all()
    upgrade_database()


# ---------- helpers ----------

def login_required(view):
    """Send visitors who are not logged in to the login page."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


@app.context_processor
def inject_user():
    # Makes `user` available in every template (used by the navigation bar)
    return {"user": current_user(), "site_name": SITE_NAME, "project_title": PROJECT_TITLE}


@app.template_filter("show_date")
def show_date(when):
    """2028-03-15 -> '15 Mar 2028'"""
    return when.strftime("%d %b %Y")


# ---------- routes ----------

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/test-results")
def test_results():
    """The recorded test results. A read-only page: it runs nothing and needs no login."""
    return render_template("test_results.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form["username"].strip().lower()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not username or not email or len(password) < 6:
            flash("Fill all fields. Password must be at least 6 characters.", "error")
            return render_template("register.html")

        exists = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if exists:
            flash("Username or email is already taken.", "error")
            return render_template("register.html")

        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]

        found = User.query.filter_by(username=username).first()

        # Same message for "no such user" and "wrong password"
        if found is None or not check_password_hash(found.password_hash, password):
            flash("Incorrect username or password.", "error")
            return render_template("login.html")

        session.clear()
        session["user_id"] = found.id
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


def today():
    return date.today()


def review_candidates(review):
    """The candidates of a stored review as Candidate objects (empty if there is none)."""
    try:
        return [Candidate.from_dict(item) for item in (review or {}).get("candidates", [])]
    except (KeyError, TypeError, ValueError):
        return []


@app.template_global()
def needs_choice(doc):
    """True when the document has no saved date but dates are waiting for the user to choose."""
    return doc.expiry_date is None and any(c.selectable for c in review_candidates(doc.review))


@app.route("/dashboard")
@login_required
def dashboard():
    documents = (
        Document.query.filter_by(user_id=session["user_id"])
        .order_by(Document.uploaded_at.desc())
        .all()
    )
    now = today()
    rows = [(doc, expiry_status(doc.expiry_date, now)) for doc in documents]

    total = len(rows)
    unchecked = sum(
        1 for doc, _ in rows
        if doc.expiry_source == "detected" or doc.category_source == "detected" or needs_choice(doc)
    )
    expired = sum(1 for _, status in rows if status.key == "expired")
    soon = sum(1 for _, status in rows if status.key == "soon")

    # ?show=attention lists only expired and soon-to-expire documents, earliest date first
    show = "attention" if request.args.get("show") == "attention" else "all"
    if show == "attention":
        rows = [row for row in rows if row[1].key in ("expired", "soon")]
        rows.sort(key=lambda row: row[0].expiry_date)

    return render_template(
        "dashboard.html", rows=rows, show=show,
        total=total, unchecked=unchecked,
        expired=expired, soon=soon, soon_days=SOON_DAYS,
    )


# ---------- upload helpers ----------

def get_extension(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def looks_like_image(file_storage):
    """Check the first bytes of the file, not just its name."""
    header = file_storage.stream.read(8)
    file_storage.stream.seek(0)
    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = header.startswith(b"\xff\xd8\xff")
    return is_png or is_jpeg


def image_problem(file_storage):
    """Return a message if the image is damaged or too large, else None."""
    try:
        image = Image.open(file_storage.stream)  # reads only the file header
        if image.width * image.height > MAX_IMAGE_PIXELS:
            return "The image resolution is too large. Please upload a smaller image."
        image.load()  # decodes the whole image; fails if it is damaged or cut off
    except Exception:
        return "The image file appears to be damaged or unreadable."
    finally:
        file_storage.stream.seek(0)
    return None


def get_own_document_or_404(doc_id):
    doc = db.session.get(Document, doc_id)
    if doc is None or doc.user_id != session["user_id"]:
        abort(404)
    return doc


def read_text(doc, look_for_date):
    """Read the stored image of a document with OCR. Nothing is saved on the record.

    Returns (outcome, text). The outcome is one of "ok", "empty", "unavailable", "failed";
    the text is None unless the outcome is "ok" or "empty".
    With look_for_date the page is read a second time if the first reading holds no date.
    """
    path = os.path.join(UPLOAD_FOLDER, doc.filename)
    try:
        text = extract_text(path, good_enough=has_expiry_date if look_for_date else None)
    except OCRUnavailable:
        return "unavailable", None
    except Exception:
        # The details go to the terminal so problems can be investigated
        app.logger.exception("Text extraction failed for document %s", doc.id)
        return "failed", None
    return ("ok" if text else "empty"), text


def run_ocr(doc):
    """Read the text of a stored document and save it on the record.

    Returns one of: "ok", "empty", "unavailable", "failed".
    The caller must commit the database session.
    """
    # Reading the page again to find a date is only worth it if the user has not given one
    outcome, text = read_text(doc, look_for_date=doc.expiry_source != "user")
    if text is not None:
        doc.extracted_text = text
    return outcome


def parse_expiry_date(value):
    """Read '2028-03-15' (what a date input sends). Returns None if it is not a sensible date."""
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if MIN_YEAR <= parsed.year <= MAX_YEAR else None


def build_review(analysis, source):
    """What is stored while the user has to decide: where it came from and the dates found."""
    return {
        "source": source, "kind": analysis.kind,
        "candidates": [c.to_dict() for c in analysis.candidates],
        "others": [c.to_dict() for c in analysis.others],
    }


def fill_expiry_from_text(doc, source="extract"):
    """Look for an expiry date in the document's text and record what was found.

    A date the user typed or confirmed is never replaced: for that, None is returned.
    Otherwise only one clear, unflagged date is filled in (as "detected"). If there are
    several possible dates, or the one found looks suspicious, nothing is filled in and the
    candidates wait in the document's review for the user to choose. If the text holds
    nothing usable, an earlier detection no longer holds, so it is cleared.
    Returns the Analysis. The caller must commit the database session.
    """
    if doc.expiry_source == "user":
        return None
    analysis = analyse(doc.extracted_text or "", today())
    winner = analysis.candidates[0] if analysis.kind == "one" else None
    doc.expiry_date = winner.date if winner else None
    doc.expiry_source = "detected" if winner else None
    to_choose = analysis.kind in ("several", "flagged")
    doc.set_review(build_review(analysis, source) if to_choose else None)
    return analysis


def review_against_saved(doc, analysis, source):
    """Show what a new reading found next to the saved date, without changing the date.

    Returns "match" (the saved date is among the dates found), "review" (dates are waiting
    for the user to choose) or "none" (nothing usable was found). The caller must commit.
    """
    selectable = [c for c in analysis.candidates if c.selectable]
    if doc.expiry_date and any(c.date == doc.expiry_date for c in selectable):
        doc.set_review(None)
        return "match"
    if selectable:
        doc.set_review(build_review(analysis, source))
        return "review"
    doc.set_review(None)
    return "none"


def prune_review(doc):
    """Drop a candidate that now equals the saved date; drop the review if nothing is left to choose."""
    review = doc.review
    if not review:
        return
    kept = [c for c in review.get("candidates", [])
            if not (doc.expiry_date and c.get("date") == doc.expiry_date.isoformat())]
    review["candidates"] = kept
    usable = any(c.selectable for c in review_candidates(review))
    doc.set_review(review if usable else None)


def fill_category_from_text(doc):
    """Guess the document's category from its text and record it as "detected".

    A category the user chose or confirmed is never replaced. Returns the guess
    (or None). If the guesser is not sure, the category is "Other" with no source.
    The caller must commit the database session.
    """
    if doc.category_source == "user":
        return None
    guess = guess_category(doc.extracted_text or "")
    doc.category = guess.category if guess else "Other"
    doc.category_source = "detected" if guess else None
    return guess


def flash_category_guessed(guess):
    flash(f"Category guessed from the text: {guess.category}. Please check it.", "warning")


def flash_expiry_found(found):
    note = f" ({NOTE_TEXT[found.notes[0]]})" if found.notes and found.notes[0] in NOTE_TEXT else ""
    flash(f"Expiry date found in the text: {show_date(found.date)}. Please check it.{note}", "warning")


def reasons(candidate):
    """Why a date looks suspicious, in a sentence."""
    return "; ".join(FLAG_TEXT[flag] for flag in candidate.flags)


def flash_expiry_result(analysis, text):
    """Tell the user what the text said about an expiry date. Each kind of result has its own words."""
    kind = analysis.kind
    if kind == "one":
        flash_expiry_found(analysis.candidates[0])
    elif kind == "several":
        flash("More than one possible expiry date was found in the text. Nothing was filled in: "
              "please open the document and choose the right one.", "warning")
    elif kind == "flagged":
        best = analysis.candidates[0]
        flash(f"A possible expiry date was found ({show_date(best.date)}), but it {reasons(best)}. "
              "It was not filled in: please open the document and check it.", "warning")
    elif kind == "uninterpretable":
        flash("The text mentions an expiry, but no date that can be used came with it. "
              "Please look at the image and enter the date yourself.", "warning")
    elif kind == "unreadable" and text:
        # (a completely empty reading was already reported by the text-extraction message)
        flash("Too little text could be read to look for an expiry date. A clearer image may help.", "warning")


# ---------- upload routes ----------

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        title = request.form["title"].strip()
        category = request.form.get("category", "")
        expiry_text = request.form.get("expiry_date", "").strip()
        file = request.files.get("file")

        if not title:
            flash("Please enter a title for the document.", "error")
            return render_template("upload.html", categories=CATEGORIES)

        if file is None or file.filename == "":
            flash("Please choose a file to upload.", "error")
            return render_template("upload.html", categories=CATEGORIES)

        extension = get_extension(file.filename)
        if extension not in ALLOWED_EXTENSIONS or not looks_like_image(file):
            flash("Only JPG and PNG images are supported.", "error")
            return render_template("upload.html", categories=CATEGORIES)

        problem = image_problem(file)
        if problem:
            flash(problem, "error")
            return render_template("upload.html", categories=CATEGORIES)

        # "auto" means: guess the category from the text once it has been read
        auto_category = category == AUTO_CATEGORY
        if category not in CATEGORIES:
            category = "Other"

        expiry_date = None
        if expiry_text:
            expiry_date = parse_expiry_date(expiry_text)
            if expiry_date is None:
                flash("Expiry date is not valid.", "error")
                return render_template("upload.html", categories=CATEGORIES)

        # Random file name: avoids clashes and never trusts the user's file name
        saved_name = uuid.uuid4().hex + "." + extension
        file.save(os.path.join(UPLOAD_FOLDER, saved_name))

        doc = Document(
            title=title,
            filename=saved_name,
            category=category,
            category_source=None if auto_category else "user",
            expiry_date=expiry_date,
            expiry_source="user" if expiry_date else None,
            user_id=session["user_id"],
        )
        db.session.add(doc)
        db.session.commit()

        # The document is already saved; reading its text is a bonus step
        outcome = run_ocr(doc)
        read_ok = outcome in ("ok", "empty")
        analysis = fill_expiry_from_text(doc, "upload") if read_ok else None
        guess = fill_category_from_text(doc) if read_ok else None
        db.session.commit()

        flash("Document uploaded successfully.", "success")
        flash(*OCR_MESSAGES[outcome])
        if analysis:
            flash_expiry_result(analysis, doc.extracted_text)
        if guess:
            flash_category_guessed(guess)
        return redirect(url_for("dashboard"))

    return render_template("upload.html", categories=CATEGORIES)


@app.route("/document/<int:doc_id>")
@login_required
def document_detail(doc_id):
    doc = get_own_document_or_404(doc_id)

    # What the text says about an expiry date, worked out from the saved text each time
    analysis = analyse(doc.extracted_text or "", today())

    # For a detected date, show the words it was found next to, so it is easy to check
    evidence, detected_notes = None, []
    if doc.expiry_source == "detected":
        match = next((c for c in analysis.candidates if c.selectable and c.date == doc.expiry_date), None)
        if match:
            evidence, detected_notes = match.label, [NOTE_TEXT[n] for n in match.notes if n in NOTE_TEXT]
    # Same for a guessed category: show the words that decided it
    category_words = None
    if doc.category_source == "detected":
        guess = guess_category(doc.extracted_text or "")
        if guess and guess.category == doc.category:
            category_words = ", ".join(guess.words)

    status = expiry_status(doc.expiry_date, today())

    # Dates waiting for the user's choice
    review = doc.review
    candidates = review_candidates(review)
    others = [Candidate.from_dict(item) for item in (review or {}).get("others", [])] if candidates else []
    # With no date saved and nothing to choose from, say plainly why nothing was found
    note = None
    if (doc.expiry_date is None and not any(c.selectable for c in candidates)
            and doc.extracted_text is not None
            and analysis.kind in ("unreadable", "no_date", "uninterpretable")):
        note = analysis
    return render_template(
        "document.html", doc=doc, evidence=evidence, status=status,
        categories=CATEGORIES, category_words=category_words,
        review=review, candidates=candidates, review_others=others, note=note,
        detected_notes=detected_notes, flag_text=FLAG_TEXT, note_text=NOTE_TEXT, role_names=ROLE_NAMES,
    )


@app.route("/document/<int:doc_id>/extract", methods=["POST"])
@login_required
def extract_document_text(doc_id):
    doc = get_own_document_or_404(doc_id)
    outcome = run_ocr(doc)
    read_ok = outcome in ("ok", "empty")
    analysis = fill_expiry_from_text(doc, "extract") if read_ok else None
    guess = fill_category_from_text(doc) if read_ok else None
    db.session.commit()

    flash(*OCR_MESSAGES[outcome])
    if analysis:
        flash_expiry_result(analysis, doc.extracted_text)
    if guess:
        flash_category_guessed(guess)
    return redirect(url_for("document_detail", doc_id=doc.id))


@app.route("/document/<int:doc_id>/expiry", methods=["POST"])
@login_required
def set_expiry(doc_id):
    doc = get_own_document_or_404(doc_id)
    action = request.form.get("action", "")

    if action in ("use_suggested", "use_candidate"):
        # The user looked at a date found in the document and chose it: it counts as the user's date
        selectable = [c for c in review_candidates(doc.review) if c.selectable]
        wanted = request.form.get("candidate", "")
        if wanted:
            chosen = next((c for c in selectable if c.date.isoformat() == wanted), None)
        else:
            chosen = selectable[0] if len(selectable) == 1 else None
        if chosen is None:
            abort(400)
        # A date that looks suspicious can still be chosen, but only on purpose
        if chosen.needs_override and request.form.get("override") != "yes":
            abort(400)
        doc.expiry_date, doc.expiry_source = chosen.date, "user"
        doc.set_review(None)
        flash("Expiry date updated to the newly found date.", "success")
    elif action == "keep":
        doc.set_review(None)
        flash("Your saved date was kept.", "success")
    elif action == "confirm" and doc.expiry_date:
        doc.expiry_source = "user"
        flash("Expiry date confirmed.", "success")
    elif action == "remove":
        # "user" with no date means: the user says there is none, so detection leaves it alone
        doc.expiry_date, doc.expiry_source = None, "user"
        flash("Expiry date removed.", "success")
    elif action == "save":
        expiry_date = parse_expiry_date(request.form.get("expiry_date", ""))
        if expiry_date is None:
            flash("Please enter a valid expiry date.", "error")
            return redirect(url_for("document_detail", doc_id=doc.id))
        doc.expiry_date, doc.expiry_source = expiry_date, "user"
        flash("Expiry date saved.", "success")
    else:
        abort(400)

    # A date that now equals the saved date has nothing left to say
    prune_review(doc)

    db.session.commit()
    return redirect(url_for("document_detail", doc_id=doc.id))


@app.route("/document/<int:doc_id>/expiry/recheck", methods=["POST"])
@login_required
def recheck_expiry(doc_id):
    """Read the original image again and show what date it holds, next to the saved one.

    Only the review (the dates found) is stored. expiry_date, its source, the extracted text and
    the category are never touched, so a correction made by the user is always safe.
    """
    doc = get_own_document_or_404(doc_id)
    outcome, text = read_text(doc, look_for_date=True)

    if text is None:
        flash(*OCR_MESSAGES[outcome])  # reading failed: nothing is changed
        return redirect(url_for("document_detail", doc_id=doc.id))

    analysis = analyse(text, today())
    result = review_against_saved(doc, analysis, "check")
    first = analysis.candidates[0] if analysis.candidates else None

    if result == "match":
        flash(f"The document was checked again and it also says {show_date(doc.expiry_date)}. Your date matches.", "success")
    elif result == "review" and analysis.kind == "several":
        flash("The document was checked again and more than one possible expiry date was found. "
              "Your saved date has not been changed: please choose below.", "warning")
    elif result == "review" and analysis.kind == "flagged":
        flash(f"The document was checked again and a possible expiry date was found ({show_date(first.date)}), "
              f"but it {reasons(first)}. Your saved date has not been changed.", "warning")
    elif result == "review":
        flash(f"The document was checked again and a different date was found: {show_date(first.date)}. "
              "Your saved date has not been changed.", "warning")
    elif outcome == "empty":
        flash("The document was checked again, but no text could be read from it.", "warning")
    elif analysis.kind == "unreadable":
        flash("The document was checked again, but too little text could be read to look for a date.", "warning")
    elif analysis.kind == "uninterpretable":
        where = analysis.wording[0] if analysis.wording else first.raw
        flash(f"The document was checked again. It mentions an expiry (\"{where}\"), but no date that can "
              "be used came with it. Compare with the image.", "warning")
    else:
        flash("The document was checked again. No expiry date was found next to an expiry word. "
              "The text itself was read, so this document may simply not have one.", "warning")

    db.session.commit()
    return redirect(url_for("document_detail", doc_id=doc.id))


@app.route("/document/<int:doc_id>/category", methods=["POST"])
@login_required
def set_category(doc_id):
    doc = get_own_document_or_404(doc_id)
    action = request.form.get("action", "")

    if action == "confirm" and doc.category_source == "detected":
        doc.category_source = "user"
        flash("Category confirmed.", "success")
    elif action == "save":
        category = request.form.get("category", "")
        if category not in CATEGORIES:
            flash("Please choose a category from the list.", "error")
            return redirect(url_for("document_detail", doc_id=doc.id))
        doc.category, doc.category_source = category, "user"
        flash("Category saved.", "success")
    else:
        abort(400)

    db.session.commit()
    return redirect(url_for("document_detail", doc_id=doc.id))


@app.route("/document/<int:doc_id>/file")
@login_required
def document_file(doc_id):
    doc = get_own_document_or_404(doc_id)
    return send_from_directory(UPLOAD_FOLDER, doc.filename)


@app.route("/document/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    doc = get_own_document_or_404(doc_id)

    path = os.path.join(UPLOAD_FOLDER, doc.filename)
    if os.path.exists(path):
        os.remove(path)

    db.session.delete(doc)
    db.session.commit()

    flash("Document deleted.", "success")
    return redirect(url_for("dashboard"))


@app.errorhandler(413)
def file_too_large(error):
    flash("File is too large. The maximum size is 5 MB.", "error")
    return redirect(url_for("upload"))


if __name__ == "__main__":
    app.run(debug=True)
