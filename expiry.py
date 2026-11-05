"""Finds the expiry date in the text that OCR read from a document.

How it works:
1. Find every date in the text (8 common formats).
2. Look at the words just before each date. Words like "Expiry" or "Valid till"
   raise its score; words like "Issued", "Birth" or "Purchase" lower it.
3. Return the date with the best score. If no date scores well enough, return
   nothing: it is better to suggest no date than to suggest the wrong one.

Numeric dates are read day first (15/03/2028 means 15 March), as in India.
Month and year only (10/2028, Oct 2028, and 05/27 after an expiry word) count as the last
day of that month. A bare year after a strong expiry word ("Expires 2028") counts as
31 December of that year, but is always flagged, so it is never filled in automatically.
Not supported: two-digit years in a full date (15/03/28).

find_expiry() returns the one best date. analyse() is the fuller answer: every possible
expiry date with the words and line around it, why a date looks suspicious, and what kind
of result it is (see analyse() below).
"""
import calendar
import re
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date

# date = the date found, label = the words before it, score = how sure we are
Found = namedtuple("Found", ["date", "label", "score"])

MIN_SCORE = 2        # a date needs at least this score to be suggested
LABEL_LENGTH = 40    # how many characters before a date are read as its label
MIN_YEAR = 2000      # years outside this range are treated as mistakes
MAX_YEAR = 2100

# ---------- finding dates ----------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_NAME = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

# OCR often reads a 1 as l, I, | or ] and a 0 as O. Inside a numeric date these
# characters are allowed, and turned back into digits before the date is read.
DIGIT = r"[0-9OolI|\]]"
YEAR = rf"(?:19|2[0O1]){DIGIT}{{2}}"
FIX_DIGITS = str.maketrans("OolI|]", "001111")

SPACE = r"[ \t]*"  # OCR sometimes adds spaces inside a date, but never a line break

# A date must not start right after a digit, or after a digit and a space. The second case
# is how OCR breaks "19/09/2031" into "1 9/09/2031": reading only "9/09/2031" would give the
# wrong day, and it is better to find no date than a wrong one.
NOT_AFTER_DIGIT = r"(?<![0-9])(?<![0-9][ \t])"

# 15/03/2028   15-03-2028   15.03.2028   (the same separator twice)
NUMERIC = re.compile(
    rf"{NOT_AFTER_DIGIT}(?P<day>{DIGIT}{{1,2}}){SPACE}(?P<sep>[/.\-]){SPACE}"
    rf"(?P<month>{DIGIT}{{1,2}}){SPACE}(?P=sep){SPACE}(?P<year>{YEAR})(?![0-9])"
)

# 2028-03-15   2028/03/15
ISO = re.compile(
    rf"{NOT_AFTER_DIGIT}(?P<year>(?:19|2[01])[0-9]{{2}}){SPACE}(?P<sep>[/.\-]){SPACE}"
    rf"(?P<month>[0-9]{{1,2}}){SPACE}(?P=sep){SPACE}(?P<day>[0-9]{{1,2}})(?![0-9])"
)

# 15 Mar 2028   15 March 2028   15-Mar-2028   15th March, 2028
DAY_MONTH_YEAR = re.compile(
    rf"(?<![0-9])(?P<day>[0-9]{{1,2}})(?:st|nd|rd|th)?[ \t.\-]*(?P<month>{MONTH_NAME})\b"
    rf"[ \t.,\-]*(?P<year>(?:19|2[01])[0-9]{{2}})(?![0-9])",
    re.IGNORECASE,
)

# March 15, 2028   Mar 15 2028
MONTH_DAY_YEAR = re.compile(
    rf"(?<![A-Za-z])(?P<month>{MONTH_NAME})\b[ \t.]*(?P<day>[0-9]{{1,2}})(?:st|nd|rd|th)?"
    rf"[ \t]*,?[ \t]*(?P<year>(?:19|2[01])[0-9]{{2}})(?![0-9])",
    re.IGNORECASE,
)


def make_date(year, month, day):
    """A real date between MIN_YEAR and MAX_YEAR, or None."""
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def read_numeric(match):
    day, month, year = (
        int(match.group(name).translate(FIX_DIGITS)) for name in ("day", "month", "year")
    )
    # Day first; if that is impossible (a month above 12), try month first
    return make_date(year, month, day) or make_date(year, day, month)


def read_iso(match):
    return make_date(int(match.group("year")), int(match.group("month")), int(match.group("day")))


def read_named(match):
    month = MONTHS[match.group("month")[:3].lower()]
    return make_date(int(match.group("year")), month, int(match.group("day")))


PATTERNS = [
    (DAY_MONTH_YEAR, read_named),
    (MONTH_DAY_YEAR, read_named),
    (ISO, read_iso),
    (NUMERIC, read_numeric),
]


def find_dates(line):
    """Return (start, end, date) for every date in one line of text, left to right."""
    found = []
    for pattern, read in PATTERNS:
        for match in pattern.finditer(line):
            overlaps = any(match.start() < end and start < match.end() for start, end, _ in found)
            when = None if overlaps else read(match)
            if when:
                found.append((match.start(), match.end(), when))
    return sorted(found)


# ---------- scoring ----------

# Words that say "this is the expiry date"
STRONG = re.compile(
    r"expir|\bexp\b|good\s*thru|\bend\s*date|\bends?\b|\bending\b|"
    r"\bvalid\s*(?:until|till|upto|up\s*to|thru|through|to)\b"
)
# Words that only hint at it
WEAK = re.compile(r"\bvalid|validity|renew")
# Words that say "this is some other date"
NEGATIVE = re.compile(
    r"issu|birth|\bdob\b|\bborn\b|purchas|printed|\bsince\b|joined|"
    r"\bstart|effective|\bfrom\b|commenc|invoice"
)
# Text between two dates that makes them a range: "01/01/2025 to 31/12/2025"
RANGE_JOIN = re.compile(r"^[ \t]*(?:(?:to|until|till|through|thru)\b|[-–—])")


def score_label(label):
    """How strongly the words before a date say 'this is the expiry date'."""
    label = label.lower()
    score = 0
    if STRONG.search(label):
        score += 4
    elif WEAK.search(label):
        score += 2
    if NEGATIVE.search(label):
        score -= 4
    return score


def find_expiry(text):
    """Return the most likely expiry date in `text` as Found(...), or None."""
    best = None
    previous_line = ""

    for line in text.splitlines():
        dates = find_dates(line)

        for i, (start, end, when) in enumerate(dates):
            # The label is the text between the previous date (or the line start) and this date
            between = line[dates[i - 1][1]:start] if i else line[:start]
            label = between[-LABEL_LENGTH:]

            # A date alone on its line: its label may be on the line above
            if i == 0 and not re.search(r"[A-Za-z]", label) and previous_line:
                if not find_dates(previous_line):
                    label = previous_line[-LABEL_LENGTH:]

            score = score_label(label)

            # "from X to Y": the second date is the end, the first is the start
            if i > 0 and RANGE_JOIN.match(between.lower()):
                score += 3
            if i + 1 < len(dates) and RANGE_JOIN.match(line[end:dates[i + 1][0]].lower()):
                score -= 3

            # Best score wins; if two dates tie, the later one wins
            if score >= MIN_SCORE and (best is None or (score, when) > (best.score, best.date)):
                best = Found(when, label.strip(), score)

        if line.strip():
            previous_line = line.strip()

    return best


# =====================================================================================
# analyse(): every possible expiry date, why it may be wrong, and what kind of result it is
# =====================================================================================

FAR_FUTURE_YEARS = 30                         # a date further away than this is suspicious
FAR_FUTURE_DAYS = round(FAR_FUTURE_YEARS * 365.25)
MIN_LEAD = 2          # the best date must beat the next different date by this many points
MIN_WORDS = 3         # fewer words than this (and no date, no expiry word) = unreadable
MAX_OTHERS = 5        # how many non-expiry dates are listed for information

# Flags stop a date from being filled in automatically. The user can still choose a flagged
# date (an "override"), except when it is not a real date at all.
UNSELECTABLE = {"not_a_date", "implausible_year"}
FLAG_TEXT = {
    "not_a_date": "is not a real calendar date, so it was probably misread",
    "implausible_year": "has a year outside 2000-2100, so it was probably misread",
    "before_issue": "is earlier than another date in the document that it should come after "
                    "(issue, start, purchase or birth date)",
    "far_future": f"is more than {FAR_FUTURE_YEARS} years away; a digit may have been misread "
                  "(for example 2029 read as 2099)",
    "year_only": "has only a year printed, so 31 December was assumed",
}
# Notes only inform; they never stop a date from being filled in
NOTE_TEXT = {
    "month_only": "Only the month and year are printed; the last day of that month was used.",
    "repaired": "Letters that look like digits were read as digits.",
}
ROLE_NAMES = {
    "expiry": "Possible expiry date", "issue": "Issue date", "birth": "Date of birth",
    "purchase": "Purchase date", "start": "Start date", "printed": "Print date",
    "other": "Date with no expiry wording",
}
ROLE_WORDS = [
    (re.compile(r"issu"), "issue"),
    (re.compile(r"birth|\bdob\b|\bborn\b"), "birth"),
    (re.compile(r"purchas|invoice"), "purchase"),
    (re.compile(r"\bstart|effective|\bfrom\b|commenc|\bsince\b|joined"), "start"),
    (re.compile(r"printed"), "printed"),
]
ANCHOR_ROLES = ("issue", "start", "purchase", "birth")   # an expiry date must not come before these


@dataclass
class Candidate:
    """A date found in the text. `date` is None when what was printed is not a real date."""
    raw: str
    date: object
    label: str
    context: str
    role: str
    score: int
    flags: list = field(default_factory=list)   # reasons not to trust it (see FLAG_TEXT)
    notes: list = field(default_factory=list)   # things worth knowing (see NOTE_TEXT)

    @property
    def selectable(self):
        return self.date is not None and not UNSELECTABLE.intersection(self.flags)

    @property
    def needs_override(self):
        return self.selectable and bool(self.flags)

    def to_dict(self):
        return {
            "raw": self.raw, "date": self.date.isoformat() if self.date else None,
            "label": self.label, "context": self.context, "role": self.role,
            "score": self.score, "flags": list(self.flags), "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data):
        when = date.fromisoformat(data["date"]) if data.get("date") else None
        return cls(data.get("raw", ""), when, data.get("label", ""), data.get("context", ""),
                   data.get("role", "expiry"), data.get("score", 0),
                   list(data.get("flags", [])), list(data.get("notes", [])))


# kind: unreadable / no_date / uninterpretable / one / several / flagged
Analysis = namedtuple("Analysis", ["kind", "candidates", "others", "wording"])


def last_day(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


# Partial dates. They are only used right after an expiry word (see scan()).
MONTH_YEAR_NAMED = re.compile(
    rf"(?<![A-Za-z])(?P<month>{MONTH_NAME})\b[ \t.,/\-]*(?P<year>(?:19|2[01])[0-9]{{2}})(?![0-9])",
    re.IGNORECASE,
)
MONTH_YEAR_NUM = re.compile(
    rf"{NOT_AFTER_DIGIT}(?<![/.\-])(?P<month>[0-9]{{1,2}}){SPACE}(?P<sep>[/.\-]){SPACE}"
    rf"(?P<year>(?:19|2[01])[0-9]{{2}})(?![0-9])"
)
# 06/07 followed by 2029 is a full date that OCR broke apart, not "June 2007"
MONTH_YY = re.compile(
    rf"{NOT_AFTER_DIGIT}(?<![/.\-])(?P<month>0?[1-9]|1[0-2]){SPACE}/{SPACE}(?P<yy>[0-9]{{2}})"
    rf"(?![0-9/.\-])(?![ \t]+[0-9]{{2,4}}\b)"
)
YEAR_ONLY = re.compile(r"(?<![0-9/.\-:,A-Za-z])(?P<year>20[0-9]{2})(?![0-9/.\-:A-Za-z])")

Match = namedtuple("Match", ["start", "end", "date", "raw", "flags", "notes", "needs"])


def full_date_match(match, read_parts, numeric=False):
    """Turn a full-date match into a Match; invalid dates are kept and flagged, not dropped."""
    year, orders = read_parts(match)
    when = next((d for d in (_calendar_date(year, m, d) for m, d in orders) if d), None)
    flags = []
    if when is None:
        flags.append("not_a_date")
    elif not MIN_YEAR <= when.year <= MAX_YEAR:
        flags.append("implausible_year")
    notes = ["repaired"] if numeric and re.search(r"[OolI|\]]", match.group(0)) else []
    return Match(match.start(), match.end(), when, match.group(0).strip(), flags, notes, 0)


def _calendar_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parts_numeric(match):
    day, month, year = (int(match.group(n).translate(FIX_DIGITS)) for n in ("day", "month", "year"))
    return year, [(month, day), (day, month)]       # day first, then month first


def _parts_iso(match):
    return int(match.group("year")), [(int(match.group("month")), int(match.group("day")))]


def _parts_named(match):
    return int(match.group("year")), [(MONTHS[match.group("month")[:3].lower()], int(match.group("day")))]


FULL_PATTERNS = [
    (DAY_MONTH_YEAR, _parts_named, False), (MONTH_DAY_YEAR, _parts_named, False),
    (ISO, _parts_iso, False), (NUMERIC, _parts_numeric, True),
]


def find_matches(line):
    """Every date-like piece of one line, left to right: full dates (also impossible ones),
    then partial dates (month and year, MM/YY, a bare year) in the gaps."""
    found = []

    def free(match):
        return not any(match.start() < m.end and m.start < match.end() for m in found)

    for pattern, parts, numeric in FULL_PATTERNS:
        for match in pattern.finditer(line):
            if free(match):
                found.append(full_date_match(match, parts, numeric))

    for pattern, kind in ((MONTH_YEAR_NAMED, "named"), (MONTH_YEAR_NUM, "num"),
                          (MONTH_YY, "yy"), (YEAR_ONLY, "year")):
        for match in pattern.finditer(line):
            if not free(match):
                continue
            # A bare year or MM/YY is only believed straight after an expiry word, with no digit
            # in between ("Valid until 14 Noy 2026" and "Exp: 0907, 2028" are broken dates)
            if kind in ("year", "yy"):
                tail = line[max(0, match.start() - 25):match.start()]
                if re.search(r"[0-9]", tail) or not STRONG.search(tail.lower()):
                    continue
            if kind == "year":
                year, when, flags, notes, needs = int(match.group("year")), None, ["year_only"], [], 4
                when = date(year, 12, 31)
            else:
                month = MONTHS[match.group("month")[:3].lower()] if kind == "named" else int(match.group("month"))
                if not 1 <= month <= 12:
                    continue
                year = int(match.group("year")) if kind != "yy" else 2000 + int(match.group("yy"))
                when, flags, notes = last_day(year, month), [], ["month_only"]
                needs = 4 if kind == "yy" else MIN_SCORE   # 05/27 could be day/month: be strict
            if not MIN_YEAR <= year <= MAX_YEAR:
                flags = flags + ["implausible_year"]
            found.append(Match(match.start(), match.end(), when, match.group(0).strip(), flags, notes, needs))
    return sorted(found)


def scan(text):
    """Every date-like piece of the text as a Candidate, with the same scoring as find_expiry."""
    candidates = []
    previous_line = ""
    for line in text.splitlines():
        matches = find_matches(line)
        for i, m in enumerate(matches):
            between = line[matches[i - 1].end:m.start] if i else line[:m.start]
            label = between[-LABEL_LENGTH:]
            if i == 0 and not re.search(r"[A-Za-z]", label) and previous_line:
                if not find_matches(previous_line):
                    label = previous_line[-LABEL_LENGTH:]

            score = score_label(label)
            starts_a_range = i + 1 < len(matches) and RANGE_JOIN.match(line[m.end:matches[i + 1].start].lower())
            if i > 0 and RANGE_JOIN.match(between.lower()):
                score += 3
            if starts_a_range:
                score -= 3

            if m.needs and score < m.needs:
                continue            # a partial date is only believed right after an expiry word

            if score >= MIN_SCORE:
                role = "expiry"
            elif starts_a_range:
                role = "start"
            else:
                low = label.lower()
                role = next((name for pattern, name in ROLE_WORDS if pattern.search(low)), "other")
            candidates.append(Candidate(
                raw=m.raw, date=m.date, label=label.strip()[-60:], context=line.strip()[:120],
                role=role, score=score, flags=list(m.flags), notes=list(m.notes),
            ))
        if line.strip():
            previous_line = line.strip()
    return candidates


def meaningful_words(text):
    return len(re.findall(r"[A-Za-z]{3,}", text))


def analyse(text, today=None):
    """Work out what the text says about an expiry date. Returns Analysis(kind, candidates, others, wording).

    kind:
      unreadable      almost no text, and no date or expiry word in it
      no_date         the text is readable but holds no expiry date or expiry word
      uninterpretable an expiry word is there but no usable date came with it
      one             one clear, unflagged expiry date (safe to fill in, still to be checked)
      several         more than one possible expiry date and no clear winner
      flagged         a clear winner, but it looks suspicious (see FLAG_TEXT)

    candidates: the possible expiry dates, best first (selectable ones, then impossible ones).
    others: other dates in the text (issue, birth, ...), for information only.
    wording: lines with expiry words, used when no date came with them.
    Nothing is thrown away silently: a date that cannot be used is listed with the reason.
    """
    today = today or date.today()
    text = text or ""
    found = scan(text)

    plausible = [c for c in found if c.score >= MIN_SCORE]
    # Earlier dates the expiry must not come before. A birth date from the 1980s is a real date
    # here even though no expiry date could be that old.
    anchors = [c.date for c in found if c.role in ANCHOR_ROLES and c.date]

    # The same date printed twice is one candidate; keep the strongest reading
    merged = {}
    for c in plausible:
        key = c.date if c.selectable or c.date else c.raw
        if key not in merged or c.score > merged[key].score:
            merged[key] = c
    for c in merged.values():
        if c.selectable:
            if (c.date - today).days > FAR_FUTURE_DAYS and "far_future" not in c.flags:
                c.flags.append("far_future")
            if anchors and c.date < max(anchors) and "before_issue" not in c.flags:
                c.flags.append("before_issue")

    selectable = sorted((c for c in merged.values() if c.selectable),
                        key=lambda c: (c.score, c.date), reverse=True)
    impossible = [c for c in merged.values() if not c.selectable]
    others, seen = [], set()
    for c in found:
        if c.score < MIN_SCORE and c.date and (c.date, c.role) not in seen:
            seen.add((c.date, c.role))
            others.append(c)
    others = others[:MAX_OTHERS]
    wording = [l.strip()[:100] for l in text.splitlines() if STRONG.search(l.lower())][:3]

    if selectable:
        clear = len(selectable) == 1 or selectable[0].score - selectable[1].score >= MIN_LEAD
        kind = ("flagged" if selectable[0].flags else "one") if clear else "several"
        return Analysis(kind, selectable + impossible, others, wording)
    if impossible or wording:
        return Analysis("uninterpretable", impossible, others, wording)
    if found or meaningful_words(text) >= MIN_WORDS:
        return Analysis("no_date", [], others, [])
    return Analysis("unreadable", [], [], [])


def has_expiry_date(text):
    """True when the text holds at least one date that could be offered as the expiry date."""
    return any(c.selectable for c in analyse(text).candidates)
