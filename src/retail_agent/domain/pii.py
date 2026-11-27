import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

EMAIL_HIDDEN = "[email hidden]"
PHONE_HIDDEN = "[phone hidden]"

type Where = Literal["query result", "query error", "report", "reply"]

# The last part of the domain must be letters, so a price like "items@19.99" is not an email.
# The lookbehind makes a match start only at the start of a word. Without it a long run of
# letters with no "@" is rescanned from every position.
EMAIL = re.compile(r"(?<![\w.%+-])[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}")
# Only the international form on one line: a plus and 10 to 15 digits. Analytics text is
# full of dates, ids and amounts, and a looser pattern would hide those.
PHONE = re.compile(r"(?<!\w)\+\d(?:[ ().-]{0,2}\d){9,14}")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class PiiMask:
    """Hides emails and phone numbers in text and counts what it hid."""

    def __init__(self) -> None:
        self.emails_hidden = 0
        self.phones_hidden = 0

    def hide(self, text: str) -> str:
        text, emails = EMAIL.subn(EMAIL_HIDDEN, text)
        self.emails_hidden += emails
        return PHONE.sub(self._hide_phone, text)

    def log(self, where: Where) -> None:
        """Write one line with the counts, never the values."""
        if self.emails_hidden or self.phones_hidden:
            logger.warning(
                "pii masked: where=%s emails=%d phones=%d",
                where,
                self.emails_hidden,
                self.phones_hidden,
            )

    def _hide_phone(self, found: re.Match[str]) -> str:
        if ISO_DATE.search(found.group()):
            # A signed number followed by a date, for example "+15 2025-01-01".
            return found.group()
        self.phones_hidden += 1
        return PHONE_HIDDEN


def mask_pii(text: str, where: Where) -> str:
    mask = PiiMask()
    text = mask.hide(text)
    mask.log(where)
    return text
