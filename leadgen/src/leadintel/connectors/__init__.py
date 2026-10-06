"""Data-source connectors (ports and adapters).

Every connector turns an upstream API into ontology objects
(:class:`~leadintel.ontology.SourceRecord`, :class:`~leadintel.ontology.Signal`)
plus the verbatim upstream payloads for the bronze zone. Nothing downstream
knows which vendor a fact came from except through its provenance.

==========================  =========================================================
Connector                   Source
==========================  =========================================================
``scrapebadger``            LinkedIn public pages & jobs, Google Search/Maps/News, websites
``linkedin_leadsync``       LinkedIn Lead Gen Form responses (official Lead Sync API)
``ga4``                     Google Analytics 4 Data API (per-visitor web activity)
``first_party``             our own tracking beacon (page views, form submissions)
==========================  =========================================================
"""
