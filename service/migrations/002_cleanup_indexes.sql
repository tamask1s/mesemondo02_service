-- Avoid repeated full-table scans as expired tokens and operation tombstones grow.
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE INDEX tickets_expiry ON tickets(expires_at);
CREATE INDEX idempotency_live_expiry ON idempotency(replay_until) WHERE encrypted_result IS NOT NULL;
CREATE INDEX orders_pending_expiry ON orders(expires_at) WHERE status='pending';
CREATE INDEX rate_limits_bucket ON rate_limits(bucket);
