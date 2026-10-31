use crate::{Result, acquisition::FIELDS, contracts::*};
use serde_json::{Value, json};
use std::collections::{BTreeMap, VecDeque};

pub fn timestamp(value: &Value) -> Result<f64> {
    let s = value.as_str().ok_or("Timestamp ausente o inválido.")?;
    Ok(chrono::DateTime::parse_from_rfc3339(s)
        .map_err(|_| "El timestamp debe incluir zona horaria y ser válido.")?
        .timestamp_micros() as f64
        / 1e6)
}
#[derive(Clone)]
pub struct EnvironmentEvaluator {
    pub config: Value,
    pub history: BTreeMap<String, VecDeque<Value>>,
    pub baseline: Value,
    pub conditions: Value,
    pub events: VecDeque<Value>,
    pub last_update: Option<f64>,
}
fn reset(c: &mut Value) {
    c["evaluable"] = json!(false);
    c["count"] = json!(0);
    c["recovery"] = json!(0);
    if c["state"] == "CANDIDATE" {
        c["state"] = json!("NORMAL");
        c["reference"] = Value::Null;
    } else if c["state"] == "RECOVERING" {
        c["state"] = json!("ACTIVE");
    }
}
impl EnvironmentEvaluator {
    pub fn new(config: Value) -> Self {
        let history = FIELDS
            .iter()
            .map(|f| (f.0.to_string(), VecDeque::new()))
            .collect();
        let mut conditions = json!({});
        for key in ["temperature", "humidity", "aqi", "eco2"] {
            conditions[key] = json!({"state":"NORMAL","count":0,"recovery":0,"reference":null,"armed":false,"rearmed_epoch_s":null,"evaluable":false});
        }
        Self {
            config,
            history,
            baseline: json!({}),
            conditions,
            events: VecDeque::new(),
            last_update: None,
        }
    }
    pub fn update(&mut self, observations: &Value, captured: f64) -> Vec<Value> {
        let mut emitted = vec![];
        let cfg = &self.config;
        if self
            .last_update
            .is_some_and(|t| captured - t > number(&cfg["max_confirmation_gap_seconds"]))
        {
            for c in self.conditions.as_object_mut().unwrap().values_mut() {
                let evaluable = c["evaluable"].clone();
                reset(c);
                c["evaluable"] = evaluable;
            }
        }
        self.last_update = Some(captured);
        for (key, c) in self.conditions.as_object_mut().unwrap() {
            if observations.get(key).is_none() {
                reset(c);
            }
        }
        for (key, _, _, _, _, _) in FIELDS {
            let Some(obs) = observations.get(key) else {
                continue;
            };
            let history = self.history.get_mut(key).unwrap();
            if obs["status"] == "VALID" {
                let sample = json!({"captured_epoch_s":captured,"id":obs["observation_id"],"value":obs["value"]});
                history.push_back(sample.clone());
                if history.len() > number(&cfg["history_capacity"]) as usize {
                    history.pop_front();
                }
                if self.baseline.get(key).is_none() {
                    self.baseline[key] = sample;
                }
            }
            let Some(c) = self.conditions.get_mut(key) else {
                continue;
            };
            if obs["status"] != "VALID" {
                reset(c);
                continue;
            }
            let value = number(&obs["value"]);
            let (reference, active, recovering, magnitude) = if key == "eco2" {
                c["evaluable"] = json!(true);
                if c["state"] == "NORMAL" && value < number(&cfg["eco2_threshold_ppm_equiv"]) {
                    c["armed"] = json!(true);
                }
                let reference = if truth(&c["reference"]) {
                    c["reference"].clone()
                } else {
                    history[history.len().saturating_sub(2)].clone()
                };
                (
                    reference,
                    truth(&c["armed"]) && value >= number(&cfg["eco2_threshold_ppm_equiv"]),
                    value <= number(&cfg["eco2_rearm_threshold"]),
                    value - number(&cfg["eco2_threshold_ppm_equiv"]),
                )
            } else {
                let target = captured - number(&cfg["window_seconds"]);
                let reference = if truth(&c["reference"]) {
                    Some(c["reference"].clone())
                } else {
                    history
                        .iter()
                        .filter(|s| {
                            (number(&s["captured_epoch_s"]) - target).abs()
                                <= number(&cfg["reference_tolerance_seconds"])
                                && (c["rearmed_epoch_s"].is_null()
                                    || number(&s["captured_epoch_s"])
                                        >= number(&c["rearmed_epoch_s"]))
                        })
                        .min_by(|a, b| {
                            (number(&a["captured_epoch_s"]) - target)
                                .abs()
                                .total_cmp(&(number(&b["captured_epoch_s"]) - target).abs())
                        })
                        .cloned()
                };
                let Some(reference) = reference.filter(|r| r["id"] != obs["observation_id"]) else {
                    c["evaluable"] = json!(false);
                    c["count"] = json!(0);
                    continue;
                };
                c["evaluable"] = json!(true);
                let magnitude = value - number(&reference["value"]);
                let (th, re) = match key {
                    "temperature" => ("temperature_rise_c", "temperature_rearm_c"),
                    "humidity" => ("humidity_rise_pp", "humidity_rearm_pp"),
                    _ => ("aqi_increase_levels", "aqi_rearm_levels"),
                };
                (
                    reference,
                    magnitude >= number(&cfg[th]),
                    magnitude <= number(&cfg[re]),
                    magnitude,
                )
            };
            if c["state"] == "NORMAL" || c["state"] == "CANDIDATE" {
                if !active {
                    c["state"] = json!("NORMAL");
                    c["count"] = json!(0);
                    c["reference"] = Value::Null;
                    continue;
                }
                c["reference"] = reference.clone();
                c["state"] = json!("CANDIDATE");
                c["count"] = json!(number(&c["count"]) as u64 + 1);
                if number(&c["count"]) >= number(&cfg["confirmation_samples"]) {
                    c["state"] = json!("ACTIVE");
                    let code = match key {
                        "temperature" => "TEMP_RISE",
                        "humidity" => "HUMIDITY_RISE",
                        "aqi" => "AQI_WORSENED",
                        _ => "ECO2_THRESHOLD_CROSSED",
                    };
                    let ids: Vec<_> = history
                        .iter()
                        .skip(history.len().saturating_sub(number(&c["count"]) as usize))
                        .map(|s| s["id"].clone())
                        .collect();
                    let ev = json!({"event_id":identifier(),"event_type":code,"field":key,"captured_at":obs["captured_at"],"magnitude":magnitude,"reference":reference,"evidence_ids":ids,"observation_id":obs["observation_id"]});
                    self.events.push_back(ev.clone());
                    if self.events.len() > number(&cfg["history_capacity"]) as usize {
                        self.events.pop_front();
                    }
                    emitted.push(ev);
                }
            } else if recovering {
                c["state"] = json!("RECOVERING");
                c["recovery"] = json!(number(&c["recovery"]) as u64 + 1);
                if number(&c["recovery"]) >= number(&cfg["confirmation_samples"]) {
                    c["state"] = json!("NORMAL");
                    c["count"] = json!(0);
                    c["recovery"] = json!(0);
                    c["reference"] = Value::Null;
                    c["rearmed_epoch_s"] = json!(captured);
                    c["armed"] = json!(true);
                }
            } else {
                c["state"] = json!("ACTIVE");
                c["recovery"] = json!(0);
            }
        }
        emitted
    }
}
#[derive(Clone)]
pub struct ContextStore {
    pub config: Value,
    pub observations: Value,
    pub received_monotonic: BTreeMap<String, f64>,
    pub age_on_receipt: BTreeMap<String, f64>,
    pub last_sensor_timestamp: Option<f64>,
    pub environment: EnvironmentEvaluator,
    pub presence_candidate: Value,
    pub presence_samples: usize,
    pub confirmed_presence: Value,
    pub conflict: bool,
    pub component_health: Value,
}
impl ContextStore {
    pub fn new(config: Value) -> Self {
        Self {
            environment: EnvironmentEvaluator::new(config["environment"].clone()),
            config,
            observations: json!({}),
            received_monotonic: BTreeMap::new(),
            age_on_receipt: BTreeMap::new(),
            last_sensor_timestamp: None,
            presence_candidate: Value::Null,
            presence_samples: 0,
            confirmed_presence: Value::Null,
            conflict: false,
            component_health: json!({}),
        }
    }
    pub fn put(&mut self, key: &str, obs: Value, now: f64, age: f64) {
        self.observations[key] = obs;
        self.received_monotonic.insert(key.into(), now);
        self.age_on_receipt.insert(key.into(), age);
    }
    pub fn ingest(
        &mut self,
        updated: &Value,
        radar: Option<&Value>,
        now: f64,
        wall: f64,
        captured_at: Option<&Value>,
    ) -> Result<Vec<Value>> {
        let captured = timestamp(
            captured_at
                .or_else(|| radar.map(|r| &r["captured_at"]))
                .unwrap_or(&Value::Null),
        )?;
        if captured > wall + number(&self.config["sensors"]["max_future_skew_seconds"]) {
            return Err("Timestamp MQTT en el futuro; compruebe sincronización de relojes.".into());
        }
        if self.last_sensor_timestamp.is_some_and(|t| captured <= t) {
            return Err("Telemetría duplicada o fuera de orden.".into());
        }
        if self.last_sensor_timestamp.is_some_and(|t| {
            captured - t > number(&self.config["environment"]["max_confirmation_gap_seconds"])
        }) {
            self.presence_samples = 0;
        }
        self.last_sensor_timestamp = Some(captured);
        if let Some(m) = updated.as_object() {
            for (key, obs) in m {
                self.put(key, obs.clone(), now, (wall - captured).max(0.));
            }
        }
        if let Some(radar) = radar {
            self.put("presence", radar.clone(), now, (wall - captured).max(0.));
        }
        let mut events =
            if wall - captured <= number(&self.config["sensors"]["environment_ttl_seconds"]) {
                self.environment.update(updated, captured)
            } else {
                for c in self
                    .environment
                    .conditions
                    .as_object_mut()
                    .unwrap()
                    .values_mut()
                {
                    c["count"] = json!(0);
                    c["recovery"] = json!(0);
                }
                vec![]
            };
        if let Some(radar) = radar.filter(|r| {
            r["status"] == "VALID"
                && wall - captured <= number(&self.config["sensors"]["presence_ttl_seconds"])
        }) {
            if radar["value"] == self.presence_candidate {
                self.presence_samples += 1;
            } else {
                self.presence_candidate = radar["value"].clone();
                self.presence_samples = 1;
            }
            if self.presence_samples
                >= number(&self.config["modes"]["reactive_debounce_samples"]) as usize
            {
                let previous = self.confirmed_presence.clone();
                self.confirmed_presence = radar["value"].clone();
                if !previous.is_null() && previous != radar["value"] {
                    events.push(json!({"event_id":identifier(),"event_type":"PRESENCE_CHANGED","previous":previous,"value":radar["value"],"evidence_ids":[radar["observation_id"]],"captured_at":radar["captured_at"]}));
                }
            }
        } else {
            self.presence_samples = 0;
        }
        Ok(events)
    }
    pub fn snapshot(&mut self, now: f64) -> Snapshot {
        let mut observations = self.observations.clone();
        for (key, obs) in observations.as_object_mut().unwrap() {
            let ttl = number(if key == "count" {
                &self.config["vision"]["ttl_seconds"]
            } else if key == "presence" {
                &self.config["sensors"]["presence_ttl_seconds"]
            } else {
                &self.config["sensors"]["environment_ttl_seconds"]
            });
            let age = (now - self.received_monotonic[key] + self.age_on_receipt[key]).max(0.);
            obs["age_seconds"] = json!(rounded(age, 2));
            if obs["status"] == "VALID"
                && age >= ttl
                && obs["metadata"]["source_kind"] != "MANUAL_CONTROL"
            {
                obs["status"] = json!("STALE");
            }
        }
        let radar = &observations["presence"];
        let count = &observations["count"];
        self.conflict = truth(&self.config["regions"]["radar_camera_comparable"])
            && radar["status"] == "VALID"
            && count["status"] == "VALID"
            && timestamp(&radar["captured_at"])
                .ok()
                .zip(timestamp(&count["captured_at"]).ok())
                .is_some_and(|(a, b)| {
                    (a - b).abs() <= number(&self.config["regions"]["comparison_max_skew_seconds"])
                })
            && truth(&radar["value"]) != truth(&count["value"]);
        if self.conflict {
            observations["presence"]["status"] = json!("CONFLICTING");
            observations["count"]["status"] = json!("CONFLICTING");
        }
        Snapshot::new(
            json!({"observations":observations,"environment_events":self.environment.events,"environment_conditions":self.environment.conditions,"session_baseline":self.environment.baseline,"conflict":self.conflict,"physical_state":"NOT_DIRECTLY_OBSERVABLE","component_health":self.component_health}),
        )
    }
}
