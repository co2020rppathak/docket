"""Guesses the category of a document from the text that OCR read from it.

How it works:
1. Every category has a list of word patterns, each worth some points
   ("insured" says a lot about Insurance; "date of birth" says little about anything).
2. A pattern counts once, however many times it appears. A category's score is the
   sum of the points of the patterns found in the text.
3. The best category wins only if its score is high enough AND it is clearly ahead of
   the second best. Otherwise the answer is "not sure" (None): a document with no
   category guess is better than one filed in the wrong place.
"""
import re
from collections import namedtuple

# category = the guess, score = its points, words = the text that earned them
Guess = namedtuple("Guess", ["category", "score", "words"])

MIN_SCORE = 4   # the winner needs at least this many points
MIN_LEAD = 2    # ...and at least this many more than the runner-up

# category -> [(pattern, points)]. Patterns are matched against lower-case text.
RULES = {
    "ID Proof": [
        (r"\bid card\b|identity card", 4),
        (r"\b(?:student|employee) id\b", 4),
        (r"\baadh?a+r\b|\bpassport\b|\bvoter\b|driving licen[cs]e|permanent account", 4),
        (r"\bid no\b|\bidentity\b", 3),
        (r"\bdepartment\b|\bdesignation\b", 1),
        (r"date of birth|\bdob\b", 1),
    ],
    "Insurance": [
        (r"insur\w*|assurance", 3),
        (r"\bpolic(?:y|yholder)\b|policy holder", 3),
        (r"sum insured|premium paid|premium amount", 3),
        (r"\bnominee\b", 2),
        (r"\bcover(?:age)?\b", 1),
        (r"\bpremium\b", 1),
    ],
    "Warranty": [
        (r"warrant(?:y|ies)|guarantee", 5),
        (r"serial n(?:o|umber)\b", 2),
        (r"model n(?:o|umber)\b", 2),
        (r"date of purchase|purchase date", 2),
        (r"\bdealer\b|\bretailer\b", 1),
        (r"\bproduct\b", 1),
    ],
    "Certificate": [
        (r"this is to certify|certified that", 4),
        (r"\bcertif(?:y|ied|icate of completion)\b", 3),
        (r"\bcertificate\b", 2),
        (r"\bcompleted\b|\bcompletion\b|\bcourse\b", 2),
        (r"\bgrade\b|\bdiploma\b|\bdegree\b|\bawarded\b", 2),
        (r"\binstitute\b|\buniversity\b|\bcollege\b", 1),
    ],
    "Medical": [
        (r"\bhealth\b", 3),
        (r"medical|hospital|\bclinic\b|pharmacy", 3),
        (r"\bpatient\b|\bdoctor\b", 3),
        (r"prescription|diagnos\w*|vaccin\w*", 3),
        (r"health insurance|mediclaim|cashless", 2),
        (r"\bmember id\b", 2),
    ],
    "Other": [
        (r"membership|member since", 4),
        (r"\bclub\b|\bgym\b|fitness|\bsports\b", 3),
        (r"subscription|receipt|invoice|\bbill\b", 2),
    ],
}

COMPILED = {
    category: [(re.compile(pattern), points) for pattern, points in rules]
    for category, rules in RULES.items()
}


def score_categories(text):
    """Return {category: (score, [words found])} for every category."""
    text = text.lower()
    scores = {}
    for category, rules in COMPILED.items():
        total, words = 0, []
        for pattern, points in rules:
            match = pattern.search(text)
            if match:
                total += points
                words.append(match.group(0))
        scores[category] = (total, words)
    return scores


def guess_category(text):
    """Return the most likely Guess(category, score, words) for `text`, or None if not sure."""
    scores = score_categories(text or "")
    ranked = sorted(scores.items(), key=lambda item: item[1][0], reverse=True)
    (best, (best_score, words)), (_, (second_score, _)) = ranked[0], ranked[1]

    if best_score < MIN_SCORE or best_score - second_score < MIN_LEAD:
        return None
    return Guess(best, best_score, words)
