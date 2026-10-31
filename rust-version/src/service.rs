use crate::{
    Result,
    agents::Adapters,
    config::load_config,
    contracts::*,
    orchestrator::{Readiness, SenseOrchestrator},
    runtime::TaskManager,
    storage::ExperimentLog,
    telemetry::ResourceMonitor,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc,
    },
    time::Duration,
};
pub fn software_metadata(root: &Path, model: &str) -> Result<Value> {
    let mut paths = vec![
        root.join("Cargo.toml"),
        root.join("Cargo.lock"),
        root.join("run.sh"),
    ];
    for dir in ["src", "public"] {
        if let Ok(entries) = std::fs::read_dir(root.join(dir)) {
            for e in entries.flatten() {
                let p = e.path();
                if p.is_file()
                    && p.extension()
                        .is_some_and(|x| ["rs", "html", "js", "css"].iter().any(|s| x == *s))
                {
                    paths.push(p);
                }
            }
        }
    }
    paths.sort();
    let mut hash = Sha256::new();
    for p in paths {
        if p.is_file() {
            hash.update(p.file_name().unwrap().to_string_lossy().as_bytes());
            hash.update(std::fs::read(p)?);
        }
    }
    let digest = hash
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let model_path = root.join("yolo26n.onnx");
    let model_hash = if model_path.is_file() {
        let mut file = std::fs::File::open(model_path)?;
        let mut h = Sha256::new();
        let mut buf = [0u8; 1048576];
        loop {
            use std::io::Read;
            let n = file.read(&mut buf)?;
            if n == 0 {
                break;
            }
            h.update(&buf[..n]);
        }
        Some(
            h.finalize()
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>(),
        )
    } else {
        None
    };
    Ok(
        json!({"software_version":digest,"rust_version":env!("SENSE_RUST_VERSION"),"platform":format!("{}/{}",std::env::consts::OS,std::env::consts::ARCH),"dependencies":dependency_versions(),"model_version":{"yolo":"yolo26n/ONNX","yolo_artifact_hash":model_hash,"gemma":model},"detector_parameters":{"imgsz":640,"classes":[0],"confidence":0.15,"device":"cpu"}}),
    )
}
struct Control {
    action: String,
    payload: Value,
    reply: mpsc::Sender<std::result::Result<Value, String>>,
    state: Arc<AtomicUsize>,
}
struct Packet {
    payload: Value,
    received: f64,
    wall: f64,
    run_id: String,
}
pub struct ExperimentService {
    pub path: PathBuf,
    pub reserved: Arc<AtomicBool>,
    pub starting: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
    controls: mpsc::SyncSender<Control>,
    inbox: Arc<Mutex<VecDequePacket>>,
    published: Arc<Mutex<Value>>,
    run_id: Arc<Mutex<Option<String>>>,
    dropped: Arc<AtomicUsize>,
    join: Mutex<Option<std::thread::JoinHandle<()>>>,
}
struct VecDequePacket {
    queue: std::collections::VecDeque<Packet>,
    capacity: usize,
}
impl ExperimentService {
    pub fn new(
        root: &Path,
        data: &Path,
        config_path: &Path,
        adapters: Adapters,
        readiness: Readiness,
    ) -> Result<Arc<Self>> {
        let config = load_config(config_path)?;
        let path = data.join("experiments.sqlite3");
        let log = ExperimentLog::new(&path)?;
        let resources = ResourceMonitor::new(&path);
        let controller = SenseOrchestrator::new(
            config.clone(),
            log,
            TaskManager::new(number(&config["interpretation"]["queue_capacity"]) as usize),
            adapters,
            readiness,
            json!({}),
        );
        let (tx, rx) = mpsc::sync_channel(8);
        let this = Arc::new(Self {
            path,
            reserved: Arc::new(AtomicBool::new(false)),
            starting: Arc::new(AtomicBool::new(false)),
            shutdown: Arc::new(AtomicBool::new(false)),
            controls: tx,
            inbox: Arc::new(Mutex::new(VecDequePacket {
                queue: std::collections::VecDeque::new(),
                capacity: number(&config["runtime"]["inbox_capacity"]) as usize,
            })),
            published: Arc::new(Mutex::new(json!({}))),
            run_id: Arc::new(Mutex::new(None)),
            dropped: Arc::new(AtomicUsize::new(0)),
            join: Mutex::new(None),
        });
        let worker = ServiceWorker {
            root: root.into(),
            config_path: config_path.into(),
            controller,
            resources,
            inbox: this.inbox.clone(),
            published: this.published.clone(),
            run_id: this.run_id.clone(),
            reserved: this.reserved.clone(),
            starting: this.starting.clone(),
            shutdown: this.shutdown.clone(),
            dropped: this.dropped.clone(),
            rx,
            session_id: utc_now(),
        };
        let join = std::thread::Builder::new()
            .name("sense-orchestrator".into())
            .spawn(move || worker.run())?;
        *this.join.lock().unwrap() = Some(join);
        Ok(this)
    }
    pub fn reserve(&self) -> Result<()> {
        self.reserved
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| "Ya hay una medición o un worker pendiente de finalizar.")?;
        self.starting.store(true, Ordering::SeqCst);
        Ok(())
    }
    pub fn call(&self, action: &str, payload: Value) -> Result<Value> {
        let (tx, rx) = mpsc::channel();
        let state = Arc::new(AtomicUsize::new(0));
        if self
            .controls
            .try_send(Control {
                action: action.into(),
                payload,
                reply: tx,
                state: state.clone(),
            })
            .is_err()
        {
            if action == "start" {
                self.starting.store(false, Ordering::SeqCst);
                if self.run_id.lock().unwrap().is_none() {
                    self.reserved.store(false, Ordering::SeqCst);
                }
            }
            return Err("Cola de control ocupada; vuelva a intentar.".into());
        }
        match rx.recv_timeout(Duration::from_secs(10)) {
            Ok(v) => v.map_err(Into::into),
            Err(_) => {
                let _ = state.compare_exchange(0, 2, Ordering::SeqCst, Ordering::SeqCst);
                Err("El comando tardó demasiado; comprueba el estado de la ejecución antes de reintentar.".into())
            }
        }
    }
    pub fn ingest(&self, payload: Value, received: f64, wall: f64) {
        let Some(run_id) = self.run_id.lock().unwrap().clone() else {
            return;
        };
        let mut inbox = self.inbox.lock().unwrap();
        if inbox.queue.len() < inbox.capacity {
            inbox.queue.push_back(Packet {
                payload,
                received,
                wall,
                run_id,
            });
        } else {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }
    pub fn snapshot(&self) -> Value {
        self.published.lock().unwrap().clone()
    }
    pub fn close(&self) {
        self.shutdown.store(true, Ordering::SeqCst);
        if let Some(join) = self.join.lock().unwrap().take() {
            let _ = join.join();
        }
    }
}
struct ServiceWorker {
    root: PathBuf,
    config_path: PathBuf,
    controller: SenseOrchestrator,
    resources: ResourceMonitor,
    inbox: Arc<Mutex<VecDequePacket>>,
    published: Arc<Mutex<Value>>,
    run_id: Arc<Mutex<Option<String>>>,
    reserved: Arc<AtomicBool>,
    starting: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
    dropped: Arc<AtomicUsize>,
    rx: mpsc::Receiver<Control>,
    session_id: String,
}
impl ServiceWorker {
    fn drain(&mut self) -> Result<()> {
        let capacity = self.inbox.lock().unwrap().capacity;
        for _ in 0..capacity {
            let packet = self.inbox.lock().unwrap().queue.pop_front();
            let Some(p) = packet else { break };
            self.controller.log.db.execute_batch("BEGIN")?;
            let result = if self.controller.running() && self.controller.run["run_id"] == p.run_id {
                self.controller.ingest(&p.payload, p.received, p.wall)
            } else {
                self.controller.log.event(
                    &p.run_id,
                    "DISPATCHER_DISCARDED",
                    &json!({"reason":"RUN_ALREADY_ENDED"}),
                )
            };
            self.controller.log.db.execute_batch(if result.is_ok() {
                "COMMIT"
            } else {
                "ROLLBACK"
            })?;
            result?;
        }
        Ok(())
    }
    fn control(&mut self, c: &Control) -> Result<Value> {
        let now = monotonic();
        match c.action.as_str() {
            "start" => {
                let config = load_config(&self.config_path)?;
                let capacity = number(&config["runtime"]["inbox_capacity"]) as usize;
                {
                    let mut inbox = self.inbox.lock().unwrap();
                    if capacity != inbox.capacity {
                        if self.controller.running() || self.controller.tasks.busy() {
                            return Err(
                                "No se puede cambiar capacidad durante una ejecución.".into()
                            );
                        }
                        inbox.queue.clear();
                        inbox.capacity = capacity;
                    }
                }
                self.controller.config = config.clone();
                self.controller.tasks.capacity =
                    number(&config["interpretation"]["queue_capacity"]) as usize;
                self.controller.metadata =
                    software_metadata(&self.root, &self.controller.adapters.model)?;
                self.controller.resources = self.resources.sample();
                self.controller.log.db.execute_batch("BEGIN")?;
                let result = self.controller.start(
                    text(&c.payload["mode"]),
                    now,
                    c.payload["session_id"].as_str().unwrap_or(&self.session_id),
                    c.payload["scenario_id"]
                        .as_str()
                        .unwrap_or("pilot-classroom"),
                    &c.payload,
                );
                self.controller.log.db.execute_batch(if result.is_ok() {
                    "COMMIT"
                } else {
                    "ROLLBACK"
                })?;
                result
            }
            "stop" => {
                self.drain()?;
                self.controller.stop("USER_STOP", now)?;
                Ok(json!({"ok":true}))
            }
            "query" => {
                self.controller
                    .query(text(&c.payload["question_id"]), now)?;
                Ok(json!({"ok":true}))
            }
            "presence" => {
                self.controller
                    .set_presence(&c.payload["detected"], now, &c.payload["near"])?;
                Ok(json!({"ok":true}))
            }
            "fault" => {
                self.controller.set_fault(&c.payload, now)?;
                Ok(json!({"ok":true}))
            }
            _ => Err("Comando no reconocido.".into()),
        }
    }
    fn run(mut self) {
        let mut sampled = f64::NEG_INFINITY;
        let mut published = f64::NEG_INFINITY;
        let mut resources = json!({});
        let mut drops = 0;
        let mut error: Option<String> = None;
        while !self.shutdown.load(Ordering::SeqCst) {
            let now = monotonic();
            let result = (|| -> Result<()> {
                if now - sampled
                    >= number(&self.controller.config["runtime"]["resource_interval_seconds"])
                {
                    resources = self.resources.sample();
                    sampled = now;
                    self.controller.resources = resources.clone();
                    if self.controller.running() {
                        self.controller.record("RESOURCE_SAMPLE", &resources)?;
                    }
                }
                for _ in 0..8 {
                    let Ok(c) = self.rx.try_recv() else { break };
                    if c.state
                        .compare_exchange(0, 1, Ordering::SeqCst, Ordering::SeqCst)
                        .is_err()
                    {
                        if c.action == "start" {
                            self.starting.store(false, Ordering::SeqCst);
                        }
                        continue;
                    }
                    let result = self.control(&c);
                    if c.action == "start" {
                        self.starting.store(false, Ordering::SeqCst);
                        if result.is_ok() {
                            error = None;
                        }
                    }
                    *self.run_id.lock().unwrap() = if self.controller.running() {
                        Some(text(&self.controller.run["run_id"]).into())
                    } else {
                        None
                    };
                    let fatal = result.as_ref().err().is_some_and(|e| {
                        e.downcast_ref::<rusqlite::Error>().is_some()
                            || e.downcast_ref::<std::io::Error>().is_some()
                    });
                    let message = result.as_ref().err().map(ToString::to_string);
                    let _ = c.reply.send(result.map_err(|e| e.to_string()));
                    if fatal {
                        return Err(message.unwrap().into());
                    }
                }
                self.drain()?;
                let total = self.dropped.load(Ordering::Relaxed);
                if total != drops && self.controller.running() {
                    self.controller.record(
                        "DISPATCHER_DROPPED",
                        &json!({"total":total,"policy":"REJECT_NEWEST"}),
                    )?;
                    drops = total;
                }
                self.controller.log.db.execute_batch("BEGIN")?;
                let tick = self.controller.tick(now, resources.clone());
                self.controller.log.db.execute_batch(if tick.is_ok() {
                    "COMMIT"
                } else {
                    "ROLLBACK"
                })?;
                tick?;
                if !self.starting.load(Ordering::SeqCst)
                    && !self.controller.running()
                    && !self.controller.tasks.busy()
                {
                    self.reserved.store(false, Ordering::SeqCst);
                }
                Ok(())
            })();
            if let Err(e) = result {
                error = Some(e.to_string());
                if self.controller.running() {
                    let _ = self
                        .controller
                        .record("SERVICE_ERROR", &json!({"error":error}));
                    if self
                        .controller
                        .stop("INTERNAL_OR_STORAGE_ERROR", now)
                        .is_err()
                    {
                        self.controller.run["status"] = json!("FAILED");
                        self.controller
                            .tasks
                            .cancel(text(&self.controller.run["run_id"]));
                    }
                }
            }
            *self.run_id.lock().unwrap() = if self.controller.running() {
                Some(text(&self.controller.run["run_id"]).into())
            } else {
                None
            };
            if now - published
                >= number(&self.controller.config["runtime"]["publish_interval_seconds"])
            {
                match self.controller.view(now) {
                    Ok(mut view) => {
                        let inbox = self.inbox.lock().unwrap();
                        view["error"] = json!(error);
                        view["dispatcher"] = json!({"queued":inbox.queue.len(),"capacity":inbox.capacity,"dropped":self.dropped.load(Ordering::Relaxed)});
                        view["reserved"] = json!(self.reserved.load(Ordering::SeqCst));
                        *self.published.lock().unwrap() = view;
                    }
                    Err(e) => {
                        error = Some(e.to_string());
                    }
                }
                published = now;
            }
            std::thread::sleep(Duration::from_secs_f64(number(
                &self.controller.config["runtime"]["tick_seconds"],
            )));
        }
        let _ = self.controller.stop("PROCESS_SHUTDOWN", monotonic());
    }
}

fn dependency_versions() -> Value {
    let mut out = json!({});
    for package in include_str!("../Cargo.lock").split("[[package]]").skip(1) {
        let field = |name: &str| {
            package.lines().find_map(|line| {
                line.strip_prefix(&format!("{name} = \""))
                    .and_then(|s| s.strip_suffix('\"'))
            })
        };
        if let (Some(name), Some(version)) = (field("name"), field("version")) {
            out[name] = json!(version);
        }
    }
    out
}
