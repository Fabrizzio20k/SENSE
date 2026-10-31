
            CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                ended_at TEXT, status TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_run ON events(run_id, sequence);
            CREATE INDEX IF NOT EXISTS events_run_type ON events(run_id, type, sequence);
            CREATE TABLE IF NOT EXISTS human_records (record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS human_records_run ON human_records(run_id);
            CREATE TABLE IF NOT EXISTS samples_1s (run_id TEXT NOT NULL, second INTEGER NOT NULL,
                timestamp TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, second));
            CREATE TABLE IF NOT EXISTS observer_requests (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                requested_at TEXT NOT NULL, reason TEXT NOT NULL, task_id TEXT, event_id TEXT,
                fields TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', record_id TEXT);
            CREATE INDEX IF NOT EXISTS observer_requests_run ON observer_requests(run_id, status);
        