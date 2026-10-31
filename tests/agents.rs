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
    json!({"inferences":["Coincidencia contextual, sin causalidad demostrada."],"unknowns":[],"recommendations":[]}).to_string()
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
    assert!(
        agents::system_prompt("Q6")
            .unwrap()
            .contains("fuente=<presence_source>")
    );
    let id = &s.document["observations"]["temperature"]["observation_id"];
    assert!(list(&r["evidence_references"]).contains(id));
    assert!(!prompt.contains(text(id)));
    assert!(prompt.contains("<presence>"));
}
#[test]
fn text_uses_snapshot_facts_not_model_measurements() {
    let s = snapshot();
    let mut response: Value = serde_json::from_str(&valid()).unwrap();
    response["observed_facts"] = json!([{"evidence_id":"invented","value":99}]);
    let r = adapter(response.to_string())
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
fn rejects_duplicate_json_keys() {
    let s = snapshot();
    let r = adapter(
        "{\"inferences\":[],\"unknowns\":[],\"recommendations\":[],\"unknowns\":[]}".into(),
    )
    .interpret(
        &command("text"),
        &s,
        None,
        &config()["interpretation"]["textual"],
        "prompt",
    )
    .unwrap()
    .data;
    assert_eq!(r["validation_status"], "REJECTED");
    assert!(text(&r["validation_error"]).contains("Clave JSON duplicada"));
    assert!(agents::parse_json_object("{\"nested\":{\"a\":1,\"a\":2}}").is_err());
}
#[test]
fn multimodal_uses_authorized_image_without_sending_snapshot_ids() {
    let s = snapshot();
    let mut cmd = command("multimodal");
    cmd["parameters"]["image_id"] = json!("image-1");
    let prompt = agents::prompt("Q7", &s);
    let a = adapter(valid());
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
    assert!(agents::system_prompt("Q7").unwrap().contains("conteo YOLO"));
    assert_eq!(
        a.interpret(
            &cmd,
            &s,
            None,
            &config()["interpretation"]["multimodal"],
            "prompt"
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
fn prompts_and_config_hash_match_python_exactly() {
    let fixture: Value = serde_json::from_str(include_str!("fixtures/prompts.json")).unwrap();
    let d = fixture["snapshot"].clone();
    let s = Snapshot {
        snapshot_id: text(&d["snapshot_id"]).into(),
        created_at: text(&d["created_at"]).into(),
        document: d,
    };
    for q in ["Q6", "Q7"] {
        assert_eq!(
            agents::prompt(q, &s),
            fixture["prompts"][q].as_str().unwrap()
        );
        assert_eq!(
            agents::system_prompt(q).unwrap(),
            fixture["system"][q].as_str().unwrap()
        );
    }
    assert_eq!(config()["config_hash"], fixture["config_hash"]);
}
