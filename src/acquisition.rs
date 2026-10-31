use crate::contracts::*;
use serde_json::{Value, json};
pub const FIELDS: [(&str, &str, &str, &str, f64, f64); 5] = [
    ("temperature", "sht40", "temperature_c", "°C", -40., 125.),
    ("humidity", "sht40", "humidity_percent", "%RH", 0., 100.),
    ("aqi", "ens160", "aqi", "ENS160 AQI", 1., 5.),
    ("tvoc", "ens160", "tvoc_ppb", "ppb", 0., 100000.),
    ("eco2", "ens160", "eco2_ppm", "ppm equivalent", 0., 100000.),
];
pub fn environment(payload: &Value, received: &str, region: &str) -> Value {
    let mut observations = json!({});
    for (key, sensor, field, unit, low, high) in FIELDS {
        let value = &payload["environment"][sensor][field];
        let valid = value.as_f64().is_some_and(|v| {
            v.is_finite() && v >= low && v <= high && (key != "aqi" || v.fract() == 0.)
        });
        observations[key] = observation(
            "EnvironmentAgent",
            text(&payload["timestamp"]),
            received,
            region,
            if valid { value.clone() } else { Value::Null },
            unit,
            if valid {
                "sensor_reported"
            } else {
                "missing_or_invalid"
            },
            if valid {
                "VALID"
            } else if value.is_null() {
                "UNAVAILABLE"
            } else {
                "ERROR"
            },
            json!({"device_id":payload["device_id"],"field":field}),
        );
    }
    observations
}
pub fn presence(payload: &Value, received: &str, region: &str) -> Value {
    let p = &payload["presence"];
    let code = &p["state_code"];
    let valid = code.as_u64().is_some_and(|v| v <= 3);
    let mut meta = json!({"state_code":code});
    for field in [
        "motion_distance_cm",
        "static_distance_cm",
        "total_distance_cm",
        "motion_energy",
        "static_energy",
    ] {
        let v = &p[field];
        meta[field] = if v
            .as_f64()
            .is_some_and(|n| n.is_finite() && (0.0..=65535.).contains(&n))
        {
            v.clone()
        } else {
            Value::Null
        };
    }
    let fields: &[&str] = match code.as_u64().filter(|_| valid) {
        Some(1) => &["motion_distance_cm"],
        Some(2) => &["static_distance_cm"],
        Some(3) => &["motion_distance_cm", "static_distance_cm"],
        _ => &[],
    };
    let source = if !fields.is_empty()
        && fields
            .iter()
            .all(|k| meta[*k].as_f64().is_some_and(|v| v > 0.))
    {
        fields
            .iter()
            .min_by(|a, b| number(&meta[**a]).total_cmp(&number(&meta[**b])))
            .copied()
    } else {
        None
    };
    meta["trigger_distance_cm"] = source.map(|s| meta[s].clone()).unwrap_or(Value::Null);
    meta["trigger_distance_source"] = json!(source);
    observation(
        "PresenceAgent",
        text(&payload["timestamp"]),
        received,
        region,
        if valid {
            json!(i32::from(number(code) != 0.))
        } else {
            Value::Null
        },
        "presence",
        "coverage_limited",
        if valid {
            "VALID"
        } else if code.is_null() {
            "UNAVAILABLE"
        } else {
            "ERROR"
        },
        meta,
    )
}
