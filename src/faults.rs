use crate::{Result, contracts::*};
use serde_json::{Value, json};
use std::collections::BTreeMap;
pub const SENSOR_FIELDS: [(&str, &[&str]); 3] = [
    ("sht40", &["temperature", "humidity"]),
    ("ens160", &["aqi", "tvoc", "eco2"]),
    ("radar", &["presence"]),
];
pub const COMPONENTS: [&str; 5] = ["sht40", "ens160", "radar", "camera", "gemma"];
pub fn public_fault(f: &Value) -> Value {
    let mut f = f.clone();
    f.as_object_mut()
        .unwrap()
        .retain(|k, _| !k.ends_with("_monotonic"));
    f
}
pub struct FaultInjector {
    pub started: f64,
    pub records: Value,
    pub disabled: BTreeMap<String, String>,
    pub timeouts: BTreeMap<String, String>,
    pub emitted: Vec<(String, Value)>,
}
impl FaultInjector {
    pub fn new(started: f64) -> Self {
        Self {
            started,
            records: json!({}),
            disabled: BTreeMap::new(),
            timeouts: BTreeMap::new(),
            emitted: vec![],
        }
    }
    fn emit(&mut self, kind: &str, id: &str, now: f64) {
        let mut f = public_fault(&self.records[id]);
        f["event_id"] = json!(identifier());
        f["elapsed_s"] = json!(rounded(now - self.started, 3));
        self.emitted.push((kind.into(), f));
    }
    fn begin(&mut self, component: &str, kind: &str, now: f64, baseline: &str) -> String {
        let id = identifier();
        self.records[&id] = json!({"fault_id":id,"component":component,"kind":kind,"simulated":true,"activated_at":utc_now(),"activated_elapsed_s":now-self.started,"activated_monotonic":now,"detected_at":null,"restored_at":null,"recovered_at":null,"task_id":null,"baseline_status":baseline,"preexisting_failure":(["FAILED","STALE","UNAVAILABLE"].contains(&baseline))});
        self.emit("FAULT_INJECTED", &id, now);
        id
    }
    pub fn set_enabled(
        &mut self,
        component: &str,
        enabled: &Value,
        now: f64,
        baseline: &str,
    ) -> Result<()> {
        if !["sht40", "ens160", "radar", "camera"].contains(&component) || !enabled.is_boolean() {
            return Err("Selecciona sht40, ens160, radar o camera y enabled booleano.".into());
        }
        if truth(enabled) {
            if let Some(id) = self.disabled.remove(component) {
                self.restore(&id, now);
            }
        } else if !self.disabled.contains_key(component) {
            let id = self.begin(
                component,
                if component == "camera" {
                    "CAMERA_UNAVAILABLE"
                } else {
                    "DATA_LOSS"
                },
                now,
                baseline,
            );
            self.disabled.insert(component.into(), id);
        }
        Ok(())
    }
    fn restored(&mut self, id: &str, now: f64) {
        let f = &mut self.records[id];
        f["restored_at"] = json!(utc_now());
        f["restored_elapsed_s"] = json!(now - self.started);
        f["restored_monotonic"] = json!(now);
    }
    fn restore(&mut self, id: &str, now: f64) {
        self.restored(id, now);
        self.emit("FAULT_RESTORED", id, now);
    }
    pub fn arm_timeout(&mut self, lane: &str, now: f64, baseline: &str) -> Result<()> {
        if !["vision", "gemma"].contains(&lane) {
            return Err("Selecciona vision o gemma para provocar timeout.".into());
        }
        if self.timeouts.contains_key(lane) {
            return Err("Ya hay un timeout armado o en curso para ese worker.".into());
        }
        let id = self.begin(
            if lane == "vision" { "camera" } else { "gemma" },
            "TIMEOUT",
            now,
            baseline,
        );
        self.timeouts.insert(lane.into(), id);
        Ok(())
    }
    pub fn task_fault(&self, lane: &str) -> Option<Value> {
        if lane == "vision"
            && let Some(id) = self.disabled.get("camera")
        {
            return Some(self.records[id].clone());
        }
        self.timeouts
            .get(lane)
            .filter(|id| self.records[*id]["task_id"].is_null())
            .map(|id| self.records[id].clone())
    }
    pub fn accepted(&mut self, fault: Option<&Value>, command: &Value, now: f64) {
        if let Some(f) = fault {
            let id = text(&f["fault_id"]);
            self.records[id]["task_id"] = command["command_id"].clone();
            self.records[id]["applied_at"] = json!(utc_now());
            self.records[id]["applied_monotonic"] = json!(now);
            self.emit("FAULT_APPLIED", id, now);
        }
    }
    pub fn observe(&mut self, health: &Value, now: f64, evidence: &BTreeMap<String, f64>) {
        let ids: Vec<_> = self.records.as_object().unwrap().keys().cloned().collect();
        for id in ids {
            let f = self.records[&id].clone();
            if truth(&f["recovered_at"]) || truth(&f["not_executed_reason"]) {
                continue;
            }
            let component = text(&f["component"]);
            if f["kind"] == "DATA_LOSS"
                && !truth(&f["detected_at"])
                && ["STALE", "UNAVAILABLE", "FAILED"].contains(&text(&health[component]["status"]))
            {
                self.records[&id]["detected_at"] = json!(utc_now());
                self.records[&id]["detection_latency_s"] = if truth(&f["preexisting_failure"]) {
                    Value::Null
                } else {
                    json!((now - number(&f["activated_monotonic"])).max(0.))
                };
                self.emit("FAULT_DETECTED", &id, now);
            }
            if truth(&f["restored_at"])
                && !truth(&f["recovered_at"])
                && health[component]["status"] == "HEALTHY"
                && evidence
                    .get(component)
                    .is_some_and(|t| *t > number(&f["restored_monotonic"]))
            {
                self.records[&id]["recovered_at"] = json!(utc_now());
                self.records[&id]["recovery_latency_s"] =
                    json!(now - number(&f["restored_monotonic"]));
                self.emit("FAULT_RECOVERED", &id, now);
            }
        }
    }
    pub fn task_event(&mut self, e: &Value, now: f64) {
        let id = text(&e["payload"]["command"]["parameters"]["fault_id"]);
        if self.records.get(id).is_none() {
            return;
        }
        let id = id.to_owned();
        let kind = text(&e["event_type"]);
        if kind == "TASK_STARTED" {
            self.records[&id]["task_started_at"] = e["payload"]["started_at"].clone();
            self.records[&id]["task_started_monotonic"] = json!(
                number(&self.records[&id]["applied_monotonic"])
                    + number(&e["payload"]["queue_seconds"])
            );
            self.emit("FAULT_TASK_STARTED", &id, now);
        }
        let f = self.records[&id].clone();
        if f["kind"] == "TIMEOUT" && kind == "TASK_TIMEOUT" && truth(&e["payload"]["reason"]) {
            self.restored(&id, now);
            self.records[&id]["not_executed_reason"] = e["payload"]["reason"].clone();
            self.emit("FAULT_NOT_EXECUTED", &id, now);
            self.timeouts.retain(|_, v| v != &id);
            return;
        }
        if (kind == "TASK_TIMEOUT" || (kind == "TASK_FAILED" && f["kind"] == "CAMERA_UNAVAILABLE"))
            && !truth(&f["detected_at"])
        {
            let since = if f["kind"] == "TIMEOUT" {
                f.get("task_started_monotonic")
                    .unwrap_or(&f["activated_monotonic"])
            } else {
                &f["activated_monotonic"]
            };
            self.records[&id]["detected_at"] = json!(utc_now());
            self.records[&id]["detection_latency_s"] = if truth(&f["preexisting_failure"]) {
                Value::Null
            } else {
                json!(now - number(since))
            };
            self.emit("FAULT_DETECTED", &id, now);
        }
        if f["kind"] == "TIMEOUT" && kind == "TASK_FAILED" {
            self.restore(&id, now);
            self.timeouts.retain(|_, v| v != &id);
        }
    }
    pub fn finish(&mut self, now: f64) {
        let ids: Vec<_> = self.records.as_object().unwrap().keys().cloned().collect();
        for id in ids {
            if !truth(&self.records[&id]["recovered_at"])
                && !truth(&self.records[&id]["not_executed_reason"])
            {
                self.emit("FAULT_RUN_ENDED", &id, now);
            }
        }
        self.disabled.clear();
        self.timeouts.clear();
    }
    pub fn view(&self) -> Value {
        json!({"disabled":self.disabled.keys().collect::<Vec<_>>(),"timeouts":self.timeouts.iter().map(|(l,id)|(l.clone(),json!(if self.records[id]["task_id"].is_null(){"ARMED"}else if truth(&self.records[id]["task_started_at"]){"RUNNING"}else{"QUEUED"}))).collect::<serde_json::Map<_,_>>(),"faults":self.records.as_object().unwrap().values().map(public_fault).collect::<Vec<_>>()})
    }
}
