"""ScrapeBadger playbooks.

=====================  =====================================================================
Playbook               What it does
=====================  =====================================================================
local_discovery        Google Maps search -> local businesses (name, site, phone, rating)
market_hiring_scan     LinkedIn guest job search for ICP roles -> companies + need signals
company_profile        LinkedIn company page (slug, or found via Google) -> firmographics
website_enrichment     company homepage -> description and detected technologies
news_triggers          Google News -> funding / M&A / expansion / leadership signals
account_research       company_profile + website_enrichment + news_triggers, best effort
person_profile         public LinkedIn profile -> person + employment links (legal gate)
=====================  =====================================================================
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from typing import Any

from leadintel.connectors.base import RunContext, require_param
from leadintel.connectors.registry import register
from leadintel.connectors.scrapebadger import mappers
from leadintel.connectors.scrapebadger.gateway import ScrapeBadgerGateway
from leadintel.core.config import Settings
from leadintel.core.errors import (
    ComplianceBlockedError,
    ConfigurationError,
    ConnectorError,
    NotFoundError,
    SourceNotFoundError,
)
from leadintel.ontology.models import EntityHint, EntityType, FetchBatch, RawPayload, Source
from leadintel.pipeline.normalize import company_domain
from leadintel.security.ssrf import validate_public_url

Playbook = Callable[[Mapping[str, Any], RunContext], Awaitable[FetchBatch]]


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class ScrapeBadgerConnector:
    name = "scrapebadger"

    def __init__(
        self,
        gateway: ScrapeBadgerGateway,
        *,
        allow_person_profiles: bool = False,
        url_validator: Callable[[str], str] = validate_public_url,
    ) -> None:
        self._gw = gateway
        self._allow_person_profiles = allow_person_profiles
        self._validate_url = url_validator
        self._playbooks: dict[str, Playbook] = {
            "local_discovery": self.local_discovery,
            "market_hiring_scan": self.market_hiring_scan,
            "company_profile": self.company_profile,
            "website_enrichment": self.website_enrichment,
            "news_triggers": self.news_triggers,
            "account_research": self.account_research,
            "person_profile": self.person_profile,
        }

    def playbooks(self) -> frozenset[str]:
        return frozenset(self._playbooks)

    async def run(self, playbook: str, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        try:
            handler = self._playbooks[playbook]
        except KeyError as exc:
            raise NotFoundError(f"unknown ScrapeBadger playbook {playbook!r}") from exc
        return await handler(params, ctx)

    # ---------------------------------------------------------------- discovery

    async def local_discovery(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        query = str(require_param(params, "query"))
        region = str(params.get("gl", "us")).lower()
        pages = max(1, min(int(params.get("pages", 1)), 5))
        batch = FetchBatch()
        for page in range(pages):
            payload = await self._gw.call(
                "google.maps.search",
                partial(self._gw.client.google.maps.search, q=query, gl=region, start=page * 20),
                budget=ctx.budget,
            )
            now = ctx.now()
            batch.raw.append(
                RawPayload(
                    source=Source.SB_GOOGLE_MAPS,
                    external_id=f"{query}#{page}",
                    fetched_at=now,
                    body=payload,
                )
            )
            results = payload.get("results") or []
            for place in results:
                record = mappers.map_maps_place(place, region=region, now=now)
                if record is not None:
                    batch.records.append(record)
            if len(results) < 20:
                break
        return batch

    async def market_hiring_scan(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        keywords = params.get("keywords") or ctx.icp.hiring_keywords[:3]
        location = params.get("location")
        date_posted = str(params.get("date_posted", "past_week"))
        batch = FetchBatch()
        for keyword in keywords:
            response = await self._gw.call(
                "linkedin.jobs_search",
                partial(
                    self._gw.client.linkedin.jobs_search,
                    keywords=keyword,
                    location=location,
                    date_posted=date_posted,
                ),
                budget=ctx.budget,
            )
            now = ctx.now()
            batch.raw.append(
                RawPayload(
                    source=Source.SB_LINKEDIN_JOBS,
                    external_id=f"{keyword}#{location}",
                    fetched_at=now,
                    body=_dump(response),
                )
            )
            for card in response.jobs:
                signal = mappers.map_job_card(card, icp=ctx.icp, now=now)
                if signal is not None:
                    batch.signals.append(signal)
        return batch

    # ---------------------------------------------------------------- enrichment

    async def _find_company(
        self, company_name: str, ctx: RunContext, batch: FetchBatch
    ) -> tuple[str | None, str | None]:
        serp = await self._gw.call(
            "google.search",
            lambda: self._gw.client.google.search.search(
                q=f"{company_name} linkedin company", mode="fast"
            ),
            budget=ctx.budget,
        )
        batch.raw.append(
            RawPayload(
                source=Source.SB_GOOGLE_SERP,
                external_id=company_name,
                fetched_at=ctx.now(),
                body=serp,
            )
        )
        return mappers.find_company_links(serp, company_name)

    async def company_profile(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        batch = FetchBatch()
        slug = params.get("linkedin_slug")
        if not slug:
            company_name = str(require_param(params, "company_name"))
            _, slug = await self._find_company(company_name, ctx, batch)
            if not slug:
                batch.warnings.append(f"no LinkedIn company page found for {company_name!r}")
                return batch
        company = await self._gw.call(
            "linkedin.company",
            lambda: self._gw.client.linkedin.get_company(str(slug)),
            budget=ctx.budget,
        )
        now = ctx.now()
        batch.raw.append(
            RawPayload(
                source=Source.SB_LINKEDIN_COMPANY,
                external_id=str(slug),
                fetched_at=now,
                body=_dump(company),
            )
        )
        batch.records.append(mappers.map_linkedin_company(company, now=now))
        return batch

    async def website_enrichment(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        domain = company_domain(str(require_param(params, "domain")))
        if domain is None:
            raise ConnectorError("domain is missing or belongs to a shared platform")
        url = self._validate_url(f"https://{domain}")
        result = await self._gw.call(
            "web.scrape",
            lambda: self._gw.client.web.scrape(url, format="html", escalate=True),
            budget=ctx.budget,
        )
        now = ctx.now()
        batch = FetchBatch()
        batch.raw.append(
            RawPayload(
                source=Source.SB_WEB,
                external_id=domain,
                fetched_at=now,
                body=result.content or "",
                content_type="text/html",
            )
        )
        if result.blocking_detected or not result.content:
            batch.warnings.append(f"{domain}: page blocked or empty")
            return batch
        batch.records.append(
            mappers.map_website(result.content, domain=domain, url=result.url or url, now=now)
        )
        return batch

    async def news_triggers(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        company_name = str(require_param(params, "company_name"))
        hint = EntityHint(
            entity_type=EntityType.ORGANIZATION,
            domain=company_domain(params.get("domain")),
            linkedin_slug=params.get("linkedin_slug"),
            name=company_name,
        )
        payload = await self._gw.call(
            "google.news.search",
            lambda: self._gw.client.google.news.search(
                q=f'"{company_name}"', max_results=int(params.get("max_results", 10))
            ),
            budget=ctx.budget,
        )
        now = ctx.now()
        batch = FetchBatch()
        batch.raw.append(
            RawPayload(
                source=Source.SB_GOOGLE_NEWS, external_id=company_name, fetched_at=now, body=payload
            )
        )
        batch.signals.extend(
            mappers.map_news(payload, company=hint, company_name=company_name, now=now)
        )
        return batch

    async def account_research(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        """Best-effort composite: a failed step becomes a warning, not a failed run."""
        company_name = str(require_param(params, "company_name"))
        batch = FetchBatch()
        domain = params.get("domain")
        slug = params.get("linkedin_slug")
        if not domain or not slug:
            found_domain, found_slug = await self._find_company(company_name, ctx, batch)
            domain, slug = domain or found_domain, slug or found_slug
        steps: list[tuple[str, Mapping[str, Any]]] = []
        if slug:
            steps.append(("company_profile", {"linkedin_slug": slug}))
        if domain:
            steps.append(("website_enrichment", {"domain": domain}))
        steps.append(
            (
                "news_triggers",
                {"company_name": company_name, "domain": domain, "linkedin_slug": slug},
            )
        )
        for step, step_params in steps:
            try:
                batch.extend(await self.run(step, step_params, ctx))
            except (SourceNotFoundError, ConnectorError) as exc:
                if exc.code == "budget_exceeded":
                    raise
                batch.warnings.append(f"{step}: {exc.message}")
        return batch

    # ---------------------------------------------------------------- people

    async def person_profile(self, params: Mapping[str, Any], ctx: RunContext) -> FetchBatch:
        if not self._allow_person_profiles:
            raise ComplianceBlockedError(
                "person-profile scraping is disabled pending legal sign-off "
                "(LEADINTEL_ALLOW_PERSON_PROFILE_SCRAPING)"
            )
        public_id = str(require_param(params, "public_id"))
        profile = await self._gw.call(
            "linkedin.profile",
            lambda: self._gw.client.linkedin.get_profile(public_id),
            budget=ctx.budget,
        )
        now = ctx.now()
        batch = FetchBatch()
        batch.raw.append(
            RawPayload(
                source=Source.SB_LINKEDIN_PROFILE,
                external_id=public_id,
                fetched_at=now,
                body=_dump(profile),
            )
        )
        batch.records.append(mappers.map_linkedin_profile(profile, now=now))
        return batch


@register("scrapebadger")
def build(settings: Settings) -> ScrapeBadgerConnector:
    if settings.scrapebadger_api_key is not None:
        api_key = settings.scrapebadger_api_key.get_secret_value()
    elif settings.scrapebadger_secret_arn:
        from leadintel.security.keyring import build_secrets_provider

        api_key = build_secrets_provider(settings).get(settings.scrapebadger_secret_arn)
    else:
        raise ConfigurationError("ScrapeBadger API key is not configured")
    gateway = ScrapeBadgerGateway.from_api_key(
        api_key,
        timeout_s=settings.scrapebadger_timeout_s,
        max_retries=settings.scrapebadger_max_retries,
        max_concurrency=settings.scrapebadger_max_concurrency,
    )
    return ScrapeBadgerConnector(
        gateway, allow_person_profiles=settings.allow_person_profile_scraping
    )
