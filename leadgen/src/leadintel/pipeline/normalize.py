"""Canonical forms for identifiers.

Entity resolution is only as good as its normalization: "ACME, Inc." and
"Acme Incorporated", "https://www.acme.com/about?utm_source=x" and "acme.com",
"+1 (415) 555-0100" and "415.555.0100" must collapse to the same keys.
Every function here is pure and returns ``None`` for unusable input instead of
raising, so mappers can apply them to messy upstream data without guards.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import phonenumbers
import tldextract

_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")

FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.uk",
        "ymail.com",
        "outlook.com",
        "hotmail.com",
        "hotmail.co.uk",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "gmx.de",
        "web.de",
        "mail.com",
        "yandex.com",
        "yandex.ru",
        "zoho.com",
        "qq.com",
        "163.com",
        "126.com",
        "naver.com",
    }
)

# Domains that host many unrelated organizations; never treat them as a company's identity.
PLATFORM_DOMAINS = frozenset(
    {
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "google.com",
        "goo.gl",
        "yelp.com",
        "wixsite.com",
        "wix.com",
        "squarespace.com",
        "wordpress.com",
        "blogspot.com",
        "medium.com",
        "github.io",
        "notion.site",
        "linktr.ee",
        "tripadvisor.com",
        "crunchbase.com",
        "bbb.org",
        "yellowpages.com",
        "angi.com",
    }
)

_TRACKING_PARAMS = frozenset(
    {"gclid", "fbclid", "msclkid", "dclid", "yclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "ref"}
)

_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "l l c",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "sarl",
        "srl",
        "spa",
        "bv",
        "nv",
        "plc",
        "pty",
        "pvt",
        "private",
        "lp",
        "llp",
        "oy",
        "ab",
        "as",
        "aps",
        "kk",
        "kg",
        "se",
        "group",
        "holdings",
        "holding",
    }
)

_HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame"})
_NAME_SUFFIXES = frozenset(
    {"jr", "sr", "ii", "iii", "iv", "phd", "md", "mba", "cpa", "esq", "pe", "cfa", "pmp"}
)

_LINKEDIN_KINDS = {"in": "person", "company": "company", "school": "school", "showcase": "company"}


@lru_cache(maxsize=1)
def _tld_extractor() -> tldextract.TLDExtract:
    # Bundled public-suffix snapshot only: no network fetch at runtime (Lambda, CI).
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- emails


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = raw.strip().strip("<>").strip().lower()
    if email.startswith("mailto:"):
        email = email[len("mailto:") :]
    email = email.split("?", 1)[0]
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    local, _, domain = email.partition("@")
    if not local or ".." in email:
        return None
    return f"{local}@{domain}"


def email_match_key(email: str) -> str:
    """Key under which address variants of one mailbox collide.

    Plus-addressing is stripped everywhere; dots are ignored only for Gmail, where
    the provider itself ignores them. The stored email keeps its original form.
    """
    local, _, domain = email.partition("@")
    local = local.split("+", 1)[0]
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return normalize_domain(email.rsplit("@", 1)[1])


def is_free_email_domain(domain: str | None) -> bool:
    return bool(domain) and domain in FREE_EMAIL_DOMAINS


# ---------------------------------------------------------------- domains & URLs


def normalize_domain(raw: str | None) -> str | None:
    """Registrable domain ("www.shop.acme.co.uk/x" -> "acme.co.uk"), or None."""
    if not raw:
        return None
    text = raw.strip().lower()
    if "@" in text and "/" not in text:
        text = text.rsplit("@", 1)[1]
    if "://" not in text:
        text = "http://" + text
    host = urlsplit(text).hostname
    if not host:
        return None
    parts = _tld_extractor()(host)
    if not parts.domain or not parts.suffix:
        return None
    return f"{parts.domain}.{parts.suffix}"


def company_domain(raw: str | None) -> str | None:
    """Like normalize_domain, but rejects free-mail and multi-tenant platform domains."""
    domain = normalize_domain(raw)
    if domain is None or domain in FREE_EMAIL_DOMAINS or domain in PLATFORM_DOMAINS:
        return None
    return domain


def normalize_url(raw: str | None) -> str | None:
    """https, lower-case host, no fragment, no tracking parameters, no trailing slash."""
    if not raw:
        return None
    text = raw.strip()
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or ""
    host = parts.hostname.lower()
    netloc = host if parts.port in (None, 80, 443) else f"{host}:{parts.port}"
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def parse_linkedin_url(raw: str | None) -> tuple[str, str] | None:
    """``("person"|"company"|"school", slug)`` for a LinkedIn profile/company/school URL."""
    if not raw:
        return None
    text = raw.strip()
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    segments = [unquote(s) for s in parts.path.split("/") if s]
    if len(segments) < 2 or segments[0].lower() not in _LINKEDIN_KINDS:
        return None
    slug = segments[1].strip().lower()
    if not slug or not re.fullmatch(r"[\w\-%.]+", slug):
        return None
    return _LINKEDIN_KINDS[segments[0].lower()], slug


def linkedin_url(kind: str, slug: str) -> str:
    prefix = {"person": "in", "company": "company", "school": "school"}[kind]
    return f"https://www.linkedin.com/{prefix}/{slug}"


# ---------------------------------------------------------------- phones


def normalize_phone(raw: str | None, default_region: str = "US") -> str | None:
    """E.164 (+14155550100), or None if the number is not plausibly valid."""
    if not raw:
        return None
    try:
        parsed = phonenumbers.parse(raw, default_region.upper())
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


# ---------------------------------------------------------------- names


def _name_tokens(raw: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", " ", raw)  # "(she/her)", "(CPA)"
    text = re.sub(r"[,|/]+", " ", text)
    tokens = [t.strip(".") for t in _squash(text).split(" ") if t.strip(".")]
    while tokens and tokens[0].lower() in _HONORIFICS:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in _NAME_SUFFIXES:
        tokens.pop()
    return tokens


def split_person_name(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """``(first, last, full)`` with honorifics, credentials and pronouns removed."""
    if not raw or not raw.strip():
        return None, None, None
    tokens = _name_tokens(raw)
    if not tokens:
        return None, None, None
    full = " ".join(tokens)
    if len(tokens) == 1:
        return tokens[0], None, full
    return tokens[0], tokens[-1], full


def person_name_key(raw: str | None) -> str | None:
    """Accent-free, lower-case "first last" used for fuzzy comparison and blocking."""
    first, last, full = split_person_name(raw)
    if not full:
        return None
    key = ascii_fold(" ".join(t for t in (first, last) if t) or full).lower()
    return re.sub(r"[^a-z0-9 ]", "", key).strip() or None


def company_name_key(raw: str | None) -> str | None:
    """ "The ACME Group, Inc." -> "acme"; used for fuzzy comparison and blocking."""
    if not raw:
        return None
    text = ascii_fold(raw).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    tokens = text.split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or None


def clean_text(raw: str | None, *, max_length: int = 2000) -> str | None:
    if raw is None:
        return None
    text = _squash(unicodedata.normalize("NFKC", raw))
    return text[:max_length] or None


def country_code(raw: str | None) -> str | None:
    """Best-effort ISO 3166-1 alpha-2 from a code or a common country name."""
    if not raw:
        return None
    text = raw.strip()
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return _COUNTRY_NAMES.get(text.lower())


_COUNTRY_NAMES = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "us": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "ireland": "IE",
    "germany": "DE",
    "deutschland": "DE",
    "france": "FR",
    "netherlands": "NL",
    "belgium": "BE",
    "spain": "ES",
    "italy": "IT",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "poland": "PL",
    "portugal": "PT",
    "united arab emirates": "AE",
    "israel": "IL",
    "south africa": "ZA",
    "australia": "AU",
    "new zealand": "NZ",
    "singapore": "SG",
    "india": "IN",
    "japan": "JP",
    "south korea": "KR",
    "hong kong": "HK",
    "brazil": "BR",
    "mexico": "MX",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "lithuania": "LT",
}


def employee_range_to_count(raw: str | None) -> int | None:
    """ "51-200 employees" -> 125 (midpoint), "10,001+ employees" -> 10001."""
    if not raw:
        return None
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", raw)]
    if not numbers:
        return None
    if len(numbers) >= 2:
        return (numbers[0] + numbers[1]) // 2
    return numbers[0]
