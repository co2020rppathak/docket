# Docket: demonstration guide

About 10 minutes. The demonstration uses the images in `demo_samples/` and shows the main idea of the project: **the system suggests, the user decides, and when it is not sure it says so.**

---

## 1. The day before: rehearse once on the demo laptop

The results below were recorded with Tesseract 5.3.4. A different Tesseract version can read a line slightly differently, so run the whole script once on the laptop you will present on.

- [ ] Laptop charged and charger packed
- [ ] `venv\Scripts\activate`, then `python check_ocr.py` shows a Tesseract version and reads the test text
- [ ] `python -m unittest` ends with `Ran 158 tests ... OK`
- [ ] Every file in `demo_samples/` uploads and gives the result in section 3
- [ ] You know your Windows colour mode (Light or Dark). The pages follow it automatically.
- [ ] The Test Results page opens at `/test-results` without logging in

## 2. Ten minutes before

- [ ] Stop the application if it is running. Delete `instance/vault.db` and everything in `uploads/` so you start with an empty vault.
- [ ] Start it: `python app.py`, then open `http://127.0.0.1:5000`
- [ ] Browser at 100% zoom, full screen, other tabs and notifications closed
- [ ] A file-explorer window open on `demo_samples/` so you can drag files into the upload page
- [ ] Wi-Fi is not needed. Nothing in the demonstration uses the internet.

## 3. The script

| # | Do | Say | Expect |
|---|---|---|---|
| 1 | Show the landing page. | "People find out a document expired when they need it. Docket reads it, finds the date and warns early." | The hook line, the sample policy, the four steps. |
| 2 | Create an account (`demo` / `secret12`), then log in. | "Each user sees only their own documents." | An empty dashboard with an empty-vault message. |
| 3 | Upload `insurance_002.png`. Leave category on "Detect automatically" and the date empty. | "I give it only a photo. Nothing else." | Messages: text extracted, **expiry date found 23 Jul 2025, please check it**, **category guessed: Insurance, please check it**. |
| 4 | Open the document. Point at the image, then the highlighted values. Press **Yes, this is correct** under the date and under the category. | "Everything the system finds is a guess until I confirm it. Now it is mine." | "Please check" boxes become a **Confirmed** stamp. An **Expired ... days ago** stamp. |
| 5 | Upload `certificate_006.jpg`. | "A second document, a different kind." | Certificate, **29 Oct 2028**, status **Valid**. |
| 6 | Upload `warranty_001.jpg`. Open it. | "This warranty has no expiry date printed. The system leaves the date empty instead of inventing one." | Category Warranty, no date. The page says the text was read but no expiry date was found, and lists the other date it saw, marked as not an expiry date. |
| 7 | Upload `demo_two_dates.png`. Open it. | "Two dates compete. A system that guesses here would sometimes be wrong, so it asks." | Nothing filled in. A list with **20 Sep 2028** (next to "Renewal due / Expiry Date") and **15 Mar 2027** (next to "Valid until"), each with its line. |
| 8 | Press **Use this date** on the right one. | "One click, and the choice is recorded as mine." | The date is saved with a **Confirmed** stamp. |
| 9 | Upload `demo_far_date.png`. Open it. | "A date 70 years away is probably a misread digit, 2029 read as 2099. It is not filled in." | **12 Dec 2099**, marked **Check carefully**, with the reason. The button reads **Use this date anyway**. |
| 10 | Upload `certificate_009.jpg`. Open it. | "A bad photo. The system admits it cannot read it, and I can still set the date myself." | "No readable text was found." Category **Other**, with no Confirmed stamp. Type a date and press **Save date**. |
| 11 | Upload `warranty_001.jpg` again, titled "Laptop warranty", and type an expiry date **10 days from today** in the upload form. | "If I already know the date, I just type it." | Status **Expires in 10 days**. |
| 12 | Go to the **Dashboard**. | "Everything that needs attention is at the top." | The count strip, a **Needs attention** banner, and the timeline with documents in Overdue, Next 30 days and Later. |
| 13 | Press **Needs attention**. | "Expired, expiring soon, or waiting for my check." | The filtered table. |
| 14 | Open any document and press **Check the document again**. | "It re-reads the image, shows what it finds next to my date, and never changes my date without me." | A message such as "The document was checked again and it also says 23 Jul 2025. Your date matches." |
| 15 | Open **Test Results** in the footer. | "158 automated tests. On 60 sample images it found 46 of 52 printed dates, with none wrong, and left all 8 date-less documents empty." | The Test Results page. |
| 16 | Close with the limitations from the same page. | "It struggles with glare, angles and blur, reads English only, and was tested on sample documents, not independently on real ones." | Nothing to show. Saying this yourself is stronger than being asked. |

Statuses depend on today's date: `insurance_002.png` is always expired, and `certificate_006.jpg` stays valid until 29 October 2028.

## 4. If something goes wrong

| What happens | What to do |
|---|---|
| A document says "No readable text was found" and it should not | Say that this is the system declining to guess. Set the date by hand. That is also part of the demonstration. |
| A different date or category than in the table | Compare with the image on the page and change it yourself. This shows that a guess can be wrong and the user stays in control. |
| "Text extraction is unavailable" | Tesseract is not found. Close the application, set `TESSERACT_CMD` to the full path of `tesseract.exe`, start again. Until then, use the manual date field. |
| The page will not open | Check that `python app.py` is still running in the terminal, and that the address is `http://127.0.0.1:5000`. |
| Port 5000 is busy | `python -c "from app import app; app.run(port=5050)"`, then open port 5050. |
| You need a clean start | Stop the application, delete `instance/vault.db` and the files in `uploads/`, start again. |

## 5. Files used

| File | Shows | Result recorded |
|---|---|---|
| `insurance_002.png` | Date and category found automatically; an expired document | 23 Jul 2025, Insurance |
| `certificate_006.jpg` | A valid document | 29 Oct 2028, Certificate |
| `warranty_001.jpg` | A document with no expiry date | No date, Warranty |
| `demo_two_dates.png` | Two competing dates, the user chooses | 20 Sep 2028 or 15 Mar 2027 |
| `demo_far_date.png` | A suspicious date, needs an override | 12 Dec 2099 flagged |
| `certificate_009.jpg` | An unreadable image | No text, Other |

`demo_two_dates.png` and `demo_far_date.png` were made for this demonstration. The other four are from the `samples/` set. Every image is synthetic and marked SAMPLE.
