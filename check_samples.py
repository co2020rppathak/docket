"""Checks how well text extraction finds the expiry date on the sample images.

Run:  python check_samples.py

It reads samples/labels.csv (the answer key made by make_samples.py), reads the
text of every image with the same OCR code the app uses (ocr.py), and reports
how often the printed expiry date was found in that text.
"""
import csv
import os
import re
import sys
import time
from collections import defaultdict

from ocr import extract_text, OCRUnavailable

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")


def squash(text):
    """Lower-case the text and keep only letters and digits.

    This way "08.11.2026" and "08 11 2026" count as the same date: spacing and
    punctuation differences are not mistakes, but a wrongly read digit is.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def load_labels():
    path = os.path.join(SAMPLES_DIR, "labels.csv")
    if not os.path.exists(path):
        sys.exit("samples/labels.csv was not found. Run make_samples.py first.")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def percent(found, total):
    if total == 0:
        return "-"
    return f"{found}/{total} ({100 * found / total:.0f}%)"


def print_table(title, tally):
    print(f"\n{title}")
    for name in sorted(tally):
        found, total = tally[name]
        print(f"  {name:<12} {percent(found, total)}")


def main():
    # Odd characters in the OCR text must not crash the report on a Windows console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    rows = load_labels()

    # tally[group][value] = [found, total]
    groups = {key: defaultdict(lambda: [0, 0]) for key in ("variant", "category", "layout")}
    misses = []
    overall = [0, 0]
    skipped = 0
    started = time.time()

    for row in rows:
        if not row["expiry_date"]:
            skipped += 1  # nothing printed on this document, nothing to find
            continue

        path = os.path.join(SAMPLES_DIR, row["filename"])
        try:
            text = extract_text(path)
        except OCRUnavailable:
            sys.exit("Tesseract is not installed. Run check_ocr.py for help.")

        found = squash(row["printed_as"]) in squash(text)

        overall[1] += 1
        overall[0] += found
        for key in groups:
            groups[key][row[key]][1] += 1
            groups[key][row[key]][0] += found

        print(f"{'found ' if found else 'MISSED'}  {row['filename']:<22} {row['printed_as']}")
        if not found:
            misses.append((row, text))

    print("\n" + "=" * 50)
    print(f"Expiry date found: {percent(*overall)}")
    print(f"Documents with no expiry printed (skipped): {skipped}")
    print(f"Time taken: {time.time() - started:.0f} seconds")

    print_table(
        "By image type (clean = scan, photo = phone photo, lowres = shrunk photo,\n"
        "              hard = angled, glare or shadow, small, compressed)",
        groups["variant"],
    )
    print_table("By category", groups["category"])
    print_table("By layout", groups["layout"])

    if misses:
        print("\n" + "=" * 50)
        print("What was read on the missed documents (lines containing a 4-digit number):")
        for row, text in misses:
            print(f"\n{row['filename']}  expected: {row['printed_as']}")
            lines = [line for line in text.splitlines() if re.search(r"\d{4}", line)]
            for line in lines or ["(no line with a 4-digit number)"]:
                print(f"    {line}")


if __name__ == "__main__":
    main()
