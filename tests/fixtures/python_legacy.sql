BEGIN TRANSACTION;
CREATE TABLE events (sequence INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL);
INSERT INTO "events" VALUES(1,'legacy-completed','2026-10-31T18:06:55.473841+00:00','PYTHON_EVENT','{"value": 0}');
INSERT INTO "events" VALUES(2,'legacy-running','2026-10-31T18:06:55.474239+00:00','OBSERVER_REQUESTED','{"request_id": "f796c3d4df26485385b9b51627676d0f", "reason": "TEST", "task_id": null, "event_id": null, "fields": ["power_w"], "requested_at": "2026-10-31T18:06:55.474224+00:00"}');
CREATE TABLE human_records (record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
INSERT INTO "human_records" VALUES('1cd35c4451894ae3be53fd0347c85895','legacy-completed','2026-10-31T18:06:55.474019+00:00','GROUND_TRUTH','{"observed_at": "2026-10-31T18:06:55.474009+00:00", "region": "camera", "visible_people": 0}');
CREATE TABLE observer_requests (request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                requested_at TEXT NOT NULL, reason TEXT NOT NULL, task_id TEXT, event_id TEXT,
                fields TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', record_id TEXT);
INSERT INTO "observer_requests" VALUES('f796c3d4df26485385b9b51627676d0f','legacy-running','2026-10-31T18:06:55.474224+00:00','TEST',NULL,NULL,'["power_w"]','PENDING',NULL);
CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                ended_at TEXT, status TEXT NOT NULL, metadata TEXT NOT NULL);
INSERT INTO "runs" VALUES('legacy-completed','2026-10-31T18:06:55.473683+00:00','2026-10-31T18:06:55.474099+00:00','COMPLETED','{"run_id": "legacy-completed", "start_time": "2026-10-31T18:06:55.473683+00:00", "duration_seconds": 1800, "guided": false}');
INSERT INTO "runs" VALUES('legacy-running','2026-10-31T18:06:55.474153+00:00',NULL,'RUNNING','{"run_id": "legacy-running", "start_time": "2026-10-31T18:06:55.474153+00:00", "duration_seconds": 1800, "guided": true}');
CREATE TABLE samples_1s (run_id TEXT NOT NULL, second INTEGER NOT NULL,
                timestamp TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, second));
INSERT INTO "samples_1s" VALUES('legacy-completed',0,'2026-10-31T18:06:55.473931+00:00','{"timestamp_utc": "2026-10-31T18:06:55.473931+00:00", "second": 0, "sensor_data_status": "VALID"}');
CREATE INDEX events_run ON events(run_id, sequence);
CREATE INDEX events_run_type ON events(run_id, type, sequence);
CREATE INDEX human_records_run ON human_records(run_id);
CREATE INDEX observer_requests_run ON observer_requests(run_id, status);
COMMIT;
