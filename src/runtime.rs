use crate::{Result, contracts::*};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, VecDeque},
    sync::{Arc, Mutex, mpsc},
};
pub struct TaskOutput {
    pub data: Value,
    pub image: Option<Arc<Vec<u8>>>,
}
impl From<Value> for TaskOutput {
    fn from(data: Value) -> Self {
        Self { data, image: None }
    }
}
pub type Action = Box<dyn FnOnce() -> Result<TaskOutput> + Send>;
#[derive(Debug)]
pub struct RemoteExecutionUncertain(pub String);
impl std::fmt::Display for RemoteExecutionUncertain {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for RemoteExecutionUncertain {}
#[derive(Default)]
struct Execution {
    started: Option<f64>,
    completed: Option<f64>,
    started_at: Option<String>,
    completed_at: Option<String>,
    result: Option<std::result::Result<TaskOutput, (String, bool)>>,
}
pub struct Task {
    pub command: Value,
    action: Option<Action>,
    pub key: String,
    pub enqueued: f64,
    pub deadline: f64,
    timeout: f64,
    pub started: f64,
    pub expired: bool,
    pub cancelled: bool,
    enqueued_monotonic: f64,
    execution: Arc<Mutex<Execution>>,
    pub simulation: Option<Value>,
}
pub struct TaskEvent {
    pub document: Value,
    pub image: Option<Arc<Vec<u8>>>,
}
pub struct TaskManager {
    pub active: BTreeMap<String, Option<Task>>,
    pub pending: VecDeque<Task>,
    pub quarantined: BTreeMap<String, Task>,
    pub capacity: usize,
    pub counters: Value,
    lifecycle_tx: mpsc::Sender<Value>,
    lifecycle_rx: mpsc::Receiver<Value>,
}
pub fn counters() -> Value {
    json!({"accepted":0,"rejected":0,"cancelled":0,"completed":0,"failed":0,"timed_out":0,"late":0})
}
impl TaskManager {
    pub fn new(capacity: usize) -> Self {
        let (tx, rx) = mpsc::channel();
        Self {
            active: [("vision".into(), None), ("gemma".into(), None)].into(),
            pending: VecDeque::new(),
            quarantined: BTreeMap::new(),
            capacity,
            counters: counters(),
            lifecycle_tx: tx,
            lifecycle_rx: rx,
        }
    }
    pub fn busy(&self) -> bool {
        self.active.values().any(Option::is_some)
            || !self.pending.is_empty()
            || !self.quarantined.is_empty()
    }
    fn inc(&mut self, key: &str) {
        self.counters[key] = json!(number(&self.counters[key]) as u64 + 1);
    }
    #[allow(clippy::too_many_arguments)] // Scheduling and simulation share the same bounded submission path.
    pub fn submit(
        &mut self,
        lane: &str,
        command: Value,
        action: Action,
        key: String,
        now: f64,
        timeout: f64,
        simulation: Option<Value>,
    ) -> Option<String> {
        let error = if self.quarantined.contains_key(lane) {
            Some("REMOTE_EXECUTION_UNCERTAIN")
        } else if self.active.values().flatten().any(|t| t.key == key)
            || self.pending.iter().any(|t| t.key == key)
        {
            Some("DUPLICATE_REQUEST")
        } else {
            None
        };
        if let Some(e) = error {
            self.inc("rejected");
            return Some(e.into());
        }
        let task = Task {
            command,
            action: Some(action),
            key,
            enqueued: now,
            deadline: now + timeout,
            timeout,
            started: 0.,
            expired: false,
            cancelled: false,
            enqueued_monotonic: monotonic(),
            execution: Arc::new(Mutex::new(Execution::default())),
            simulation,
        };
        if self.active[lane].is_none() {
            self.start(lane, task, now);
        } else if lane == "gemma" && self.pending.len() < self.capacity {
            self.pending.push_back(task);
        } else {
            self.inc("rejected");
            return Some("QUEUE_SATURATED".into());
        }
        self.inc("accepted");
        None
    }
    fn start(&mut self, lane: &str, mut task: Task, now: f64) {
        task.started = now;
        task.deadline = now + task.timeout;
        task.command["deadline"] = json!(
            (chrono::Utc::now() + chrono::Duration::milliseconds((task.timeout * 1000.) as i64))
                .to_rfc3339_opts(chrono::SecondsFormat::Micros, false)
        );
        let simulated = task.simulation.is_some();
        let command = task.command.clone();
        let key = task.key.clone();
        let enqueued = task.enqueued_monotonic;
        if simulated {
            let mut e = task.execution.lock().unwrap();
            e.started = Some(monotonic());
            e.started_at = Some(utc_now());
            let _=self.lifecycle_tx.send(event(text(&command["command_id"]),text(&command["target_agent"]),"TASK_STARTED",json!({"command":command,"started_at":e.started_at,"queue_seconds":now-task.enqueued,"semantic_key":key,"simulated":true,"model_executed":false}),None));
            if task.simulation.as_ref().unwrap()["kind"] == "CAMERA_UNAVAILABLE" {
                e.completed = Some(monotonic());
                e.completed_at = Some(utc_now());
                e.result = Some(Err(("CAMERA_UNAVAILABLE".into(), false)));
            }
            drop(e);
            task.action = None;
        } else {
            let exec = task.execution.clone();
            let tx = self.lifecycle_tx.clone();
            let action = task.action.take().unwrap();
            std::thread::spawn(move || {
                let started = monotonic();
                let started_at = utc_now();
                {
                    let mut e = exec.lock().unwrap();
                    e.started = Some(started);
                    e.started_at = Some(started_at.clone());
                }
                let _=tx.send(event(text(&command["command_id"]),text(&command["target_agent"]),"TASK_STARTED",json!({"command":command,"started_at":started_at,"queue_seconds":started-enqueued,"semantic_key":key}),None));
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(action))
                    .unwrap_or_else(|_| Err("El worker terminó por pánico.".into()))
                    .map_err(|e| {
                        let remote = e.downcast_ref::<RemoteExecutionUncertain>().is_some()
                            || e.downcast_ref::<reqwest::Error>()
                                .is_some_and(|e| e.is_timeout() || e.is_connect() || e.is_body());
                        (e.to_string(), remote)
                    });
                let mut e = exec.lock().unwrap();
                e.completed = Some(monotonic());
                e.completed_at = Some(utc_now());
                e.result = Some(result);
            });
        }
        self.active.insert(lane.into(), Some(task));
    }
    pub fn poll(&mut self, now: f64, allow_start: bool) -> Vec<TaskEvent> {
        let mut events = vec![];
        for lane in ["vision", "gemma"] {
            let Some(mut task) = self.active.get_mut(lane).unwrap().take() else {
                continue;
            };
            let mut e = task.execution.lock().unwrap();
            let mut payload = json!({"command":task.command,"queue_seconds":task.started-task.enqueued,"duration_seconds":now-task.started,"semantic_key":task.key});
            if let Some(start) = e.started {
                payload["started_at"] = json!(e.started_at);
                payload["completed_at"] = json!(e.completed_at);
                payload["queue_seconds"] = json!(start - task.enqueued_monotonic);
                payload["duration_seconds"] = json!(e.completed.unwrap_or_else(monotonic) - start);
            }
            if task.simulation.is_some() {
                payload["simulated"] = json!(true);
                payload["model_executed"] = json!(false);
                payload["duration_seconds"] = json!(now - task.started);
                payload["queue_seconds"] = json!(task.started - task.enqueued);
            }
            let in_time = e
                .completed
                .zip(e.started)
                .is_some_and(|(end, start)| end - start < task.timeout);
            if !task.expired && !task.cancelled && now >= task.deadline && !in_time {
                task.expired = true;
                self.inc("timed_out");
                events.push(TaskEvent {
                    document: event(
                        text(&task.command["command_id"]),
                        text(&task.command["target_agent"]),
                        "TASK_TIMEOUT",
                        payload.clone(),
                        None,
                    ),
                    image: None,
                });
                if task.simulation.is_some() && e.result.is_none() {
                    e.completed = Some(monotonic());
                    e.completed_at = Some(utc_now());
                    payload["completed_at"] = json!(e.completed_at);
                    e.result = Some(Err(("DEADLINE_EXCEEDED".into(), false)));
                }
            }
            if let Some(result) = e.result.take() {
                let late = task.expired || task.cancelled;
                let mut uncertain = false;
                let (kind, error, image) = match result {
                    Ok(out) => {
                        payload["result"] = out.data;
                        payload["late"] = json!(late);
                        self.inc("completed");
                        ("TASK_COMPLETED", None, out.image)
                    }
                    Err((error, remote)) => {
                        self.inc("failed");
                        if lane == "gemma" && remote {
                            uncertain = true;
                            payload["remote_execution_uncertain"] = json!(true);
                        }
                        ("TASK_FAILED", Some(error), None)
                    }
                };
                if late {
                    self.inc("late");
                    payload["late"] = json!(true);
                }
                events.push(TaskEvent {
                    document: event(
                        text(&task.command["command_id"]),
                        text(&task.command["target_agent"]),
                        kind,
                        payload,
                        error,
                    ),
                    image,
                });
                drop(e);
                if uncertain {
                    self.quarantined.insert(lane.into(), task);
                }
            } else {
                drop(e);
                self.active.insert(lane.into(), Some(task));
            }
        }
        let mut retained = VecDeque::new();
        while let Some(task) = self.pending.pop_front() {
            let expiry = task.command["parameters"]["image_expires_monotonic"].as_f64();
            if expiry.is_some_and(|t| now >= t) {
                self.inc("timed_out");
                events.push(TaskEvent{document:event(text(&task.command["command_id"]),text(&task.command["target_agent"]),"TASK_TIMEOUT",json!({"command":task.command,"queue_seconds":now-task.enqueued,"semantic_key":task.key,"reason":"IMAGE_EXPIRED_IN_QUEUE"}),None),image:None});
            } else {
                retained.push_back(task);
            }
        }
        self.pending = retained;
        if allow_start
            && self.active["gemma"].is_none()
            && !self.quarantined.contains_key("gemma")
            && let Some(task) = self.pending.pop_front()
        {
            self.start("gemma", task, now);
        }
        let mut starts: Vec<_> = self
            .lifecycle_rx
            .try_iter()
            .map(|document| TaskEvent {
                document,
                image: None,
            })
            .collect();
        starts.extend(events);
        starts
    }
    pub fn cancel(&mut self, run_id: &str) -> Vec<Value> {
        let mut commands = vec![];
        for lane in ["vision", "gemma"] {
            let Some(task) = self.active.get_mut(lane).unwrap().as_mut() else {
                continue;
            };
            if task.command["experiment_run_id"] == run_id && !task.cancelled {
                task.cancelled = true;
                if task.simulation.is_some() {
                    let mut e = task.execution.lock().unwrap();
                    if e.result.is_none() {
                        e.completed = Some(monotonic());
                        e.completed_at = Some(utc_now());
                        e.result = Some(Err(("".into(), false)));
                    }
                }
                commands.push(task.command.clone());
            }
        }
        self.pending.retain(|t| {
            if t.command["experiment_run_id"] == run_id {
                commands.push(t.command.clone());
                false
            } else {
                true
            }
        });
        self.counters["cancelled"] =
            json!(number(&self.counters["cancelled"]) as usize + commands.len());
        commands
    }
    pub fn view(&self, now: f64) -> Value {
        let mut active = vec![];
        for t in ["vision", "gemma"]
            .iter()
            .filter_map(|lane| self.active[*lane].as_ref())
        {
            active.push(json!({"command_id":t.command["command_id"],"agent":t.command["target_agent"],"simulated":t.simulation.is_some(),"question_id":t.command["parameters"]["question_id"],"elapsed_seconds":rounded(now-t.started,1),"status":if t.cancelled||t.expired{"DRAINING"}else{"RUNNING"}}));
        }
        for t in self.quarantined.values() {
            active.push(json!({"command_id":t.command["command_id"],"agent":t.command["target_agent"],"question_id":t.command["parameters"]["question_id"],"elapsed_seconds":rounded(now-t.started,1),"status":"REMOTE_EXECUTION_UNCERTAIN"}));
        }
        json!({"active":active,"queued":self.pending.len(),"queue_capacity":self.capacity,"counters":self.counters})
    }
}
