-- User interactions tracking for learning loop
CREATE TABLE IF NOT EXISTS user_interactions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL CHECK (interaction_type IN (
        'idea_selected', 'idea_rejected', 'idea_edited',
        'content_published', 'content_deleted', 'field_regenerated'
    )),
    reference_id TEXT,
    reference_type TEXT CHECK (reference_type IN ('idea', 'carousel', 'video', 'profile_field')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_user_interactions_user_date 
    ON user_interactions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_interactions_type 
    ON user_interactions (user_id, interaction_type);

-- RLS
ALTER TABLE user_interactions ENABLE ROW LEVEL SECURITY;

-- Users can read their own interactions
CREATE POLICY "Users read own interactions" ON user_interactions
    FOR SELECT USING (auth.uid() = user_id);

-- Users can insert their own interactions
CREATE POLICY "Users insert own interactions" ON user_interactions
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Service role can do everything (for the API)
CREATE POLICY "Service role full access" ON user_interactions
    FOR ALL USING (auth.role() = 'service_role');
