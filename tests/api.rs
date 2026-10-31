mod common;
use common::*;
use sense_people_counter::{contracts::*, storage::ExperimentLog};
use serde_json::{Value, json};
use std::{
    io::{Cursor, Read},
    sync::atomic::Ordering,
};
#[tokio::test]
async fn start_contract_and_exclusive_sandbox() {
    let h = ApiHarness::new();
    let id = h.start("E").await;
    assert!(!id.is_empty());
    assert!(
        h.app
            .enqueue("capture", String::new())
            .unwrap_err()
            .to_string()
            .contains("Finaliza la medición")
    );
    assert_eq!(
        h.request("POST", "/api/experiments/start", json!({"mode":"C"}))
            .await
            .0,
        409
    );
}
#[tokio::test]
async fn invalid_inputs_do_not_start() {
    let h = ApiHarness::new();
    for body in [
        Value::Null,
        json!([]),
        json!({"mode":"G"}),
        json!({"mode":"C","scenario_id":[]}),
    ] {
        assert_eq!(
            h.request("POST", "/api/experiments/start", body).await.0,
            400
        );
    }
    assert_eq!(h.app.snapshot()["measurement"]["running"], false);
}
#[tokio::test]
async fn presence_control_requires_a_valid_mode() {
    let h = ApiHarness::new();
    h.start("B").await;
    for body in [
        json!({"mode":"manual","detected":true}),
        json!({"mode":"auto"}),
    ] {
        assert_eq!(
            h.request("POST", "/api/experiments/presence", body).await.0,
            202
        );
    }
    for body in [
        Value::Null,
        json!({"mode":"manual"}),
        json!({"mode":"manual","detected":1}),
        json!({"mode":"other"}),
        json!({"mode":"auto","near":true}),
    ] {
        assert_eq!(
            h.request("POST", "/api/experiments/presence", body).await.0,
            400
        );
    }
}
#[tokio::test]
async fn busy_manual_task_blocks_experiment() {
    let h = ApiHarness::new();
    h.app.state.lock().unwrap()["sandbox_busy"] = json!(true);
    assert_eq!(
        h.request("POST", "/api/experiments/start", json!({"mode":"A"}))
            .await
            .0,
        409
    );
    assert!(!h.app.get_service().unwrap().reserved.load(Ordering::SeqCst));
}
#[test]
fn mqtt_malformed_data_does_not_crash_callback() {
    let h = ApiHarness::new();
    for raw in [b"[]".as_slice(), b"{\"temperature\":NaN}", b"\xff", b"{"] {
        h.app.mqtt_message(raw);
    }
    h.app.mqtt_message(&vec![b'x'; 65537]);
    assert_eq!(h.app.snapshot()["telemetry"], json!({}));
    h.app
        .mqtt_message(telemetry(wall_time()).to_string().as_bytes());
    assert_eq!(
        h.app.snapshot()["telemetry"]["schema"],
        "rustio.iot.telemetry.v1"
    );
}
#[tokio::test]
async fn assets_and_preparation_still_exist() {
    let h = ApiHarness::new();
    let (status, _, bytes) = h.request("GET", "/", Value::Null).await;
    assert_eq!(status, 200);
    let html = String::from_utf8(bytes).unwrap();
    for expected in [
        "id=\"preparation\"",
        "id=\"take-photo\"",
        "id=\"measurement-mode\"",
        "id=\"measurement-pipeline\"",
    ] {
        assert!(html.contains(expected));
    }
    for asset in ["measurement.js", "measurement.css"] {
        assert_eq!(
            h.request("GET", &format!("/public/{asset}"), Value::Null)
                .await
                .0,
            200
        );
    }
}
#[tokio::test]
async fn offline_is_the_same_ui_and_does_not_start_services() {
    let h = ApiHarness::new();
    let live = h.request("GET", "/", Value::Null).await.2;
    let offline = h.request("GET", "/offline", Value::Null).await.2;
    assert_eq!(live, offline);
    let html = String::from_utf8(offline).unwrap();
    assert!(html.contains("id=\"replay-tab\""));
    assert!(html.contains("/public/offline.js"));
    for asset in [
        "api.js",
        "offline.js",
        "app.js",
        "replay.js",
        "replay-data.js",
        "replay.css",
    ] {
        assert_eq!(
            h.request("GET", &format!("/public/{asset}"), Value::Null)
                .await
                .0,
            200
        );
    }
    assert!(!h.temp.path().join("data").exists());
}
#[tokio::test]
async fn human_records_are_validated_and_separate() {
    let h = ApiHarness::new();
    let id = h.start("B").await;
    let path = format!("/api/experiments/{id}/human-records");
    let truth = json!({"observed_at":utc_now(),"region":"camera","visible_people":3});
    let energy = json!({"observed_at":utc_now(),"scope":"whole_run","value":2.4,"unit":"Wh"});
    assert_eq!(
        h.request(
            "POST",
            &path,
            json!({"kind":"GROUND_TRUTH","payload":truth})
        )
        .await
        .0,
        201
    );
    assert_eq!(
        h.request(
            "POST",
            &path,
            json!({"kind":"EXTERNAL_ENERGY","payload":energy})
        )
        .await
        .0,
        201
    );
    let mut invalid = truth;
    invalid["visible_people"] = json!(-1);
    assert_eq!(
        h.request(
            "POST",
            &path,
            json!({"kind":"GROUND_TRUTH","payload":invalid})
        )
        .await
        .0,
        400
    );
    let mut invalid = energy;
    invalid["unit"] = json!("CPU%");
    assert_eq!(
        h.request(
            "POST",
            &path,
            json!({"kind":"EXTERNAL_ENERGY","payload":invalid})
        )
        .await
        .0,
        400
    );
    let (_, body, _) = h
        .request("GET", &format!("/api/experiments/{id}"), Value::Null)
        .await;
    assert!(body["run"].get("visible_people").is_none());
}
#[tokio::test]
async fn invalid_measurement_config_does_not_block_preparation() {
    let h = ApiHarness::new();
    std::fs::write(h.temp.path().join("sense/pilot.yaml"), "invalid: config").unwrap();
    assert_eq!(
        h.request("POST", "/api/experiments/start", json!({"mode":"E"}))
            .await
            .0,
        409
    );
    assert_eq!(h.request("GET", "/", Value::Null).await.0, 200);
}
#[tokio::test]
async fn real_dispatcher_start_ingest_stop_and_export_without_hardware() {
    let h = ApiHarness::new();
    let id = h.start("B").await;
    h.app
        .mqtt_message(telemetry(wall_time()).to_string().as_bytes());
    assert_eq!(
        h.request(
            "POST",
            "/api/experiments/query",
            json!({"question_id":"Q3"})
        )
        .await
        .0,
        202
    );
    assert_eq!(
        h.request("POST", "/api/experiments/stop", json!({}))
            .await
            .0,
        202
    );
    let (status, _, bytes) = h
        .request("GET", &format!("/api/experiments/{id}/export"), Value::Null)
        .await;
    assert_eq!(status, 200);
    let text = String::from_utf8(bytes).unwrap();
    assert!(text.contains("OBSERVATIONS_RECEIVED"));
    assert!(text.contains("RUN_FINISHED"));
    assert_eq!(
        h.request("GET", &format!("/api/experiments/{id}"), Value::Null)
            .await
            .1["run"]["status"],
        "COMPLETED"
    );
}
#[tokio::test]
async fn new_api_exports_live_and_resolves_after_stop() {
    let h = ApiHarness::new();
    let id = h.start("B").await;
    let path = format!("/api/experiments/{id}");
    let (status, _, bytes) = h
        .request("GET", &format!("{path}/export?format=csv"), Value::Null)
        .await;
    assert_eq!(status, 200);
    let mut zip = zip::ZipArchive::new(Cursor::new(bytes)).unwrap();
    let mut metadata = String::new();
    zip.by_name("metadata.json")
        .unwrap()
        .read_to_string(&mut metadata)
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&metadata).unwrap()["status"],
        "RUNNING"
    );
    assert_eq!(
        h.request("POST", &format!("{path}/observer-requests"), json!({}))
            .await
            .0,
        201
    );
    h.request("POST", "/api/experiments/stop", json!({})).await;
    let (_, details, _) = h.request("GET", &path, Value::Null).await;
    let request = text(&details["observer_requests"][0]["request_id"]);
    let mut p = initial();
    p["action"] = json!("Fin anticipado");
    let (status, body, _) = h
        .request("POST", &format!("{path}/observer-requests/{request}"), p)
        .await;
    assert_eq!(status, 201, "{body}");
    assert_eq!(
        body["observer_previous"],
        json!({"power_w":0,"visible_people":0})
    );
    let power = json!({"kind":"EXTERNAL_POWER","payload":{"observed_at":utc_now(),"value":10,"unit":"W","scope":"whole_run"}});
    assert_eq!(
        h.request("POST", &format!("{path}/human-records"), power)
            .await
            .0,
        201
    );
}
#[tokio::test]
async fn fault_api_rejects_other_modes_and_invalid_controls() {
    let h = ApiHarness::new();
    h.start("E").await;
    let control = json!({"action":"availability","component":"sht40","enabled":false});
    assert_eq!(
        h.request("POST", "/api/experiments/faults", control.clone())
            .await
            .0,
        409
    );
    h.request("POST", "/api/experiments/stop", json!({})).await;
    let service = h.app.get_service().unwrap();
    for _ in 0..100 {
        if !service.reserved.load(Ordering::SeqCst) {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    }
    h.start("F").await;
    assert_eq!(
        h.request("POST", "/api/experiments/faults", control)
            .await
            .0,
        202
    );
    for bad in [
        Value::Null,
        json!([]),
        json!({"action":"availability","component":"sht40","enabled":0}),
        json!({"action":"availability","component":"cpu","enabled":false}),
        json!({"action":"timeout","lane":"other"}),
    ] {
        assert_eq!(
            h.request("POST", "/api/experiments/faults", bad).await.0,
            400
        );
    }
}
#[tokio::test]
async fn request_limits_cursors_and_missing_runs() {
    let h = ApiHarness::new();
    let id = h.start("B").await;
    assert_eq!(
        h.request(
            "GET",
            &format!("/api/experiments/{id}?after=bad"),
            Value::Null
        )
        .await
        .0,
        400
    );
    assert_eq!(
        h.request("GET", "/api/experiments/missing", Value::Null)
            .await
            .0,
        404
    );
    let log = ExperimentLog::reader(&h.app.get_service().unwrap().path).unwrap();
    assert!(log.run(&id).unwrap().is_some());
    use tower::ServiceExt;
    let req = axum::http::Request::builder()
        .method("POST")
        .uri("/api/chat")
        .body(axum::body::Body::from(vec![b'a'; 65537]))
        .unwrap();
    let r = sense_people_counter::api::router(h.app.clone())
        .oneshot(req)
        .await
        .unwrap();
    assert_eq!(r.status(), 413);
}
#[tokio::test]
async fn sandbox_and_sse_contract_without_hardware() {
    use tokio_stream::StreamExt;
    use tower::ServiceExt;
    let h = ApiHarness::new();
    for phase in ["yolo", "text", "vision"] {
        h.app.set_phase(phase, "ready", "fixture");
    }
    for operation in ["capture", "yolo", "chat", "vision"] {
        let (status, body, _) = h
            .request(
                "POST",
                &format!("/api/{operation}"),
                json!({"question":"Pregunta de prueba"}),
            )
            .await;
        assert_eq!(status, 202, "{body}");
        for _ in 0..200 {
            if !truth(&h.app.state.lock().unwrap()["sandbox_busy"]) {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(1)).await;
        }
        assert_eq!(
            h.app.state.lock().unwrap()["tasks"][operation]["status"],
            "ready"
        );
    }
    assert_eq!(
        h.request("GET", "/api/capture", Value::Null).await.2,
        b"image"
    );
    assert!(text(&h.app.state.lock().unwrap()["tasks"]["yolo"]["detail"]).starts_with("2 persona"));
    let request = axum::http::Request::builder()
        .uri("/events")
        .body(axum::body::Body::empty())
        .unwrap();
    let response = sense_people_counter::api::router(h.app.clone())
        .oneshot(request)
        .await
        .unwrap();
    assert_eq!(response.headers()["content-type"], "text/event-stream");
    let bytes = response
        .into_body()
        .into_data_stream()
        .next()
        .await
        .unwrap()
        .unwrap();
    let data = std::str::from_utf8(&bytes)
        .unwrap()
        .trim()
        .strip_prefix("data:")
        .unwrap()
        .trim();
    let snapshot: Value = serde_json::from_str(data).unwrap();
    assert_eq!(snapshot["sandbox"]["ready"], true);
    assert_eq!(snapshot["has_capture"], true);
    assert_eq!(snapshot["measurement"]["running"], false);
    assert!(!h.temp.path().join("data").exists());
    assert_eq!(
        h.request("GET", "/api/experiments/start", Value::Null)
            .await
            .0,
        405
    );
    let request = axum::http::Request::builder()
        .method("POST")
        .uri("/api/experiments/start")
        .header("content-type", "text/plain")
        .body(axum::body::Body::from("{\"mode\":\"B\"}"))
        .unwrap();
    let response = sense_people_counter::api::router(h.app.clone())
        .oneshot(request)
        .await
        .unwrap();
    assert_eq!(response.status(), 400);
}
