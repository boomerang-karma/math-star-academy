# Architecture decision records

Each record captures one significant decision: the context, the decision, the
alternatives weighed, and the consequences we accept. Records are immutable once
accepted. To change course, add a new record that supersedes the old one.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-serverless-first.md) | Serverless first on AWS | Accepted |
| [0002](0002-aurora-postgresql-as-graph-store.md) | Aurora PostgreSQL as system of record and graph store | Accepted |
| [0003](0003-ontology-with-provenance.md) | Ontology with per-attribute provenance and survivorship | Accepted |
| [0004](0004-probabilistic-entity-resolution.md) | Probabilistic entity resolution with a human review queue | Accepted |
| [0005](0005-scrapebadger-behind-anti-corruption-layer.md) | ScrapeBadger first, behind an anti-corruption layer | Accepted |
| [0006](0006-field-level-encryption-and-blind-indexes.md) | Field-level envelope encryption with blind indexes | Accepted |
| [0007](0007-row-level-security-for-territories.md) | Territory scoping with PostgreSQL row-level security | Accepted |
| [0008](0008-claude-on-bedrock-for-briefs.md) | Claude on Amazon Bedrock for account briefs | Accepted |
| [0009](0009-spa-auth-pkce-single-origin.md) | Single-origin SPA with Cognito PKCE | Accepted |
| [0010](0010-cdk-in-python.md) | AWS CDK in Python | Accepted |

Template: copy any record, renumber it, and keep the headings: Status, Context,
Decision, Alternatives, Consequences.
