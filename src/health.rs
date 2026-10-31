use crate::{
    context::timestamp,
    contracts::*,
    faults::{COMPONENTS, SENSOR_FIELDS},
};
use serde_json::{Value, json};
use std::collections::BTreeMap;
pub struct HealthMonitor {
    pub started: f64,
    pub config: Value,
    pub components: Value,
    pub evidence_times: BTreeMap<String, f64>,
    pub retry_after: BTreeMap<String, f64>,
    pub emitted: Vec<(String, Value)>,
}
impl HealthMonitor {
    pub fn new(started: f64, config: Value) -> Self {
        let mut components = json!({});
        for c in COMPONENTS {
            components[c] = json!({"status":"UNKNOWN","reason":"NO_EVIDENCE","since":utc_now()});
        }
        Self {
            started,
            config,
            components,
            evidence_times: BTreeMap::new(),
            retry_after: BTreeMap::new(),
            emitted: vec![],
        }
    }
    pub fn change(&mut self, c: &str, status: &str, reason: &str, now: f64) {
        let previous = self.components[c].clone();
        if previous["status"] == status && previous["reason"] == reason {
            return;
        }
        let current = json!({"status":status,"reason":reason,"since":utc_now()});
        self.components[c] = current.clone();
        let mut payload = current;
        payload["component"] = json!(c);
        payload["previous"] = previous["status"].clone();
        payload["elapsed_s"] = json!(now - self.started);
        self.emitted
            .push(("COMPONENT_HEALTH_CHANGED".into(), payload));
    }
    pub fn sensors(&mut self, obs: &Value, now: f64) {
        for (c, fields) in SENSOR_FIELDS {
            let ttl = number(
                &self.config["sensors"][if c == "radar" {
                    "presence_ttl_seconds"
                } else {
                    "environment_ttl_seconds"
                }],
            );
            let statuses: Vec<_> = fields.iter().map(|k| text(&obs[*k]["status"])).collect();
            if statuses.iter().all(|s| *s == "VALID") {
                self.change(c, "HEALTHY", "FRESH_EVIDENCE", now);
                self.evidence_times.insert(
                    c.into(),
                    fields
                        .iter()
                        .map(|k| number(&obs[*k]["received_monotonic"]))
                        .fold(f64::INFINITY, f64::min),
                );
            } else if statuses.contains(&"ERROR") {
                self.change(c, "FAILED", "INVALID_READING", now);
            } else if statuses.contains(&"STALE") {
                self.change(c, "STALE", "EVIDENCE_EXPIRED", now);
            } else if statuses.contains(&"UNAVAILABLE") || now - self.started >= ttl {
                self.change(c, "UNAVAILABLE", "NO_SENSOR_DATA", now);
            }
        }
    }
    pub fn task_event(&mut self, e: &Value, now: f64) {
        let c = if e["source_agent"] == "VisionAgent" {
            "camera"
        } else {
            "gemma"
        };
        let kind = text(&e["event_type"]);
        if ["TASK_FAILED", "TASK_TIMEOUT"].contains(&kind) {
            self.change(c, "FAILED", kind, now);
            let cooldown = if c == "camera" {
                number(&self.config["vision"]["cooldown_seconds"])
            } else {
                number(&self.config["interpretation"]["textual"]["cooldown_seconds"]).min(number(
                    &self.config["interpretation"]["multimodal"]["cooldown_seconds"],
                ))
            };
            self.retry_after.insert(c.into(), now + cooldown);
        } else if kind == "TASK_STARTED" && self.components[c]["status"] == "FAILED" {
            self.change(c, "RECOVERING", "PROBE_RUNNING", now);
        } else if kind == "TASK_COMPLETED" && !truth(&e["payload"]["late"]) {
            self.change(c, "HEALTHY", "TASK_SUCCEEDED", now);
            let captured = if c == "camera" {
                &e["payload"]["result"]["captured_at"]
            } else {
                &e["payload"]["started_at"]
            };
            self.evidence_times.insert(
                c.into(),
                timestamp(captured)
                    .map(|t| now - (wall_time() - t).max(0.))
                    .unwrap_or(now),
            );
        }
    }
    pub fn available(&self, c: &str, now: f64) -> bool {
        now >= *self.retry_after.get(c).unwrap_or(&f64::NEG_INFINITY)
    }
    pub fn degraded(&self) -> bool {
        self.components
            .as_object()
            .unwrap()
            .values()
            .any(|v| ["STALE", "UNAVAILABLE", "FAILED", "RECOVERING"].contains(&text(&v["status"])))
    }
}
