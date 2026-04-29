-- V016: add given_up_at to make the retry terminal state explicit.
-- State machine:
--   failed_at IS NOT NULL, sent_at IS NULL, given_up_at IS NULL → pending retry
--   sent_at IS NOT NULL                                         → delivered (terminal)
--   given_up_at IS NOT NULL                                     → exhausted (terminal)
ALTER TABLE alerts.sent_alerts ADD COLUMN given_up_at TIMESTAMPTZ;
COMMENT ON COLUMN alerts.sent_alerts.given_up_at IS
    'Set by RetryWorker after 4 failed delivery attempts — terminal failure state';
