import time

import pytest

from retail_agent.domain.pii import mask_pii


@pytest.mark.parametrize(
    "email",
    [
        "anna@example.com",
        "anna.petrova@example.com",
        "anna+orders@example.com",
        "anna_p@mail.example.co.uk",
        "ANNA@EXAMPLE.COM",
        "josé@café.example",
    ],
)
def test_email_is_hidden(email) -> None:
    assert mask_pii(f"Write to {email} today.", "reply") == "Write to [email hidden] today."


def test_every_email_in_the_text_is_hidden() -> None:
    text = mask_pii("anna@example.com and ben@acme.example", "reply")

    assert text == "[email hidden] and [email hidden]"


@pytest.mark.parametrize(
    "phone",
    ["+15550109999", "+1 555 010 9999", "+1 (555) 010-9999", "+44 20 7946 0958", "+1.555.010.9999"],
)
def test_international_phone_number_is_hidden(phone) -> None:
    assert mask_pii(f"Call {phone} now.", "reply") == "Call [phone hidden] now."


@pytest.mark.parametrize(
    "text",
    [
        "Revenue grew on 2025-01-01 at 10:15:00.",
        "Order 4821003377 holds 3 items.",
        "Total: $2,323,551.45, up +12.5% from 2024.",
        "Growth of +1,250,000 units.",
        "SKU A1B2-C3D4-5566-7788, customer 100245.",
        "Polo Ralph Lauren @ 20% off",
        "5 items@19.99 each, ratio 2@4.99",
        "Growth: +15\n- 2025-01-01 was the peak",
        "The change was +15 2025-01-01 to 2025-02-01.",
        "Customers 100245+15550109999 combined.",
        "No personal details here.",
    ],
)
def test_dates_amounts_and_ids_are_left_alone(text) -> None:
    assert mask_pii(text, "reply") == text


def test_masking_is_logged_with_counts_and_without_the_values(caplog) -> None:
    mask_pii("anna@example.com, ben@acme.example, +1 555 010 9999", "reply")

    assert "pii masked: where=reply emails=2 phones=1" in caplog.text
    assert "anna" not in caplog.text
    assert "555" not in caplog.text


def test_clean_text_writes_nothing_to_the_log(caplog) -> None:
    mask_pii("Revenue is up.", "reply")

    assert caplog.text == ""


def test_a_long_text_without_an_email_is_checked_quickly() -> None:
    started = time.monotonic()

    mask_pii("a" * 200_000, "reply")

    assert time.monotonic() - started < 1.0
