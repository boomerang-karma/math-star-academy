"""ScrapeBadger adapter: the platform's first and broadest data source.

ScrapeBadger (https://scrapebadger.com) exposes LinkedIn's public, logged-out
surface (company pages, public profiles, guest job search), Google Search, Maps
and News, and generic website scraping behind one API key. This package wraps
the official ``scrapebadger`` SDK:

``gateway``    anti-corruption layer: timeouts, concurrency, error mapping, credits
``mappers``    pure functions from SDK models/dicts to ontology objects
``connector``  the playbooks (discovery, enrichment, signals) callable by name
"""
