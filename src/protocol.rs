use crate::{Result, context::timestamp, contracts::*};
use serde_json::{Value, json};
pub const PROTOCOL_VERSION: &str = "sense-observer-1";
pub fn checkpoints() -> Value {
    json!({"S1":[600,900],"S2":[300,600,900,1200,1500],"S3":[600,1200]})
}
pub fn validate_observation(p: &Value, fields: &[String]) -> Result<()> {
    if !p.is_object() {
        return Err("La observación debe ser un objeto.".into());
    }
    if timestamp(&p["observed_at"])? > wall_time() + 5. {
        return Err("La hora observada no puede estar en el futuro.".into());
    }
    for key in ["power_observed_at", "people_observed_at"] {
        if p.get(key).is_some() && timestamp(&p[key])? > wall_time() + 5. {
            return Err("La hora de lectura no puede estar en el futuro.".into());
        }
    }
    let unavailable = p.get("unavailable_fields").cloned().unwrap_or(json!([]));
    if !unavailable.as_array().is_some_and(|a| {
        a.iter()
            .all(|f| f.as_str().is_some_and(|s| fields.iter().any(|x| x == s)))
            && a.iter().collect::<std::collections::HashSet<_>>().len() == a.len()
    }) {
        return Err("Campos no observados inválidos.".into());
    }
    if truth(&unavailable) && text(&p["missing_reason"]).trim().is_empty() {
        return Err("Explica por qué no pudiste observar los campos pendientes.".into());
    }
    let repeated = p.get("repeated_fields").cloned().unwrap_or(json!([]));
    if !repeated.as_array().is_some_and(|a| {
        a.iter().all(|f| {
            f.as_str().is_some_and(|s| {
                fields.iter().any(|x| x == s) && ["power_w", "visible_people"].contains(&s)
            }) && !list(&unavailable).contains(f)
        }) && a.iter().collect::<std::collections::HashSet<_>>().len() == a.len()
    }) {
        return Err("Campos repetidos inválidos.".into());
    }
    for field in fields {
        let v = &p[field];
        if list(&unavailable).contains(&json!(field)) {
            if !v.is_null() {
                return Err("Un campo no observado debe quedar vacío.".into());
            }
            continue;
        }
        match field.as_str() {
            "power_w" if !v.as_f64().is_some_and(|n| n.is_finite() && n >= 0.) => {
                return Err("Registra una potencia W finita y no negativa.".into());
            }
            "visible_people" if v.as_u64().is_none() => {
                return Err("Registra personas como entero no negativo.".into());
            }
            "action" if text(v).trim().is_empty() => {
                return Err("Describe la acción realmente realizada.".into());
            }
            _ => {}
        }
    }
    if fields.iter().any(|f| f == "visible_people") && text(&p["region"]).trim().is_empty() {
        return Err("Indica la región observada.".into());
    }
    for key in [
        "region",
        "notes",
        "missing_reason",
        "action",
        "observer",
        "instrument",
        "equipment",
    ] {
        if let Some(v) = p.get(key)
            && v.as_str().is_none_or(|s| s.chars().count() > 2000)
        {
            return Err(format!("{key}: texto de hasta 2000 caracteres.").into());
        }
    }
    Ok(())
}
pub fn validate_guided_start(p: &Value) -> Result<()> {
    if p.get("guided").is_some_and(|v| !v.is_boolean()) {
        return Err("guided debe ser booleano.".into());
    }
    if !truth(&p["guided"]) {
        return Ok(());
    }
    if checkpoints().get(text(&p["scenario_id"])).is_none()
        || !p["repetition"]
            .as_u64()
            .is_some_and(|n| (1..=3).contains(&n))
    {
        return Err("Selecciona escenario S1–S3 y repetición 1–3.".into());
    }
    validate_observation(
        &p["initial_observation"],
        &["power_w".into(), "visible_people".into()],
    )?;
    for key in ["observer", "instrument", "equipment"] {
        if text(&p["initial_observation"][key]).trim().is_empty() {
            return Err("Completa observador, vatímetro y equipos medidos.".into());
        }
    }
    Ok(())
}
