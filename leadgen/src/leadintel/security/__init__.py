"""Security building blocks.

=========================  ====================================================
Module                     Responsibility
=========================  ====================================================
``crypto``                 KMS envelope encryption for restricted attributes
``blind_index``            keyed HMAC indexes for equality search on ciphertext
``authz``                  roles, permissions, territory scoping, PII masking
``audit``                  tamper-evident (hash-chained) audit events
``secrets``                Secrets Manager access with caching
``jwt_verifier``           Cognito access-token verification
``webhooks``               inbound webhook signature verification
``ssrf``                   outbound URL validation
``redaction``              scrubbing of identifiers and credentials from logs
=========================  ====================================================
"""
