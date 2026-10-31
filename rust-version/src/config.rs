use crate::{Result, contracts::*};
use serde_json::{Value, json};
use std::path::Path;

pub fn load_config(path: &Path) -> Result<Value> {
    let mut config: Value = serde_yaml_ng::from_str(&std::fs::read_to_string(path)?)
        .map_err(|e| format!("Configuración YAML inválida: {e}"))?;
    validate_config(&config)?;
    let digest = hash(python_json(&config).as_bytes());
    config["config_hash"] = json!(digest);
    Ok(config)
}
pub fn validate_config(c: &Value) -> Result<()> {
    if !c.is_object() {
        return Err("La configuración debe ser un objeto YAML.".into());
    }
    let positive: &[(&str, &[&str])] = &[
        (
            "environment",
            &[
                "window_seconds",
                "reference_tolerance_seconds",
                "confirmation_samples",
                "max_confirmation_gap_seconds",
                "history_capacity",
                "temperature_rise_c",
                "humidity_rise_pp",
                "aqi_increase_levels",
                "eco2_threshold_ppm_equiv",
            ],
        ),
        (
            "vision",
            &[
                "ttl_seconds",
                "cooldown_seconds",
                "max_requests_per_window",
                "request_window_seconds",
                "timeout_seconds",
                "image_ttl_seconds",
                "max_image_bytes",
            ],
        ),
        (
            "interpretation",
            &["queue_capacity", "relationship_alignment_seconds"],
        ),
        (
            "runtime",
            &[
                "tick_seconds",
                "evaluation_interval_seconds",
                "publish_interval_seconds",
                "cycle_timeout_seconds",
                "max_cycle_requests",
                "max_run_seconds",
                "inbox_capacity",
                "min_available_mb",
                "max_rss_mb",
                "max_cpu_percent",
                "resource_interval_seconds",
                "max_database_mb",
                "min_disk_free_mb",
            ],
        ),
        (
            "sensors",
            &[
                "environment_ttl_seconds",
                "presence_ttl_seconds",
                "max_future_skew_seconds",
            ],
        ),
        (
            "modes",
            &[
                "periodic_interval_seconds",
                "reactive_debounce_samples",
                "reactive_min_interval_seconds",
                "reactive_enter_below_cm",
                "reactive_exit_at_or_above_cm",
            ],
        ),
        ("regions", &["comparison_max_skew_seconds"]),
    ];
    for (section, names) in positive {
        if !c[*section].is_object() {
            return Err(format!("Falta la sección de configuración {section}.").into());
        }
        for name in *names {
            if !c[*section][*name]
                .as_f64()
                .is_some_and(|v| v.is_finite() && v > 0.)
            {
                return Err(format!("Falta un límite positivo: {section}.{name}").into());
            }
        }
    }
    if number(&c["modes"]["reactive_exit_at_or_above_cm"])
        <= number(&c["modes"]["reactive_enter_below_cm"])
    {
        return Err("El umbral de salida reactiva debe superar al de entrada.".into());
    }
    for (s, n) in [
        ("environment", "confirmation_samples"),
        ("environment", "history_capacity"),
        ("vision", "max_requests_per_window"),
        ("vision", "max_image_bytes"),
        ("interpretation", "queue_capacity"),
        ("runtime", "inbox_capacity"),
        ("runtime", "max_cycle_requests"),
        ("modes", "reactive_debounce_samples"),
    ] {
        integer(&c[s][n], s, n)?;
    }
    for (name, threshold) in [
        ("temperature_rearm_c", "temperature_rise_c"),
        ("humidity_rearm_pp", "humidity_rise_pp"),
        ("aqi_rearm_levels", "aqi_increase_levels"),
        ("eco2_rearm_threshold", "eco2_threshold_ppm_equiv"),
    ] {
        if !c["environment"][name]
            .as_f64()
            .is_some_and(|v| v.is_finite() && v >= 0. && v < number(&c["environment"][threshold]))
        {
            return Err(format!(
                "Defina environment.{name} por debajo de {threshold} antes de iniciar."
            )
            .into());
        }
    }
    if number(&c["interpretation"]["max_concurrent"]) != 1. {
        return Err("El piloto admite una sola inferencia Gemma activa.".into());
    }
    for kind in ["textual", "multimodal"] {
        let budget = &c["interpretation"][kind];
        if !budget.is_object() {
            return Err(format!("Falta interpretation.{kind}.").into());
        }
        for name in [
            "timeout_seconds",
            "cooldown_seconds",
            "max_requests_per_window",
            "request_window_seconds",
            "max_tokens",
        ] {
            if !budget[name]
                .as_f64()
                .is_some_and(|v| v.is_finite() && v > 0.)
            {
                return Err(
                    format!("Falta un límite positivo: interpretation.{kind}.{name}").into(),
                );
            }
            if ["max_requests_per_window", "max_tokens"].contains(&name) {
                integer(&budget[name], &format!("interpretation.{kind}"), name)?;
            }
        }
    }
    if !truth(&c["config_version"]) || !truth(&c["hardware_profile"]) {
        return Err("Faltan config_version o hardware_profile.".into());
    }
    if !c["enabled_modes"].as_array().is_some_and(|v| {
        !v.is_empty()
            && v.iter().all(|m| {
                m.as_str()
                    .is_some_and(|s| ["A", "B", "C", "D", "E", "F"].contains(&s))
            })
    }) {
        return Err("enabled_modes debe contener modos A–F.".into());
    }
    for name in ["radar_region", "camera_region", "environment_region"] {
        if c["regions"][name].as_str().is_none_or(|s| s.is_empty()) {
            return Err(format!("Falta regions.{name}.").into());
        }
    }
    if !c["regions"]["radar_camera_comparable"].is_boolean() {
        return Err("regions.radar_camera_comparable debe ser booleano.".into());
    }
    Ok(())
}
fn integer(v: &Value, s: &str, n: &str) -> Result<()> {
    if v.is_i64() || v.is_u64() {
        Ok(())
    } else {
        Err(format!("Se requiere un entero: {s}.{n}").into())
    }
}
