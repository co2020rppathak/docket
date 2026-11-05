"""Reads the text out of a document image using Tesseract OCR."""
import os
import shutil

import pytesseract
from PIL import Image, ImageOps

# Places where the Windows installer puts Tesseract
_WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]

# Small images are enlarged to MIN_WIDTH (better accuracy);
# huge images are shrunk to MAX_WIDTH (keeps reading time short)
MIN_WIDTH = 1600
MAX_WIDTH = 3200

# Tesseract normally finds the page layout by itself. "--psm 6" tells it the page is one
# block of text, which keeps a label and its value together on one line in a table.
ROWS_MODE = "--psm 6"


def _configure_tesseract():
    """Tell pytesseract where tesseract.exe is, if it is not on the PATH."""
    custom = os.environ.get("TESSERACT_CMD")
    if custom:
        pytesseract.pytesseract.tesseract_cmd = custom
    elif shutil.which("tesseract") is None:
        for path in _WINDOWS_PATHS:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break


_configure_tesseract()


class OCRUnavailable(Exception):
    """Raised when Tesseract is not installed or cannot be found."""


def tesseract_version():
    """Return the Tesseract version as text, or None if it is missing."""
    try:
        return str(pytesseract.get_tesseract_version())
    except pytesseract.TesseractNotFoundError:
        return None


def prepare_image(path):
    """Open an image and make it easier for Tesseract to read."""
    with Image.open(path) as original:
        # Phone photos can be stored sideways; this turns them upright
        image = ImageOps.exif_transpose(original)

        # Transparent PNGs: put them on a white background first
        if "A" in image.getbands() or "transparency" in image.info:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            image = Image.alpha_composite(background, image)

        image = image.convert("L")  # grayscale

    new_width = min(max(image.width, MIN_WIDTH), MAX_WIDTH)
    if new_width != image.width:
        new_height = round(image.height * new_width / image.width)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    return ImageOps.autocontrast(image)


def clean_text(text):
    """Trim spaces and collapse long runs of blank lines."""
    lines = [line.strip() for line in text.splitlines()]
    cleaned = []
    for line in lines:
        if line == "" and (not cleaned or cleaned[-1] == ""):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def read_image(image, config=""):
    """Run Tesseract once and return the cleaned-up text."""
    return clean_text(pytesseract.image_to_string(image, config=config, timeout=60))


def extract_text(path, good_enough=None):
    """Return the text found in the image at `path` (may be empty).

    `good_enough` is optional: a function that gives a true value when a text
    contains what the caller is looking for (for example an expiry date). If the
    first reading is not good enough, the page is read a second time with the page
    treated as one block of text, which keeps the rows of a table together. The
    second reading is used only if it is good enough.
    """
    image = prepare_image(path)
    try:
        text = read_image(image)
        if good_enough is not None and not good_enough(text):
            try:
                second = read_image(image, ROWS_MODE)
            except RuntimeError:
                second = ""  # a failed second reading must not spoil the first one
            if good_enough(second):
                return second
        return text
    except pytesseract.TesseractNotFoundError as error:
        raise OCRUnavailable("Tesseract is not installed.") from error
