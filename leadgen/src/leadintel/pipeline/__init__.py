"""Data pipeline: normalize -> resolve -> score.

``normalize``    canonical forms for emails, domains, phones, names, URLs
``resolution``   blocking, pairwise matching, clustering, survivorship
``scoring``      explainable fit / intent / engagement scores and tiers
``service``      orchestration over the repositories (used by Lambda handlers)
"""
