"""Creates synthetic sample documents, with an answer key, for testing the vault.

Every document is clearly marked SAMPLE, uses made-up names and issuers, and does
not copy the layout of any real government document or ID.

Run:  python make_samples.py                  -> 60 documents in the "samples" folder
      python make_samples.py --count 300      -> more documents
      python make_samples.py --seed 5         -> a different random set

The answer key (what each document's expiry date really is) is saved as
samples/labels.csv. Its "variant" column says how the image was made:
clean = flat scan, photo = phone photo, lowres = shrunk photo,
hard = angled, with glare or shadow, small and heavily compressed.
"""
import argparse
import csv
import os
import random
import re
from datetime import date, timedelta

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# ---------------------------------------------------------------- fonts

FONT_DIRS = [
    r"C:\Windows\Fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/crosextra",
    "/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
]

# (regular, bold) font files; only the ones installed on this computer are used
FONT_FAMILIES = [
    ("arial.ttf", "arialbd.ttf"),
    ("times.ttf", "timesbd.ttf"),
    ("calibri.ttf", "calibrib.ttf"),
    ("verdana.ttf", "verdanab.ttf"),
    ("tahoma.ttf", "tahomabd.ttf"),
    ("segoeui.ttf", "segoeuib.ttf"),
    ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
    ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf"),
    ("Carlito-Regular.ttf", "Carlito-Bold.ttf"),
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
]


def find_font(file_name):
    for folder in FONT_DIRS:
        path = os.path.join(folder, file_name)
        if os.path.exists(path):
            return path
    return None


def installed_families():
    families = []
    for regular, bold in FONT_FAMILIES:
        regular_path, bold_path = find_font(regular), find_font(bold)
        if regular_path and bold_path:
            families.append((regular_path, bold_path))
    return families or [(None, None)]  # None = Pillow's built-in font


_font_cache = {}


def get_font(path, size):
    key = (path, size)
    if key not in _font_cache:
        if path:
            _font_cache[key] = ImageFont.truetype(path, size)
        else:
            _font_cache[key] = ImageFont.load_default(size=size)
    return _font_cache[key]


def fit_font(draw, text, path, size, max_width):
    """Return the largest font (not above `size`) whose text fits in max_width."""
    while size > 14 and draw.textlength(text, font=get_font(path, size)) > max_width:
        size -= 2
    return get_font(path, size)


# ---------------------------------------------------------------- made-up data

FIRST_NAMES = [
    "Aarav", "Diya", "Rohan", "Sneha", "Kabir", "Meera", "Arjun", "Anaya",
    "Vikram", "Isha", "Nikhil", "Riya", "Sameer", "Tanvi", "Yash", "Pooja",
    "Karan", "Neha", "Rahul", "Priya",
]
LAST_NAMES = [
    "Sharma", "Patil", "Deshmukh", "Verma", "Kulkarni", "Iyer", "Singh", "Joshi",
    "Nair", "Khan", "Gupta", "Reddy", "Mehta", "Bose", "Pawar", "Thakur",
    "Menon", "Shah", "Rao", "Naik",
]

DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y",
    "%d %B %Y", "%B %d, %Y", "%Y-%m-%d", "%d-%b-%Y",
]
DATE_WEIGHTS = [40, 15, 8, 12, 8, 5, 5, 7]  # dd/mm/yyyy is the most common

GENERIC_EXPIRY_LABELS = [
    "Valid until", "Valid Upto", "Valid Thru", "Valid till", "Expiry Date",
    "Date of Expiry", "Expires on", "Expiry:", "Exp:",
]

CARD_EXPIRY_LABELS = ["Valid Upto", "Valid Thru", "Valid till", "Expiry Date", "Exp:"]


def pick_expiry(rng, today):
    """Some documents are already expired, some expire soon, most are fine."""
    roll = rng.random()
    if roll < 0.15:
        days = -rng.randint(1, 500)
    elif roll < 0.40:
        days = rng.randint(1, 60)
    else:
        days = rng.randint(61, 1800)
    return today + timedelta(days=days)


# ---------------------------------------------------------------- document types
# Each builder returns the fixed content of one kind of document.

def build_id_card(rng, person):
    return {
        "category": "ID Proof", "prefix": "idcard", "shape": "card",
        "issuer": rng.choice([
            "Example Institute of Technology (SAMPLE)",
            "Demo Corp Ltd. (SAMPLE)",
            "Sample City Library",
        ]),
        "title": rng.choice(["STUDENT ID CARD", "EMPLOYEE ID CARD", "MEMBER ID CARD"]),
        "rows": [
            ("Name", person),
            ("ID No", f"SMP-{rng.randint(2020, 2026)}-{rng.randint(1000, 9999)}"),
            ("Department", rng.choice(["Computer Engineering", "Mechanical", "Accounts", "Library"])),
        ],
        "with_birth_date": True,
        "expiry_labels": CARD_EXPIRY_LABELS,
        "validity_years": [1, 2, 3, 4, 5],
        "accent": rng.choice([(25, 70, 130), (120, 30, 40), (30, 100, 70)]),
        "card_bg": (246, 247, 250),
    }


def build_insurance(rng, person):
    return {
        "category": "Insurance", "prefix": "insurance", "shape": "page",
        "issuer": rng.choice([
            "Example General Insurance Co. (SAMPLE)",
            "Sample Life Assurance Ltd.",
            "Demo Motor and Health Insurance",
        ]),
        "title": rng.choice(["POLICY SCHEDULE", "CERTIFICATE OF INSURANCE"]),
        "rows": [
            ("Policyholder", person),
            ("Policy No", f"POL/SMP/{rng.randint(2022, 2026)}/{rng.randint(100000, 999999)}"),
            ("Plan", rng.choice([
                "Comprehensive Motor Cover", "Family Health Floater",
                "Two-Wheeler Package Policy", "Home Protect Plan",
            ])),
            ("Sum Insured", f"Rs. {rng.choice([300000, 500000, 1000000, 2500000]):,}"),
            ("Premium Paid", f"Rs. {rng.randint(3000, 45000):,}"),
        ],
        "issue_label": "Date of Issue",
        "expiry_labels": GENERIC_EXPIRY_LABELS + ["Policy valid until", "Cover ends on"],
        "validity_years": [1],
        "accent": (20, 60, 120),
    }


def build_warranty(rng, person):
    product, code = rng.choice([
        ("Smart TV 43 inch", "TV"), ("Front Load Washing Machine", "WM"),
        ("Laptop 15.6 inch", "LP"), ("Split Air Conditioner 1.5 Ton", "AC"),
        ("Refrigerator 260 L", "RF"),
    ])
    return {
        "category": "Warranty", "prefix": "warranty", "shape": "page",
        "issuer": rng.choice(["Acme Electronics (SAMPLE)", "Demo Appliances Ltd. (SAMPLE)"]),
        "title": rng.choice(["WARRANTY CARD", "PRODUCT WARRANTY CERTIFICATE"]),
        "rows": [
            ("Customer", person),
            ("Product", product),
            ("Model No", f"{code}-{rng.randint(100, 999)}{rng.choice('ABCX')}"),
            ("Serial No", f"SN{rng.randint(100000000, 999999999)}"),
            ("Dealer", rng.choice(["Sample Retail Store", "Demo Electronics Mart"])),
            ("Warranty", rng.choice(["1 Year Comprehensive", "2 Years Comprehensive", "3 Years on Compressor"])),
        ],
        "issue_label": "Date of Purchase",
        "expiry_labels": GENERIC_EXPIRY_LABELS + ["Warranty valid until", "Warranty expires on"],
        "validity_years": [1, 2, 3],
        "accent": (150, 60, 20),
    }


def build_certificate(rng, person):
    return {
        "category": "Certificate", "prefix": "certificate", "shape": "certificate",
        "issuer": "Example Institute of Technology (SAMPLE)",
        "person": person,
        "course": rng.choice([
            "Python Programming Fundamentals", "Data Analysis with Spreadsheets",
            "First Aid and Safety Training", "Web Application Development",
        ]),
        "rows": [
            ("Certificate No", f"CERT-{rng.randint(10000, 99999)}"),
            ("Grade", rng.choice(["A", "A+", "B+"])),
        ],
        "issue_label": "Date of Issue",
        "expiry_labels": GENERIC_EXPIRY_LABELS + ["Certificate valid until"],
        "validity_years": [1, 2, 3, 5],
        "accent": (90, 40, 110),
    }


def build_health_card(rng, person):
    return {
        "category": "Medical", "prefix": "health", "shape": "card",
        "issuer": rng.choice(["Sample Health Plan (SAMPLE)", "Demo Care Insurance (SAMPLE)"]),
        "title": "HEALTH INSURANCE CARD",
        "rows": [
            ("Member", person),
            ("Member ID", f"HLT-{rng.randint(100000, 999999)}"),
            ("Plan", rng.choice(["Family Floater", "Individual Basic", "Senior Care"])),
        ],
        "with_birth_date": True,
        "expiry_labels": CARD_EXPIRY_LABELS + ["Cover valid until"],
        "validity_years": [1, 2],
        "accent": (0, 110, 120),
        "card_bg": (242, 249, 249),
    }


def build_membership(rng, person):
    return {
        "category": "Other", "prefix": "membership", "shape": "page",
        "issuer": rng.choice(["Demo Fitness Club (SAMPLE)", "Sample City Sports Club"]),
        "title": "MEMBERSHIP CERTIFICATE",
        "rows": [
            ("Member", person),
            ("Membership No", f"MEM-{rng.randint(10000, 99999)}"),
            ("Plan", rng.choice(["Annual Gold", "Annual Standard", "Premium"])),
            ("Branch", rng.choice(["Central Branch", "Lakeside Branch"])),
        ],
        "issue_label": "Member Since",
        "expiry_labels": GENERIC_EXPIRY_LABELS + ["Membership expires on", "Membership valid until"],
        "validity_years": [1, 2],
        "accent": (30, 110, 60),
    }


BUILDERS = [
    build_id_card, build_insurance, build_warranty,
    build_certificate, build_health_card, build_membership,
]


def assemble(spec, rng, today):
    """Adds the dates and returns (rows to print, answer key)."""
    date_format = rng.choices(DATE_FORMATS, weights=DATE_WEIGHTS)[0]

    def show(day):
        return day.strftime(date_format)

    rows = list(spec["rows"])
    expiry = pick_expiry(rng, today)
    issued = expiry - timedelta(days=365 * rng.choice(spec["validity_years"]))

    # Other dates on the document: the detector must not mistake them for the expiry
    if spec.get("issue_label"):
        rows.append((spec["issue_label"], show(issued)))
    if spec.get("with_birth_date"):
        born = today - timedelta(days=365 * rng.randint(18, 50) + rng.randint(0, 364))
        rows.append(("Date of Birth", show(born)))

    label = printed = expiry_iso = ""
    if rng.random() > 0.10:  # about one document in ten has no expiry date at all
        if spec["category"] == "Insurance" and rng.random() < 0.2:
            label = "Policy Period"
            start = expiry - timedelta(days=364)
            expiry_row = (label, f"{show(start)} to {show(expiry)}")
        else:
            label = rng.choice(spec["expiry_labels"])
            expiry_row = (label, show(expiry))
        printed, expiry_iso = show(expiry), expiry.isoformat()

        if spec["shape"] == "card":
            rows.append(expiry_row)  # on cards the expiry is the last line
        else:
            rows.insert(rng.randint(2, len(rows)), expiry_row)

    footer_date = ""
    if spec["shape"] == "page" and rng.random() < 0.4:
        footer_date = show(today - timedelta(days=rng.randint(0, 30)))

    key = {"expiry_date": expiry_iso, "printed_as": printed, "label_used": label}
    return rows, footer_date, key


# ---------------------------------------------------------------- drawing the documents

def add_watermark(img, bold_path, size, angle):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = get_font(bold_path, size)
    width = draw.textlength("SAMPLE", font=font)
    draw.text(
        ((img.width - width) / 2, img.height / 2 - size * 0.6), "SAMPLE",
        font=font, fill=(0, 0, 0, 28),
    )
    layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def render_page(spec, rows, footer_date, style, colon, family):
    """A portrait A4-style page: issuer, title and a list of fields."""
    regular, bold = family
    width, height = 1240, 1754
    page = add_watermark(Image.new("RGB", (width, height), (252, 251, 248)), bold, 300, 35)
    draw = ImageDraw.Draw(page)
    accent = spec["accent"]

    draw.text((90, 90), spec["issuer"], font=fit_font(draw, spec["issuer"], bold, 44, width - 180), fill=accent)
    draw.line([(90, 160), (width - 90, 160)], fill=accent, width=4)

    title_font = get_font(bold, 56)
    title_width = draw.textlength(spec["title"], font=title_font)
    draw.text(((width - title_width) / 2, 220), spec["title"], font=title_font, fill=(25, 25, 25))

    label_font = get_font(bold, 30)
    labels = [label + (":" if colon and not label.endswith(":") else "") for label, _ in rows]
    value_x = 110 + max(draw.textlength(text, font=label_font) for text in labels) + 40

    y = 370
    for text, (_, value) in zip(labels, rows):
        draw.text((110, y), text, font=label_font, fill=(70, 70, 70))
        if style == "table":
            x = value_x
            draw.line([(90, y + 52), (width - 90, y + 52)], fill=(210, 210, 210), width=2)
        else:
            x = 110 + draw.textlength(text, font=label_font) + 16
        value_font = fit_font(draw, value, regular, 31, width - 90 - x)
        draw.text((x, y), value, font=value_font, fill=(15, 15, 15))
        y += 74

    small = get_font(regular, 22)
    if footer_date:
        draw.text((90, height - 190), f"Printed on {footer_date}", font=small, fill=(120, 120, 120))
    draw.text(
        (90, height - 150),
        "SAMPLE DOCUMENT - generated for software testing - not valid for any purpose",
        font=small, fill=(120, 120, 120),
    )
    return page


def render_certificate(spec, rows, family):
    """A landscape certificate with centred text."""
    regular, bold = family
    width, height = 1754, 1240
    page = add_watermark(Image.new("RGB", (width, height), (253, 252, 247)), bold, 280, 25)
    draw = ImageDraw.Draw(page)
    accent = spec["accent"]
    draw.rectangle([40, 40, width - 40, height - 40], outline=accent, width=8)
    draw.rectangle([62, 62, width - 62, height - 62], outline=accent, width=2)

    def centred(text, y, font, fill):
        draw.text(((width - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)

    centred(spec["issuer"], 120, get_font(bold, 40), accent)
    centred("CERTIFICATE OF COMPLETION", 210, get_font(bold, 64), (25, 25, 25))
    centred("This is to certify that", 340, get_font(regular, 34), (70, 70, 70))
    centred(spec["person"], 410, get_font(bold, 68), (15, 15, 15))
    centred("has successfully completed the course", 520, get_font(regular, 34), (70, 70, 70))
    centred(spec["course"], 585, get_font(bold, 46), accent)

    y = 730
    for label, value in rows:
        centred(f"{label}: {value}", y, get_font(regular, 32), (30, 30, 30))
        y += 62

    draw.line([(width / 2 - 180, height - 210), (width / 2 + 180, height - 210)], fill=(80, 80, 80), width=2)
    centred("Authorised Signatory", height - 196, get_font(regular, 26), (80, 80, 80))
    centred("SAMPLE DOCUMENT - generated for software testing - not valid for any purpose",
            height - 122, get_font(regular, 22), (120, 120, 120))
    return page


def render_card(spec, rows, family):
    """A landscape card with a grey placeholder instead of a photo."""
    regular, bold = family
    width, height = 1011, 638
    card = add_watermark(Image.new("RGB", (width, height), spec["card_bg"]), bold, 170, 25)
    draw = ImageDraw.Draw(card)
    accent = spec["accent"]

    draw.rectangle([0, 0, width, 100], fill=accent)
    draw.text((30, 26), spec["issuer"], font=fit_font(draw, spec["issuer"], bold, 40, width - 60), fill="white")
    draw.text((30, 114), spec["title"], font=get_font(bold, 30), fill=accent)

    # Placeholder for the photo: a grey box with a simple head-and-shoulders shape
    draw.rectangle([36, 175, 266, 465], fill=(222, 224, 228), outline=(150, 150, 150), width=2)
    draw.ellipse([111, 205, 191, 285], fill=(170, 172, 178))
    draw.pieslice([56, 330, 246, 500], 180, 360, fill=(170, 172, 178))

    label_font, value_font = get_font(regular, 28), get_font(bold, 32)
    y = 165
    for index, (label, value) in enumerate(rows):
        text = label + ("" if label.endswith(":") else ":")
        draw.text((300, y), text, font=label_font, fill=(80, 80, 80))
        x = 300 + draw.textlength(text, font=label_font) + 14
        is_expiry_row = index == len(rows) - 1 and any(word in label.lower() for word in ("valid", "exp", "cover"))
        value_font = fit_font(draw, value, bold, 32, width - 30 - x)
        draw.text((x, y), value, font=value_font, fill=accent if is_expiry_row else (15, 15, 15))
        y += 58

    draw.rectangle([0, height - 52, width, height], fill=(232, 232, 232))
    note = "SAMPLE CARD - FOR SOFTWARE TESTING ONLY"
    note_font = get_font(regular, 22)
    draw.text(((width - draw.textlength(note, font=note_font)) / 2, height - 40), note, font=note_font, fill=(110, 110, 110))
    return card


# ---------------------------------------------------------------- making it look like a photo

DESK_COLORS = [(74, 62, 52), (92, 92, 98), (120, 98, 76), (58, 68, 80), (140, 140, 135), (46, 46, 50)]


def keystone(sheet, rng):
    """Make one edge of the sheet look farther away, as when a phone is held at an angle."""
    w, h = sheet.size
    s = int(min(w, h) * rng.uniform(0.04, 0.09))
    corners = rng.choice([
        [(-s, 0), (0, h), (w, h), (w + s, 0)],      # top edge farther away
        [(0, 0), (-s, h), (w + s, h), (w, 0)],      # bottom edge farther away
        [(0, -s), (0, h + s), (w, h), (w, 0)],      # left edge farther away
        [(0, 0), (0, h), (w, h + s), (w, -s)],      # right edge farther away
    ])
    flat = [value for point in corners for value in point]
    return sheet.transform((w, h), Image.Transform.QUAD, flat, Image.Resampling.BILINEAR)


def glare_or_shadow(picture, rng):
    """Add a bright reflection (lamp, window) or a dark patch (a hand or phone in the way)."""
    width, height = picture.size
    radius = int(min(width, height) * rng.uniform(0.14, 0.24))
    cx = rng.randint(width // 5, width * 4 // 5)
    cy = rng.randint(height // 5, height * 4 // 5)

    if rng.random() < 0.5:
        colour, strength = (255, 255, 255), rng.randint(110, 190)   # glare
    else:
        colour, strength = (15, 15, 15), rng.randint(70, 130)       # shadow

    patch = Image.new("L", picture.size, 0)
    ImageDraw.Draw(patch).ellipse([cx - radius * 1.5, cy - radius, cx + radius * 1.5, cy + radius], fill=strength)
    patch = patch.filter(ImageFilter.GaussianBlur(radius * 0.5))
    return Image.composite(Image.new("RGB", picture.size, colour), picture, patch)


def photograph(doc, rng, canvas_scale, rounded, hard=False):
    """Put the document on a desk: tilted, with shadow, uneven light, blur and noise.

    hard=True also tilts the sheet away from the camera and adds glare or a
    shadow, like a quick photo taken at an angle under a lamp.
    """
    doc_width, doc_height = doc.size
    width, height = int(doc_width * canvas_scale[0]), int(doc_height * canvas_scale[1])
    desk = Image.new("RGB", (width, height), rng.choice(DESK_COLORS))

    mask = Image.new("L", doc.size, 255)
    if rounded:
        mask = Image.new("L", doc.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, doc_width - 1, doc_height - 1], radius=36, fill=255)
    sheet = doc.convert("RGBA")
    sheet.putalpha(mask)
    if hard:
        sheet = keystone(sheet, rng)
    turn = 12 if hard else 6
    sheet = sheet.rotate(rng.uniform(-turn, turn), resample=Image.Resampling.BICUBIC, expand=True)

    x = (width - sheet.width) // 2 + rng.randint(-20, 20)
    y = (height - sheet.height) // 2 + rng.randint(-20, 20)

    shadow_mask = sheet.getchannel("A").point(lambda a: a * 120 // 255).filter(ImageFilter.GaussianBlur(14))
    desk.paste(Image.new("RGB", sheet.size, (0, 0, 0)), (x + 10, y + 14), shadow_mask)
    desk.paste(sheet, (x, y), sheet)

    # Uneven lighting: one side of the picture is darker than the other
    gradient = Image.linear_gradient("L").rotate(rng.choice([0, 90, 180, 270])).resize((width, height))
    floor = rng.randint(190, 235)
    light = gradient.point(lambda v: floor + v * (255 - floor) // 255)
    desk = ImageChops.multiply(desk, Image.merge("RGB", (light, light, light)))
    desk = ImageEnhance.Brightness(desk).enhance(rng.uniform(0.95, 1.2))
    if hard:
        desk = glare_or_shadow(desk, rng)

    desk = desk.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    noise = Image.effect_noise((width, height), rng.uniform(4, 9))
    return ImageChops.add(desk, Image.merge("RGB", (noise, noise, noise)), 1.0, -128)


# ---------------------------------------------------------------- main

def shrink(picture, scale):
    """Make the picture smaller, which also makes its text smaller and harder to read."""
    size = (int(picture.width * scale), int(picture.height * scale))
    return picture.resize(size, Image.Resampling.LANCZOS)


def variant_plan(count, rng):
    """Decide what kind of image each document becomes.

    The mix is exact, not luck of the draw: out of every 20 documents there are
    5 clean scans, 8 phone photos, 3 shrunk photos and 4 hard photos, in random order.
    """
    block = ["clean"] * 5 + ["photo"] * 8 + ["lowres"] * 3 + ["hard"] * 4
    plan = []
    while len(plan) < count:
        rng.shuffle(block)
        plan += block
    return plan[:count]


SAMPLE_NAME = re.compile(r"^(idcard|insurance|warranty|certificate|health|membership)_\d{3}\.(png|jpg)$")


def remove_old_samples(folder):
    """Delete only files made by an earlier run of this script."""
    for name in os.listdir(folder):
        if SAMPLE_NAME.match(name) or name == "labels.csv":
            os.remove(os.path.join(folder, name))


def main():
    parser = argparse.ArgumentParser(description="Create synthetic sample documents.")
    parser.add_argument("--count", type=int, default=60, help="how many documents (default 60)")
    parser.add_argument("--seed", type=int, default=7, help="same seed = same documents")
    parser.add_argument("--out", default="samples", help="output folder (default: samples)")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    variants = variant_plan(args.count, rng)
    families = installed_families()
    today = date.today()

    os.makedirs(args.out, exist_ok=True)
    remove_old_samples(args.out)

    with open(os.path.join(args.out, "labels.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "category", "expiry_date", "printed_as", "label_used", "layout", "variant"])

        counters = {}
        for number in range(args.count):
            person = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            spec = BUILDERS[number % len(BUILDERS)](rng, person)
            rows, footer_date, key = assemble(spec, rng, today)
            family = rng.choice(families)
            style = rng.choice(["inline", "table"])
            colon = rng.random() < 0.75

            if spec["shape"] == "card":
                layout, canvas, rounded = "card", (1.35, 1.9), True
                document = render_card(spec, rows, family)
            elif spec["shape"] == "certificate":
                layout, canvas, rounded = "certificate", (1.12, 1.2), False
                document = render_certificate(spec, rows, family)
            else:
                layout, canvas, rounded = style, (1.17, 1.1), False
                document = render_page(spec, rows, footer_date, style, colon, family)

            variant = variants[number]
            counters[spec["prefix"]] = counters.get(spec["prefix"], 0) + 1
            base = f"{spec['prefix']}_{counters[spec['prefix']]:03d}"

            if variant == "clean":
                file_name = base + ".png"
                document.save(os.path.join(args.out, file_name), optimize=True)
            else:
                picture = photograph(document, rng, canvas, rounded, hard=(variant == "hard"))
                quality = rng.randint(60, 85)
                if variant == "lowres":  # like a photo that was shrunk by a chat app
                    picture = shrink(picture, rng.uniform(0.68, 0.8))
                elif variant == "hard":  # small, soft and heavily compressed
                    picture = shrink(picture, rng.uniform(0.5, 0.65))
                    picture = picture.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 0.9)))
                    quality = rng.randint(30, 50)
                file_name = base + ".jpg"
                picture.save(os.path.join(args.out, file_name), quality=quality)

            writer.writerow([
                file_name, spec["category"], key["expiry_date"], key["printed_as"],
                key["label_used"], layout, variant,
            ])
            print(f"{number + 1:>4}/{args.count}  {file_name}")

    print(f"\nDone. {args.count} documents and labels.csv are in the '{args.out}' folder.")


if __name__ == "__main__":
    main()
