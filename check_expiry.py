"""Measures how well the app finds the expiry date on the sample documents.

Run:  python check_expiry.py

For every document in samples/labels.csv (the answer key made by make_samples.py)
it reads the text with the app's OCR, runs the expiry detector on that text, and
compares the result with the true expiry date.

If there is no samples folder yet, run make_samples.py first.
"""
import csv
import os
import re
import sys
import time
from collections import defaultdict

from expiry import analyse, has_expiry_date
from ocr import extract_text, OCRUnavailable

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Usage: python check_expiry.py [folder]   (default folder: samples)
SAMPLES_DIR = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(BASE_DIR, "samples")


def squash(text):
    """Lower-case and keep only letters and digits (spacing differences do not matter)."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def load_labels():
    path = os.path.join(SAMPLES_DIR, "labels.csv")
    if not os.path.exists(path):
        sys.exit("samples/labels.csv was not found. Run make_samples.py first.")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def percent(part, total):
    return f"{part}/{total} ({100 * part / total:.0f}%)" if total else "-"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # odd OCR characters must not crash the report

    rows = load_labels()
    started = time.time()

    # Documents that have an expiry date printed on them
    correct = []        # the right date was found
    wrong = []          # a different date was found (the dangerous case)
    missed_ocr = []     # nothing found, because OCR never read the date
    missed_rule = []    # nothing found, although the date was in the text
    by_type = defaultdict(lambda: [0, 0])   # image type -> [correct, total]

    # Documents with no expiry date printed on them
    left_empty = []     # correctly nothing found
    invented = []       # a date was filled in where there is none
    offered_right = []  # several or suspicious dates were put up for the user to choose, the right one among them
    offered_wrong = []  # ... but the right date was not among them
    offered_noise = []  # ... for a document that has no expiry date
    outcomes = defaultdict(int)   # what the analysis said, by kind

    date_read_by_ocr = 0   # printed dates that OCR managed to read exactly
    right_when_read = 0    # of those, how many the detector then picked correctly

    for row in rows:
        path = os.path.join(SAMPLES_DIR, row["filename"])
        try:
            # The same reading the app does: read again if the first reading has no date
            text = extract_text(path, good_enough=has_expiry_date)
        except OCRUnavailable:
            sys.exit("Tesseract is not installed. Run check_ocr.py for help.")

        analysis = analyse(text)
        outcomes[analysis.kind] += 1
        # Only one clear, unflagged date is filled in; several or suspicious dates wait for the user
        found = analysis.candidates[0] if analysis.kind == "one" else None
        got = found.date.isoformat() if found else ""
        offered = [c.date.isoformat() for c in analysis.candidates if c.selectable] if analysis.kind in ("several", "flagged") else []
        expected = row["expiry_date"]

        if not expected:
            if offered:
                offered_noise.append(row)
                print(f"offered {row['filename']:<22} (no expiry printed) {', '.join(offered)}")
                continue
            (invented if got else left_empty).append((row, got, found, text))
            print(f"{'FALSE ' if got else 'ok    '}  {row['filename']:<22} (no expiry printed) {got}")
            continue

        readable = squash(row["printed_as"]) in squash(text)
        date_read_by_ocr += readable
        by_type[row["variant"]][1] += 1

        if got == expected:
            correct.append(row)
            right_when_read += readable
            by_type[row["variant"]][0] += 1
            print(f"ok      {row['filename']:<22} {got}")
        elif offered:
            (offered_right if expected in offered else offered_wrong).append(row)
            print(f"offered {row['filename']:<22} expected {expected}, offered {', '.join(offered)}")
        elif got:
            wrong.append((row, got, found, text))
            print(f"WRONG   {row['filename']:<22} expected {expected}, got {got}")
        elif readable:
            missed_rule.append((row, got, found, text))
            print(f"MISSED  {row['filename']:<22} expected {expected} (it was in the text)")
        else:
            missed_ocr.append((row, got, found, text))
            print(f"missed  {row['filename']:<22} expected {expected} (OCR did not read it)")

    with_date = len(correct) + len(wrong) + len(missed_ocr) + len(missed_rule) + len(offered_right) + len(offered_wrong)
    without_date = len(left_empty) + len(invented)

    print("\n" + "=" * 56)
    print(f"Documents with an expiry date printed: {with_date}")
    print(f"  found the right date        {percent(len(correct), with_date)}")
    print(f"  found a WRONG date          {len(wrong)}      <- the worst case")
    print(f"  put up for choosing, right date among them  {len(offered_right)}")
    print(f"  put up for choosing, right date NOT among them  {len(offered_wrong)}")
    print(f"  found nothing (OCR failed)  {len(missed_ocr)}")
    print(f"  found nothing (rule failed) {len(missed_rule)}")
    print(f"Documents with no expiry date printed: {without_date}")
    print(f"  correctly left empty        {percent(len(left_empty), without_date)}")
    print(f"  filled in a date anyway     {len(invented)}")
    print(f"  put dates up for choosing   {len(offered_noise)}")
    print("What the analysis said: " + ", ".join(f"{kind} {count}" for kind, count in sorted(outcomes.items())))

    print(f"\nOCR read the printed date correctly in {percent(date_read_by_ocr, with_date)} of them.")
    print(f"Of those, the detector picked the right date in {percent(right_when_read, date_read_by_ocr)}.")
    print(f"Time taken: {time.time() - started:.0f} seconds")

    print("\nRight date found, by image type (clean = scan, photo = phone photo, lowres = shrunk")
    print("photo, hard = angled, glare or shadow, small, compressed):")
    for name in sorted(by_type):
        right, total = by_type[name]
        print(f"  {name:<8} {percent(right, total)}")

    problems = wrong + invented + missed_rule
    if problems:
        print("\n" + "=" * 56)
        print("Mistakes made by the detector itself (not by OCR):")
        for row, got, found, text in problems:
            print(f"\n{row['filename']}  printed: {row['printed_as'] or '(none)'}  suggested: {got or '(nothing)'}")
            if found:
                print(f"    because the words before it were: {found.label!r} (score {found.score})")
            for line in [l for l in text.splitlines() if re.search(r"\d{4}", l)]:
                print(f"    text: {line}")


if __name__ == "__main__":
    main()
