use crate::{
    Result, acquisition,
    agents::{self, Adapters},
    context::{ContextStore, timestamp},
    contracts::*,
    faults::{FaultInjector, SENSOR_FIELDS},
    health::HealthMonitor,
    policy::{Decision, PolicyEngine, answer_questions, semantic_key},
    protocol,
    runtime::{TaskEvent, TaskManager},
    storage::ExperimentLog,
    telemetry::budget_reason,
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashSet, VecDeque},
    sync::Arc,
};
pub type Readiness = Arc<dyn Fn() -> Value + Send + Sync>;
pub struct ImageEvidence {
    pub image_id: String,
    pub bytes: Arc<Vec<u8>>,
    pub captured_at: String,
    pub expires: f64,
}
pub struct SenseOrchestrator {
    pub config: Value,
    pub log: ExperimentLog,
    pub tasks: TaskManager,
    pub adapters: Adapters,
    pub readiness: Readiness,
    pub metadata: Value,
    pub run: Value,
    pub fsm: String,
    pub cycle: Value,
    pub transitions: VecDeque<Value>,
    pub errors: VecDeque<Value>,
    pub interpretations: VecDeque<Value>,
    pub decisions: VecDeque<Value>,
    pub resources: Value,
    pub latest_snapshot: Value,
    pub answers: Value,
    pub dirty: bool,
    pub next_evaluation: f64,
    pub image: Option<ImageEvidence>,
    pub attempted: HashSet<String>,
    pub result_keys: Value,
    pub events: Vec<Value>,
    pub last_decisions: Value,
    pub last_multimodal_context: Value,
    pub explicit: HashSet<String>,
    pub manual_presence: Option<bool>,
    pub last_sensor_presence: Value,
    pub context: ContextStore,
    pub policy: PolicyEngine,
    pub started: f64,
    pub health: HealthMonitor,
    pub faults: FaultInjector,
    pub sensor_observations: BTreeMap<String, (Value, f64, f64)>,
    pub last_raw_presence: Value,
    pub raw_presence_received: f64,
    pub raw_presence_age: f64,
    pub manual_near: Option<bool>,
    pub last_sample_second: i64,
    pub next_manual_second: i64,
    pub checkpoints: HashSet<i64>,
}
fn bounded(q: &mut VecDeque<Value>, v: Value, max: usize) {
    q.push_back(v);
    if q.len() > max {
        q.pop_front();
    }
}
impl SenseOrchestrator {
    pub fn new(
        config: Value,
        log: ExperimentLog,
        tasks: TaskManager,
        adapters: Adapters,
        readiness: Readiness,
        metadata: Value,
    ) -> Self {
        Self {
            context: ContextStore::new(config.clone()),
            policy: PolicyEngine::new(config.clone(), "C", 0.),
            health: HealthMonitor::new(0., config.clone()),
            faults: FaultInjector::new(0.),
            config,
            log,
            tasks,
            adapters,
            readiness,
            metadata,
            run: Value::Null,
            fsm: "WAIT".into(),
            cycle: Value::Null,
            transitions: VecDeque::new(),
            errors: VecDeque::new(),
            interpretations: VecDeque::new(),
            decisions: VecDeque::new(),
            resources: json!({}),
            latest_snapshot: Value::Null,
            answers: json!({}),
            dirty: false,
            next_evaluation: 0.,
            image: None,
            attempted: HashSet::new(),
            result_keys: json!({}),
            events: vec![],
            last_decisions: json!({}),
            last_multimodal_context: Value::Null,
            explicit: HashSet::new(),
            manual_presence: None,
            last_sensor_presence: Value::Null,
            started: 0.,
            sensor_observations: BTreeMap::new(),
            last_raw_presence: Value::Null,
            raw_presence_received: 0.,
            raw_presence_age: 0.,
            manual_near: None,
            last_sample_second: -1,
            next_manual_second: 60,
            checkpoints: HashSet::new(),
        }
    }
    pub fn running(&self) -> bool {
        self.run["status"] == "RUNNING"
    }
    pub fn start(
        &mut self,
        mode: &str,
        now: f64,
        session: &str,
        scenario: &str,
        experiment: &Value,
    ) -> Result<Value> {
        protocol::validate_guided_start(experiment)?;
        if truth(&experiment["guided"])
            && number(&self.config["runtime"]["max_run_seconds"]) != 1800.
        {
            return Err("La ejecución guiada requiere runtime.max_run_seconds=1800 para registrar 30 minutos.".into());
        }
        if self.running() || self.tasks.busy() {
            return Err("Hay una ejecución o un worker pendiente de finalizar.".into());
        }
        if !list(&self.config["enabled_modes"]).contains(&json!(mode)) {
            return Err("Modo experimental no habilitado.".into());
        }
        if (self.readiness)()
            .as_object()
            .is_some_and(|m| m.values().any(|v| v == "loading" || v == "waiting"))
        {
            return Err("Espere a que termine la preparación.".into());
        }
        let reason = if truth(&self.resources) {
            budget_reason(&self.resources, &self.config["runtime"])
        } else {
            Some("RESOURCE_MONITOR_UNAVAILABLE")
        };
        if let Some(r) = reason {
            return Err(format!("No se puede iniciar: {r}").into());
        }
        self.context = ContextStore::new(self.config.clone());
        self.policy = PolicyEngine::new(self.config.clone(), mode, now);
        self.run = self.metadata.clone();
        if !self.run.is_object() {
            self.run = json!({});
        }
        let values = json!({"run_id":identifier(),"session_id":session,"scenario_id":scenario,"mode":mode,"start_time":utc_now(),"end_time":null,"status":"RUNNING","config_version":self.config["config_version"],"config_hash":self.config["config_hash"],"config":self.config,"hardware_profile":self.config["hardware_profile"],"guided":experiment.get("guided").unwrap_or(&json!(false)),"repetition":experiment["repetition"],"duration_seconds":number(&self.config["runtime"]["max_run_seconds"]).min(1800.),"protocol_version":protocol::PROTOCOL_VERSION,"power_interval_seconds":60,"observer":experiment["initial_observation"]["observer"],"instrument":experiment["initial_observation"]["instrument"],"equipment":experiment["initial_observation"]["equipment"],"observation_region":self.config["regions"]["camera_region"],"policy_mode":self.policy.mode});
        self.run
            .as_object_mut()
            .unwrap()
            .extend(values.as_object().unwrap().clone());
        self.started = now;
        self.health = HealthMonitor::new(now, self.config.clone());
        self.faults = FaultInjector::new(now);
        self.sensor_observations.clear();
        self.last_raw_presence = Value::Null;
        self.raw_presence_received = 0.;
        self.raw_presence_age = 0.;
        self.manual_near = None;
        self.last_sample_second = -1;
        self.next_manual_second = 60;
        self.checkpoints.clear();
        self.fsm = "WAIT".into();
        self.cycle = Value::Null;
        self.image = None;
        self.transitions.clear();
        self.errors.clear();
        self.interpretations.clear();
        self.decisions.clear();
        self.attempted.clear();
        self.result_keys = json!({});
        self.last_decisions = json!({});
        self.events.clear();
        self.explicit.clear();
        self.last_multimodal_context = Value::Null;
        self.manual_presence = None;
        self.last_sensor_presence = Value::Null;
        self.answers = json!({});
        self.tasks.counters = crate::runtime::counters();
        self.log.begin(&self.run)?;
        self.record("RUN_STARTED", &self.run)?;
        if truth(&self.run["guided"]) {
            let id = text(&self.run["run_id"]);
            let request = self.log.request_observer(
                id,
                "RUN_INITIAL",
                &["power_w", "visible_people"],
                None,
                None,
                None,
            )?;
            self.log
                .resolve_observer(id, &request, &experiment["initial_observation"])?;
        }
        self.sample(now)?;
        self.dirty = true;
        Ok(self.run.clone())
    }
    pub fn record(&self, kind: &str, p: &Value) -> Result<()> {
        let id = text(&self.run["run_id"]);
        self.log.event(id, kind, p)?;
        if truth(&self.run["guided"]) {
            if ["FAULT_INJECTED", "FAULT_RESTORED", "FAULT_RECOVERED"].contains(&kind) {
                self.log.request_observer(
                    id,
                    kind,
                    &["power_w", "action"],
                    p["task_id"].as_str(),
                    p["event_id"].as_str(),
                    None,
                )?;
            }
            if kind == "MANUAL_PRESENCE_CHANGED" {
                self.log.request_observer(
                    id,
                    kind,
                    &["power_w", "visible_people", "action"],
                    None,
                    p["event_id"].as_str(),
                    None,
                )?;
            }
        }
        Ok(())
    }
    fn flush_monitors(&mut self) -> Result<()> {
        let events = std::mem::take(&mut self.health.emitted);
        for (k, p) in events {
            self.record(&k, &p)?;
        }
        let events = std::mem::take(&mut self.faults.emitted);
        for (k, p) in events {
            self.record(&k, &p)?;
        }
        Ok(())
    }
    pub fn transition(&mut self, target: &str, reason: &str) -> Result<()> {
        let allowed: &[&str] = match self.fsm.as_str() {
            "WAIT" => &["ACQUIRE"],
            "ACQUIRE" => &["ASSESS", "DEGRADED"],
            "ASSESS" => &["VISION", "INTERPRET", "REPORT", "DEGRADED"],
            "VISION" => &["ASSESS", "DEGRADED"],
            "INTERPRET" => &["REPORT", "DEGRADED"],
            "REPORT" => &["WAIT", "DEGRADED"],
            "DEGRADED" => &["REPORT"],
            _ => &[],
        };
        if !allowed.contains(&target) {
            return Err(format!("Transición inválida {} → {target}", self.fsm).into());
        }
        let t = json!({"from":self.fsm,"to":target,"reason":reason,"cycle_id":self.cycle["cycle_id"],"timestamp":utc_now(),"elapsed_seconds":rounded(monotonic()-number(&self.cycle["started_monotonic"]),3)});
        bounded(&mut self.transitions, t.clone(), 96);
        self.cycle["actions"]
            .as_array_mut()
            .unwrap()
            .push(json!(target));
        self.record("FSM_TRANSITION", &t)?;
        self.fsm = target.into();
        Ok(())
    }
    pub fn ingest(&mut self, p: &Value, now: f64, wall: f64) -> Result<()> {
        if !self.running() {
            return Ok(());
        }
        let parsed = (|| -> Result<(Value, Vec<Value>)> {
            if !p.is_object() || p["schema"] != "rustio.iot.telemetry.v1" {
                return Err("Contrato MQTT no reconocido.".into());
            }
            timestamp(&p["timestamp"])?;
            let received = chrono::DateTime::from_timestamp_micros((wall * 1e6) as i64)
                .ok_or("Timestamp inválido")?
                .to_rfc3339_opts(chrono::SecondsFormat::Micros, false);
            let mut env = acquisition::environment(
                p,
                &received,
                text(&self.config["regions"]["environment_region"]),
            );
            let raw =
                acquisition::presence(p, &received, text(&self.config["regions"]["radar_region"]));
            let mut presence = Some(raw.clone());
            for (c, fields) in SENSOR_FIELDS {
                if self.faults.disabled.contains_key(c) {
                    for k in fields {
                        env.as_object_mut().unwrap().shift_remove(*k);
                    }
                    if c == "radar" {
                        presence = None;
                    }
                }
            }
            let mut events = self.context.ingest(
                &env,
                if self.manual_presence.is_none() {
                    presence.as_ref()
                } else {
                    None
                },
                now,
                wall,
                Some(&p["timestamp"]),
            )?;
            self.last_raw_presence = raw.clone();
            self.raw_presence_received = now;
            self.raw_presence_age = (wall - timestamp(&raw["captured_at"])?).max(0.);
            if let Some(ref radar) = presence {
                self.last_sensor_presence = radar.clone();
                self.sensor_observations.insert(
                    "presence".into(),
                    (
                        radar.clone(),
                        now,
                        (wall - timestamp(&radar["captured_at"])?).max(0.),
                    ),
                );
            }
            for (k, o) in env.as_object().unwrap() {
                self.sensor_observations.insert(
                    k.clone(),
                    (
                        o.clone(),
                        now,
                        (wall - timestamp(&o["captured_at"])?).max(0.),
                    ),
                );
            }
            if self.manual_presence.is_none()
                && let Some(r) = presence
            {
                events.extend(self.policy.observe_presence(&r, wall)?);
            }
            Ok((raw, events))
        })();
        let (raw, events) = match parsed {
            Ok(v) => v,
            Err(e) => {
                self.record("OBSERVATION_REJECTED", &json!({"reason":e.to_string()}))?;
                return Ok(());
            }
        };
        let mut obs = self.context.observations.clone();
        obs.as_object_mut().unwrap().shift_remove("count");
        self.record("OBSERVATIONS_RECEIVED",&json!({"raw":p,"dispatcher_wait_seconds":(monotonic()-now).max(0.),"raw_presence":raw,"observations":obs}))?;
        for e in &events {
            self.record(text(&e["event_type"]), e)?;
            if truth(&self.run["guided"]) {
                self.log.request_observer(
                    text(&self.run["run_id"]),
                    text(&e["event_type"]),
                    &["power_w", "visible_people", "action"],
                    None,
                    e["event_id"].as_str(),
                    None,
                )?;
            }
        }
        self.events.extend(events);
        let excess = self
            .events
            .len()
            .saturating_sub(number(&self.config["runtime"]["inbox_capacity"]) as usize);
        self.events.drain(..excess);
        self.dirty = true;
        Ok(())
    }
    pub fn set_presence(&mut self, detected: &Value, now: f64, near: &Value) -> Result<()> {
        if !self.running() || !["B", "C", "D", "E", "F"].contains(&text(&self.run["mode"])) {
            return Err("El control manual de presencia requiere B–F activos.".into());
        }
        if (!detected.is_null() && !detected.is_boolean())
            || (!near.is_null() && !near.is_boolean())
        {
            return Err("Presencia y zona manual requieren booleanos.".into());
        }
        if !near.is_null()
            && (self.run["mode"] != "B" || detected.is_null() || (truth(near) && !truth(detected)))
        {
            return Err(
                "La zona manual solo se admite en B; zona próxima requiere presencia.".into(),
            );
        }
        let previous = self.context.observations["presence"].clone();
        let was_manual = self.manual_presence.is_some();
        self.manual_presence = detected.as_bool();
        self.manual_near = if self.run["mode"] == "B" {
            detected.as_bool().map(|b| near.as_bool().unwrap_or(b))
        } else {
            None
        };
        self.record("MANUAL_PRESENCE_CHANGED",&json!({"event_id":identifier(),"mode":if detected.is_null(){"AUTO"}else{"MANUAL"},"detected":detected,"near":self.manual_near,"raw_observation_id":self.last_raw_presence["observation_id"],"elapsed_s":now-self.started}))?;
        self.dirty = true;
        if detected.is_null() {
            self.context.presence_samples = 0;
            self.context.confirmed_presence = Value::Null;
            self.policy.reset_reactive();
            if let Some((o, received, age)) = self.sensor_observations.get("presence") {
                self.context.put("presence", o.clone(), *received, *age);
            } else {
                self.context
                    .observations
                    .as_object_mut()
                    .unwrap()
                    .shift_remove("presence");
            }
            return Ok(());
        }
        let captured = utc_now();
        let mut meta = json!({"source_kind":"MANUAL_CONTROL"});
        if self.run["mode"] == "B" {
            meta["manual_near"] = json!(self.manual_near);
        }
        let p = observation(
            "OperatorControl",
            &captured,
            &captured,
            text(&self.config["regions"]["radar_region"]),
            json!(i32::from(truth(detected))),
            "presence",
            "operator_control",
            "VALID",
            meta,
        );
        self.context.put("presence", p.clone(), now, 0.);
        if self.run["mode"] == "B" {
            if !was_manual {
                self.policy.reactive_last_timestamp = None;
            }
            for e in self
                .policy
                .observe_presence(&p, timestamp(&json!(captured))?)?
            {
                self.record(text(&e["event_type"]), &e)?;
            }
        }
        if previous.is_null() || previous["value"] != p["value"] {
            let e = json!({"event_id":identifier(),"event_type":"PRESENCE_CHANGED","source":"MANUAL_CONTROL","previous":previous["value"],"value":p["value"],"evidence_ids":[p["observation_id"]],"captured_at":p["captured_at"]});
            self.record("PRESENCE_CHANGED", &e)?;
            self.events.push(e);
            let excess = self
                .events
                .len()
                .saturating_sub(number(&self.config["runtime"]["inbox_capacity"]) as usize);
            self.events.drain(..excess);
        }
        Ok(())
    }
    pub fn set_fault(&mut self, p: &Value, now: f64) -> Result<()> {
        if !self.running() || self.run["mode"] != "F" {
            return Err("La inyección de fallas solo está disponible en F activo.".into());
        }
        match text(&p["action"]) {
            "availability" => {
                let c = text(&p["component"]);
                let baseline = self.health.components[c]["status"]
                    .as_str()
                    .unwrap_or("UNKNOWN");
                self.faults.set_enabled(c, &p["enabled"], now, baseline)?;
            }
            "timeout" => {
                let lane = text(&p["lane"]);
                if self.tasks.quarantined.contains_key(lane) {
                    return Err("El runtime remoto sigue sin confirmar; recupéralo antes de armar otra prueba.".into());
                }
                self.faults.arm_timeout(
                    lane,
                    now,
                    text(
                        &self.health.components[if lane == "vision" { "camera" } else { "gemma" }]
                            ["status"],
                    ),
                )?;
            }
            _ => return Err("Usa action availability o timeout.".into()),
        }
        self.flush_monitors()
    }
    pub fn update_health(&mut self, now: f64) -> Result<()> {
        let mut readings = json!({});
        for (k, (o, received, age)) in &self.sensor_observations {
            let mut status = o["status"].clone();
            let ttl = number(
                &self.config["sensors"][if k == "presence" {
                    "presence_ttl_seconds"
                } else {
                    "environment_ttl_seconds"
                }],
            );
            if status == "VALID" && now - received + age >= ttl {
                status = json!("STALE");
            }
            readings[k] = json!({"status":status,"received_monotonic":received});
        }
        self.health.sensors(&readings, now);
        self.context.component_health = self.health.components.clone();
        self.faults
            .observe(&self.health.components, now, &self.health.evidence_times);
        self.flush_monitors()
    }
    pub fn query(&mut self, q: &str, now: f64) -> Result<()> {
        if !self.running()
            || crate::policy::questions().get(q).is_none()
            || (q == "Q7" && self.policy.mode != "E")
        {
            return Err("Pregunta no disponible en la ejecución actual.".into());
        }
        self.explicit.insert(q.into());
        if ["Q6", "Q7"].contains(&q) && self.health.components["gemma"]["status"] == "FAILED" {
            let key = semantic_key(
                q,
                &self.context.snapshot(now).document,
                &self.adapters.model,
                if q == "Q7" {
                    self.image.as_ref().map(|i| i.image_id.as_str())
                } else {
                    None
                },
            );
            self.attempted.remove(&key);
        }
        if q == "Q2" {
            self.policy.request_visual_count();
        }
        self.record("QUESTION_REQUESTED", &json!({"question_id":q}))?;
        self.dirty = true;
        Ok(())
    }
    pub fn tick(&mut self, now: f64, resources: Value) -> Result<()> {
        self.resources = resources;
        if self.running() && now - self.started >= number(&self.run["duration_seconds"]) {
            self.stop("MAX_RUN_DURATION", now)?;
        }
        let allow =
            self.running() && budget_reason(&self.resources, &self.config["runtime"]).is_none();
        for event in self.tasks.poll(now, allow) {
            self.handle_task(event, now)?;
        }
        if !self.running() {
            return Ok(());
        }
        self.update_health(now)?;
        if self.image.as_ref().is_some_and(|i| now >= i.expires) {
            self.record(
                "IMAGE_EXPIRED",
                &json!({"image_id":self.image.as_ref().unwrap().image_id}),
            )?;
            self.image = None;
        }
        self.sample(now)?;
        if truth(&self.run["guided"]) {
            let elapsed = now - self.started;
            if elapsed >= self.next_manual_second as f64 {
                let due = (elapsed / 60.).floor() as i64 * 60;
                self.log.request_observer(
                    text(&self.run["run_id"]),
                    &format!("PERIODIC_W:{due}"),
                    &["power_w"],
                    None,
                    None,
                    None,
                )?;
                if due > self.next_manual_second {
                    self.record(
                        "OBSERVER_SCHEDULE_GAP",
                        &json!({"from_s":self.next_manual_second,"to_s":due}),
                    )?;
                }
                self.next_manual_second = due + 60;
            }
            for second in list(&protocol::checkpoints()[text(&self.run["scenario_id"])]) {
                let second = number(&second) as i64;
                if elapsed >= second as f64 && self.checkpoints.insert(second) {
                    self.log.request_observer(
                        text(&self.run["run_id"]),
                        &format!("SCENARIO_CHECKPOINT:{second}"),
                        &["power_w", "visible_people", "action"],
                        None,
                        None,
                        None,
                    )?;
                }
            }
        }
        if budget_reason(&self.resources, &self.config["runtime"]) == Some("STORAGE_BUDGET") {
            return self.stop("STORAGE_BUDGET", now);
        }
        if !self.cycle.is_null() && self.fsm == "VISION" {
            if now >= number(&self.cycle["deadline_monotonic"]) || self.health.degraded() {
                let reason = if now >= number(&self.cycle["deadline_monotonic"]) {
                    "CYCLE_DEADLINE"
                } else {
                    "COMPONENT_FAILURE_DURING_VISION"
                };
                self.transition("DEGRADED", reason)?;
                self.answers = answer_questions(
                    &self.context.snapshot(now),
                    text(&self.run["mode"]),
                    number(&self.config["interpretation"]["relationship_alignment_seconds"]),
                );
                self.report(now)?;
            }
            return Ok(());
        }
        if self.dirty || now >= self.next_evaluation {
            self.dirty = false;
            self.next_evaluation =
                now + number(&self.config["runtime"]["evaluation_interval_seconds"]);
            self.cycle = json!({"cycle_id":identifier(),"started_at":utc_now(),"started_monotonic":now,"deadline_monotonic":now+number(&self.config["runtime"]["cycle_timeout_seconds"]),"requests":0,"pending":null,"actions":[],"vision_attempted":false});
            self.transition("ACQUIRE", "SENSOR_EVENT_OR_TIMER")?;
            self.transition("ASSESS", "AVAILABLE_OBSERVATIONS")?;
            self.assess(now)?;
        }
        Ok(())
    }
    pub fn assess(&mut self, now: f64) -> Result<()> {
        let snapshot = self.context.snapshot(now);
        let d = &snapshot.document;
        self.latest_snapshot = d.clone();
        self.answers = answer_questions(
            &snapshot,
            text(&self.run["mode"]),
            number(&self.config["interpretation"]["relationship_alignment_seconds"]),
        );
        self.policy.visual_need(d, &self.events);
        for (q, saved) in self.result_keys.as_object().unwrap() {
            let image = if q == "Q7" {
                self.image.as_ref().map(|i| i.image_id.as_str())
            } else {
                None
            };
            if saved["result"]["validation_status"] == "VALIDATED"
                && saved["semantic_key"] == semantic_key(q, d, &self.adapters.model, image)
            {
                let r = &saved["result"];
                self.answers[q]["status"] = json!("INTERPRETED");
                self.answers[q]["answer"] = r["inferences"].clone();
                self.answers[q]["pending_information"] = json!([]);
                self.answers[q]["evidence_ids"] = r["evidence_references"].clone();
                self.answers[q]["interpretation_id"] = r["interpretation_id"].clone();
                self.answers[q]["source_snapshot_id"] = r["snapshot_id"].clone();
            }
        }
        let previous: HashSet<_> = self
            .policy
            .needs
            .as_object()
            .unwrap()
            .values()
            .map(|n| text(&n["need_id"]).to_owned())
            .collect();
        for n in list(&self.policy.information_needs(&self.answers, d)) {
            if !previous.contains(text(&n["need_id"])) {
                self.record("INFORMATION_NEED_CREATED", &n)?;
            }
        }
        self.record("CONTEXT_UPDATED", d)?;
        if truth(&d["conflict"]) {
            self.record("CONTEXT_CONFLICT",&json!({"snapshot_id":snapshot.snapshot_id,"reason":"COMPARABLE_PRESENCE_DISAGREES"}))?;
        }
        if d["observations"]["count"]["status"] == "STALE" && !truth(&self.last_decisions["stale"])
        {
            self.record(
                "VISUAL_COUNT_STALE",
                &json!({"snapshot_id":snapshot.snapshot_id}),
            )?;
            self.last_decisions["stale"] = json!(true);
        }
        let ready = (self.readiness)();
        let reason = budget_reason(&self.resources, &self.config["runtime"]);
        let previous_period = self.policy.next_period;
        let mut decision = self.policy.vision(
            d,
            now,
            &self.events,
            ready["yolo"] == "ready" && self.health.available("camera", now),
            self.tasks.active["vision"].is_some(),
            reason,
        );
        if self.run["mode"] == "A" && previous_period != self.policy.next_period {
            let due = ((self.policy.next_period - previous_period)
                / number(&self.config["modes"]["periodic_interval_seconds"]))
            .round_ties_even() as i64;
            self.record("PERIOD_SCHEDULE",&json!({"first_due_monotonic":previous_period,"evaluated_monotonic":now,"intervals_due":due,"missed_intervals":if decision.action.is_some(){due-1}else{due},"reason":decision.reason}))?;
        }
        self.events.clear();
        if truth(&self.cycle["vision_attempted"])
            || number(&self.cycle["requests"])
                >= number(&self.config["runtime"]["max_cycle_requests"])
        {
            decision = Decision::new(None, "Q2", "CYCLE_REQUEST_LIMIT");
        }
        self.record_decision("VISION", &decision)?;
        if decision.action.is_some() {
            let mut command=self.command("VisionAgent","vision","Q2",&decision.reason,number(&self.config["vision"]["timeout_seconds"]),json!({"region":self.config["regions"]["camera_region"],"snapshot_id":snapshot.snapshot_id,"trigger_event_id":if self.run["mode"]=="B"{self.policy.reactive_pending["event_id"].clone()}else{Value::Null}}));
            let fault = self.faults.task_fault("vision");
            Self::fault_parameters(&mut command, fault.as_ref());
            let adapter = self.adapters.clone();
            let cmd = command.clone();
            let max = number(&self.config["vision"]["max_image_bytes"]) as usize;
            let error = self.tasks.submit(
                "vision",
                command.clone(),
                Box::new(move || adapter.vision(&cmd, max)),
                format!("vision:{}", text(&self.run["run_id"])),
                now,
                number(&self.config["vision"]["timeout_seconds"]),
                fault.clone(),
            );
            if let Some(error) = error {
                self.record(
                    "VISION_SKIPPED",
                    &json!({"reason":error,"question_id":"Q2"}),
                )?;
            } else {
                self.faults.accepted(fault.as_ref(), &command, now);
                self.flush_monitors()?;
                self.record("COMMAND_ISSUED", &command)?;
                self.record("VISION_REQUESTED",&json!({"command_id":command["command_id"],"question_id":"Q2","reason":decision.reason}))?;
                self.policy.accepted_vision(now);
                self.cycle["requests"] = json!(number(&self.cycle["requests"]) as u64 + 1);
                self.cycle["vision_attempted"] = json!(true);
                self.cycle["pending"] = command["command_id"].clone();
                self.transition("VISION", &decision.reason)?;
                return Ok(());
            }
        }
        if self.interpret(&snapshot, now, &ready, reason)? {
            self.transition("INTERPRET", "ASYNC_TASK_ACCEPTED")?;
        }
        if self.health.degraded()
            || !d["observations"]
                .as_object()
                .unwrap()
                .values()
                .any(|v| v["status"] == "VALID")
        {
            self.transition("DEGRADED", "COMPONENT_FAILURE_OR_INSUFFICIENT_EVIDENCE")?;
        }
        self.report(now)
    }
    fn fault_parameters(c: &mut Value, f: Option<&Value>) {
        if let Some(f) = f {
            c["parameters"]["fault_id"] = f["fault_id"].clone();
            c["parameters"]["simulated"] = json!(true);
            c["parameters"]["model_executed"] = json!(false);
        }
    }
    fn record_decision(&mut self, kind: &str, d: &Decision) -> Result<()> {
        let p = json!({"action":d.action,"question_id":d.question_id,"reason":d.reason,"cycle_id":self.cycle["cycle_id"],"snapshot_id":self.latest_snapshot["snapshot_id"]});
        let mut full = p.clone();
        full["kind"] = json!(kind);
        self.record("POLICY_EVALUATED", &full)?;
        let key = json!([d.action, d.reason]);
        if self.last_decisions[kind] != key || d.action.is_some() {
            if d.action.is_none() {
                self.record(&format!("{kind}_SKIPPED"), &p)?;
            }
            bounded(&mut self.decisions, full, 20);
        }
        self.last_decisions[kind] = key;
        Ok(())
    }
    pub fn command(
        &self,
        agent: &str,
        action: &str,
        q: &str,
        reason: &str,
        timeout: f64,
        mut parameters: Value,
    ) -> Value {
        parameters["question_id"] = json!(q);
        json!({"command_id":identifier(),"correlation_id":self.cycle["cycle_id"],"experiment_run_id":self.run["run_id"],"target_agent":agent,"action":action,"created_at":utc_now(),"deadline":(chrono::Utc::now()+chrono::Duration::milliseconds((timeout*1000.)as i64)).to_rfc3339_opts(chrono::SecondsFormat::Micros,false),"parameters":parameters,"reason":reason,"schema":SCHEMA_VERSION})
    }
    pub fn interpret(
        &mut self,
        s: &Snapshot,
        now: f64,
        ready: &Value,
        resource: Option<&str>,
    ) -> Result<bool> {
        let d = &s.document;
        let mut accepted = false;
        for (kind, q) in [("text", "Q6"), ("multimodal", "Q7")] {
            let budget = self.config["interpretation"][if kind == "text" {
                "textual"
            } else {
                "multimodal"
            }]
            .clone();
            let image = if kind == "multimodal" {
                self.image.as_ref().map(|i| i.bytes.clone())
            } else {
                None
            };
            let image_id = if kind == "multimodal" {
                self.image.as_ref().map(|i| i.image_id.clone())
            } else {
                None
            };
            let key = semantic_key(q, d, &self.adapters.model, image_id.as_deref());
            let mut decision = self.policy.interpretation(
                kind,
                &self.answers[q],
                now,
                &key,
                &self.attempted,
                ready[if kind == "text" { "text" } else { "vision" }] == "ready"
                    && self.health.available("gemma", now),
                resource,
            );
            if number(&self.cycle["requests"])
                >= number(&self.config["runtime"]["max_cycle_requests"])
            {
                decision = Decision::new(None, q, "CYCLE_REQUEST_LIMIT");
            }
            let episode = list(&d["environment_events"])
                .last()
                .map(|e| e["event_id"].clone())
                .unwrap_or(Value::Null);
            let context_key = json!([d["observations"]["count"]["value"], episode]);
            if kind == "multimodal" && decision.action.is_some() {
                let reason = if image.is_none() {
                    Some("NO_FRESH_AUTHORIZED_IMAGE")
                } else if d["observations"]["count"]["status"] != "VALID" {
                    Some("INSUFFICIENT_EVIDENCE")
                } else if context_key == self.last_multimodal_context && !self.explicit.contains(q)
                {
                    Some("NO_ADDITIONAL_INFORMATION_EXPECTED")
                } else {
                    None
                };
                if let Some(r) = reason {
                    decision = Decision::new(None, q, r);
                }
            }
            let label = if kind == "text" {
                "TEXT_SLM"
            } else {
                "MULTIMODAL"
            };
            self.record_decision(label, &decision)?;
            if decision.action.is_none() {
                continue;
            }
            let prompt = agents::prompt(q, s);
            let expiry = if kind == "multimodal" {
                self.image.as_ref().map(|i| i.expires)
            } else {
                None
            };
            let mut command=self.command("InterpretationAgent",kind,q,&decision.reason,number(&budget["timeout_seconds"]),json!({"snapshot_id":s.snapshot_id,"image_id":image_id,"semantic_key":key,"image_expires_monotonic":expiry}));
            let fault = self.faults.task_fault("gemma");
            Self::fault_parameters(&mut command, fault.as_ref());
            let adapter = self.adapters.clone();
            let cmd = command.clone();
            let snapshot = s.clone();
            let input = prompt.clone();
            let cfg = budget.clone();
            let error = self.tasks.submit(
                "gemma",
                command.clone(),
                Box::new(move || {
                    if image.is_some() && expiry.is_some_and(|t| monotonic() >= t) {
                        return Err("IMAGE_EXPIRED_IN_QUEUE".into());
                    }
                    adapter.interpret(
                        &cmd,
                        &snapshot,
                        image.as_deref().map(Vec::as_slice),
                        &cfg,
                        &input,
                    )
                }),
                key.clone(),
                now,
                number(&budget["timeout_seconds"]),
                fault.clone(),
            );
            if let Some(error) = error {
                self.record(
                    &format!("{label}_SKIPPED"),
                    &json!({"reason":error,"question_id":q}),
                )?;
            } else {
                self.faults.accepted(fault.as_ref(), &command, now);
                self.flush_monitors()?;
                self.attempted.insert(key);
                self.cycle["requests"] = json!(number(&self.cycle["requests"]) as u64 + 1);
                self.policy.accepted_interpretation(kind, now);
                self.record("COMMAND_ISSUED", &command)?;
                self.record(&format!("{label}_REQUESTED"),&json!({"command_id":command["command_id"],"question_id":q,"reason":decision.reason}))?;
                self.record("SLM_INPUT",&json!({"request_id":command["command_id"],"prompt":prompt,"image_id":image_id,"system_prompt":agents::system_prompt(q),"generation_config":budget,"model_id":self.adapters.model,"snapshot_id":s.snapshot_id}))?;
                if kind == "multimodal" {
                    self.last_multimodal_context = context_key;
                }
                accepted = true;
            }
        }
        self.explicit.clear();
        Ok(accepted)
    }
    pub fn report(&mut self, _now: f64) -> Result<()> {
        if self.fsm != "REPORT" {
            self.transition("REPORT", "RESULT_OR_JUSTIFIED_ABSTENTION")?;
        }
        self.record(
            "RESULT_PUBLISHED",
            &json!({"cycle_id":self.cycle["cycle_id"],"answers":self.answers}),
        )?;
        self.transition("WAIT", "REPORT_RECORDED")
    }
    pub fn handle_task(&mut self, event: TaskEvent, now: f64) -> Result<()> {
        let e = event.document;
        let p = e["payload"].clone();
        let cmd = p["command"].clone();
        let id = text(&cmd["experiment_run_id"]);
        let result = p["result"].clone();
        let mut logged = p.clone();
        for k in [
            "error",
            "event_id",
            "timestamp",
            "schema",
            "source_agent",
            "correlation_id",
        ] {
            logged[k] = e[k].clone();
        }
        let kind = text(&e["event_type"]);
        self.log.event(id, kind, &logged)?;
        if self.run["run_id"] == id
            && truth(&self.run["guided"])
            && [
                "TASK_STARTED",
                "TASK_COMPLETED",
                "TASK_FAILED",
                "TASK_TIMEOUT",
            ]
            .contains(&kind)
        {
            let fields: &[&str] = if cmd["action"] == "vision" && kind == "TASK_STARTED" {
                &["power_w", "visible_people"]
            } else {
                &["power_w"]
            };
            let requested = if kind == "TASK_STARTED" {
                p["started_at"].as_str()
            } else {
                p["completed_at"].as_str()
            }
            .or(e["timestamp"].as_str());
            self.log.request_observer(
                id,
                &format!("{}_{}", text(&cmd["action"]).to_uppercase(), kind),
                fields,
                cmd["command_id"].as_str(),
                e["event_id"].as_str(),
                requested,
            )?;
        }
        let same = self.running() && self.run["run_id"] == id;
        if same {
            self.health.task_event(&e, now);
            self.faults.task_event(&e, now);
            self.flush_monitors()?;
            self.context.component_health = self.health.components.clone();
        }
        if !same || truth(&p["late"]) {
            if truth(&result) && cmd["action"] != "vision" {
                self.log.event(id, "HISTORICAL_INTERPRETATION", &result)?;
                if self.run["run_id"] == id {
                    let mut r = result;
                    r["historical"] = json!(true);
                    bounded(&mut self.interpretations, r, 20);
                }
            }
            return Ok(());
        }
        if truth(&e["error"]) || kind == "TASK_TIMEOUT" {
            bounded(
                &mut self.errors,
                json!({"timestamp":utc_now(),"detail":if truth(&e["error"]){e["error"].clone()}else{json!("TASK_TIMEOUT")},"request_id":cmd["command_id"]}),
                20,
            );
        }
        if kind == "TASK_STARTED" {
            return Ok(());
        }
        if cmd["action"] == "vision" {
            if ["TASK_FAILED", "TASK_TIMEOUT"].contains(&kind)
                && ["C", "D", "E"].contains(&self.policy.mode.as_str())
            {
                self.policy.pending_visual_reason = Some("RETRY_VISUAL_EVIDENCE".into());
            }
            if kind == "TASK_COMPLETED" && truth(&result) {
                let age = (wall_time() - timestamp(&result["captured_at"])?).max(0.);
                let obs = observation(
                    "VisionAgent",
                    text(&result["captured_at"]),
                    &utc_now(),
                    text(&result["region"]),
                    result["count"].clone(),
                    "visible_people",
                    text(&result["quality"]),
                    "VALID",
                    json!({"image_id":result["image_id"],"model_id":self.metadata["model_version"]["yolo"]}),
                );
                self.context.put("count", obs.clone(), now, age);
                self.record(
                    "VISION_OBSERVATION",
                    &json!({"task_id":cmd["command_id"],"observation":obs}),
                )?;
                self.last_decisions["stale"] = json!(false);
                if self.policy.mode == "E"
                    && age < number(&self.config["vision"]["image_ttl_seconds"])
                    && let Some(bytes) = event.image
                {
                    self.image = Some(ImageEvidence {
                        image_id: text(&result["image_id"]).into(),
                        bytes,
                        captured_at: text(&result["captured_at"]).into(),
                        expires: now + number(&self.config["vision"]["image_ttl_seconds"]) - age,
                    });
                }
            }
            if self.fsm == "VISION" && self.cycle["pending"] == cmd["command_id"] {
                if kind == "TASK_COMPLETED" {
                    self.transition("ASSESS", "VISION_RESULT_RECEIVED")?;
                    self.assess(now)?;
                } else if ["TASK_FAILED", "TASK_TIMEOUT"].contains(&kind) {
                    self.transition(
                        "DEGRADED",
                        e["error"]
                            .as_str()
                            .filter(|s| !s.is_empty())
                            .unwrap_or("TASK_TIMEOUT"),
                    )?;
                    let s = self.context.snapshot(now);
                    self.latest_snapshot = s.document.clone();
                    self.answers = answer_questions(
                        &s,
                        text(&self.run["mode"]),
                        number(&self.config["interpretation"]["relationship_alignment_seconds"]),
                    );
                    self.report(now)?;
                }
            }
        } else if truth(&result) {
            let mut r = result.clone();
            r["historical"] = json!(true);
            bounded(&mut self.interpretations, r, 20);
            self.result_keys[text(&cmd["parameters"]["question_id"])] =
                json!({"semantic_key":p["semantic_key"],"result":result});
            self.dirty = true;
        }
        Ok(())
    }
    pub fn stop(&mut self, reason: &str, now: f64) -> Result<()> {
        if !self.running() {
            return Ok(());
        }
        if self.fsm != "WAIT" {
            if self.fsm != "DEGRADED" {
                self.transition("DEGRADED", reason)?;
            }
            self.report(now)?;
        }
        for cmd in self.tasks.cancel(text(&self.run["run_id"])) {
            self.record("TASK_CANCELLED",&json!({"command_id":cmd["command_id"],"reason":reason,"physical_cancellation_supported":false}))?;
        }
        self.image = None;
        let duration = number(&self.run["duration_seconds"]);
        let elapsed = (now - self.started).max(0.).min(duration);
        let expected = duration.ceil().min(elapsed.ceil().max(1.)) as i64;
        if self.last_sample_second + 1 < expected {
            self.record("SAMPLE_GAP",&json!({"from_second":self.last_sample_second+1,"to_second":expected-1,"reason":"RUN_ENDED_WITHOUT_SAMPLE"}))?;
        }
        self.run["elapsed_s"] = json!(elapsed);
        self.run["expected_samples"] = json!(expected);
        self.run["finish_reason"] = json!(reason);
        self.run["status"] = json!(if ["USER_STOP", "MAX_RUN_DURATION"].contains(&reason) {
            "COMPLETED"
        } else {
            "FAILED"
        });
        self.run["end_time"] = json!(utc_now());
        self.record("RUN_FINISHED",&json!({"reason":reason,"end_time":self.run["end_time"],"counters":self.tasks.counters}))?;
        if truth(&self.run["guided"]) {
            self.log.request_observer(
                text(&self.run["run_id"]),
                "RUN_FINAL",
                &["power_w", "visible_people", "action"],
                None,
                None,
                None,
            )?;
        }
        self.faults.finish(now);
        self.flush_monitors()?;
        self.log.finish(
            text(&self.run["run_id"]),
            text(&self.run["status"]),
            Some(&self.run),
        )
    }
    pub fn sample(&mut self, now: f64) -> Result<()> {
        let second = (now - self.started).max(0.) as i64;
        if second <= self.last_sample_second
            || second as f64 >= number(&self.run["duration_seconds"])
        {
            return Ok(());
        }
        if second > self.last_sample_second + 1 {
            self.record("SAMPLE_GAP",&json!({"from_second":self.last_sample_second+1,"to_second":second-1,"reason":"SAMPLER_DELAY"}))?;
        }
        let mut d = crate::trace::sample_document(self, now);
        d["second"] = json!(second);
        self.log.sample(text(&self.run["run_id"]), second, &d)?;
        self.last_sample_second = second;
        Ok(())
    }
    pub fn view(&mut self, now: f64) -> Result<Value> {
        let has = !self.run.is_null();
        let context = if has {
            self.context.snapshot(now).document
        } else {
            Value::Null
        };
        let mut run = self.run.clone();
        if let Some(m) = run.as_object_mut() {
            m.shift_remove("config");
        }
        let mut raw = if has {
            self.last_raw_presence.clone()
        } else {
            Value::Null
        };
        if !raw.is_null() {
            let age = (now - self.raw_presence_received + self.raw_presence_age).max(0.);
            raw["age_seconds"] = json!(rounded(age, 2));
            if raw["status"] == "VALID"
                && age >= number(&self.config["sensors"]["presence_ttl_seconds"])
            {
                raw["status"] = json!("STALE");
            }
        }
        let id = text(&self.run["run_id"]);
        Ok(
            json!({"running":self.running(),"run":run,"fsm":self.fsm,"cycle":self.cycle,"observation_region":self.config["regions"]["camera_region"],"component_health":if has{self.health.components.clone()}else{json!({})},"fault_control":if has&&self.run["mode"]=="F"{self.faults.view()}else{Value::Null},"raw_presence":raw,"elapsed_s":if self.running(){(now-self.started).min(number(&self.run["duration_seconds"]))}else{number(&self.run["elapsed_s"])},"observer_requests":if has{self.log.observer_requests(id,true)?}else{vec![]},"observer_previous":if has{self.log.observer_previous(id)?}else{json!({})},"quality":if has{self.log.quality(id)?}else{Value::Null},"transitions":self.transitions,"context":context,"answers":self.answers,"needs":if has{self.policy.needs.as_object().unwrap().values().cloned().collect::<Vec<_>>()}else{vec![]},"tasks":self.tasks.view(now),"interpretations":self.interpretations,"decisions":self.decisions,"errors":self.errors,"resources":self.resources,"enabled_modes":self.config["enabled_modes"],"config_version":self.config["config_version"],"questions":self.answers.as_object().unwrap().iter().map(|(k,v)|(k.clone(),v["question"].clone())).collect::<serde_json::Map<_,_>>(),"reactive_trigger":if has&&self.run["mode"]=="B"{self.policy.reactive_view(&context)}else{Value::Null},"presence_control":if has&&["B","C","D","E","F"].contains(&text(&self.run["mode"])){json!({"mode":if self.manual_presence.is_some(){"MANUAL"}else{"AUTO"},"detected":self.manual_presence,"near":self.manual_near})}else{Value::Null}}),
        )
    }
}
