from __future__ import annotations

import pytest

from leadintel.pipeline import normalize as n


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Jane.Doe@Acme.COM ", "jane.doe@acme.com"),
        ("mailto:sales@acme.com?subject=hi", "sales@acme.com"),
        ("<ops@acme.io>", "ops@acme.io"),
        ("not-an-email", None),
        ("a..b@acme.com", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_email(raw: str | None, expected: str | None) -> None:
    assert n.normalize_email(raw) == expected


def test_email_match_key() -> None:
    assert n.email_match_key("j.a.n.e+news@googlemail.com") == "jane@gmail.com"
    assert n.email_match_key("jane.doe+x@acme.com") == "jane.doe@acme.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Acme.com/about?utm_source=x", "acme.com"),
        ("shop.acme.co.uk", "acme.co.uk"),
        ("jane@mail.acme.io", "acme.io"),
        ("localhost", None),
        (None, None),
    ],
)
def test_normalize_domain(raw: str | None, expected: str | None) -> None:
    assert n.normalize_domain(raw) == expected


def test_company_domain_rejects_free_mail_and_platforms() -> None:
    assert n.company_domain("acme.com") == "acme.com"
    assert n.company_domain("gmail.com") is None
    assert n.company_domain("https://acme.wixsite.com/home") is None
    assert n.company_domain("https://www.linkedin.com/company/acme") is None


def test_normalize_url_strips_tracking() -> None:
    url = "HTTP://WWW.Acme.com/pricing/?utm_source=li&gclid=1&plan=pro#top"
    assert n.normalize_url(url) == "https://www.acme.com/pricing?plan=pro"
    assert n.normalize_url("ftp://acme.com") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.linkedin.com/in/Jane-Doe-123/?trk=x", ("person", "jane-doe-123")),
        ("uk.linkedin.com/company/acme-inc/about", ("company", "acme-inc")),
        ("https://linkedin.com/school/mit", ("school", "mit")),
        ("https://linkedin.com/feed/", None),
        ("https://evil-linkedin.com/in/x", None),
        ("https://www.linkedin.com.evil.example/in/x", None),
    ],
)
def test_parse_linkedin_url(raw: str, expected: tuple[str, str] | None) -> None:
    assert n.parse_linkedin_url(raw) == expected


def test_normalize_phone() -> None:
    assert n.normalize_phone("(415) 555-2671") == "+14155552671"
    assert n.normalize_phone("+44 20 7946 0958") == "+442079460958"
    assert n.normalize_phone("020 7946 0958", default_region="GB") == "+442079460958"
    assert n.normalize_phone("12") is None
    assert n.normalize_phone(None) is None


def test_person_names() -> None:
    assert n.split_person_name("Dr. Jane  A. Doe, PhD (she/her)") == ("Jane", "Doe", "Jane A Doe")
    assert n.person_name_key("José Álvarez") == "jose alvarez"
    assert n.person_name_key("Madonna") == "madonna"
    assert n.split_person_name("   ") == (None, None, None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The ACME Group, Inc.", "acme"),
        ("Acme Incorporated", "acme"),
        ("Müller & Söhne GmbH", "muller and sohne"),
        ("Co", "co"),
        (None, None),
    ],
)
def test_company_name_key(raw: str | None, expected: str | None) -> None:
    assert n.company_name_key(raw) == expected


def test_misc_helpers() -> None:
    assert n.country_code("United States") == "US"
    assert n.country_code("de") == "DE"
    assert n.country_code("Atlantis") is None
    assert n.employee_range_to_count("51-200 employees") == 125
    assert n.employee_range_to_count("10,001+ employees") == 10001
    assert n.clean_text("  a \n\t b  ") == "a b"
