from contextlib import contextmanager
import time
import psycopg
from psycopg.rows import dict_row
from .crypto import digest
from .config import ROOT

class Database:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.settings.database_url, row_factory=dict_row, connect_timeout=5, options='-c statement_timeout=15000 -c lock_timeout=10000') as conn:
            yield conn

    def migrate(self):
        with self.transaction() as c:
            c.execute('SELECT pg_advisory_xact_lock(72002001)')
            c.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL)')
            for path in sorted((ROOT / 'service/migrations').glob('*.sql')):
                checksum = digest(path.read_bytes())
                row = c.execute('SELECT sha256 FROM schema_migrations WHERE name=%s', (path.name,)).fetchone()
                if row:
                    if row['sha256'] != checksum:
                        raise ValueError('Previously applied migration changed')
                else:
                    c.execute(path.read_text())
                    c.execute('INSERT INTO schema_migrations VALUES (%s,%s)', (path.name, checksum))
            c.execute('INSERT INTO backend_profile VALUES(true,%s) ON CONFLICT DO NOTHING', (self.settings.profile,))
            if c.execute('SELECT profile FROM backend_profile').fetchone()['profile'] != self.settings.profile:
                raise ValueError('Database profile mismatch')

    def check_profile(self):
        with self.transaction() as c:
            if c.execute('SELECT profile FROM backend_profile').fetchone()['profile'] != self.settings.profile:
                raise ValueError('Database profile mismatch')

    def rate(self, key, limit, now):
        with self.transaction() as c:
            count = c.execute('INSERT INTO rate_limits VALUES (%s,%s,1) ON CONFLICT(key,bucket) DO UPDATE SET count=rate_limits.count+1 RETURNING count', (digest(key), now//60)).fetchone()['count']
            return count <= limit

    def cleanup(self):
        now = int(time.time())
        with self.transaction() as c:
            for table in ('challenges','sessions','tickets'):
                c.execute(f'DELETE FROM {table} WHERE expires_at <= %s', (now,))
            c.execute('DELETE FROM rate_limits WHERE bucket < %s', (now//60-2,))
            c.execute('UPDATE idempotency SET encrypted_result=NULL WHERE replay_until <= %s AND encrypted_result IS NOT NULL', (now,))
            c.execute("UPDATE orders SET status='cancelled' WHERE status='pending' AND expires_at<=%s", (now,))
