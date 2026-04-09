-- Migration 002: Dual font selection (primary + secondary)
-- Apply this in Supabase Dashboard > SQL Editor

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS font_style_secondary TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS font_prompt_secondary TEXT;
