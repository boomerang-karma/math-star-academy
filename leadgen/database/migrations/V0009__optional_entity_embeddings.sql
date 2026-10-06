-- Optional: entity embeddings for lookalike-account search (roadmap phase 3).
-- Created only where pgvector is available (Aurora PostgreSQL ships it); a plain
-- local PostgreSQL without the extension skips this and the feature stays disabled.
--
-- leadintel:as-login-user   (CREATE EXTENSION needs the connecting user)

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
        CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
        CREATE TABLE IF NOT EXISTS graph.entity_embedding (
            entity_id   uuid PRIMARY KEY REFERENCES graph.entity (id) ON DELETE CASCADE,
            model       text NOT NULL,
            embedding   extensions.vector(1024) NOT NULL,
            updated_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS entity_embedding_hnsw_idx ON graph.entity_embedding
            USING hnsw (embedding extensions.vector_cosine_ops);
        ALTER TABLE graph.entity_embedding OWNER TO leadintel_owner;
        GRANT SELECT ON graph.entity_embedding TO leadintel_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON graph.entity_embedding TO leadintel_pipeline;
    ELSE
        RAISE NOTICE 'pgvector is not available: skipping graph.entity_embedding';
    END IF;
END
$$;
