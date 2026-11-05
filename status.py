"""Turns an expiry date into a status the dashboard can show.

States:
  expired  - the date is before today
  soon     - the date is today, or at most SOON_DAYS days away
  valid    - the date is further away than that
  none     - the document has no expiry date
"""
from collections import namedtuple
from datetime import date

SOON_DAYS = 30  # "expiring soon" means this many days or fewer

# key = the state, label = the words shown to the user, days = days until expiry (negative if past)
Status = namedtuple("Status", ["key", "label", "days"])


def days_text(count):
    return f"{count} day" if count == 1 else f"{count} days"


def expiry_status(expiry_date, today=None):
    """Return the Status of a document that expires on `expiry_date` (a date or None)."""
    if expiry_date is None:
        return Status("none", "No expiry date", None)

    today = today or date.today()
    days = (expiry_date - today).days

    if days < 0:
        return Status("expired", f"Expired {days_text(-days)} ago", days)
    if days == 0:
        return Status("soon", "Expires today", days)
    if days <= SOON_DAYS:
        return Status("soon", f"Expires in {days_text(days)}", days)
    return Status("valid", "Valid", days)
