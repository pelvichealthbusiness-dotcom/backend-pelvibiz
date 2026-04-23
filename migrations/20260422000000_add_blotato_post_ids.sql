ALTER TABLE requests_log
    ADD COLUMN IF NOT EXISTS blotato_post_ids JSONB DEFAULT '{}'::jsonb;
