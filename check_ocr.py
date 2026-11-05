"""Checks that Tesseract is installed and can read text.

Run:  python check_ocr.py
"""
import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

from ocr import extract_text, tesseract_version

version = tesseract_version()
if version is None:
    print("Tesseract was NOT found.")
    print("1. Install it from https://github.com/UB-Mannheim/tesseract/wiki")
    print("2. Close this terminal, open a new one, and run this check again.")
    print("If it is installed in a custom folder, set the TESSERACT_CMD")
    print("environment variable to the full path of tesseract.exe.")
    raise SystemExit(1)

print("Tesseract found, version", version)

sample = "Insurance policy valid until 31/12/2030"
image = Image.new("RGB", (1600, 200), "white")
font = ImageFont.load_default(size=48)
ImageDraw.Draw(image).text((40, 60), sample, fill="black", font=font)

with tempfile.TemporaryDirectory() as folder:
    path = os.path.join(folder, "sample.png")
    image.save(path)
    result = extract_text(path)

print("Text read from the sample image:", repr(result))
if "31/12/2030" in result:
    print("OCR is working.")
else:
    print("Tesseract ran, but the sample text was not read correctly.")
    raise SystemExit(1)
