-- ============================================================
-- Plaudia — Migration 002 : Multi-user Auth + RLS + Shares
-- ============================================================
-- Exécuter APRÈS supabase-schema.sql
-- Active RLS sur toutes les tables et crée les policies
-- ============================================================

-- ============================================================
-- 1. ROW LEVEL SECURITY — Activation
-- ============================================================
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
-- 2. RLS POLICIES — enterprises
-- ============================================================
-- Admin voit tout, user voit ses propres entreprises
CREATE POLICY "enterprises_owner_all" ON enterprises
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "enterprises_admin_all" ON enterprises
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 3. RLS POLICIES — projects
-- ============================================================
CREATE POLICY "projects_owner_all" ON projects
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "projects_admin_all" ON projects
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 4. RLS POLICIES — recordings
-- ============================================================
CREATE POLICY "recordings_owner_all" ON recordings
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "recordings_admin_all" ON recordings
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 5. RLS POLICIES — crs
-- ============================================================
CREATE POLICY "crs_owner_all" ON crs
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "crs_admin_all" ON crs
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 6. RLS POLICIES — cr_versions
-- ============================================================
CREATE POLICY "cr_versions_owner_all" ON cr_versions
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "cr_versions_admin_all" ON cr_versions
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 7. RLS POLICIES — glossary
-- ============================================================
-- owner_id NULL = partagé, owner_id = auth.uid() = personnel
CREATE POLICY "glossary_read_all" ON glossary
    FOR SELECT USING (owner_id IS NULL OR owner_id = auth.uid());
CREATE POLICY "glossary_owner_write" ON glossary
    FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY "glossary_owner_update" ON glossary
    FOR UPDATE USING (owner_id = auth.uid());
CREATE POLICY "glossary_owner_delete" ON glossary
    FOR DELETE USING (owner_id = auth.uid());
CREATE POLICY "glossary_admin_all" ON glossary
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 8. RLS POLICIES — templates
-- ============================================================
CREATE POLICY "templates_read_all" ON templates
    FOR SELECT USING (true);
CREATE POLICY "templates_admin_all" ON templates
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 9. RLS POLICIES — cr_style_guide
-- ============================================================
CREATE POLICY "cr_style_guide_owner_all" ON cr_style_guide
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "cr_style_guide_admin_all" ON cr_style_guide
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 10. RLS POLICIES — rag_chunks
-- ============================================================
CREATE POLICY "rag_chunks_owner_all" ON rag_chunks
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "rag_chunks_admin_all" ON rag_chunks
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 11. RLS POLICIES — chat_sessions / chat_messages
-- ============================================================
CREATE POLICY "chat_sessions_owner_all" ON chat_sessions
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "chat_sessions_admin_all" ON chat_sessions
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );
CREATE POLICY "chat_messages_owner_all" ON chat_messages
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "chat_messages_admin_all" ON chat_messages
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 12. RLS POLICIES — participants
-- ============================================================
CREATE POLICY "participants_owner_all" ON participants
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "participants_admin_all" ON participants
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 13. RLS POLICIES — action_items
-- ============================================================
CREATE POLICY "action_items_owner_all" ON action_items
    FOR ALL USING (owner_id = auth.uid());
CREATE POLICY "action_items_admin_all" ON action_items
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 14. RLS POLICIES — user_profiles
-- ============================================================
CREATE POLICY "user_profiles_self" ON user_profiles
    FOR SELECT USING (id = auth.uid());
CREATE POLICY "user_profiles_admin_all" ON user_profiles
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 15. RLS POLICIES — oauth_tokens
-- ============================================================
CREATE POLICY "oauth_tokens_owner_all" ON oauth_tokens
    FOR ALL USING (owner_id = auth.uid());

-- ============================================================
-- 16. RLS POLICIES — knowledge_base
-- ============================================================
CREATE POLICY "knowledge_base_read_all" ON knowledge_base
    FOR SELECT USING (true);
CREATE POLICY "knowledge_base_admin_all" ON knowledge_base
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 17. RLS POLICIES — enterprise_counts (vue matérialisée)
-- ============================================================
GRANT SELECT ON enterprise_counts TO anon;
GRANT SELECT ON enterprise_counts TO authenticated;

-- ============================================================
-- 18. TABLE — project_shares
-- ============================================================
CREATE TABLE IF NOT EXISTS project_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    shared_with_email TEXT NOT NULL,
    permission TEXT NOT NULL DEFAULT 'view'
        CHECK (permission = ANY (ARRAY['view', 'edit'])),
    shared_by UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE project_shares ENABLE ROW LEVEL SECURITY;

CREATE POLICY "project_shares_owner_all" ON project_shares
    FOR ALL USING (shared_by = auth.uid());
CREATE POLICY "project_shares_admin_all" ON project_shares
    FOR ALL USING (
        EXISTS (SELECT 1 FROM user_profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- 19. TRIGGER — auto-create user_profiles on signup
-- ============================================================
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO user_profiles (id, email, name, role)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data ->> 'full_name', NEW.email),
        'user'
    )
    ON CONFLICT (id) DO UPDATE SET email = NEW.email;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ============================================================
-- 20. REFRESH — enterprise_counts (auto après insert/update/delete)
-- ============================================================
CREATE OR REPLACE FUNCTION refresh_enterprise_counts()
RETURNS TRIGGER AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY enterprise_counts;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_refresh_enterprise_counts_crs ON crs;
CREATE TRIGGER trg_refresh_enterprise_counts_crs
    AFTER INSERT OR UPDATE OR DELETE ON crs
    FOR EACH STATEMENT EXECUTE FUNCTION refresh_enterprise_counts();

DROP TRIGGER IF EXISTS trg_refresh_enterprise_counts_recordings ON recordings;
CREATE TRIGGER trg_refresh_enterprise_counts_recordings
    AFTER INSERT OR UPDATE OR DELETE ON recordings
    FOR EACH STATEMENT EXECUTE FUNCTION refresh_enterprise_counts();

-- ============================================================
-- 21. MIGRATION — is_system flag for projects
-- ============================================================
-- Remplace le fragile filtre par nom "Général"
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT false;

-- Les projets "Général" existants sont marqués comme système
UPDATE projects SET is_system = true WHERE name = 'Général';