#![allow(dead_code)]
use sense_people_counter::{
    agents::Adapters, config::load_config, contracts::*, orchestrator::SenseOrchestrator,
    runtime::TaskManager, storage::ExperimentLog,
};
use serde_json::{Value, json};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
pub fn config() -> Value {
    load_config(&Path::new(env!("CARGO_MANIFEST_DIR")).join("sense/pilot.yaml")).unwrap()
}
pub fn resources() -> Value {
    json!({"available_mb":4096,"main":{"rss_mb":100},"cpu_total_percent":10,"database_mb":1,"disk_free_mb":4096})
}
pub fn stamp(at: f64) -> String {
    chrono::DateTime::from_timestamp_micros((at * 1e6) as i64)
        .unwrap()
        .to_rfc3339_opts(chrono::SecondsFormat::Micros, false)
}
pub fn telemetry(at: f64) -> Value {
    json!({"schema":"rustio.iot.telemetry.v1","device_id":"rpi5-01","timestamp":stamp(at),"environment":{"sht40":{"temperature_c":26.33,"humidity_percent":70.63},"ens160":{"aqi":2,"tvoc_ppb":70,"eco2_ppm":497}},"presence":{"state_code":2,"state":"Persona estática"}})
}
pub fn command(action: &str) -> Value {
    json!({"command_id":identifier(),"correlation_id":"cycle","experiment_run_id":"run","target_agent":if action=="vision"{"VisionAgent"}else{"InterpretationAgent"},"action":action,"created_at":utc_now(),"deadline":utc_now(),"parameters":{"question_id":if action=="vision"{"Q2"}else if action=="text"{"Q6"}else{"Q7"}},"reason":"TEST","schema":"sense.v1"})
}
pub fn initial() -> Value {
    json!({"observed_at":utc_now(),"power_observed_at":utc_now(),"people_observed_at":utc_now(),"region":"rasp_shared_view","power_w":0,"visible_people":0,"observer":"Operador","instrument":"Medidor","equipment":"Pi + sensores","unavailable_fields":[]})
}
pub struct Harness {
    pub temp: tempfile::TempDir,
    pub c: SenseOrchestrator,
    pub now: f64,
    pub wall: f64,
    pub second: Arc<Mutex<f64>>,
    pub captures: Arc<Mutex<Vec<f64>>>,
    pub completions: Arc<Mutex<Vec<Option<Vec<u8>>>>>,
    pub ready: Arc<Mutex<Value>>,
}
impl Harness {
    pub fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let cfg = config();
        let now = monotonic();
        let wall = wall_time();
        let second = Arc::new(Mutex::new(0.));
        let captures = Arc::new(Mutex::new(vec![]));
        let completions = Arc::new(Mutex::new(vec![]));
        let (s, c) = (second.clone(), captures.clone());
        let completion = completions.clone();
        let adapters = Adapters {
            capture: Arc::new(move || {
                let t = *s.lock().unwrap();
                c.lock().unwrap().push(t);
                Ok((b"image".to_vec(), stamp(wall + t)))
            }),
            detector: Arc::new(|_| Ok(2)),
            completion: Arc::new(move |_, image, _| {
                completion.lock().unwrap().push(image.map(|b| b.to_vec()));
                Ok(
                    json!({"content":"{\"inferences\":[\"Descripción de prueba.\"],\"unknowns\":[],\"recommendations\":[]}"}),
                )
            }),
            model: "test".into(),
        };
        let ready = Arc::new(Mutex::new(
            json!({"yolo":"ready","text":"ready","vision":"ready"}),
        ));
        let rd = ready.clone();
        let mut c = SenseOrchestrator::new(
            cfg,
            ExperimentLog::new(&temp.path().join("experiments.sqlite3")).unwrap(),
            TaskManager::new(1),
            adapters,
            Arc::new(move || rd.lock().unwrap().clone()),
            json!({"model_version":{"yolo":"test","gemma":"test"}}),
        );
        c.resources = resources();
        Self {
            temp,
            c,
            now,
            wall,
            second,
            captures,
            completions,
            ready,
        }
    }
    pub fn disable_models(&mut self) {
        *self.ready.lock().unwrap() = json!({"yolo":"error","text":"error","vision":"error"});
    }
    pub fn start(&mut self, mode: &str) -> Value {
        self.c
            .start(mode, self.now, "session", "scenario", &json!({}))
            .unwrap()
    }
    pub fn guided(&mut self, mode: &str, scenario: &str, repetition: i32) -> Value {
        self.c.start(mode,self.now,"session",scenario,&json!({"guided":true,"scenario_id":scenario,"repetition":repetition,"initial_observation":initial()})).unwrap()
    }
    pub fn step(&mut self, second: f64) {
        *self.second.lock().unwrap() = second;
        self.c.log.db.execute_batch("BEGIN").unwrap();
        let r = self.c.tick(self.now + second, resources());
        self.c
            .log
            .db
            .execute_batch(if r.is_ok() { "COMMIT" } else { "ROLLBACK" })
            .unwrap();
        r.unwrap();
    }
    pub fn ingest(&mut self, second: f64, p: Option<Value>) {
        *self.second.lock().unwrap() = second;
        self.c
            .ingest(
                &p.unwrap_or_else(|| telemetry(self.wall + second)),
                self.now + second,
                self.wall + second,
            )
            .unwrap();
    }
    pub fn finish_lane(&mut self, lane: &str, second: f64) {
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.c.tasks.active[lane].is_some() {
            assert!(Instant::now() < deadline, "worker {lane} did not complete");
            std::thread::sleep(Duration::from_millis(1));
            self.step(second);
        }
    }
    pub fn finish_vision(&mut self) {
        self.step(0.);
        self.finish_lane("vision", 0.1);
    }
    pub fn fault(&mut self, component: &str, enabled: bool, second: f64) {
        self.c
            .set_fault(
                &json!({"action":"availability","component":component,"enabled":enabled}),
                self.now + second,
            )
            .unwrap();
    }
    pub fn events(&self) -> Vec<Value> {
        let mut bytes = vec![];
        self.c
            .log
            .export_ndjson(text(&self.c.run["run_id"]), &mut bytes)
            .unwrap();
        String::from_utf8(bytes)
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }
    pub fn event(&self, kind: &str) -> Value {
        self.events()
            .into_iter()
            .find(|e| e["type"] == kind)
            .unwrap_or_else(|| panic!("missing event {kind}"))
    }
}
pub struct ApiHarness {
    pub temp: tempfile::TempDir,
    pub app: Arc<sense_people_counter::api::AppState>,
}
impl ApiHarness {
    pub fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path();
        std::fs::create_dir(root.join("sense")).unwrap();
        std::fs::create_dir(root.join("public")).unwrap();
        let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("public");
        for file in [
            "index.html",
            "measurement.js",
            "measurement.css",
            "api.js",
            "offline.js",
            "app.js",
            "replay.js",
            "replay-data.js",
            "replay.css",
        ] {
            std::fs::copy(source.join(file), root.join("public").join(file)).unwrap();
        }
        let mut cfg = config();
        cfg["runtime"]["tick_seconds"] = json!(0.005);
        cfg["runtime"]["publish_interval_seconds"] = json!(0.01);
        cfg["runtime"]["min_available_mb"] = json!(1);
        cfg["runtime"]["max_cpu_percent"] = json!(101);
        std::fs::write(
            root.join("sense/pilot.yaml"),
            serde_yaml_ng::to_string(&cfg).unwrap(),
        )
        .unwrap();
        let adapters = Harness::new().c.adapters.clone();
        let app = sense_people_counter::api::AppState::with_adapters(root, adapters);
        for name in ["yolo", "text", "vision"] {
            app.set_phase(name, "error", "test");
        }
        Self { temp, app }
    }
    pub async fn request(&self, method: &str, path: &str, body: Value) -> (u16, Value, Vec<u8>) {
        use tower::ServiceExt;
        let req = axum::http::Request::builder()
            .method(method)
            .uri(path)
            .header("content-type", "application/json")
            .body(axum::body::Body::from(body.to_string()))
            .unwrap();
        let response = sense_people_counter::api::router(self.app.clone())
            .oneshot(req)
            .await
            .unwrap();
        let status = response.status().as_u16();
        let bytes = axum::body::to_bytes(response.into_body(), 64 * 1024 * 1024)
            .await
            .unwrap()
            .to_vec();
        let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        (status, value, bytes)
    }
    pub async fn start(&self, mode: &str) -> String {
        let (status, body, _) = self
            .request("POST", "/api/experiments/start", json!({"mode":mode}))
            .await;
        assert_eq!(status, 202, "{body}");
        text(&body["run_id"]).into()
    }
}
impl Drop for ApiHarness {
    fn drop(&mut self) {
        self.app.close();
    }
}
