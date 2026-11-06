mod common;
use common::*;
use sense_people_counter::{
    contracts::*,
    runtime::{RemoteExecutionUncertain, TaskManager, TaskOutput},
};
use serde_json::json;
use std::{
    sync::mpsc,
    time::{Duration, Instant},
};
fn wait(t: &mut TaskManager, now: f64) -> Vec<sense_people_counter::runtime::TaskEvent> {
    let mut out = vec![];
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        out.extend(t.poll(now, false));
        if out
            .iter()
            .any(|e| ["TASK_COMPLETED", "TASK_FAILED"].contains(&text(&e.document["event_type"])))
        {
            return out;
        }
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(1));
    }
}
#[test]
fn timeout_retains_physical_slot_and_bounds_queue() {
    let mut t = TaskManager::new(1);
    let (tx, rx) = mpsc::channel();
    t.submit(
        "gemma",
        command("multimodal"),
        Box::new(move || {
            rx.recv()?;
            Ok(json!({}).into())
        }),
        "one".into(),
        0.,
        1.,
        None,
    );
    t.submit(
        "gemma",
        command("text"),
        Box::new(|| Ok(json!({}).into())),
        "two".into(),
        0.,
        5.,
        None,
    );
    assert_eq!(
        t.submit(
            "gemma",
            command("text"),
            Box::new(|| Ok(json!({}).into())),
            "three".into(),
            0.,
            5.,
            None
        )
        .as_deref(),
        Some("QUEUE_SATURATED")
    );
    let events = t.poll(2., false);
    assert!(
        events
            .iter()
            .any(|e| e.document["event_type"] == "TASK_TIMEOUT")
    );
    assert!(t.active["gemma"].is_some());
    assert_eq!(t.pending.len(), 1);
    tx.send(()).unwrap();
    let events = wait(&mut t, 3.);
    assert!(events.iter().any(|e| truth(&e.document["payload"]["late"])));
}
#[test]
fn cancellation_keeps_worker_occupied_until_done() {
    let mut t = TaskManager::new(1);
    let (tx, rx) = mpsc::channel();
    t.submit(
        "gemma",
        command("text"),
        Box::new(move || {
            rx.recv()?;
            Ok(json!({}).into())
        }),
        "one".into(),
        0.,
        10.,
        None,
    );
    assert_eq!(t.cancel("run").len(), 1);
    assert!(t.busy());
    assert_eq!(t.view(1.)["active"][0]["status"], "DRAINING");
    tx.send(()).unwrap();
    wait(&mut t, 2.);
    assert!(!t.busy());
}
#[test]
fn queued_question_gets_full_timeout_after_previous_question_finishes() {
    let mut t = TaskManager::new(1);
    t.submit(
        "gemma",
        command("text"),
        Box::new(|| panic!("simulation ran")),
        "one".into(),
        0.,
        2.,
        Some(json!({"kind":"TIMEOUT"})),
    );
    t.submit(
        "gemma",
        command("multimodal"),
        Box::new(|| panic!("simulation ran")),
        "two".into(),
        0.,
        1.,
        Some(json!({"kind":"TIMEOUT"})),
    );
    assert!(
        t.poll(1.5, true)
            .iter()
            .all(|e| e.document["event_type"] != "TASK_TIMEOUT")
    );
    assert_eq!(t.pending.len(), 1);
    t.poll(2., true);
    let second = t.active["gemma"].as_ref().unwrap();
    assert_eq!(second.command["parameters"]["question_id"], "Q7");
    assert_eq!(second.started, 2.);
    assert_eq!(second.deadline, 3.);
    assert!(
        t.poll(2.9, true)
            .iter()
            .all(|e| e.document["event_type"] != "TASK_TIMEOUT")
    );
    let events = t.poll(3., true);
    assert!(
        events
            .iter()
            .any(|e| e.document["event_type"] == "TASK_TIMEOUT"
                && e.document["payload"]["command"]["parameters"]["question_id"] == "Q7")
    );
    assert!(!t.busy());
}
#[test]
fn queued_result_uses_execution_duration_when_poll_arrives_late() {
    let mut t = TaskManager::new(1);
    t.submit(
        "gemma",
        command("text"),
        Box::new(|| panic!("simulation ran")),
        "one".into(),
        0.,
        1.,
        Some(json!({"kind":"TIMEOUT"})),
    );
    t.submit(
        "gemma",
        command("multimodal"),
        Box::new(|| panic!("simulation ran")),
        "two".into(),
        0.,
        0.5,
        Some(json!({"kind":"CAMERA_UNAVAILABLE"})),
    );
    std::thread::sleep(Duration::from_millis(550));
    t.poll(1., true);
    let events = wait(&mut t, 2.);
    assert!(
        events
            .iter()
            .any(|e| e.document["event_type"] == "TASK_FAILED")
    );
    assert!(
        events
            .iter()
            .all(|e| e.document["event_type"] != "TASK_TIMEOUT")
    );
    assert_eq!(t.counters["late"], 1); // Only the first, simulated timeout is late.
}
#[test]
fn remote_timeout_does_not_prove_runtime_stopped() {
    let mut t = TaskManager::new(1);
    t.submit(
        "gemma",
        command("text"),
        Box::new(|| {
            Err(RemoteExecutionUncertain("El servidor puede seguir trabajando".into()).into())
        }),
        "one".into(),
        0.,
        10.,
        None,
    );
    let events = wait(&mut t, 1.);
    assert!(
        events
            .iter()
            .any(|e| truth(&e.document["payload"]["remote_execution_uncertain"]))
    );
    assert!(t.busy());
    assert_eq!(
        t.submit(
            "gemma",
            command("text"),
            Box::new(|| Ok(json!({}).into())),
            "two".into(),
            2.,
            10.,
            None
        )
        .as_deref(),
        Some("REMOTE_EXECUTION_UNCERTAIN")
    );
}
#[test]
fn expired_queued_image_is_not_retained_or_executed() {
    let mut t = TaskManager::new(1);
    let (tx, rx) = mpsc::channel();
    t.submit(
        "gemma",
        command("text"),
        Box::new(move || {
            rx.recv()?;
            Ok(json!({}).into())
        }),
        "one".into(),
        0.,
        10.,
        None,
    );
    let mut c = command("multimodal");
    c["parameters"]["image_expires_monotonic"] = json!(1);
    t.submit(
        "gemma",
        c,
        Box::new(|| panic!("expired image ran")),
        "two".into(),
        0.,
        10.,
        None,
    );
    let events = t.poll(2., false);
    assert!(
        events
            .iter()
            .any(|e| e.document["payload"]["reason"] == "IMAGE_EXPIRED_IN_QUEUE")
    );
    assert!(t.pending.is_empty());
    tx.send(()).unwrap();
    wait(&mut t, 3.);
}
#[test]
fn timeout_and_completion_events_do_not_share_mutable_payload() {
    let mut t = TaskManager::new(1);
    t.submit(
        "vision",
        command("vision"),
        Box::new(|| Ok(TaskOutput::from(json!({"count":2})))),
        "one".into(),
        0.,
        1.,
        None,
    );
    let events = wait(&mut t, 0.1);
    let start = events
        .iter()
        .find(|e| e.document["event_type"] == "TASK_STARTED")
        .unwrap();
    assert!(start.document["payload"].get("result").is_none());
    let end = events
        .iter()
        .find(|e| e.document["event_type"] == "TASK_COMPLETED")
        .unwrap();
    assert_eq!(end.document["payload"]["result"]["count"], 2);
    assert!(end.document["payload"]["completed_at"].is_string());
}
