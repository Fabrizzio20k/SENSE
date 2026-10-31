mod common;
use common::*;
use sense_people_counter::{contracts::*, storage::ExperimentLog};
use serde_json::json;
use std::sync::{Arc, mpsc};
#[test]
fn e_keeps_monitoring_during_multimodal_and_late_result_is_historical() {
    let mut h = Harness::new();
    let (tx, rx) = mpsc::channel();
    let rx = std::sync::Mutex::new(rx);
    h.c.adapters.completion = Arc::new(move |_, _, _| {
        rx.lock().unwrap().recv()?;
        Ok(json!({"content":"invalid model output"}))
    });
    h.start("E");
    h.ingest(0., None);
    h.finish_vision();
    assert!(h.c.tasks.active["gemma"].is_some());
    assert_eq!(h.c.fsm, "WAIT");
    let original = h.c.context.observations["count"].clone();
    let mut p = telemetry(h.wall + 2.);
    p["environment"]["sht40"]["temperature_c"] = json!(29);
    h.ingest(2., Some(p));
    h.step(2.);
    assert_eq!(h.c.context.observations["temperature"]["value"], 29);
    assert_eq!(h.c.context.observations["count"], original);
    h.c.stop("USER_STOP", h.now + 3.).unwrap();
    assert!(h.c.tasks.busy());
    tx.send(()).unwrap();
    h.finish_lane("gemma", 4.);
    assert!(truth(&h.c.interpretations.back().unwrap()["historical"]));
    h.event("HISTORICAL_INTERPRETATION");
}
#[test]
fn unchanged_count_does_not_interpret_every_image() {
    let mut h = Harness::new();
    h.start("E");
    h.finish_vision();
    h.finish_lane("gemma", 1.);
    h.step(61.);
    assert!(h.c.tasks.active["vision"].is_none());
    assert_eq!(h.captures.lock().unwrap().len(), 1);
    assert_eq!(h.completions.lock().unwrap().len(), 1);
}
#[test]
fn new_run_resets_context_and_policy() {
    let mut h = Harness::new();
    h.start("B");
    h.ingest(0., None);
    h.step(0.);
    assert!(h.captures.lock().unwrap().is_empty());
    h.c.stop("USER_STOP", h.now + 1.).unwrap();
    h.start("C");
    assert_eq!(h.c.context.observations, json!({}));
    assert_eq!(h.c.policy.mode, "C");
}
#[test]
fn manual_presence_drives_c_and_auto_releases_it() {
    let mut h = Harness::new();
    h.start("C");
    h.c.set_presence(&json!(true), h.now, &json!(null)).unwrap();
    assert_eq!(
        h.c.view(h.now).unwrap()["presence_control"],
        json!({"mode":"MANUAL","detected":true,"near":null})
    );
    h.step(0.);
    assert_eq!(
        h.c.tasks.active["vision"].as_ref().unwrap().command["reason"],
        "COMPARABLE_PRESENCE_CHANGED"
    );
    h.c.set_presence(&json!(null), h.now + 1., &json!(null))
        .unwrap();
    assert_eq!(
        h.c.view(h.now + 1.).unwrap()["presence_control"]["mode"],
        "AUTO"
    );
    h.finish_lane("vision", 1.1);
}
#[test]
fn manual_presence_is_unavailable_in_a() {
    let mut h = Harness::new();
    h.start("A");
    assert!(h.c.set_presence(&json!(true), h.now, &json!(null)).is_err());
}
#[test]
fn vision_failure_degrades_without_stopping_sensors() {
    let mut h = Harness::new();
    h.c.adapters.detector = Arc::new(|_| Err("Cámara desconectada".into()));
    h.start("C");
    h.c.events.push(json!({"event_type":"TEMP_RISE"}));
    h.finish_vision();
    assert!(h.c.running());
    assert!(h.c.transitions.iter().any(|t| t["to"] == "DEGRADED"));
    h.ingest(1., None);
    assert_eq!(h.c.context.observations["temperature"]["value"], 26.33);
}
#[test]
fn textual_mode_d_gets_structured_snapshot_without_image() {
    let mut h = Harness::new();
    h.start("D");
    h.ingest(0., None);
    for kind in ["TEMP_RISE", "AQI_WORSENED"] {
        h.c.context.environment.events.push_back(json!({"event_id":identifier(),"event_type":kind,"magnitude":1,"captured_at":stamp(h.wall)}));
        h.c.events.push(json!({"event_type":kind}));
    }
    h.finish_vision();
    assert_eq!(
        h.c.tasks.active["gemma"].as_ref().unwrap().command["action"],
        "text"
    );
    h.finish_lane("gemma", 0.2);
    assert_eq!(*h.completions.lock().unwrap(), vec![None]);
}
#[test]
fn single_vision_per_cycle_even_with_conflict() {
    let mut h = Harness::new();
    h.start("C");
    let mut p = telemetry(h.wall);
    p["presence"]["state_code"] = json!(0);
    h.ingest(0., Some(p));
    h.c.events.push(json!({"event_type":"TEMP_RISE"}));
    h.finish_vision();
    assert_eq!(h.captures.lock().unwrap().len(), 1);
    assert_eq!(h.c.cycle["requests"], 1);
    assert_eq!(h.c.fsm, "WAIT");
}
#[test]
fn b_near_zone_command_is_linked_to_confirmed_evidence() {
    let mut h = Harness::new();
    h.start("B");
    for s in 0..3 {
        let mut p = telemetry(h.wall + s as f64);
        p["presence"]["static_distance_cm"] = json!(20);
        p["presence"]["motion_distance_cm"] = json!(300);
        p["presence"]["total_distance_cm"] = json!(5);
        h.ingest(s as f64, Some(p));
        h.step(s as f64);
        if s < 2 {
            assert!(h.c.tasks.active["vision"].is_none());
        }
    }
    let command = &h.c.tasks.active["vision"].as_ref().unwrap().command;
    assert_eq!(command["reason"], "RADAR_NEAR_CONFIRMED");
    let event = h.event("RADAR_NEAR_CONFIRMED");
    assert_eq!(
        command["parameters"]["trigger_event_id"],
        event["payload"]["event_id"]
    );
    assert_eq!(list(&event["payload"]["evidence_ids"]).len(), 3);
    h.finish_lane("vision", 2.1);
}
#[test]
fn trace_contains_config_snapshot_reason_and_transitions() {
    let mut h = Harness::new();
    h.start("C");
    h.step(0.);
    h.c.stop("USER_STOP", h.now + 1.).unwrap();
    let events = json!(h.events()).to_string();
    for required in [
        "config_hash",
        "FSM_TRANSITION",
        "NO_VISUAL_NEED",
        "snapshot_id",
        "RESULT_PUBLISHED",
        "RUN_FINISHED",
    ] {
        assert!(events.contains(required), "{required}");
    }
}
#[test]
fn human_truth_is_separate_and_restart_marks_interrupted() {
    let mut h = Harness::new();
    let run = h.start("B");
    h.c.log
        .human_record(
            text(&run["run_id"]),
            "GROUND_TRUTH",
            &json!({"count":5,"observed_at":utc_now()}),
        )
        .unwrap();
    assert_eq!(h.c.context.observations, json!({}));
    let log = ExperimentLog::new(&h.c.log.path).unwrap();
    assert_eq!(
        log.run(text(&run["run_id"])).unwrap().unwrap()["status"],
        "INTERRUPTED"
    );
}
