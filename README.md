# Docket

**Intelligent Document Management System for Automated Categorization and Expiry Detection**

Project Phase 1 · Computer Engineering · BIT Wardha

Docket keeps a person's important documents (insurance policies, warranty cards, certificates, IDs, medical papers) in one place. You upload a photo or scan. The system reads the text with OCR, finds the expiry date, guesses the category, and shows on a dashboard what has expired or is about to.

**One rule runs through the whole project: the system suggests, the user decides.** Anything the system finds is marked as a guess ("Check", "Auto", "Please check") until the user confirms it. A date or category the user has set is never overwritten. When the system is not sure, it shows nothing rather than a wrong answer.

---

## 1. What it does

| Area | What the user gets |
|---|---|
| Accounts | Register, log in, log out. Every user sees only their own documents. |
| Upload | JPG or PNG, up to 5 MB, with a title, an optional category and an optional expiry date. Drag-and-drop with an image preview. |
| Text reading | Tesseract OCR reads the image. If the first reading finds no date, the page is read a second time in a different mode. |
| Expiry detection | Finds dates next to words like "valid until", "expires on", "expiry date". Skips birth, issue and purchase dates. Understands 8 date formats, including month and year only. |
| Several or suspicious dates | If two dates compete, or one looks wrong (more than 30 years away, earlier than the issue date, not a real calendar date), nothing is filled in. The document page lists the candidates with the line they came from, and the user chooses. |
| Categorization | Insurance, Warranty, Certificate, ID Proof, Medical or Other, chosen from the words in the text. If no category is clearly ahead, the answer is "Other" and it is left unconfirmed. |
| Status | Expired, Expiring soon (30 days or fewer), Valid, or No date. Calculated every time a page is shown, never stored. |
| Dashboard | Counts, a deadline timeline (Overdue / Next 30 days / 31 to 90 days / Later), a "Needs attention" filter, and a table of all documents. |
| Document page | The image, category and date with confirm / change / remove, the extracted text, "Check the document again" and "Extract text again". |
| Test Results page | Public page at `/test-results` showing the recorded testing figures. It only displays them and never runs a test. |

---

## 2. Requirements

- Python 3.13 or newer (tested on 3.13 on Linux and 3.14 on Windows)
- Tesseract OCR 5 (the program, not just the Python package)
- The Python packages in `requirements.txt`: Flask, Flask-SQLAlchemy, pytesseract, Pillow

No internet connection is needed to run the application. Text is read on your own computer.

---

## 3. Installation (Windows)

1. **Install Python** from python.org. Tick "Add python.exe to PATH" in the installer.
2. **Install Tesseract.** Download the Windows installer from the UB Mannheim page (`github.com/UB-Mannheim/tesseract/wiki`) and keep the default install folder, `C:\Program Files\Tesseract-OCR`. The application finds it there by itself. If you installed it somewhere else, set the full path before starting:
   ```
   set TESSERACT_CMD=D:\Tools\Tesseract-OCR\tesseract.exe
   ```
3. **Unzip the project** and open a terminal in the `doc-vault` folder.
4. **Create a virtual environment and install the packages:**
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
5. **Check that text reading works:**
   ```
   python check_ocr.py
   ```
   It prints the Tesseract version and reads a small test image. If it says Tesseract was not found, see Troubleshooting below.
6. **Start the application:**
   ```
   python app.py
   ```
7. Open **http://127.0.0.1:5000** in a browser.

The database (`instance/vault.db`) and the `uploads/` folder are created automatically on first start.

*Linux or macOS:* install Tesseract with `sudo apt install tesseract-ocr` or `brew install tesseract`, activate the environment with `source venv/bin/activate`, and the rest is the same.

---

## 4. Using it

1. Create an account, then log in.
2. Choose **Upload document**, pick an image, give it a title and press Upload. Leave the category on "Detect automatically" and the date empty to let the system read the document. Reading takes a second or two.
3. A date or category found by the system is marked **Check** or **Please check**. Open the document, compare it with the image, and press **Yes, this is correct** or change it.
4. If the system could not decide, the document page explains why and, for competing dates, lists the candidates. Choose **Use this date**, or set a date yourself.
5. The dashboard lists what needs attention. **Check the document again** re-reads the image and shows the date it finds next to yours without changing yours.

The `demo_samples/` folder holds a few images for trying this out. `docs/DEMO.md` is a step-by-step demonstration script.

---

## 5. Tests and checks

Run from the project folder, with the environment active:

```
python -m unittest
```

This runs **158 tests** in under a minute: expiry detection 47, status 13, categorization 20, application 78. The application tests use a temporary database, so your own data is never touched, and several restart the application in a new process to prove that data survives.

Measurement scripts for the sample images (the `samples/` folder, with its answer key `samples/labels.csv`):

| Command | What it measures |
|---|---|
| `python check_ocr.py` | Tesseract is installed and can read text. |
| `python check_expiry.py` | Expiry detection on the 60 sample images: 46 of 52 printed dates found, 0 wrong, 8 of 8 documents without a date left empty. |
| `python check_categories.py` | Category guesses on the same images, against the answer key: 56 of 60 right, 4 left as "Other" because the system was not sure, 0 wrong. |
| `python check_samples.py` | OCR only: did Tesseract read the printed date at all (46 of 52)? Breaks the result down by image type, category and layout, and shows what it read on each missed document. Always reads `samples/`. |
| `python check_db.py` | Lists registered users. |

The sample images are synthetic. Every one is marked SAMPLE and uses made-up names. `make_samples.py` is the program that created them. To make a new set, run `python make_samples.py --count 20 --out demo_set` and then `python check_expiry.py demo_set`. Always give `--out`: without it the program replaces the images in `samples/`.

**Where the figures on the Test Results page come from.** The 158 tests and the 60-image figures can be reproduced with this project as shipped. The 300-document evaluation, the 180-document categorization figure and the 34 mutation checks were run during development with extra images and scripts that are not part of this zip.

---

## 6. Project structure

```
doc-vault/
├── app.py              Routes, login, upload rules, page rendering
├── models.py           Database tables: User, Document
├── ocr.py              Prepares the image and runs Tesseract
├── expiry.py           Finds and judges expiry dates in text
├── categorize.py       Guesses the category from words in the text
├── status.py           Expired / soon / valid from a date
├── templates/          HTML pages (Jinja2)
├── static/style.css    All styling, including the automatic dark mode
├── uploads/            Uploaded images (created automatically)
├── instance/vault.db   SQLite database (created automatically)
├── samples/            60 synthetic test images and labels.csv
├── demo_samples/       Images used by the demonstration
├── docs/DEMO.md        Demonstration script and checklist
├── test_*.py           The 158 automated tests
├── check_*.py          Measurement and setup checks
└── make_samples.py     Creates the synthetic sample set
```

---

## 7. How it works

### Components

```
 Browser ── HTTP ──►  app.py  (routes, login, upload rules, pages)
                        │
        ┌───────────────┼────────────────┬─────────────────┐
        ▼               ▼                ▼                 ▼
      ocr.py         expiry.py      categorize.py       status.py
   image → text   text → dates    text → category    date → status
   (Tesseract)
                        │
                        ▼
                    models.py ──► SQLite (instance/vault.db)
                                  + image files in uploads/
```

### What happens when a document is uploaded

1. **Checks.** A title is present, the extension is JPG or PNG, the file is no larger than 5 MB, it really is an image, and its pixel count is sane. Anything else is refused with a message.
2. **Save.** The image is stored under a random file name. The original name is never used on disk.
3. **Read.** `ocr.py` turns the image upright, converts it to grayscale, resizes it to between 1600 and 3200 pixels wide and boosts the contrast. Tesseract reads it. If that text contains no expiry date, the page is read again with the whole page treated as one block of text, which keeps a label and its value on one line. The second reading is used only if it does better.
4. **Analyse.** `expiry.analyse()` finds every date, scores each by the words before it, and returns one of six results:

   | Result | Meaning | What the user sees |
   |---|---|---|
   | one | One clear expiry date | Filled in, marked **Check** |
   | several | Two or more compete | Nothing filled in; the candidates are listed to choose from |
   | flagged | A date looks suspicious | Nothing filled in; offered with a warning and "Use this date anyway" |
   | uninterpretable | A date was seen but is not a real date | Explained; set it yourself |
   | no_date | Text was read, no expiry date in it | Left empty, with the reason |
   | unreadable | Too little text to judge | "Not enough text could be read" |

5. **Categorize.** `categorize.guess_category()` adds up points for word patterns per category. The winner needs at least 4 points and a lead of at least 2 over the runner-up, otherwise the category is "Other" and unconfirmed.
6. **Store.** Only a clear result is saved as the document's date. Competing dates are kept as a pending review (`review_json`) and never replace a date unless the user chooses one.
7. **Show.** The dashboard computes each document's status from its date and today's date on every request.

### Who decided what

Each document records where its category and its expiry date came from:

| Source value | Meaning | Shown as |
|---|---|---|
| `user` | Typed, chosen or confirmed by the user | Plain value, "Confirmed" stamp |
| `detected` | Found by the system, not yet confirmed | "Check" / "Auto" / "Please check" |
| empty | Nothing set | A dash |

A `detected` value can be replaced when the text is extracted again. A `user` value never is. "Check the document again" never changes a saved value; it only shows what it finds next to it.

### Database

| Table | Columns |
|---|---|
| `user` | id, username (unique), email (unique), password_hash |
| `document` | id, title, filename, category, category_source, expiry_date, expiry_source, review_json, extracted_text, uploaded_at, user_id |

When the application starts it adds any column an older `vault.db` is missing, so existing data survives an upgrade.

### Pages

| Route | Page | Login needed |
|---|---|---|
| `/` | Landing page | No |
| `/test-results` | Recorded test figures | No |
| `/register`, `/login`, `/logout` | Accounts | No |
| `/dashboard` | Counts, timeline, table | Yes |
| `/upload` | Upload form | Yes |
| `/document/<id>` | One document | Yes, owner only |
| `/document/<id>/extract`, `/expiry`, `/expiry/recheck`, `/category`, `/delete` | Changes (POST only) | Yes, owner only |
| `/document/<id>/file` | The image itself | Yes, owner only |

Another user's document returns "not found", not "forbidden", so its existence is not revealed.

---

## 8. Known limitations

**Accuracy**
- OCR accuracy drops with glare, shadows, steep angles and blur. On the angled, shadowed and compressed sample images only 5 of 11 printed dates were read; on clean scans, ordinary phone photos and shrunken photos it was 41 of 41. When OCR fails the system says so and leaves the date empty.
- JPG and PNG only. No PDF.
- English text only.
- Numeric dates are read day first (15/03/2028 is 15 March). Two-digit years in a full date (15/03/28) are not supported.
- Results come from internal, synthetic and sample-based testing. They are not an independent real-world validation.

**Scope**
- Documents can be deleted but an image cannot be replaced; delete the document and upload a clearer image.
- No reminders by e-mail or phone. The dashboard is the only alert.
- No password reset, no e-mail verification.
- Single-user machine, SQLite database.

**Security: for a demonstration on one computer, not for a public server**
- The secret key is written in `app.py`.
- The application starts in Flask's debug mode.
- Forms have no CSRF tokens. The login cookie uses `SameSite=Lax`, which blocks the usual cross-site form posts.
- The connection is plain HTTP.

Before putting it on a real server you would change all four.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| "Tesseract is not installed" or `check_ocr.py` says it was not found | Install Tesseract (step 2), then open a **new** terminal. If it is in a non-default folder, set `TESSERACT_CMD` to the full path of `tesseract.exe`. |
| `pip` or `python` is not recognised | Reinstall Python and tick "Add python.exe to PATH". |
| Port 5000 is already in use | Close the other program, or start with `python -c "from app import app; app.run(port=5050)"` and open port 5050. |
| Start again with an empty vault | Stop the application, delete `instance/vault.db` and the files inside `uploads/`, and start again. |
| A reading looks wrong | That is expected sometimes. Compare with the image, then change the value yourself. |
