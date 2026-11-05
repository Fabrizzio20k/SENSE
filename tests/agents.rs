mod common;
use common::*;
use sense_people_counter::{
    agents::{self, Adapters},
    contracts::*,
    inference,
};
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};
fn snapshot() -> Snapshot {
    let mut c = sense_people_counter::context::ContextStore::new(config());
    let p = telemetry(wall_time());
    let env = sense_people_counter::acquisition::environment(&p, &utc_now(), "sensor_location");
    let radar = sense_people_counter::acquisition::presence(&p, &utc_now(), "rasp_shared_view");
    c.ingest(&env, Some(&radar), 0., wall_time(), None).unwrap();
    c.snapshot(0.)
}
fn adapter(content: String) -> Adapters {
    Adapters {
        capture: Arc::new(|| Ok((b"image".to_vec(), utc_now()))),
        detector: Arc::new(|_| Ok(2)),
        completion: Arc::new(move |_, _, _| Ok(json!({"content":content}))),
        model: "gemma".into(),
    }
}
fn valid() -> String {
    "1. La humedad aumentó.\n2. La ocupación podría contribuir, sin causalidad demostrada.\n3. Comparar lecturas y tiempos.".into()
}
#[test]
fn validates_facts_and_does_not_send_images_in_d() {
    let s = snapshot();
    let mut a = adapter(valid());
    let calls = Arc::new(Mutex::new(vec![]));
    let observed = calls.clone();
    a.completion = Arc::new(move |_, image, opts| {
        observed
            .lock()
            .unwrap()
            .push((image.is_some(), opts.clone()));
        Ok(json!({"content":valid(),"usage":{"completion_tokens":20}}))
    });
    let prompt = agents::prompt("Q6", &s);
    let r = a
        .interpret(
            &command("text"),
            &s,
            None,
            &config()["interpretation"]["textual"],
            &prompt,
        )
        .unwrap()
        .data;
    assert_eq!(r["validation_status"], "VALIDATED");
    assert_eq!(r["snapshot_id"], s.snapshot_id);
    assert!(!calls.lock().unwrap()[0].0);
    let options = calls.lock().unwrap()[0].1.clone();
    assert_eq!(options["temperature"], 0);
    assert_eq!(options["max_tokens"], 256);
    assert!(options.get("response_format").is_none());
    let payload = inference::request_payload("gemma", &prompt, None, &options);
    assert_eq!(payload["max_completion_tokens"], 256);
    assert!(payload.get("response_format").is_none());
    assert_eq!(r["summary"], valid());
    assert_eq!(r["inferences"], json!([valid()]));
    let id = &s.document["observations"]["temperature"]["observation_id"];
    assert!(list(&r["evidence_references"]).contains(id));
    assert!(!prompt.contains(text(id)));
    assert!(serde_json::from_str::<Value>(&prompt).is_ok());
}
#[test]
fn text_uses_snapshot_facts_not_model_measurements() {
    let s = snapshot();
    let r = adapter("1. Temperatura 99 según el modelo; no modifica mediciones.".into())
        .interpret(
            &command("text"),
            &s,
            None,
            &config()["interpretation"]["textual"],
            "prompt",
        )
        .unwrap()
        .data;
    assert_eq!(r["validation_status"], "VALIDATED");
    assert!(!list(&r["observed_facts"]).iter().any(|f| f["value"] == 99));
}
#[test]
fn rejects_duplicate_json_keys_in_legacy_parser() {
    assert!(agents::parse_json_object("{\"a\":1,\"a\":2}").is_err());
    assert!(agents::parse_json_object("{\"nested\":{\"a\":1,\"a\":2}}").is_err());
}
#[test]
fn rejects_empty_degenerate_structured_oversized_and_truncated_responses() {
    let s = snapshot();
    for content in [
        "".into(),
        " \n\t : ".into(),
        "{\"summary\":\"texto\"}".into(),
        "a".repeat(2001),
        "texto\u{0000}".into(),
    ] {
        let result = adapter(content)
            .interpret(
                &command("text"),
                &s,
                None,
                &config()["interpretation"]["textual"],
                "prompt",
            )
            .unwrap()
            .data;
        assert_eq!(result["validation_status"], "REJECTED");
        assert!(result.get("summary").is_none());
    }
    let mut a = adapter(valid());
    a.completion =
        Arc::new(|_, _, _| Ok(json!({"content":"Texto incompleto", "finish_reason":"length"})));
    assert_eq!(
        a.interpret(
            &command("text"),
            &s,
            None,
            &config()["interpretation"]["textual"],
            "prompt"
        )
        .unwrap()
        .data["validation_status"],
        "REJECTED"
    );
    let mut empty = s.clone();
    empty.document["observations"] = json!({});
    assert_eq!(
        adapter(valid())
            .interpret(
                &command("text"),
                &empty,
                None,
                &config()["interpretation"]["textual"],
                "prompt"
            )
            .unwrap()
            .data["validation_status"],
        "REJECTED"
    );
}
#[test]
fn multimodal_uses_authorized_image_without_sending_snapshot_ids() {
    let s = snapshot();
    let mut cmd = command("multimodal");
    cmd["parameters"]["image_id"] = json!("image-1");
    let prompt = agents::prompt("Q7", &s);
    let mut a = adapter(valid());
    a.completion = Arc::new(|prompt, image, options| {
        let evidence: Value = serde_json::from_str(prompt).unwrap();
        assert!(
            evidence["preguntas"][0]
                .as_str()
                .unwrap()
                .contains("imagen")
        );
        assert!(options.get("response_format").is_none());
        assert_eq!(options["temperature"], 0);
        assert_eq!(options["max_tokens"], 256);
        assert!(image.is_none_or(|bytes| bytes == b"image"));
        Ok(json!({"content":valid()}))
    });
    let r = a
        .interpret(
            &cmd,
            &s,
            Some(b"image"),
            &config()["interpretation"]["multimodal"],
            &prompt,
        )
        .unwrap()
        .data;
    assert_eq!(r["validation_status"], "VALIDATED");
    assert!(list(&r["evidence_references"]).contains(&json!("image-1")));
    assert!(!prompt.contains("image-1"));
    assert!(!prompt.contains(&s.snapshot_id));
    let system = agents::system_prompt("Q7").unwrap();
    assert!(system.contains("conteo YOLO"));
    assert!(system.contains("oclusiones"));
    assert!(system.contains("no demuestra ventilacion"));
    assert_eq!(
        a.interpret(
            &cmd,
            &s,
            None,
            &config()["interpretation"]["multimodal"],
            &prompt
        )
        .unwrap()
        .data["validation_status"],
        "REJECTED"
    );
}
#[test]
fn uses_completion_token_limit() {
    let p = inference::request_payload(
        "gemma",
        "prompt",
        None,
        &json!({"max_tokens":256,"response_format":{"type":"json_object"},"system_prompt":"system"}),
    );
    assert_eq!(p["max_completion_tokens"], 256);
    assert!(p.get("max_tokens").is_none());
    assert_eq!(
        p["messages"][0],
        json!({"role":"system","content":"system"})
    );
    assert_eq!(p["messages"][1]["content"], "prompt");
}
#[test]
fn keeps_multimodal_content_for_images() {
    let p = inference::request_payload(
        "gemma",
        "prompt",
        Some((b"image", "image/jpeg")),
        &json!({}),
    );
    assert_eq!(
        p["messages"][0]["content"][0],
        json!({"type":"text","text":"prompt"})
    );
    assert_eq!(p["messages"][0]["content"][1]["type"], "image_url");
    assert!(!inference::log_payload(&p).to_string().contains("base64"));
}
#[test]
fn vision_respects_image_memory_limit() {
    let a = adapter(valid());
    assert!(
        a.vision(&json!({"parameters":{"region":"camera"}}), 1)
            .is_err()
    );
    assert_eq!(
        a.vision(&json!({"parameters":{"region":"camera"}}), 1024)
            .unwrap()
            .data["count"],
        2
    );
}
#[test]
fn archived_python_config_hash_is_preserved() {
    let fixture: Value = serde_json::from_str(include_str!("fixtures/prompts.json")).unwrap();
    let mut current = config();
    let current_hash = current
        .as_object_mut()
        .unwrap()
        .remove("config_hash")
        .unwrap();
    assert_eq!(current_hash, hash(python_json(&current).as_bytes()));
    // La referencia Python usaba 512 MiB; el piloto actual permite 10 GiB.
    current["runtime"]["max_database_mb"] = json!(512);
    assert_eq!(
        hash(python_json(&current).as_bytes()),
        fixture["config_hash"]
    );
}

#[test]
fn evidence_includes_real_changes_latest_events_quality_and_explicit_people_count() {
    let mut s = snapshot();
    s.created_at = "2026-11-05T10:10:00Z".into();
    let now = sense_people_counter::context::timestamp(&json!(s.created_at)).unwrap();
    let obs = &mut s.document["observations"];
    obs["humidity"]["value"] = json!(82.);
    obs["humidity"]["captured_at"] = json!(s.created_at);
    obs["aqi"]["status"] = json!("ERROR");
    obs["aqi"]["value"] = json!(99);
    obs["count"] = json!({"value":7,"unit":"persons","status":"VALID","captured_at":utc_now(),"age_seconds":1});
    s.document["session_baseline"]["humidity"] =
        json!({"value":70.,"captured_epoch_s":now-600.,"id":"baseline-id"});
    s.document["component_health"] = json!({"ens160":{"status":"FAILED","reason":"INVALID_READING","since":"2026-11-05T10:00:00Z"}});
    s.document["environment_events"] = json!([
        {"event_id":"old-event","event_type":"HUMIDITY_RISE","field":"humidity","magnitude":5,"captured_at":"2026-11-05T10:09:30Z"},
        {"event_id":"latest-event","event_type":"HUMIDITY_RISE","field":"humidity","magnitude":12,"captured_at":"2026-11-05T10:09:50Z","reference":{"value":70,"captured_epoch_s":now-600.,"id":"reference-id"}}
    ]);
    for q in ["Q6", "Q7"] {
        let raw = agents::prompt(q, &s);
        let input: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(input["personas_visibles_en_una_captura"], 7);
        assert_eq!(input["presencia"]["fuente"], "radar");
        assert!(input["ENS160"]["AQI_actual"].is_null());
        assert_eq!(input["ENS160"]["estados"]["AQI"], "ERROR");
        assert_eq!(
            input["SHT40"]["cambios_desde_inicio"]["humedad_porcentaje"]["delta"],
            12.
        );
        assert_eq!(
            input["SHT40"]["cambios_desde_inicio"]["humedad_porcentaje"]["direccion"],
            "SUBE"
        );
        assert_eq!(
            input["SHT40"]["cambios_desde_inicio"]["humedad_porcentaje"]["intervalo_segundos"],
            600.
        );
        assert!(input["ENS160"]["cambios_desde_inicio"].get("AQI").is_none());
        assert_eq!(input["eventos"].as_array().unwrap().len(), 1);
        assert_eq!(input["eventos"][0]["antiguedad_segundos"], 10.);
        assert_eq!(input["ENS160"]["motivo"], "INVALID_READING");
        for id in [
            "baseline-id",
            "old-event",
            "latest-event",
            "reference-id",
            &s.snapshot_id,
        ] {
            assert!(!raw.contains(id));
        }
        assert_eq!(input["ENS160"]["antiguedad_estado_segundos"], 600.);
        assert_eq!(input["SHT40"]["estados"]["humedad_porcentaje"], "VALID");
        assert_eq!(input["preguntas"].as_array().unwrap().len(), 3);
        assert!(
            agents::system_prompt(q)
                .unwrap()
                .contains("tres preguntas numeradas")
        );
    }
}

#[test]
fn compact_prompt_has_a_size_budget_and_preserves_unknown_times() {
    let mut s = snapshot();
    s.document["observations"]["count"] =
        json!({"value":21,"unit":"persons","status":"VALID","age_seconds":1});
    s.document["component_health"] =
        json!({"ens160":{"status":"FAILED","reason":"INVALID_READING","since":"invalid"}});
    s.document["environment_events"] = json!([
        {"event_type":"HUMIDITY_RISE","field":"humidity","captured_at":"invalid"},
        {"event_type":"ECO2_THRESHOLD_CROSSED","field":"eco2","captured_at":"2999-01-01T00:00:00Z"}
    ]);
    s.document["session_baseline"]["humidity"]["captured_epoch_s"] = json!(1e15);
    for q in ["Q6", "Q7"] {
        let prompt = agents::prompt(q, &s);
        let system = agents::system_prompt(q).unwrap();
        // Presupuesto de bytes para evitar reintroducir metadatos repetidos; no estima tokens.
        assert!(
            prompt.len() + system.len() < 3500,
            "{q}: {} bytes",
            prompt.len() + system.len()
        );
        let input: Value = serde_json::from_str(&prompt).unwrap();
        assert!(input["eventos"][0]["antiguedad_segundos"].is_null());
        assert!(input["eventos"][1]["antiguedad_segundos"].is_null());
        assert_eq!(input["eventos"][0]["estado_actual"], "UNKNOWN");
        assert!(input["ENS160"]["antiguedad_estado_segundos"].is_null());
        assert!(
            input["SHT40"]["cambios_desde_inicio"]["humedad_porcentaje"]["intervalo_segundos"]
                .is_null()
        );
        assert_eq!(input["personas_visibles_en_una_captura"], 21);
    }
}

#[test]
fn interpretation_cache_changes_with_sensor_health_but_not_its_own_completion() {
    let mut s = snapshot();
    let key =
        |s: &Snapshot| sense_people_counter::policy::semantic_key("Q6", &s.document, "gemma", None);
    let before = key(&s);
    s.document["component_health"] = json!({"gemma":{"status":"HEALTHY"}});
    assert_eq!(key(&s), before);
    s.document["component_health"]["ens160"] =
        json!({"status":"FAILED","reason":"INVALID_READING","since":"first"});
    let failed = key(&s);
    assert_ne!(failed, before);
    s.document["component_health"]["ens160"]["since"] = json!("later");
    assert_eq!(key(&s), failed);
    s.document["component_health"]["ens160"]["status"] = json!("HEALTHY");
    assert_ne!(key(&s), failed);
}

#[test]
fn spanish_context_distinguishes_healthy_stable_from_missing_and_failed_evidence() {
    let mut s = snapshot();
    s.document["component_health"] =
        json!({"sht40":{"status":"HEALTHY"},"ens160":{"status":"HEALTHY"}});
    s.document["observations"]["count"] = json!({"value":21,"status":"VALID","age_seconds":1});
    let input: Value = serde_json::from_str(&agents::prompt("Q6", &s)).unwrap();
    assert_eq!(input["SHT40"]["salud"], "HEALTHY");
    assert_eq!(input["ENS160"]["salud"], "HEALTHY");
    assert_eq!(input["personas_visibles_en_una_captura"], 21);
    assert_eq!(
        input["SHT40"]["cambios_desde_inicio"]["humedad_porcentaje"]["delta"],
        0.
    );
    assert_eq!(
        input["ENS160"]["cambios_desde_inicio"]["eCO2_ppm_equivalente"]["delta"],
        0.
    );
    assert!(input["eventos"].as_array().unwrap().is_empty());
    assert!(input["ENS160"].get("motivo").is_none());

    s.document["observations"]["count"]["status"] = json!("STALE");
    s.document["observations"]["humidity"]["status"] = json!("UNAVAILABLE");
    s.document["component_health"] = json!({});
    let input: Value = serde_json::from_str(&agents::prompt("Q6", &s)).unwrap();
    assert!(input["personas_visibles_en_una_captura"].is_null());
    assert_eq!(input["estado_conteo"], "STALE");
    assert!(input["SHT40"]["humedad_porcentaje_actual"].is_null());
    assert_eq!(
        input["SHT40"]["estados"]["humedad_porcentaje"],
        "UNAVAILABLE"
    );
    assert!(
        input["SHT40"]["cambios_desde_inicio"]
            .get("humedad_porcentaje")
            .is_none()
    );
    assert_eq!(input["SHT40"]["salud"], "UNKNOWN");
}
