"""Measures how well the app guesses the category of the sample documents.

Run:  python check_categories.py [folder]      (default folder: samples)

For every document in labels.csv (the answer key made by make_samples.py) it reads
the text the same way the app does, guesses the category, and compares the guess
with the true category.
"""
import csv
import os
import sys
import time
from collections import Counter, defaultdict

from categorize import guess_category
from expiry import find_expiry
from ocr import extract_text, OCRUnavailable

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SAMPLES_DIR = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(BASE_DIR, "samples")


def percent(part, total):
    return f"{part}/{total} ({100 * part / total:.0f}%)" if total else "-"


def main():
    path = os.path.join(SAMPLES_DIR, "labels.csv")
    if not os.path.exists(path):
        sys.exit("samples/labels.csv was not found. Run make_samples.py first.")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    started = time.time()
    right, wrong, unsure = [], [], []
    by_type = defaultdict(lambda: [0, 0])
    mixups = Counter()

    for row in rows:
        try:
            text = extract_text(os.path.join(SAMPLES_DIR, row["filename"]), good_enough=find_expiry)
        except OCRUnavailable:
            sys.exit("Tesseract is not installed. Run check_ocr.py for help.")
        guess = guess_category(text)
        by_type[row["variant"]][1] += 1

        if guess is None:
            unsure.append(row)
            print(f"unsure  {row['filename']:<22} (is {row['category']})")
        elif guess.category == row["category"]:
            right.append(row)
            by_type[row["variant"]][0] += 1
            print(f"ok      {row['filename']:<22} {guess.category}")
        else:
            wrong.append(row)
            mixups[(row["category"], guess.category)] += 1
            print(f"WRONG   {row['filename']:<22} is {row['category']}, guessed {guess.category} ({', '.join(guess.words)})")

    total = len(rows)
    print("\n" + "=" * 56)
    print(f"Documents: {total}")
    print(f"  right category      {percent(len(right), total)}")
    print(f"  WRONG category      {len(wrong)}      <- the worst case")
    print(f"  not sure (Other)    {len(unsure)}")
    for (real, said), count in mixups.most_common():
        print(f"    {real} taken for {said}: {count}")
    print(f"Time taken: {time.time() - started:.0f} seconds")
    print("\nRight category, by image type:")
    for name in sorted(by_type):
        print(f"  {name:<8} {percent(*by_type[name])}")


if __name__ == "__main__":
    main()
