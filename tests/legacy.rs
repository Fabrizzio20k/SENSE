use sense_people_counter::{contracts::*, storage::ExperimentLog};
#[test]
fn opens_python_database_preserves_history_and_interrupts_unfinished_runs() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("experiments.sqlite3");
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute_batch(include_str!("fixtures/python_legacy.sql"))
        .unwrap();
    drop(db);
    let log = ExperimentLog::new(&path).unwrap();
    assert_eq!(
        log.run("legacy-completed").unwrap().unwrap()["status"],
        "COMPLETED"
    );
    assert_eq!(
        log.run("legacy-running").unwrap().unwrap()["status"],
        "INTERRUPTED"
    );
    assert_eq!(
        log.events("legacy-completed", 0, 200).unwrap()[0]["payload"]["value"],
        0
    );
    assert!(
        !log.observer_requests("legacy-running", true)
            .unwrap()
            .is_empty()
    );
    assert!(!truth(
        &log.quality("legacy-running").unwrap()["record_complete"]
    ));
    let mut bytes = vec![];
    log.export_ndjson("legacy-completed", &mut bytes).unwrap();
    assert!(String::from_utf8(bytes).unwrap().contains("GROUND_TRUTH"));
}
