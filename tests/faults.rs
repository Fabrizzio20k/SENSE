mod common;
use common::*;
use sense_people_counter::{
    contracts::*,
    runtime::{RemoteExecutionUncertain, TaskOutput},
    service::ExperimentService,
    storage::ExperimentLog,
    trace::export_csv_zip,
};
use serde_json::{Value, json};
use std::{
    io::Read,
    sync::{Arc, mpsc},
};
fn harness() -> Harness {
    let mut h = Harness::new();
    h.c.config["vision"]["timeout_seconds"] = json!(2);
    h.c.config["vision"]["cooldown_seconds"] = json!(1);
    for kind in ["textual", "multimodal"] {
        h.c.config["interpretation"][kind]["timeout_seconds"] = json!(2);
        h.c.config["interpretation"][kind]["cooldown_seconds"] = json!(1);
    }
    h
}
fn fault(h: &Harness) -> Value {
    h.c.faults
        .records
        .as_object()
        .unwrap()
        .values()
        .next()
        .unwrap()
        .clone()
}
#[test]
fn f_reuses_e_policy_and_includes_multimodal() {
    let mut h = harness();
    let r = h.start("F");
    h.ingest(0., None);
    h.finish_vision();
    assert_eq!(r["policy_mode"], "E");
    assert_eq!(
        h.c.tasks.active["gemma"].as_ref().unwrap().command["parameters"]["question_id"],
        "Q7"
    );
    h.finish_lane("gemma", 0.2);
    assert_eq!(h.c.answers["Q7"]["status"], "INTERPRETED");
    assert_eq!(h.captures.lock().unwrap().len(), 1);
    assert_eq!(h.completions.lock().unwrap().len(), 1);
}
#[test]
fn sensor_blackout_retains_age_then_detects_and_recovers_on_new_data() {
    let mut h = harness();
    h.disable_models();
    h.start("F");
    h.ingest(0., None);
    h.step(0.);
    let original = h.c.context.observations["temperature"].clone();
    h.fault("sht40", false, 1.);
    for s in 1..12 {
        let mut p = telemetry(h.wall + s as f64);
        p["environment"]["sht40"]["temperature_c"] = json!(30);
        h.ingest(s as f64, Some(p));
        h.step(s as f64);
    }
    let s = h.c.context.snapshot(h.now + 11.).document;
    assert_eq!(
        s["observations"]["temperature"]["observation_id"],
        original["observation_id"]
    );
    assert_eq!(s["observations"]["temperature"]["status"], "STALE");
    assert_eq!(s["observations"]["aqi"]["status"], "VALID");
    assert!(number(&fault(&h)["detection_latency_s"]) > 0.);
    h.fault("sht40", true, 12.);
    h.step(12.);
    assert!(fault(&h)["recovered_at"].is_null());
    h.ingest(13., None);
    h.step(13.);
    assert_eq!(h.c.health.components["sht40"]["status"], "HEALTHY");
    assert!(!fault(&h)["recovered_at"].is_null());
    assert_eq!(fault(&h)["recovery_latency_s"], 1.0);
    let file = export_csv_zip(&h.c.log.path, text(&h.c.run["run_id"])).unwrap();
    let mut zip = zip::ZipArchive::new(file).unwrap();
    let mut csv = String::new();
    zip.by_name("faults.csv")
        .unwrap()
        .read_to_string(&mut csv)
        .unwrap();
    assert!(csv.contains(text(&fault(&h)["fault_id"])));
}
#[test]
fn manual_radar_does_not_hide_physical_source_loss() {
    let mut h = harness();
    h.disable_models();
    h.guided("F", "S1", 1);
    h.ingest(0., None);
    h.step(0.);
    h.fault("radar", false, 1.);
    h.c.set_presence(&json!(true), h.now + 1., &Value::Null)
        .unwrap();
    for s in 2..9 {
        let mut p = telemetry(h.wall + s as f64);
        p["presence"]["state_code"] = json!(0);
        h.ingest(s as f64, Some(p));
        h.step(s as f64);
    }
    let s = h.c.context.snapshot(h.now + 8.).document;
    assert_eq!(s["observations"]["presence"]["status"], "VALID");
    assert_eq!(
        s["observations"]["presence"]["source_agent"],
        "OperatorControl"
    );
    assert_eq!(h.c.health.components["radar"]["status"], "STALE");
    h.c.set_presence(&Value::Null, h.now + 9., &Value::Null)
        .unwrap();
    assert_eq!(
        h.c.context.snapshot(h.now + 9.).document["observations"]["presence"]["status"],
        "STALE"
    );
}
#[test]
fn held_manual_presence_is_sampled_without_changes_and_auto_restores_real_age() {
    for mode in ["B", "C", "D", "E", "F"] {
        for detected in [false, true] {
            let mut h = harness();
            h.disable_models();
            h.start(mode);
            h.ingest(0., None);
            h.c.set_presence(&json!(detected), h.now, &Value::Null)
                .unwrap();
            let initial = h.c.context.observations["presence"].clone();
            let raw = h.c.last_raw_presence.clone();
            let changes = |h: &Harness| {
                h.events()
                    .iter()
                    .filter(|e| {
                        [
                            "PRESENCE_CHANGED",
                            "SENSOR_PRESENCE_CHANGED",
                            "RADAR_ZONE_ENTERED",
                            "RADAR_ZONE_EXITED",
                        ]
                        .contains(&text(&e["type"]))
                    })
                    .count()
            };
            let initial_changes = changes(&h);
            for second in 0..=101 {
                h.step(second as f64);
                let view = h.c.view(h.now + second as f64 + 0.5).unwrap();
                let presence = &view["context"]["observations"]["presence"];
                assert_eq!(presence["value"], i32::from(detected));
                assert_eq!(presence["age_seconds"], 0.5);
                assert_eq!(presence["source_agent"], "OperatorControl");
                assert_eq!(presence["metadata"]["source_kind"], "MANUAL_CONTROL");
            }
            assert_eq!(changes(&h), initial_changes);
            assert!(h.captures.lock().unwrap().is_empty());
            assert!(h.completions.lock().unwrap().is_empty());
            assert_eq!(h.c.last_raw_presence, raw);
            let view = h.c.view(h.now + 101.5).unwrap();
            assert!(number(&view["raw_presence"]["age_seconds"]) >= 101.);
            assert_eq!(view["raw_presence"]["status"], "STALE");
            assert_eq!(h.c.health.components["radar"]["status"], "STALE");
            let held = &h.c.context.observations["presence"];
            assert_ne!(held["observation_id"], initial["observation_id"]);
            assert_eq!(held["metadata"]["control_set_at"], initial["captured_at"]);
            assert_eq!(held["metadata"]["sample_kind"], "HELD_MANUAL_CONTROL");
            assert!(held["metadata"].get("trigger_distance_cm").is_none());
            let from = sense_people_counter::context::timestamp(&initial["captured_at"]).unwrap();
            let to = sense_people_counter::context::timestamp(&held["captured_at"]).unwrap();
            assert!((to - from - 101.).abs() < 0.001);
            let samples = h
                .events()
                .iter()
                .filter(|e| e["type"] == "PRESENCE_CONTROL_SAMPLED")
                .count();
            assert_eq!(samples, 101);

            h.c.set_presence(&Value::Null, h.now + 102., &Value::Null)
                .unwrap();
            h.step(102.);
            let restored =
                h.c.view(h.now + 102.).unwrap()["context"]["observations"]["presence"].clone();
            assert_eq!(restored["observation_id"], raw["observation_id"]);
            assert_eq!(restored["status"], "STALE");
            assert!(number(&restored["age_seconds"]) >= 102.);
            assert_eq!(
                h.events()
                    .iter()
                    .filter(|e| e["type"] == "PRESENCE_CONTROL_SAMPLED")
                    .count(),
                samples
            );

            h.c.set_presence(&json!(detected), h.now + 103., &Value::Null)
                .unwrap();
            h.c.stop("USER_STOP", h.now + 103.).unwrap();
            let stopped = h.c.context.observations["presence"].clone();
            h.step(104.);
            assert_eq!(h.c.context.observations["presence"], stopped);
        }
    }
}
#[test]
fn manual_b_triggers_zone_changes_without_centimeters_or_fake_samples() {
    let mut h = harness();
    h.guided("B", "S1", 1);
    h.c.set_presence(&json!(true), h.now, &Value::Null).unwrap();
    h.step(0.);
    assert_eq!(
        h.c.tasks.active["vision"].as_ref().unwrap().command["reason"],
        "RADAR_NEAR_CONFIRMED"
    );
    assert!(
        h.c.context.observations["presence"]["metadata"]
            .get("trigger_distance_cm")
            .is_none()
    );
    assert_eq!(
        h.c.view(h.now).unwrap()["reactive_trigger"]["required_samples"],
        1
    );
    assert!(
        h.event("RADAR_NEAR_CONFIRMED")["payload"]
            .get("source")
            .is_none()
    );
    h.finish_lane("vision", 0.1);
    h.c.set_presence(&json!(false), h.now + 31., &Value::Null)
        .unwrap();
    h.step(31.);
    assert_eq!(
        h.c.tasks.active["vision"].as_ref().unwrap().command["reason"],
        "RADAR_ZONE_EXITED"
    );
    h.finish_lane("vision", 31.1);
    h.c.set_presence(&json!(true), h.now + 31.2, &Value::Null)
        .unwrap();
    assert_eq!(
        h.c.policy.reactive_pending["event_type"],
        "RADAR_ZONE_ENTERED"
    );
    h.c.set_presence(&Value::Null, h.now + 32., &Value::Null)
        .unwrap();
    assert_eq!(
        h.c.view(h.now + 32.).unwrap()["reactive_trigger"]["state"],
        "UNKNOWN"
    );
}
#[test]
fn switching_to_manual_preserves_presence_without_requesting_an_observation() {
    for mode in ["B", "C", "D", "E", "F"] {
        for detected in [false, true] {
            let mut h = harness();
            h.disable_models();
            let run = h.guided(mode, "S1", 1);
            for second in 0..3 {
                let mut p = telemetry(h.wall + second as f64);
                p["presence"]["state_code"] = json!(if detected { 2 } else { 0 });
                p["presence"]["static_distance_cm"] = json!(20);
                h.ingest(second as f64, Some(p));
            }
            let requests =
                h.c.log
                    .observer_requests(text(&run["run_id"]), false)
                    .unwrap();
            let changes = h.events().len();
            let near = if mode == "B" {
                json!(detected)
            } else {
                Value::Null
            };
            for second in 3..5 {
                h.c.set_presence(&json!(detected), h.now + second as f64, &near)
                    .unwrap();
                assert_eq!(h.c.manual_presence, Some(detected));
                assert_eq!(
                    h.c.context.observations["presence"]["value"],
                    i32::from(detected)
                );
                assert_eq!(h.events().len(), changes, "{mode}, detected={detected}");
                assert_eq!(
                    h.c.log
                        .observer_requests(text(&run["run_id"]), false)
                        .unwrap(),
                    requests
                );
            }
            h.c.set_presence(&json!(!detected), h.now + 5., &Value::Null)
                .unwrap();
            assert_eq!(
                h.event("SENSOR_PRESENCE_CHANGED")["payload"]["detected"],
                !detected
            );
            h.event("PRESENCE_CHANGED");
            assert_eq!(
                h.c.log
                    .observer_requests(text(&run["run_id"]), false)
                    .unwrap()
                    .len(),
                requests.len() + 1
            );
            h.c.set_presence(&json!(detected), h.now + 6., &near)
                .unwrap();
            let changes = h.events().len();
            h.c.set_presence(&Value::Null, h.now + 7., &Value::Null)
                .unwrap();
            assert_eq!(h.events().len(), changes);
            assert_eq!(h.c.manual_presence, None);
        }
    }
}
#[test]
fn manual_zone_change_is_recorded_even_when_presence_stays_detected() {
    let mut h = harness();
    h.disable_models();
    let run = h.guided("B", "S1", 1);
    let mut p = telemetry(h.wall);
    p["presence"]["static_distance_cm"] = json!(300);
    h.ingest(0., Some(p));
    h.c.set_presence(&json!(true), h.now + 1., &json!(false))
        .unwrap();
    assert!(
        !h.events()
            .iter()
            .any(|e| e["type"] == "SENSOR_PRESENCE_CHANGED")
    );
    let requests =
        h.c.log
            .observer_requests(text(&run["run_id"]), false)
            .unwrap()
            .len();
    h.c.set_presence(&json!(true), h.now + 2., &json!(true))
        .unwrap();
    assert_eq!(h.event("SENSOR_PRESENCE_CHANGED")["payload"]["near"], true);
    h.event("RADAR_ZONE_ENTERED");
    assert_eq!(
        h.c.log
            .observer_requests(text(&run["run_id"]), false)
            .unwrap()
            .len(),
        requests + 1
    );
    assert!(!h.events().iter().any(|e| e["type"] == "PRESENCE_CHANGED"));
}
#[test]
fn manual_controls_available_b_through_f_but_not_a_or_as_ground_truth() {
    let mut h = harness();
    for mode in ["B", "C", "D", "E", "F"] {
        let r = h.guided(mode, "S1", 1);
        h.c.set_presence(&json!(true), h.now, &Value::Null).unwrap();
        assert_eq!(
            h.c.context.observations["presence"]["source_agent"],
            "OperatorControl"
        );
        assert!(
            h.c.log
                .observer_requests(text(&r["run_id"]), false)
                .unwrap()
                .iter()
                .any(|r| r["reason"] == "SENSOR_PRESENCE_CHANGED")
        );
        let event = h.event("SENSOR_PRESENCE_CHANGED");
        assert_eq!(event["payload"]["detected"], true);
        assert!(event["payload"].get("mode").is_none());
        assert!(
            h.events()
                .iter()
                .all(|e| !text(&e["type"]).starts_with("MANUAL_"))
        );
        assert!(
            h.event("PRESENCE_CHANGED")["payload"]
                .get("source")
                .is_none()
        );
        h.c.stop("USER_STOP", h.now + 0.1).unwrap();
    }
    h.start("A");
    assert!(h.c.set_presence(&json!(true), h.now, &Value::Null).is_err());
}
#[test]
fn same_value_with_manual_origin_invalidates_prior_inference_context() {
    let mut h = harness();
    h.start("F");
    h.ingest(0., None);
    let raw = h.c.context.snapshot(h.now).document;
    h.c.set_presence(&json!(true), h.now, &Value::Null).unwrap();
    let manual = h.c.context.snapshot(h.now).document;
    assert_eq!(
        raw["observations"]["presence"]["value"],
        manual["observations"]["presence"]["value"]
    );
    assert_ne!(
        sense_people_counter::policy::semantic_key("Q6", &raw, "test", None),
        sense_people_counter::policy::semantic_key("Q6", &manual, "test", None)
    );
}
#[test]
fn camera_failure_uses_common_degraded_path_and_bounded_probe() {
    let mut h = harness();
    h.start("F");
    h.ingest(0., None);
    h.fault("camera", false, 0.);
    h.step(0.);
    h.step(0.1);
    assert!(h.captures.lock().unwrap().is_empty());
    assert_eq!(h.c.health.components["camera"]["status"], "FAILED");
    assert_eq!(h.c.fsm, "WAIT");
    h.step(0.5);
    assert_eq!(h.c.tasks.counters["accepted"], 1);
    h.fault("camera", true, 0.6);
    h.step(1.2);
    h.finish_lane("vision", 1.3);
    assert_eq!(h.captures.lock().unwrap().len(), 1);
    assert_eq!(h.c.health.components["camera"]["status"], "HEALTHY");
    assert!(!fault(&h)["recovered_at"].is_null());
    h.finish_lane("gemma", 1.4);
}
#[test]
fn simulated_gemma_timeout_never_executes_model_and_allows_verified_recovery() {
    let mut h = harness();
    h.start("F");
    h.ingest(0., None);
    h.c.set_fault(&json!({"action":"timeout","lane":"gemma"}), h.now)
        .unwrap();
    h.finish_vision();
    assert!(h.completions.lock().unwrap().is_empty());
    assert!(
        h.c.tasks.active["gemma"]
            .as_ref()
            .unwrap()
            .simulation
            .is_some()
    );
    h.step(2.2);
    assert!(h.c.tasks.quarantined.is_empty());
    assert!(h.c.tasks.active["gemma"].is_none());
    assert_eq!(h.c.health.components["gemma"]["status"], "FAILED");
    h.c.query("Q7", h.now + 3.3).unwrap();
    h.step(3.3);
    h.finish_lane("gemma", 3.4);
    assert_eq!(h.completions.lock().unwrap().len(), 1);
    assert_eq!(h.c.health.components["gemma"]["status"], "HEALTHY");
    assert!(!fault(&h)["recovered_at"].is_null());
    let file = export_csv_zip(&h.c.log.path, text(&h.c.run["run_id"])).unwrap();
    let mut zip = zip::ZipArchive::new(file).unwrap();
    let mut csv = String::new();
    zip.by_name("inference_tasks.csv")
        .unwrap()
        .read_to_string(&mut csv)
        .unwrap();
    let mut rdr = csv::Reader::from_reader(csv.trim_start_matches('\u{feff}').as_bytes());
    let fields = rdr.headers().unwrap().clone();
    let records: Vec<_> = rdr.records().map(|r| r.unwrap()).collect();
    let index = |k: &str| fields.iter().position(|v| v == k).unwrap();
    let r = records
        .iter()
        .find(|r| !r[index("fault_id")].is_empty())
        .unwrap();
    assert_eq!(&r[index("simulated")], "True");
    assert_eq!(&r[index("model_executed")], "False");
    assert_eq!(&r[index("timed_out")], "True");
}
#[test]
fn simulated_vision_timeout_and_stop_release_without_background_threads() {
    let mut h = harness();
    h.start("F");
    h.c.set_fault(&json!({"action":"timeout","lane":"vision"}), h.now)
        .unwrap();
    h.step(0.);
    h.step(2.1);
    assert!(h.captures.lock().unwrap().is_empty());
    assert!(h.c.tasks.active["vision"].is_none());
    assert_eq!(h.c.tasks.counters["timed_out"], 1);
    h.c.stop("USER_STOP", h.now + 2.2).unwrap();
    h.start("F");
    h.c.set_fault(&json!({"action":"timeout","lane":"vision"}), h.now)
        .unwrap();
    h.step(0.);
    h.c.stop("USER_STOP", h.now + 0.1).unwrap();
    h.step(0.2);
    assert!(!h.c.tasks.busy());
}
#[test]
fn real_remote_timeout_still_quarantines_runtime_in_f() {
    let mut h = harness();
    h.c.adapters.completion =
        Arc::new(|_, _, _| Err(RemoteExecutionUncertain("real uncertainty".into()).into()));
    h.start("F");
    h.ingest(0., None);
    h.finish_vision();
    h.finish_lane("gemma", 0.2);
    assert!(h.c.tasks.quarantined.contains_key("gemma"));
    assert!(
        h.c.set_fault(&json!({"action":"timeout","lane":"gemma"}), h.now + 1.)
            .is_err()
    );
}
#[test]
fn all_scenarios_three_repetitions_and_six_modes_keep_distinct_runs() {
    let mut h = harness();
    let mut ids = std::collections::HashSet::new();
    for mode in ["A", "B", "C", "D", "E", "F"] {
        for scenario in ["S1", "S2", "S3"] {
            for repetition in 1..=3 {
                let run = h.guided(mode, scenario, repetition);
                let id = text(&run["run_id"]);
                ids.insert(id.to_owned());
                h.c.stop("USER_STOP", h.now + 0.1).unwrap();
                let saved = h.c.log.run(id).unwrap().unwrap();
                assert_eq!(saved["mode"], mode);
                assert_eq!(saved["scenario_id"], scenario);
                assert_eq!(saved["repetition"], repetition);
            }
        }
    }
    assert_eq!(ids.len(), 54);
}
#[test]
fn fault_controller_rejects_other_modes_and_invalid_controls() {
    let mut h = harness();
    h.start("E");
    assert!(
        h.c.set_fault(
            &json!({"action":"availability","component":"sht40","enabled":false}),
            h.now
        )
        .is_err()
    );
    h.c.stop("USER_STOP", h.now + 0.1).unwrap();
    h.start("F");
    for bad in [
        json!({"action":"availability","component":"cpu","enabled":false}),
        json!({"action":"availability","component":"sht40","enabled":0}),
        json!({"action":"timeout","lane":"other"}),
        json!({"action":"other"}),
    ] {
        assert!(h.c.set_fault(&bad, h.now).is_err());
    }
    let mut p = telemetry(h.wall);
    p["timestamp"] = Value::Null;
    h.ingest(0., Some(p));
    assert!(h.c.running());
}
#[test]
fn brief_recovered_blackout_is_not_detected_retroactively() {
    let mut h = harness();
    h.disable_models();
    h.start("F");
    h.ingest(0., None);
    h.step(0.);
    h.fault("sht40", false, 1.);
    h.fault("sht40", true, 2.);
    h.ingest(3., None);
    h.step(3.);
    assert!(!fault(&h)["recovered_at"].is_null());
    assert!(fault(&h)["detected_at"].is_null());
    h.step(20.);
    assert!(fault(&h)["detected_at"].is_null());
}
#[test]
fn timeout_expiring_in_queue_is_reported_as_not_executed() {
    let mut h = harness();
    h.disable_models();
    h.start("F");
    let (tx, rx) = mpsc::channel();
    let mut first = command("text");
    first["experiment_run_id"] = h.c.run["run_id"].clone();
    h.c.tasks.submit(
        "gemma",
        first.clone(),
        Box::new(move || {
            rx.recv()?;
            Ok(TaskOutput::from(json!({})))
        }),
        "blocker".into(),
        h.now,
        100.,
        None,
    );
    h.c.set_fault(&json!({"action":"timeout","lane":"gemma"}), h.now)
        .unwrap();
    let f = h.c.faults.task_fault("gemma").unwrap();
    let mut second = first;
    second["command_id"] = json!(identifier());
    second["parameters"]["fault_id"] = f["fault_id"].clone();
    h.c.tasks.submit(
        "gemma",
        second.clone(),
        Box::new(|| panic!("simulation ran")),
        "simulated".into(),
        h.now,
        1.,
        Some(f.clone()),
    );
    h.c.faults.accepted(Some(&f), &second, h.now);
    h.step(2.);
    assert!(h.c.faults.timeouts.is_empty());
    assert_eq!(fault(&h)["not_executed_reason"], "QUEUE_DEADLINE");
    assert!(fault(&h)["detected_at"].is_null());
    tx.send(()).unwrap();
    h.finish_lane("gemma", 2.1);
}
#[test]
fn preexisting_failure_does_not_claim_a_detection_latency() {
    let mut h = harness();
    h.disable_models();
    h.start("F");
    h.step(12.);
    h.fault("sht40", false, 13.);
    h.step(13.);
    assert!(truth(&fault(&h)["preexisting_failure"]));
    assert!(fault(&h)["detection_latency_s"].is_null());
}
#[test]
fn f_collects_1800_samples_and_stops_with_faults_without_browser() {
    let mut h = harness();
    h.disable_models();
    let run = h.guided("F", "S3", 3);
    for c in ["sht40", "ens160", "radar"] {
        h.fault(c, false, 0.);
    }
    for s in 0..=1800 {
        h.step(s as f64);
    }
    assert!(!h.c.running());
    let q = h.c.log.quality(text(&run["run_id"])).unwrap();
    assert_eq!(q["samples"], 1800);
    assert_eq!(q["missing_samples"], 0);
    assert!(h.c.faults.disabled.is_empty());
    assert!(h.captures.lock().unwrap().is_empty());
}
#[test]
fn control_storage_failure_stops_collection_instead_of_running_unlogged() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    std::fs::create_dir(root.join("sense")).unwrap();
    let mut cfg = config();
    cfg["runtime"]["min_available_mb"] = json!(1);
    cfg["runtime"]["max_cpu_percent"] = json!(101);
    cfg["runtime"]["tick_seconds"] = json!(0.01);
    std::fs::write(
        root.join("sense/pilot.yaml"),
        serde_yaml_ng::to_string(&cfg).unwrap(),
    )
    .unwrap();
    let adapters = Harness::new().c.adapters.clone();
    let service = ExperimentService::new(
        root,
        &root.join("data"),
        &root.join("sense/pilot.yaml"),
        adapters,
        Arc::new(|| json!({"yolo":"error","text":"error","vision":"error"})),
    )
    .unwrap();
    service.reserve().unwrap();
    let run = service.call("start", json!({"mode":"F"})).unwrap();
    let log = ExperimentLog::reader(&service.path).unwrap();
    log.db.execute_batch("CREATE TRIGGER fail_fault BEFORE INSERT ON events WHEN NEW.type='FAULT_INJECTED' BEGIN SELECT RAISE(FAIL,'No se pudo guardar la intervención'); END;").unwrap();
    assert!(
        service
            .call(
                "fault",
                json!({"action":"availability","component":"sht40","enabled":false})
            )
            .is_err()
    );
    service.call("stop", json!({})).unwrap();
    let saved = log.run(text(&run["run_id"])).unwrap().unwrap();
    assert_eq!(saved["status"], "FAILED");
    service.close();
}
#[test]
fn explicit_manual_actions_do_not_depend_on_sensor_timestamp_ordering() {
    let mut h = harness();
    h.start("B");
    h.c.set_presence(&json!(true), h.now, &Value::Null).unwrap();
    h.c.policy.reactive_last_timestamp = Some(wall_time() + 1000.);
    h.c.set_presence(&json!(false), h.now + 1., &Value::Null)
        .unwrap();
    assert_eq!(
        h.c.policy.reactive_pending["event_type"],
        "RADAR_ZONE_EXITED"
    );
}
