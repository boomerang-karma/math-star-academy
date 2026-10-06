"""Load a synthetic, fully fictional dataset through the real pipeline.

    python -m leadintel.devtools.demo

Every company, person and domain here is invented (``.example``-style names on
reserved or fictional domains). The data exercises the same paths production
data does: several sources describing the same companies and people, intent
signals, web visits stitched to a person through a form submission, and a
borderline match that lands in the review queue.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from leadintel.connectors.first_party import TrackEvent, event_signals, form_source_records
from leadintel.core.config import Settings
from leadintel.ontology.models import (
    EntityHint,
    EntityType,
    FetchBatch,
    LawfulBasis,
    RelationshipAssertion,
    RelationType,
    Signal,
    SignalType,
    Source,
    SourceRecord,
)
from leadintel.pipeline.icp import load_icp
from leadintel.pipeline.service import PipelineService
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.keyring import build_blind_indexer, build_field_cipher
from leadintel.storage.db import connect
from leadintel.storage.pipeline_repo import PipelineRepository
from leadintel.storage.raw_store import LocalRawStore

COMPANIES = [
    # name, domain, linkedin slug, industry, employees, country, city, technologies
    (
        "Northwind Analytics",
        "northwindanalytics.com",
        "northwind-analytics",
        "Software Development",
        312,
        "US",
        "Austin",
        ["hubspot", "segment"],
    ),
    (
        "Contoso Robotics",
        "contosorobotics.io",
        "contoso-robotics",
        "Industrial Automation",
        1800,
        "GB",
        "London",
        ["salesforce"],
    ),
    (
        "Fabrikam Payments",
        "fabrikampay.com",
        "fabrikam-payments",
        "Financial Services",
        640,
        "US",
        "New York",
        ["salesforce", "segment", "intercom"],
    ),
    (
        "Tailspin Health",
        "tailspinhealth.com",
        "tailspin-health",
        "Hospitals and Health Care",
        4200,
        "US",
        "Boston",
        ["marketo"],
    ),
    (
        "Wingtip Logistics",
        "wingtiplogistics.com",
        "wingtip-logistics",
        "Transportation",
        95,
        "CA",
        "Toronto",
        ["hubspot"],
    ),
    (
        "Litware Security",
        "litwaresec.com",
        "litware-security",
        "Computer and Network Security",
        220,
        "DE",
        "Berlin",
        ["hubspot", "google_analytics"],
    ),
    (
        "Adventure Works Media",
        "adventureworks-media.com",
        "adventure-works-media",
        "Marketing Services",
        48,
        "AU",
        "Sydney",
        ["google_analytics"],
    ),
    (
        "Proseware Cloud",
        "prosewarecloud.com",
        "proseware-cloud",
        "IT Services and IT Consulting",
        510,
        "IE",
        "Dublin",
        ["salesforce", "segment"],
    ),
]

PEOPLE = [
    # name, title, company index, email local part, visitor id
    ("Jordan Lee", "Head of Revenue Operations", 0, "jordan.lee", "v_demo_jordan_0001"),
    ("Avery Quinn", "VP Sales", 0, "avery.quinn", None),
    ("Morgan Patel", "Chief Revenue Officer", 2, "morgan", "v_demo_morgan_0002"),
    ("Riley Chen", "Director of Demand Generation", 5, "riley.chen", "v_demo_riley_00003"),
    ("Sam Okafor", "Sales Operations Manager", 7, "sam.okafor", None),
    ("Casey Novak", "Software Engineer", 1, "casey", None),
]

SIGNALS = [
    # company index, type, title, days ago, strength
    (0, SignalType.FUNDING, "Northwind Analytics raises $40M Series B", 9, 0.9),
    (0, SignalType.JOB_POSTING, "Hiring: Sales Development Representative", 3, 1.0),
    (0, SignalType.LEADERSHIP_CHANGE, "Northwind Analytics appoints new CMO", 16, 0.6),
    (2, SignalType.EXPANSION, "Fabrikam Payments opens new office in Chicago", 21, 0.7),
    (2, SignalType.JOB_POSTING, "Hiring: Revenue Operations Analyst", 6, 1.0),
    (3, SignalType.NEWS_MENTION, "Tailspin Health featured in industry report", 40, 0.3),
    (5, SignalType.JOB_POSTING, "Hiring: Business Development Representative", 2, 1.0),
    (5, SignalType.FUNDING, "Litware Security closes seed extension", 60, 0.9),
    (7, SignalType.ACQUISITION, "Proseware Cloud acquires a monitoring startup", 30, 0.7),
    (1, SignalType.JOB_POSTING, "Hiring: Senior Backend Engineer", 5, 0.3),
]


def build_batches(now: datetime, bidx: BlindIndexer) -> list[tuple[str, FetchBatch]]:
    rng = random.Random(7)  # deterministic demo data
    linkedin = FetchBatch()
    website = FetchBatch()
    for name, domain, slug, industry, employees, country, city, tech in COMPANIES:
        linkedin.records.append(
            SourceRecord(
                source=Source.SB_LINKEDIN_COMPANY,
                external_id=slug,
                entity_type=EntityType.ORGANIZATION,
                observed_at=now - timedelta(days=rng.randint(1, 20)),
                attributes={
                    "name": name,
                    "domain": domain,
                    "linkedin_slug": slug,
                    "linkedin_url": f"https://www.linkedin.com/company/{slug}",
                    "industry": industry,
                    "employee_count": employees,
                    "hq_country": country,
                    "hq_city": city,
                },
            )
        )
        website.records.append(
            SourceRecord(
                source=Source.SB_WEB,
                external_id=domain,
                entity_type=EntityType.ORGANIZATION,
                observed_at=now - timedelta(days=rng.randint(1, 10)),
                attributes={
                    "name": name,
                    "domain": domain,
                    "website": f"https://{domain}",
                    "technologies": tech,
                },
            )
        )
    # Same name, no shared identifier: stays a separate entity (never merged on name alone).
    # The people below (profile vs. form, name + employer only) land in the review queue.
    linkedin.records.append(
        SourceRecord(
            source=Source.SB_GOOGLE_MAPS,
            external_id="demo-place-northwind-hq",
            entity_type=EntityType.ORGANIZATION,
            observed_at=now - timedelta(days=4),
            attributes={
                "name": "Northwind Analytics HQ",
                "hq_country": "US",
                "hq_city": "Austin",
                "google_place_id": "demo-place-northwind-hq",
            },
        )
    )
    for index, kind, title, days, strength in SIGNALS:
        name, domain, slug, *_ = COMPANIES[index]
        linkedin.signals.append(
            Signal(
                signal_type=kind,
                source=Source.SB_GOOGLE_NEWS
                if kind is not SignalType.JOB_POSTING
                else Source.SB_LINKEDIN_JOBS,
                external_id=f"demo-{slug}-{days}-{kind.value}",
                occurred_at=now - timedelta(days=days),
                title=title,
                strength=strength,
                subject=EntityHint(
                    entity_type=EntityType.ORGANIZATION,
                    linkedin_slug=slug,
                    domain=domain,
                    name=name,
                ),
            )
        )

    people = FetchBatch()
    web_events = FetchBatch()
    for person, title, company_index, local, visitor in PEOPLE:
        name, domain, slug, *_ = COMPANIES[company_index]
        public_id = person.lower().replace(" ", "-") + "-demo"
        people.records.append(
            SourceRecord(
                source=Source.SB_LINKEDIN_PROFILE,
                external_id=public_id,
                entity_type=EntityType.PERSON,
                observed_at=now - timedelta(days=12),
                attributes={
                    "full_name": person,
                    "first_name": person.split()[0],
                    "last_name": person.split()[-1],
                    "title": title,
                    "linkedin_slug": public_id,
                    "company_name": name,
                },
                relationships=[
                    RelationshipAssertion(
                        rel_type=RelationType.WORKS_AT,
                        target=EntityHint(
                            entity_type=EntityType.ORGANIZATION, linkedin_slug=slug, name=name
                        ),
                    )
                ],
            )
        )
        if visitor:
            for day, path in ((6, "/blog/forecasting"), (3, "/pricing"), (2, "/customers")):
                event = TrackEvent.model_validate(
                    {
                        "visitor_id": visitor,
                        "event": "page_view",
                        "url": f"https://www.example-seller.com{path}",
                        "ts": (now - timedelta(days=day)).isoformat(),
                    }
                )
                web_events.signals.extend(event_signals(event, icp=load_icp(), bidx=bidx))
            form = TrackEvent.model_validate(
                {
                    "visitor_id": visitor,
                    "event": "form_submit",
                    "url": "https://www.example-seller.com/demo",
                    "ts": (now - timedelta(days=1)).isoformat(),
                    "form": {
                        "email": f"{local}@{domain}",
                        "name": person,
                        "company": name,
                        "title": title,
                        "form_id": "demo-request",
                        "marketing_consent": True,
                    },
                }
            )
            web_events.records.extend(form_source_records(form))
            web_events.signals.extend(event_signals(form, icp=load_icp(), bidx=bidx))
    for record in people.records:
        assert record.lawful_basis is LawfulBasis.LEGITIMATE_INTEREST
    return [
        ("scrapebadger:company_profile", linkedin),
        ("scrapebadger:website_enrichment", website),
        ("scrapebadger:person_profile", people),
        ("first_party:beacon", web_events),
    ]


def main() -> None:
    settings = Settings()
    if not settings.is_local:
        raise SystemExit("the demo loader only runs with LEADINTEL_ENV=local")
    if settings.worker_database_url is None:
        raise SystemExit("set LEADINTEL_WORKER_DATABASE_URL (pipeline-role login) in .env")
    bidx = build_blind_indexer(settings)
    now = datetime.now(UTC)
    with connect(settings.worker_database_url.get_secret_value()) as conn:
        service = PipelineService(
            PipelineRepository(conn, cipher=build_field_cipher(settings), bidx=bidx),
            raw_store=LocalRawStore(f"{settings.local_data_dir}/raw"),
            bidx=bidx,
            icp=load_icp(),
        )
        for label, batch in build_batches(now, bidx):
            connector, playbook = label.split(":")
            summary = service.ingest(
                batch, connector=connector, playbook=playbook, params={"demo": True}
            )
            print(f"ingested {label}: {summary['records']} records, {summary['signals']} signals")
        print("resolved:", service.resolve_pending())
        print("scored leads:", service.score())


if __name__ == "__main__":
    main()
