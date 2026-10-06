# 0006. Field-level envelope encryption with blind indexes

**Status:** Accepted

## Context

Emails and personal phone numbers are the most sensitive data we hold.
Storage-level encryption (Aurora/KMS) does not protect them from:

- anyone with database read access
- database snapshots shared by mistake
- logs that capture query results

We still need to find people by email: deduplication, suppression checks,
DSARs.

## Decision

- **Encryption.** Restricted attributes are encrypted with AES-256-GCM under a
  data key wrapped by a customer-managed KMS key. The encryption context
  (tenant, purpose, application) is bound into both KMS and the GCM associated
  data. Data keys are cached briefly.
- **Lookups.** Use HMAC-SHA256 blind indexes (keyed per field, key held in
  Secrets Manager). Nothing is ever looked up by plaintext.
- **Access.** Decryption happens only in the API for `pii:read` holders. Every
  decryption is audited, and everyone else sees masked values.

## Alternatives

- **pgcrypto in the database.** Keys would live in, or pass through, the
  database. That defeats the purpose.
- **Deterministic encryption for lookups.** It leaks equality just like a blind
  index, but ties lookups to the encryption key and rotation.
- **Tokenization service.** Another stateful system to run.

## Consequences

- **Database-only compromise.** A database dump without KMS access reveals no
  contact details.
- **Equality only.** Blind indexes support only equality lookups, which is all
  we need.
- **Key rotation.** The KMS key rotates automatically. The blind-index key
  cannot be rotated in place: suppressions for erased people exist only as
  indexes. Rotation needs versioned keys with dual lookup (roadmap).
