"""Pure mapping from ScrapeBadger responses to ontology objects.

LinkedIn endpoints return typed Pydantic models from the SDK; Google endpoints
return plain dicts whose documented keys are used here (``results`` for Maps,
``organic_results`` for Search). Field aliases are accepted where the upstream
shape has varied, and anything unusable is dropped rather than guessed.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from leadintel.ontology.models import (
    EntityHint,
    EntityType,
    RelationshipAssertion,
    RelationType,
    Signal,
    SignalType,
    Source,
    SourceRecord,
)
from leadintel.pipeline.icp import IcpProfile
from leadintel.pipeline.normalize import (
    clean_text,
    company_domain,
    company_name_key,
    country_code,
    employee_range_to_count,
    linkedin_url,
    normalize_phone,
    normalize_url,
    parse_linkedin_url,
    split_person_name,
)


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v not in (None, "", [], {})}


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_date(raw: Any, *, fallback: datetime) -> datetime:
    """ISO dates/datetimes from upstream; relative strings ("3 days ago") fall back."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, str):
        text = raw.strip().replace("Z", "+00:00")
        for candidate in (text, text[:10]):
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return fallback


def _slug_from(url: str | None, kind: str) -> str | None:
    parsed = parse_linkedin_url(url)
    return parsed[1] if parsed and parsed[0] == kind else None


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


# ---------------------------------------------------------------- LinkedIn


def map_linkedin_company(company: Any, *, now: datetime) -> SourceRecord:
    slug = str(company.universal_name).strip().lower()
    address = company.address
    hq_parts = (
        [address.street, address.city, address.region, address.postal_code, address.country]
        if address
        else []
    )
    attributes = _compact(
        {
            "name": clean_text(company.name),
            "linkedin_slug": slug,
            "linkedin_url": linkedin_url("company", slug),
            "website": normalize_url(company.website),
            "domain": company_domain(company.website),
            "industry": clean_text(company.industry),
            "description": clean_text(company.description, max_length=4000),
            "specialties": [s for s in (clean_text(x) for x in company.specialties) if s],
            "employee_count": company.employee_count
            or employee_range_to_count(company.company_size),
            "employee_range": clean_text(company.company_size),
            "founded_year": company.founded,
            "follower_count": company.follower_count,
            "hq_city": clean_text(address.city) if address else None,
            "hq_region": clean_text(address.region) if address else None,
            "hq_country": country_code(address.country) if address else None,
            "address": ", ".join(p for p in hq_parts if p) or None,
        }
    )
    return SourceRecord(
        source=Source.SB_LINKEDIN_COMPANY,
        external_id=slug,
        entity_type=EntityType.ORGANIZATION,
        observed_at=now,
        attributes=attributes,
        source_url=company.linkedin_url,
    )


def _split_location(location: str | None) -> tuple[str | None, str | None, str | None]:
    """ "San Francisco, California, United States" -> (city, region, country code)."""
    if not location:
        return None, None, None
    parts = [p.strip() for p in location.split(",") if p.strip()]
    country = country_code(parts[-1]) if parts else None
    if country and len(parts) >= 3:
        return parts[0], parts[1], country
    if country and len(parts) == 2:
        return parts[0], None, country
    return (parts[0] if parts else None), None, country


def _title_from_headline(headline: str | None) -> str | None:
    if not headline:
        return None
    title = re.split(r"\s+(?:at|@)\s+|\s+\|\s+", headline, maxsplit=1)[0]
    return clean_text(title, max_length=200)


def map_linkedin_profile(profile: Any, *, now: datetime) -> SourceRecord:
    slug = str(profile.public_id).strip().lower()
    first, last, full = split_person_name(profile.name)
    city, region, country = _split_location(profile.location)
    title = (
        clean_text(profile.job_titles[0])
        if profile.job_titles
        else _title_from_headline(profile.headline)
    )
    company_slug = _slug_from(profile.current_company_url, "company")

    relationships: list[RelationshipAssertion] = []
    if profile.current_company or company_slug:
        relationships.append(
            RelationshipAssertion(
                rel_type=RelationType.WORKS_AT,
                target=EntityHint(
                    entity_type=EntityType.ORGANIZATION,
                    linkedin_slug=company_slug,
                    name=clean_text(profile.current_company),
                ),
                properties=_compact({"title": title}),
            )
        )
    for job in profile.experience:
        if job.end_year is None or not (job.company or job.company_url):
            continue  # current roles are covered by WORKS_AT above
        relationships.append(
            RelationshipAssertion(
                rel_type=RelationType.WORKED_AT,
                target=EntityHint(
                    entity_type=EntityType.ORGANIZATION,
                    linkedin_slug=_slug_from(job.company_url, "company"),
                    name=clean_text(job.company),
                ),
                properties=_compact(
                    {
                        "title": clean_text(job.title),
                        "start_year": job.start_year,
                        "end_year": job.end_year,
                    }
                ),
            )
        )

    attributes = _compact(
        {
            "full_name": full,
            "first_name": first,
            "last_name": last,
            "headline": clean_text(profile.headline, max_length=300),
            "title": title,
            "linkedin_slug": slug,
            "linkedin_url": linkedin_url("person", slug),
            "city": clean_text(city),
            "region": clean_text(region),
            "country": country or country_code(profile.country),
            "company_name": clean_text(profile.current_company),
        }
    )
    return SourceRecord(
        source=Source.SB_LINKEDIN_PROFILE,
        external_id=slug,
        entity_type=EntityType.PERSON,
        observed_at=now,
        attributes=attributes,
        relationships=relationships,
        source_url=profile.linkedin_url,
    )


def map_job_card(card: Any, *, icp: IcpProfile, now: datetime) -> Signal | None:
    """A job posting is a growth signal; one for a role we sell into is a need signal."""
    company_slug = _slug_from(card.company_url, "company")
    company = clean_text(card.company)
    if not (company_slug or company) or not card.title:
        return None
    relevance = icp.hiring_relevance(card.title)
    return Signal(
        signal_type=SignalType.JOB_POSTING,
        source=Source.SB_LINKEDIN_JOBS,
        external_id=str(card.job_id),
        occurred_at=parse_date(card.posted_at, fallback=now),
        subject=EntityHint(
            entity_type=EntityType.ORGANIZATION, linkedin_slug=company_slug, name=company
        ),
        title=f"Hiring: {clean_text(card.title, max_length=200)}",
        strength=round(0.3 + 0.7 * relevance, 3),
        url=card.job_url,
        attributes=_compact(
            {
                "job_title": clean_text(card.title, max_length=200),
                "location": clean_text(card.location),
                "relevant_to_icp": relevance > 0,
            }
        ),
    )


# ---------------------------------------------------------------- Google Maps


def map_maps_place(place: dict[str, Any], *, region: str, now: datetime) -> SourceRecord | None:
    place_id = _first(place, "place_id", "data_id", "data_cid")
    name = clean_text(_first(place, "title", "name"))
    if not place_id or not name:
        return None
    website = _first(place, "website", "link")
    categories = _first(place, "types", "type", "category", "categories")
    if isinstance(categories, str):
        categories = [categories]
    reviews = _first(place, "reviews", "reviews_count", "review_count")
    attributes = _compact(
        {
            "name": name,
            "google_place_id": str(place_id),
            "website": normalize_url(website),
            "domain": company_domain(website),
            "phone": normalize_phone(_first(place, "phone", "phone_number"), default_region=region),
            "address": clean_text(_first(place, "address", "full_address")),
            "rating": float(place["rating"])
            if isinstance(place.get("rating"), int | float)
            else None,
            "review_count": int(reviews) if isinstance(reviews, int) else None,
            "categories": [c for c in (clean_text(str(x)) for x in categories or []) if c],
            "hq_country": region.upper(),
        }
    )
    return SourceRecord(
        source=Source.SB_GOOGLE_MAPS,
        external_id=str(place_id),
        entity_type=EntityType.ORGANIZATION,
        observed_at=now,
        attributes=attributes,
    )


# ---------------------------------------------------------------- Google Search


def find_company_links(serp: dict[str, Any], company_name: str) -> tuple[str | None, str | None]:
    """``(website_domain, linkedin_company_slug)`` from organic results.

    A website only counts if the company's name key appears in the result's title
    or domain, which keeps directories and namesakes out.
    """
    name_key = company_name_key(company_name) or ""
    name_tokens = [t for t in name_key.split() if len(t) > 2] or name_key.split()
    website: str | None = None
    slug: str | None = None
    for result in serp.get("organic_results") or []:
        link = result.get("link") or ""
        if slug is None:
            slug = _slug_from(link, "company")
        if website is None:
            domain = company_domain(link)
            haystack = f"{(result.get('title') or '').lower()} {domain or ''}"
            if domain and name_tokens and all(t in haystack for t in name_tokens):
                website = domain
        if website and slug:
            break
    return website, slug


# ---------------------------------------------------------------- Google News

_NEWS_RULES: tuple[tuple[SignalType, re.Pattern[str], float], ...] = (
    (
        SignalType.FUNDING,
        re.compile(r"\b(raises?|raised|funding|series [a-f]\b|seed round|valuation)\b", re.I),
        0.9,
    ),
    (
        SignalType.ACQUISITION,
        re.compile(r"\b(acquires?|acquired|acquisition|merger|merges)\b", re.I),
        0.7,
    ),
    (
        SignalType.EXPANSION,
        re.compile(r"\b(expands?|expansion|opens? new|new office|launch(es|ed)? in)\b", re.I),
        0.7,
    ),
    (
        SignalType.LEADERSHIP_CHANGE,
        re.compile(
            r"\b(appoints?|names? .{0,40}\b(ceo|cfo|cto|cmo|cro|president)|joins as)\b", re.I
        ),
        0.6,
    ),
)


def classify_headline(title: str) -> tuple[SignalType, float]:
    for signal_type, pattern, strength in _NEWS_RULES:
        if pattern.search(title):
            return signal_type, strength
    return SignalType.NEWS_MENTION, 0.3


def _news_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("news_results", "articles", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


def map_news(
    payload: dict[str, Any], *, company: EntityHint, company_name: str, now: datetime
) -> list[Signal]:
    """Trigger events about a company. Articles that do not name it are dropped (namesakes)."""
    name_key = company_name_key(company_name) or ""
    signals: list[Signal] = []
    for article in _news_items(payload):
        title = clean_text(article.get("title"), max_length=300)
        link = normalize_url(_first(article, "link", "url"))
        if not title or not link:
            continue
        body = f"{title} {article.get('snippet') or ''}"
        if name_key and name_key not in (company_name_key(body) or ""):
            continue
        signal_type, strength = classify_headline(title)
        source = article.get("source")
        publisher = source.get("name") if isinstance(source, dict) else source
        signals.append(
            Signal(
                signal_type=signal_type,
                source=Source.SB_GOOGLE_NEWS,
                external_id=_short_hash(link),
                occurred_at=parse_date(
                    _first(article, "iso_date", "published_at", "date"), fallback=now
                ),
                subject=company,
                title=title,
                strength=strength,
                url=link,
                attributes=_compact({"publisher": clean_text(publisher)}),
            )
        )
    return signals


# ---------------------------------------------------------------- websites

_TECH_FINGERPRINTS: dict[str, tuple[str, ...]] = {
    "hubspot": (r"js\.hs-scripts\.com", r"js\.hsforms\.net", r"hs-analytics"),
    "salesforce": (r"force\.com", r"pardot\.com", r"pi\.pardot"),
    "marketo": (r"munchkin\.marketo", r"mktoforms"),
    "google_analytics": (r"googletagmanager\.com/gtag", r"google-analytics\.com"),
    "google_tag_manager": (r"googletagmanager\.com/gtm\.js",),
    "segment": (r"cdn\.segment\.com",),
    "intercom": (r"widget\.intercom\.io", r"js\.intercomcdn\.com"),
    "drift": (r"js\.driftt\.com",),
    "zendesk": (r"static\.zdassets\.com",),
    "hotjar": (r"static\.hotjar\.com",),
    "stripe": (r"js\.stripe\.com",),
    "shopify": (r"cdn\.shopify\.com",),
    "wordpress": (r"/wp-content/", r"/wp-includes/"),
    "webflow": (r"assets\.website-files\.com", r"webflow\.js"),
    "nextjs": (r"__NEXT_DATA__", r"/_next/static/"),
    "linkedin_insight": (r"snap\.licdn\.com",),
}
_COMPILED_TECH = {
    name: [re.compile(p, re.I) for p in pats] for name, pats in _TECH_FINGERPRINTS.items()
}
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_RE = re.compile(
    r"<meta[^>]+(?:name|property)=[\"'](description|og:description|og:site_name)[\"'][^>]*content=[\"']([^\"']*)[\"']",
    re.I,
)


def detect_technologies(html: str) -> list[str]:
    return sorted(
        name for name, patterns in _COMPILED_TECH.items() if any(p.search(html) for p in patterns)
    )


def map_website(html: str, *, domain: str, url: str, now: datetime) -> SourceRecord:
    meta = {key.lower(): value for key, value in _META_RE.findall(html)}
    title_match = _TITLE_RE.search(html)
    site_name = meta.get("og:site_name") or (title_match.group(1) if title_match else None)
    if site_name:
        site_name = re.split(r"\s+[|\-\u2013\u2014:]\s+", site_name.strip())[0]
    attributes = _compact(
        {
            "name": clean_text(site_name, max_length=200),
            "domain": domain,
            "website": normalize_url(url),
            "description": clean_text(
                meta.get("description") or meta.get("og:description"), max_length=1000
            ),
            "technologies": detect_technologies(html),
        }
    )
    return SourceRecord(
        source=Source.SB_WEB,
        external_id=domain,
        entity_type=EntityType.ORGANIZATION,
        observed_at=now,
        attributes=attributes,
        source_url=normalize_url(url),
    )
