import re
import unicodedata

REDACTED = "[redacted]"
MAX_ERROR_CHARS = 300

URL = re.compile(r"https?://\S+")
QUERY_POSITION = re.compile(r"\s*at \[\d+:\d+\]")
PROJECT_PATH = re.compile(r"projects/[^/\s]+")
CONTROL_AND_INVISIBLE = ("Cc", "Cf")


def redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return PROJECT_PATH.sub(f"projects/{REDACTED}", text)


def one_line(text: str) -> str:
    return " ".join(text.split())


def error_text(detail: str, secrets: tuple[str, ...]) -> str:
    text = QUERY_POSITION.sub("", URL.sub("", detail))
    return one_line(redact(text, secrets))[:MAX_ERROR_CHARS]


def safe_text(text: str) -> str:
    return "".join(
        char
        for char in text
        if char in "\n\t" or unicodedata.category(char) not in CONTROL_AND_INVISIBLE
    )
