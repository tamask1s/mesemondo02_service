CREATE TABLE backend_profile (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), profile text NOT NULL CHECK(profile IN ('dev','production')));
CREATE TABLE devices (
 id uuid PRIMARY KEY, public_key text NOT NULL UNIQUE, security_profile text NOT NULL CHECK(security_profile IN ('dev','production')),
 hardware_id text NOT NULL CHECK(hardware_id = 'mm02-s3n16r8-r1'), status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked')),
 created_at bigint NOT NULL
);
CREATE TABLE challenges (id uuid PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices, nonce text NOT NULL, expires_at bigint NOT NULL, consumed boolean NOT NULL DEFAULT false);
CREATE INDEX challenges_expiry ON challenges(expires_at);
CREATE TABLE sessions (token_hash text PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices, issued_at bigint NOT NULL, expires_at bigint NOT NULL);
CREATE INDEX sessions_device ON sessions(device_id);
CREATE TABLE contents (id uuid PRIMARY KEY, title text NOT NULL, description text NOT NULL, price_minor bigint NOT NULL CHECK(price_minor BETWEEN 0 AND 9007199254740991), currency text NOT NULL CHECK(currency='HUF'));
CREATE TABLE content_versions (content_id uuid NOT NULL REFERENCES contents, version integer NOT NULL CHECK(version>0), manifest_jws text NOT NULL, manifest_sha256 text NOT NULL, PRIMARY KEY(content_id,version));
CREATE TABLE files (id uuid PRIMARY KEY, sha256 text NOT NULL CHECK(length(sha256)=64), size_bytes bigint NOT NULL CHECK(size_bytes BETWEEN 1 AND 2147483648), media_type text NOT NULL);
CREATE TABLE content_files (content_id uuid NOT NULL, version integer NOT NULL, file_id uuid NOT NULL REFERENCES files, PRIMARY KEY(content_id,version,file_id), FOREIGN KEY(content_id,version) REFERENCES content_versions);
CREATE TABLE entitlements (device_id uuid NOT NULL REFERENCES devices, content_id uuid NOT NULL REFERENCES contents, grant_id uuid NOT NULL UNIQUE, issued_at bigint NOT NULL, PRIMARY KEY(device_id,content_id));
CREATE TABLE tickets (token_hash text PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices, file_id uuid NOT NULL REFERENCES files, content_id uuid REFERENCES contents, expires_at bigint NOT NULL);
CREATE INDEX tickets_device ON tickets(device_id);
CREATE TABLE orders (id uuid PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices, status text NOT NULL CHECK(status IN ('pending','paid','failed','cancelled')), total_minor bigint NOT NULL CHECK(total_minor>=0), currency text NOT NULL CHECK(currency='HUF'), provider text NOT NULL, merchant text NOT NULL, expires_at bigint NOT NULL, checkout_hash text NOT NULL UNIQUE);
CREATE TABLE order_items (order_id uuid NOT NULL REFERENCES orders, content_id uuid NOT NULL REFERENCES contents, price_minor bigint NOT NULL CHECK(price_minor>=0), PRIMARY KEY(order_id,content_id));
CREATE TABLE payment_events (provider text NOT NULL, event_id uuid NOT NULL, body_hash text NOT NULL, order_id uuid NOT NULL REFERENCES orders, PRIMARY KEY(provider,event_id));
CREATE TABLE recovery_hashes (device_id uuid PRIMARY KEY REFERENCES devices, token_hash text NOT NULL, issued_at bigint NOT NULL);
CREATE TABLE idempotency (device_id uuid NOT NULL REFERENCES devices, operation text NOT NULL, key uuid NOT NULL, request_hash text NOT NULL, encrypted_result text, replay_until bigint NOT NULL, PRIMARY KEY(device_id,operation,key));
CREATE TABLE transfer_audit (id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES devices, target_id uuid NOT NULL REFERENCES devices, created_at bigint NOT NULL, UNIQUE(source_id), CHECK(source_id<>target_id));
CREATE TABLE audit (id bigserial PRIMARY KEY, action text NOT NULL, device_id uuid, object_id uuid, created_at bigint NOT NULL);
CREATE TABLE firmware_releases (id uuid PRIMARY KEY, published_order bigserial UNIQUE, hardware_id text NOT NULL, version text NOT NULL, secure_version integer NOT NULL CHECK(secure_version BETWEEN 0 AND 65535), manifest_jws text NOT NULL, file_id uuid NOT NULL REFERENCES files, created_at bigint NOT NULL, UNIQUE(hardware_id,version));
CREATE TABLE rate_limits (key text NOT NULL, bucket bigint NOT NULL, count integer NOT NULL, PRIMARY KEY(key,bucket));
