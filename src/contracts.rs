use chrono::{SecondsFormat, Utc};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

pub const SCHEMA_VERSION: &str = "sense.v1";
pub const STATES: &[&str] = &[
    "WAIT",
    "ACQUIRE",
    "ASSESS",
    "VISION",
    "INTERPRET",
    "REPORT",
    "DEGRADED",
];
pub fn identifier() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}
pub fn utc_now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, false)
}
pub fn wall_time() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
pub fn monotonic() -> f64 {
    static START: std::sync::OnceLock<(std::time::Instant, f64)> = std::sync::OnceLock::new();
    let (start, base) =
        START.get_or_init(|| (std::time::Instant::now(), sysinfo::System::uptime() as f64));
    base + start.elapsed().as_secs_f64()
}
pub fn number(v: &Value) -> f64 {
    v.as_f64().unwrap_or(0.0)
}
pub fn text(v: &Value) -> &str {
    v.as_str().unwrap_or("")
}
pub fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(_) => number(v) != 0.0,
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
pub fn list(v: &Value) -> Vec<Value> {
    v.as_array().cloned().unwrap_or_default()
}
pub fn rounded(v: f64, digits: i32) -> f64 {
    let m = 10_f64.powi(digits);
    (v * m).round_ties_even() / m
}
pub fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
// Python's sorted JSON representation is part of persisted configuration/semantic hashes.
pub fn python_json(v: &Value) -> String {
    json_compat(v, true, false)
}
pub fn python_json_ordered(v: &Value) -> String {
    json_compat(v, false, false)
}
pub fn python_json_compact(v: &Value) -> String {
    json_compat(v, false, true)
}
fn json_compat(v: &Value, sorted: bool, compact: bool) -> String {
    let comma = if compact { "," } else { ", " };
    let colon = if compact { ":" } else { ": " };
    match v {
        Value::String(s) => {
            let quoted = serde_json::to_string(s).unwrap();
            let mut out = String::new();
            for ch in quoted.chars() {
                if ch >= '\u{007f}' {
                    let mut buf = [0u16; 2];
                    for unit in ch.encode_utf16(&mut buf) {
                        out.push_str(&format!("\\u{unit:04x}"));
                    }
                } else {
                    out.push(ch);
                }
            }
            out
        }
        Value::Array(a) => format!(
            "[{}]",
            a.iter()
                .map(|v| json_compat(v, sorted, compact))
                .collect::<Vec<_>>()
                .join(comma)
        ),
        Value::Object(m) => {
            let mut entries: Vec<_> = m.iter().collect();
            if sorted {
                entries.sort_by_key(|(k, _)| *k);
            }
            format!(
                "{{{}}}",
                entries
                    .into_iter()
                    .map(|(k, v)| format!(
                        "{}{colon}{}",
                        json_compat(&json!(k), sorted, compact),
                        json_compat(v, sorted, compact)
                    ))
                    .collect::<Vec<_>>()
                    .join(comma)
            )
        }
        _ => v.to_string(),
    }
}
#[derive(Clone, Debug)]
pub struct Snapshot {
    pub snapshot_id: String,
    pub created_at: String,
    pub document: Value,
}
impl Snapshot {
    pub fn new(mut document: Value) -> Self {
        let snapshot_id = identifier();
        let created_at = utc_now();
        document["schema"] = json!(SCHEMA_VERSION);
        document["snapshot_id"] = json!(snapshot_id);
        document["created_at"] = json!(created_at);
        Self {
            snapshot_id,
            created_at,
            document,
        }
    }
}
#[allow(clippy::too_many_arguments)] // Same fields as the persisted observation contract.
pub fn observation(
    agent: &str,
    captured: &str,
    received: &str,
    region: &str,
    value: Value,
    unit: &str,
    quality: &str,
    status: &str,
    metadata: Value,
) -> Value {
    json!({"observation_id":identifier(),"source_agent":agent,"captured_at":captured,"received_at":received,"region":region,"value":value,"unit":unit,"quality":quality,"status":status,"metadata":metadata,"schema":SCHEMA_VERSION})
}
pub fn event(
    correlation: &str,
    agent: &str,
    kind: &str,
    payload: Value,
    error: Option<String>,
) -> Value {
    json!({"correlation_id":correlation,"source_agent":agent,"event_type":kind,"payload":payload,"error":error,"event_id":identifier(),"timestamp":utc_now(),"schema":SCHEMA_VERSION})
}
