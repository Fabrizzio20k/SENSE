use crate::{context::timestamp, contracts::*};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet, VecDeque};
pub fn questions() -> Value {
    json!({
"Q1":"¿Hay presencia humana en la región monitoreada?","Q2":"¿Cuántas personas son visibles actualmente?","Q3":"¿Cuáles son las condiciones ambientales actuales?","Q4":"¿Ha ocurrido un cambio ambiental relevante?","Q5":"¿La información disponible es suficiente y consistente?","Q6":"¿Qué relación contextual puede describirse entre ocupación y condiciones ambientales?","Q7":"¿Qué información adicional aporta la imagen sobre la situación del aula?"})
}
pub fn semantic_key(
    question: &str,
    snapshot: &Value,
    model: &str,
    image_id: Option<&str>,
) -> String {
    let mut evidence = json!({});
    if let Some(obs) = snapshot["observations"].as_object() {
        for (key, v) in obs {
            evidence[key] = json!({"value":v["value"],"status":v["status"],"region":v["region"],"source_agent":v["source_agent"],"source_kind":v["metadata"]["source_kind"]});
        }
    }
    let mut input = json!({"question":question,"evidence":evidence,"model":model,"image_id":image_id,"episodes":list(&snapshot["environment_events"]).iter().map(|e|e["event_id"].clone()).collect::<Vec<_>>()});
    let mut health = json!({});
    if let Some(components) = snapshot["component_health"].as_object() {
        for (name, component) in components
            .iter()
            .filter(|(name, _)| name.as_str() != "gemma")
        {
            health[name] = json!({"status":component["status"],"reason":component["reason"]});
        }
    }
    if health.as_object().is_some_and(|m| !m.is_empty()) {
        input["component_health"] = health;
    }
    hash(python_json(&input).as_bytes())
}
fn answer(
    s: &Snapshot,
    q: &str,
    status: &str,
    value: Value,
    keys: &[&str],
    limits: &[&str],
    pending: Value,
) -> Value {
    json!({"question_id":q,"question":questions()[q],"status":status,"answer":value,"evidence_ids":keys.iter().filter_map(|k|s.document["observations"].get(*k).map(|o|o["observation_id"].clone())).collect::<Vec<_>>(),"evaluated_at":s.created_at,"snapshot_id":s.snapshot_id,"limitations":limits,"pending_information":pending})
}
pub fn answer_questions(s: &Snapshot, mode: &str, alignment: f64) -> Value {
    let mode = if mode == "F" { "E" } else { mode };
    let d = &s.document;
    let obs = &d["observations"];
    let p = &obs["presence"];
    let c = &obs["count"];
    let vp = p["status"] == "VALID";
    let vc = c["status"] == "VALID";
    let mut out = json!({});
    out["Q1"] = answer(
        s,
        "Q1",
        if vp { "RESOLVED" } else { "ABSTAINED" },
        json!(if vp {
            if truth(&p["value"]) {
                "Presencia detectada"
            } else {
                "Sin presencia detectada"
            }
        } else {
            "Radar sin evidencia vigente."
        }),
        &["presence"],
        &["Solo cobertura del radar; no representa toda el aula ni proporciona conteo."],
        if vp {
            json!([])
        } else {
            json!(["PRESENCE_REQUIRED"])
        },
    );
    out["Q2"] = answer(
        s,
        "Q2",
        if vc { "RESOLVED" } else { "PENDING" },
        if vc { c["value"].clone() } else { Value::Null },
        &["count"],
        &["Personas visibles en la región de cámara; estimación YOLO."],
        if vc {
            json!([])
        } else {
            json!(["VISUAL_COUNT_REQUIRED"])
        },
    );
    let keys = ["temperature", "humidity", "aqi", "tvoc", "eco2"];
    let mut env = json!({});
    let mut missing_env = vec![];
    for k in keys {
        env[k] = json!({"value":obs[k]["value"],"unit":obs[k]["unit"],"status":obs[k].get("status").cloned().unwrap_or(json!("UNKNOWN"))});
        if env[k]["status"] != "VALID" {
            missing_env.push(k);
        }
    }
    out["Q3"] = answer(
        s,
        "Q3",
        if missing_env.is_empty() {
            "RESOLVED"
        } else {
            "PARTIAL"
        },
        env,
        &keys,
        &["eCO₂ es estimado; AQI es el índice del ENS160. No constituye una alerta certificada."],
        json!(missing_env),
    );
    let events = list(&d["environment_events"]);
    let warming = d["environment_conditions"].as_object().is_some_and(|m| {
        m.iter()
            .any(|(k, v)| k != "eco2" && !truth(&v["evaluable"]))
    });
    out["Q4"]=answer(s,"Q4",if warming||out["Q3"]["status"]!="RESOLVED"{"PARTIAL"}else{"RESOLVED"},json!(events.iter().map(|e|json!({"event_type":e["event_type"],"magnitude":e["magnitude"],"captured_at":e["captured_at"]})).collect::<Vec<_>>()),&keys,&["Cambios confirmados de esta sesión; referencia de ventana y rearme documentados. No implica causalidad."],if warming{json!(["Ventana de comparación incompleta o en rearme."])}else{json!([])});
    let allkeys = [
        "temperature",
        "humidity",
        "aqi",
        "tvoc",
        "eco2",
        "presence",
        "count",
    ];
    let missing: Vec<_> = allkeys
        .iter()
        .filter(|k| obs[**k]["status"] != "VALID")
        .copied()
        .collect();
    let obskeys: Vec<&str> = obs
        .as_object()
        .map(|m| m.keys().map(String::as_str).collect())
        .unwrap_or_default();
    out["Q5"] = answer(
        s,
        "Q5",
        if missing.is_empty() {
            "RESOLVED"
        } else {
            "ABSTAINED"
        },
        json!(if missing.is_empty() {
            "Evidencia vigente dentro de sus regiones."
        } else {
            "Información incompleta, vencida o no comparable."
        }),
        &obskeys,
        &["Radar y cámara solo se comparan si su cobertura fue declarada comparable."],
        json!(missing),
    );
    let related = !events.is_empty()
        && vc
        && vp
        && ["count", "presence"].iter().all(|k| {
            timestamp(&obs[*k]["captured_at"])
                .ok()
                .zip(timestamp(&events.last().unwrap()["captured_at"]).ok())
                .is_some_and(|(a, b)| (a - b).abs() <= alignment)
        });
    let complex = related
        && events
            .iter()
            .rev()
            .take(4)
            .map(|e| text(&e["event_type"]))
            .collect::<HashSet<_>>()
            .len()
            >= 2;
    out["Q6"] = answer(
        s,
        "Q6",
        if complex {
            "PARTIAL"
        } else if related {
            "RESOLVED"
        } else {
            "ABSTAINED"
        },
        json!(if related {
            "Coincidencia temporal de cambios ambientales y evidencia de ocupación; no demuestra causalidad."
        } else {
            "No hay un episodio ambiental y evidencia de ocupación temporalmente comparables."
        }),
        &allkeys,
        &["No se puede atribuir el cambio ambiental a las personas."],
        if complex && ["D", "E"].contains(&mode) {
            json!(["TEXT_INTERPRETATION_REQUIRED"])
        } else {
            json!([])
        },
    );
    out["Q7"] = answer(
        s,
        "Q7",
        if mode == "E" {
            "PENDING"
        } else {
            "NOT_APPLICABLE"
        },
        json!(if mode == "E" {
            "Pendiente de imagen pertinente y necesidad visual adicional."
        } else {
            "Capacidad disponible en E y F."
        }),
        &["count"],
        &["Descripción inferida; sin identificación ni reconocimiento facial."],
        if mode == "E" {
            json!(["MULTIMODAL_INTERPRETATION_REQUIRED"])
        } else {
            json!([])
        },
    );
    out
}
#[derive(Clone, Debug)]
pub struct Decision {
    pub action: Option<String>,
    pub question_id: String,
    pub reason: String,
}
impl Decision {
    pub fn new(action: Option<&str>, q: &str, reason: &str) -> Self {
        Self {
            action: action.map(str::to_owned),
            question_id: q.into(),
            reason: reason.into(),
        }
    }
}
pub struct PolicyEngine {
    pub config: Value,
    pub mode: String,
    pub next_period: f64,
    pub reactive_pending: Value,
    pub reactive_confirmed: Option<bool>,
    pub reactive_candidate: Option<bool>,
    pub reactive_evidence: VecDeque<Value>,
    pub reactive_last_timestamp: Option<f64>,
    pub reactive_zone_override: Option<bool>,
    pub last_visual: f64,
    pub visual_requests: VecDeque<f64>,
    pub slm_requests: BTreeMap<String, VecDeque<f64>>,
    pub last_slm: BTreeMap<String, f64>,
    pub needs: Value,
    pub pending_visual_reason: Option<String>,
}
impl PolicyEngine {
    pub fn new(config: Value, mode: &str, started: f64) -> Self {
        Self {
            config,
            mode: if mode == "F" { "E".into() } else { mode.into() },
            next_period: started,
            reactive_pending: Value::Null,
            reactive_confirmed: None,
            reactive_candidate: None,
            reactive_evidence: VecDeque::new(),
            reactive_last_timestamp: None,
            reactive_zone_override: None,
            last_visual: f64::NEG_INFINITY,
            visual_requests: VecDeque::new(),
            slm_requests: [
                ("text".into(), VecDeque::new()),
                ("multimodal".into(), VecDeque::new()),
            ]
            .into(),
            last_slm: [
                ("text".into(), f64::NEG_INFINITY),
                ("multimodal".into(), f64::NEG_INFINITY),
            ]
            .into(),
            needs: json!({}),
            pending_visual_reason: None,
        }
    }
    pub fn observe_presence(&mut self, o: &Value, wall: f64) -> crate::Result<Vec<Value>> {
        if self.mode != "B" {
            return Ok(vec![]);
        }
        let meta = &o["metadata"];
        let manual = self.reactive_zone_override.is_some();
        let captured = timestamp(&o["captured_at"])?;
        if !manual {
            if let Some(t) = self.reactive_last_timestamp {
                if captured <= t {
                    return Ok(vec![]);
                }
                if captured - t >= number(&self.config["sensors"]["presence_ttl_seconds"]) {
                    self.reactive_evidence.clear();
                }
            }
            self.reactive_last_timestamp = Some(captured);
        }
        let distance = &meta["trigger_distance_cm"];
        if o["status"] != "VALID"
            || (!manual
                && wall - captured >= number(&self.config["sensors"]["presence_ttl_seconds"]))
            || (!manual && truth(&o["value"]) && distance.is_null())
        {
            self.reactive_candidate = None;
            self.reactive_evidence.clear();
            return Ok(vec![]);
        }
        let modes = &self.config["modes"];
        let threshold = number(
            &modes[if self.reactive_confirmed == Some(true) {
                "reactive_exit_at_or_above_cm"
            } else {
                "reactive_enter_below_cm"
            }],
        );
        let near = if manual {
            self.reactive_zone_override.unwrap()
        } else {
            truth(&o["value"]) && number(distance) < threshold
        };
        if manual || self.reactive_candidate != Some(near) {
            self.reactive_evidence.clear();
        }
        self.reactive_candidate = Some(near);
        self.reactive_evidence
            .push_back(o["observation_id"].clone());
        if self.reactive_evidence.len() > number(&modes["reactive_debounce_samples"]) as usize {
            self.reactive_evidence.pop_front();
        }
        if (!manual
            && self.reactive_evidence.len() < number(&modes["reactive_debounce_samples"]) as usize)
            || self.reactive_confirmed == Some(near)
        {
            return Ok(vec![]);
        }
        let previous = self.reactive_confirmed;
        self.reactive_confirmed = Some(near);
        if previous.is_none() && !near {
            return Ok(vec![]);
        }
        let ev = json!({"event_id":identifier(),"event_type":if previous.is_none(){"RADAR_NEAR_CONFIRMED"}else if near{"RADAR_ZONE_ENTERED"}else{"RADAR_ZONE_EXITED"},"previous":previous,"near":near,"distance_cm":distance,"distance_source":meta["trigger_distance_source"],"enter_below_cm":modes["reactive_enter_below_cm"],"exit_at_or_above_cm":modes["reactive_exit_at_or_above_cm"],"confirmation_samples":self.reactive_evidence.len(),"region":o["region"],"evidence_ids":self.reactive_evidence,"captured_at":o["captured_at"]});
        self.reactive_pending = ev.clone();
        Ok(vec![ev])
    }
    pub fn reset_reactive(&mut self) {
        self.reactive_zone_override = None;
        self.reactive_confirmed = None;
        self.reactive_candidate = None;
        self.reactive_pending = Value::Null;
        self.reactive_last_timestamp = None;
        self.reactive_evidence.clear();
    }
    pub fn reactive_view(&self, s: &Value) -> Value {
        let o = &s["observations"]["presence"];
        let m = &o["metadata"];
        let modes = &self.config["modes"];
        if let Some(near) = self.reactive_zone_override {
            let state = if near { "NEAR" } else { "FAR" };
            return json!({"state":state,"candidate":state,"distance_cm":null,"distance_source":null,"confirmed_samples":1,"required_samples":1,"pending_event":self.reactive_pending,"enter_below_cm":modes["reactive_enter_below_cm"],"exit_at_or_above_cm":modes["reactive_exit_at_or_above_cm"]});
        }
        let known = ["VALID", "CONFLICTING"].contains(&text(&o["status"]))
            && (o["value"] == 0 || !m["trigger_distance_cm"].is_null());
        json!({"state":if !known{"UNKNOWN"}else if self.reactive_evidence.len()<number(&modes["reactive_debounce_samples"]) as usize{"CONFIRMING"}else if self.reactive_confirmed==Some(true){"NEAR"}else{"FAR"},"candidate":self.reactive_candidate.map(|b|if b{"NEAR"}else{"FAR"}),"distance_cm":m["trigger_distance_cm"],"distance_source":m["trigger_distance_source"],"confirmed_samples":if known{self.reactive_evidence.len()}else{0},"required_samples":modes["reactive_debounce_samples"],"enter_below_cm":modes["reactive_enter_below_cm"],"exit_at_or_above_cm":modes["reactive_exit_at_or_above_cm"],"pending_event":self.reactive_pending})
    }
    pub fn information_needs(&mut self, answers: &Value, s: &Value) -> Value {
        for (q, kind) in [
            ("Q1", "PRESENCE_REQUIRED"),
            ("Q2", "VISUAL_COUNT_REQUIRED"),
            ("Q3", "ENVIRONMENT_STATUS_REQUIRED"),
            ("Q5", "CONFLICT_RESOLUTION_REQUIRED"),
            ("Q6", "TEXT_INTERPRETATION_REQUIRED"),
            ("Q7", "MULTIMODAL_INTERPRETATION_REQUIRED"),
        ] {
            let a = &answers[q];
            let mut needed = truth(&a["pending_information"]) && a["status"] != "NOT_APPLICABLE";
            if q == "Q2" && ["C", "D", "E"].contains(&self.mode.as_str()) {
                needed = self.pending_visual_reason.is_some();
            }
            if needed && (self.needs.get(q).is_none() || self.needs[q]["status"] == "RESOLVED") {
                let expiry = chrono::DateTime::parse_from_rfc3339(text(&s["created_at"])).unwrap()
                    + chrono::Duration::milliseconds(
                        (number(&self.config["runtime"]["max_run_seconds"]) * 1000.) as i64,
                    );
                self.needs[q] = json!({"need_id":identifier(),"type":kind,"question_id":q,"question":questions()[q],"origin":"CONTEXT_EVALUATION","region":if ["Q2","Q7"].contains(&q){self.config["regions"]["camera_region"].clone()}else{json!("source_regions")},"created_at":s["created_at"],"expires_at":expiry.to_rfc3339_opts(chrono::SecondsFormat::Micros,false),"priority":if ["Q1","Q3"].contains(&q){1}else{2},"status":"PENDING"});
            }
            if self.needs.get(q).is_some() {
                self.needs[q]["status"] = json!(if needed { "PENDING" } else { "RESOLVED" });
                self.needs[q]["evidence_ids"] = a["evidence_ids"].clone();
                self.needs[q]["missing_information"] = a["pending_information"].clone();
            }
        }
        json!(self.needs.as_object().unwrap().values().collect::<Vec<_>>())
    }
    pub fn visual_need(&mut self, s: &Value, events: &[Value]) -> Option<String> {
        if !["C", "D", "E"].contains(&self.mode.as_str()) {
            return None;
        }
        let count = &s["observations"]["count"];
        let changed = events.iter().any(|e| e["event_type"] == "PRESENCE_CHANGED")
            && truth(&self.config["regions"]["radar_camera_comparable"]);
        let env = events.iter().any(|e| {
            [
                "TEMP_RISE",
                "HUMIDITY_RISE",
                "AQI_WORSENED",
                "ECO2_THRESHOLD_CROSSED",
            ]
            .contains(&text(&e["event_type"]))
        });
        if count["status"] == "VALID" && !truth(&s["conflict"]) {
            self.pending_visual_reason = None;
            return if changed {
                Some("COMPARABLE_PRESENCE_CHANGED".into())
            } else if env {
                Some("ENVIRONMENT_CONTEXT_REQUIRED".into())
            } else {
                None
            };
        }
        if self.pending_visual_reason.is_some() {
            return self.pending_visual_reason.clone();
        }
        self.pending_visual_reason = if truth(&s["conflict"]) {
            Some("RESOLVABLE_CONFLICT")
        } else if changed {
            Some("COMPARABLE_PRESENCE_CHANGED")
        } else if env {
            Some("ENVIRONMENT_CONTEXT_REQUIRED")
        } else if self.mode == "E" && !truth(count) {
            Some("MULTIMODAL_REFERENCE_REQUIRED")
        } else {
            None
        }
        .map(str::to_owned);
        self.pending_visual_reason.clone()
    }
    pub fn request_visual_count(&mut self) {
        self.pending_visual_reason = Some("EXPLICIT_VISUAL_COUNT_REQUEST".into());
    }
    pub fn vision(
        &mut self,
        s: &Value,
        now: f64,
        events: &[Value],
        available: bool,
        busy: bool,
        resource: Option<&str>,
    ) -> Decision {
        let no = |r: &str| Decision::new(None, "Q2", r);
        let reason;
        match self.mode.as_str() {
            "A" => {
                if now < self.next_period {
                    return no("PERIOD_NOT_DUE");
                }
                reason = "PERIODIC_SCHEDULE".into();
            }
            "B" => {
                let trigger = self.reactive_view(s);
                if trigger["state"] == "UNKNOWN" {
                    self.reactive_evidence.clear();
                    return no("RADAR_DISTANCE_UNKNOWN");
                }
                if trigger["state"] == "CONFIRMING" {
                    return no("RADAR_ZONE_CONFIRMING");
                }
                if !truth(&self.reactive_pending) {
                    return no("NO_REACTIVE_TRIGGER");
                }
                reason = text(&self.reactive_pending["event_type"]).to_owned();
            }
            _ => {
                let Some(r) = self.visual_need(s, events) else {
                    return no("NO_VISUAL_NEED");
                };
                reason = r;
                if s["observations"]["count"]["status"] == "VALID" {
                    return no("ALREADY_FRESH");
                }
            }
        }
        if self.mode == "A" {
            let interval = number(&self.config["modes"]["periodic_interval_seconds"]);
            let due = ((now - self.next_period) / interval).floor() + 1.;
            self.next_period += due * interval;
        }
        if busy {
            return no(if self.mode == "A" {
                "MISSED_PERIOD_BUSY"
            } else {
                "DUPLICATE_REQUEST"
            });
        }
        if !available {
            return no("CAMERA_UNAVAILABLE");
        }
        if let Some(r) = resource {
            return no(r);
        }
        let cooldown = number(if self.mode == "B" {
            &self.config["modes"]["reactive_min_interval_seconds"]
        } else {
            &self.config["vision"]["cooldown_seconds"]
        });
        if self.mode != "A" && now - self.last_visual < cooldown {
            return no("COOLDOWN_ACTIVE");
        }
        while self
            .visual_requests
            .front()
            .is_some_and(|t| now - t >= number(&self.config["vision"]["request_window_seconds"]))
        {
            self.visual_requests.pop_front();
        }
        if self.visual_requests.len()
            >= number(&self.config["vision"]["max_requests_per_window"]) as usize
        {
            return no("RATE_LIMIT");
        }
        Decision::new(Some("vision"), "Q2", &reason)
    }
    pub fn accepted_vision(&mut self, now: f64) {
        self.last_visual = now;
        self.visual_requests.push_back(now);
        self.reactive_pending = Value::Null;
        self.pending_visual_reason = None;
    }
    #[allow(clippy::too_many_arguments)] // Preserve the policy inputs from the reference implementation.
    pub fn interpretation(
        &mut self,
        kind: &str,
        a: &Value,
        now: f64,
        key: &str,
        attempted: &HashSet<String>,
        available: bool,
        resource: Option<&str>,
    ) -> Decision {
        let q = if kind == "text" { "Q6" } else { "Q7" };
        let no = |r: &str| Decision::new(None, q, r);
        if !(if kind == "text" {
            ["D", "E"].contains(&self.mode.as_str())
        } else {
            self.mode == "E"
        }) {
            return no("MODE_CAPABILITY_DISABLED");
        }
        if kind == "text"
            && !list(&a["pending_information"]).contains(&json!("TEXT_INTERPRETATION_REQUIRED"))
        {
            return no("NOT_REQUIRED_FOR_QUESTION");
        }
        if attempted.contains(key) {
            return no("DUPLICATE_REQUEST");
        }
        if !available {
            return no("MODEL_UNAVAILABLE");
        }
        if let Some(r) = resource {
            return no(r);
        }
        let b = &self.config["interpretation"][if kind == "text" {
            "textual"
        } else {
            "multimodal"
        }];
        if now - self.last_slm[kind] < number(&b["cooldown_seconds"]) {
            return no("COOLDOWN_ACTIVE");
        }
        let h = self.slm_requests.get_mut(kind).unwrap();
        while h
            .front()
            .is_some_and(|t| now - t >= number(&b["request_window_seconds"]))
        {
            h.pop_front();
        }
        if h.len() >= number(&b["max_requests_per_window"]) as usize {
            return no("RATE_LIMIT");
        }
        Decision::new(Some(kind), q, "UNRESOLVED_CONTEXTUAL_NEED")
    }
    pub fn accepted_interpretation(&mut self, kind: &str, now: f64) {
        self.last_slm.insert(kind.into(), now);
        self.slm_requests.get_mut(kind).unwrap().push_back(now);
    }
}
