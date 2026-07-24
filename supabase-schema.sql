-- ============================================================
-- Plaudia — Schéma Supabase (migration d'installation)
-- ============================================================
-- Exécuter dans l'éditeur SQL Supabase sur un nouveau projet
-- Nécessite : extensions vector, pgcrypto, uuid-ossp

-- ============================================================
-- 1. EXTENSIONS
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- 2. TABLES
-- ============================================================

-- Entreprises clientes
CREATE TABLE enterprises (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Projets par entreprise
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    keywords TEXT[],
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Enregistrements Plaud
CREATE TABLE recordings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plaud_file_id TEXT UNIQUE,
    title TEXT,
    client_name TEXT,
    meeting_type TEXT,
    meeting_subject TEXT,
    recorded_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    raw_transcript TEXT,
    transcript_segments JSONB,
    transcript_fetched_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status = ANY (ARRAY['pending', 'transcribing', 'transcribed', 'summarizing', 'ready', 'error'])),
    error_message TEXT,
    is_private BOOLEAN NOT NULL DEFAULT false,
    enterprise_id UUID REFERENCES enterprises(id),
    project_id UUID REFERENCES projects(id),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Comptes-rendus
CREATE TABLE crs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id UUID UNIQUE NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status = ANY (ARRAY['draft', 'ready', 'sent', 'validated'])),
    last_edit_instruction TEXT,
    doc_url TEXT,
    email_sent_to TEXT[],
    sent_at TIMESTAMPTZ,
    enterprise_id UUID REFERENCES enterprises(id),
    project_id UUID REFERENCES projects(id),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historique des versions de CR
CREATE TABLE cr_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cr_id UUID NOT NULL REFERENCES crs(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_validated BOOLEAN DEFAULT false,
    owner_id UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Corrections orthographiques auto-apprenantes
CREATE TABLE glossary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES auth.users(id),
    term_raw TEXT NOT NULL,
    term_corrected TEXT NOT NULL,
    uses_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Templates HTML des CRs
CREATE TABLE templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    html_template TEXT,
    prompt_instructions TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Leçons de style apprises des éditions
CREATE TABLE cr_style_guide (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES auth.users(id),
    category TEXT NOT NULL DEFAULT 'style'
        CHECK (category = ANY (ARRAY['style', 'structure', 'tone', 'format', 'vocabulary'])),
    instruction TEXT NOT NULL,
    example_before TEXT,
    example_after TEXT,
    source_cr_id UUID REFERENCES crs(id),
    applied_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chunks vectorisés pour le RAG
CREATE TABLE rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    cr_id UUID REFERENCES crs(id),
    chunk_index INTEGER NOT NULL,
    chunk_type TEXT NOT NULL
        CHECK (chunk_type = ANY (ARRAY['transcription_full', 'cr_section', 'cr_final_table'])),
    content TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB NOT NULL DEFAULT '{}',
    client_name TEXT,
    meeting_date DATE,
    enterprise_id UUID REFERENCES enterprises(id),
    project_id UUID REFERENCES projects(id),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sessions de chat RAG
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    title TEXT,
    tags JSONB DEFAULT '[]',
    enterprise_id UUID REFERENCES enterprises(id),
    project_id UUID REFERENCES projects(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Messages des sessions de chat
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    role TEXT NOT NULL CHECK (role = ANY (ARRAY['user', 'assistant'])),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Profils utilisateurs
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id),
    email TEXT NOT NULL,
    name TEXT,
    role TEXT NOT NULL DEFAULT 'user'
        CHECK (role = ANY (ARRAY['user', 'admin'])),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tokens OAuth (Google)
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    provider TEXT NOT NULL CHECK (provider = ANY (ARRAY['gmail', 'drive'])),
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    token_expiry TIMESTAMPTZ,
    scope TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Participants aux réunions
CREATE TABLE participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT,
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Actions à faire
CREATE TABLE action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    cr_id UUID REFERENCES crs(id),
    description TEXT NOT NULL,
    responsible TEXT,
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status = ANY (ARRAY['pending', 'done'])),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Base de connaissances
CREATE TABLE knowledge_base (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL,
    value TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 4. TRIGGERS
-- ============================================================

-- Mise à jour automatique de updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enterprises_updated_at
    BEFORE UPDATE ON enterprises FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_projects_updated_at
    BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_recordings_updated_at
    BEFORE UPDATE ON recordings FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_crs_updated_at
    BEFORE UPDATE ON crs FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Propager enterprise_id de recordings → crs
CREATE OR REPLACE FUNCTION propagate_enterprise_to_crs()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.enterprise_id IS DISTINCT FROM OLD.enterprise_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id THEN
        UPDATE crs
        SET enterprise_id = NEW.enterprise_id,
            project_id = NEW.project_id,
            updated_at = now()
        WHERE recording_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_propagate_enterprise_to_crs
    AFTER UPDATE OF enterprise_id, project_id ON recordings
    FOR EACH ROW EXECUTE FUNCTION propagate_enterprise_to_crs();

-- Réécriture rétroactive des CRs via le glossaire
-- (à créer si besoin)
-- CREATE OR REPLACE FUNCTION glossary_retroactive_rewrite() ...

-- ============================================================
-- 5. RPC — RAG search
-- ============================================================
CREATE OR REPLACE FUNCTION match_rag_chunks(
    query_embedding VECTOR(1536),
    match_threshold FLOAT DEFAULT 0.7,
    match_count INT DEFAULT 20,
    client_name TEXT DEFAULT NULL,
    enterprise_id UUID DEFAULT NULL,
    project_id UUID DEFAULT NULL
)
RETURNS TABLE(
    id UUID,
    recording_id UUID,
    cr_id UUID,
    chunk_index INT,
    chunk_type TEXT,
    content TEXT,
    metadata JSONB,
    client_name TEXT,
    meeting_date DATE,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        rc.id,
        rc.recording_id,
        rc.cr_id,
        rc.chunk_index,
        rc.chunk_type,
        rc.content,
        rc.metadata,
        rc.client_name,
        rc.meeting_date,
        1 - (rc.embedding <=> query_embedding) AS similarity
    FROM rag_chunks rc
    WHERE 1 - (rc.embedding <=> query_embedding) > match_threshold
      AND (client_name IS NULL OR rc.client_name = client_name)
      AND (enterprise_id IS NULL OR rc.enterprise_id = enterprise_id)
      AND (project_id IS NULL OR rc.project_id = project_id)
    ORDER BY rc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================
-- 5. VUE MATÉRIALISÉE — enterprise_counts (2026-07-20)
-- ============================================================
-- Remplacer l'endpoint GET /v1/enterprises/with-counts (supprimé du backend en CQRS)
-- par cette vue. Le frontend doit lire enterprise_counts directement via Supabase.

CREATE MATERIALIZED VIEW IF NOT EXISTS enterprise_counts AS
SELECT
  e.id AS enterprise_id,
  COUNT(DISTINCT cr.id) AS cr_count,
  COUNT(DISTINCT r.id) AS recording_count
FROM enterprises e
LEFT JOIN crs cr ON cr.enterprise_id = e.id
LEFT JOIN recordings r ON r.enterprise_id = e.id
GROUP BY e.id;

CREATE UNIQUE INDEX IF NOT EXISTS enterprise_counts_pkey ON enterprise_counts (enterprise_id);

-- Note : après un refresh de la vue, redonner les permissions :
GRANT SELECT ON enterprise_counts TO anon;
GRANT SELECT ON enterprise_counts TO authenticated;

-- ============================================================
-- 6. ROW LEVEL SECURITY
-- ============================================================
-- Active RLS sur toutes les tables.
-- Les policies détaillées sont dans migrations/002_multi_user_rls.sql

ALTER TABLE enterprises ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE crs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cr_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE glossary ENABLE ROW LEVEL SECURITY;
ALTER TABLE templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE cr_style_guide ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 7. is_system flag for projects
-- ============================================================
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT false;