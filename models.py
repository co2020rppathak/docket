import json
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now_utc():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    documents = db.relationship("Document", backref="owner", lazy=True)


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50))
    # Where category came from: "user" (chosen or confirmed by the user)
    # or "detected" (guessed from the document text and not confirmed yet)
    category_source = db.Column(db.String(10))
    expiry_date = db.Column(db.Date)
    # Where expiry_date came from: "user" (typed or confirmed by the user)
    # or "detected" (found in the document text and not confirmed yet)
    expiry_source = db.Column(db.String(10))
    # Old columns, no longer used. A suggestion kept here by an older version is moved into
    # review_json (and these are cleared) when the application starts.
    suggested_date = db.Column(db.Date)
    suggested_label = db.Column(db.String(60))
    # Dates waiting for the user's decision, as JSON: where they came from, the possible
    # expiry dates with the words and line around them, and other dates for information.
    # They are only suggestions and never replace expiry_date unless the user chooses one.
    review_json = db.Column(db.Text)
    extracted_text = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=now_utc)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    @property
    def review(self):
        """The pending review as a dict, or None (also None if the stored text is damaged)."""
        if not self.review_json:
            return None
        try:
            data = json.loads(self.review_json)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def set_review(self, data):
        self.review_json = json.dumps(data) if data else None
