-- Add failure_notified_at to track when user was alerted about a publishing failure
ALTER TABLE requests_log
  ADD COLUMN IF NOT EXISTS failure_notified_at TIMESTAMPTZ DEFAULT NULL;
