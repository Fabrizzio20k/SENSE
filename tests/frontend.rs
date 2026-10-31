use sense_people_counter::{contracts::*, storage::ExperimentLog, trace::export_csv_zip};
use serde_json::json;
use std::{
    io::{Read, Write},
    process::Command,
};
#[test]
fn frontend_and_rust_exports() {
    let temp = tempfile::tempdir().unwrap();
    let start = "2026-10-27T12:00:00Z";
    let run = json!({"run_id":"12345","mode":"E","status":"COMPLETED","start_time":start,"duration_seconds":30,"elapsed_s":30});
    let samples = vec![
        json!({"second":0,"elapsed_s":0,"visible_count":0,"presence":0,"fsm_state":"WAIT"}),
        json!({"second":2,"elapsed_s":2,"visible_count":3,"presence":1,"fsm_state":"VISION"}),
    ];
    let events = vec![
        (
            "RESULT_PUBLISHED",
            "2026-10-27T12:00:02.000Z",
            json!({"answers":{"Q2":{"question_id":"Q2","question":"Personas","answer":3}}}),
        ),
        (
            "FSM_TRANSITION",
            "2026-10-27T12:00:03.000Z",
            json!({"from":"VISION","to":"ASSESS"}),
        ),
        (
            "HISTORICAL_INTERPRETATION",
            "2026-10-27T12:00:35.000Z",
            json!({"question_id":"Q7","validation_status":"VALIDATED","inferences":["Simulado"]}),
        ),
    ];
    let log = ExperimentLog::new(&temp.path().join("trace.sqlite3")).unwrap();
    log.begin(&run).unwrap();
    for mut s in samples {
        s["timestamp_utc"] = json!(start);
        log.sample("12345", number(&s["second"]) as i64, &s)
            .unwrap();
    }
    for (kind, at, mut p) in events {
        p["timestamp"] = json!(at);
        p["cycle_id"] = json!("test-cycle");
        log.event("12345", kind, &p).unwrap();
    }
    let record = json!({"run_id":"12345","record_id":"98765","kind":"OBSERVER_RECORD","power_w":0,"visible_people":0,"observed_at":"2026-10-27T12:00:01.000Z","recorded_at":"2026-10-27T12:00:09.000Z","notes":"=2+2\n<img src=x onerror=alert(1)>","repeated_fields":["power_w"]});
    log.human_record("12345", "OBSERVER_RECORD", &record)
        .unwrap();
    log.finish("12345", "COMPLETED", Some(&run)).unwrap();
    let mut jpeg = std::io::Cursor::new(Vec::new());
    image::RgbImage::from_pixel(4, 2, image::Rgb([255u8, 0, 0]))
        .write_to(&mut jpeg, image::ImageFormat::Jpeg)
        .unwrap();
    log.save_image("12345", "test-image", &jpeg.into_inner())
        .unwrap();
    let production = temp.path().join("production.zip");
    let mut bytes = vec![];
    export_csv_zip(&log.path, "12345")
        .unwrap()
        .read_to_end(&mut bytes)
        .unwrap();
    std::fs::write(&production, bytes).unwrap();
    let legacy = temp.path().join("legacy.zip");
    let mut zip = zip::ZipWriter::new(std::fs::File::create(&legacy).unwrap());
    for(name,data)in [("metadata.json",run.to_string()),("samples_1s.csv","second,elapsed_s,visible_count\r\n0,0,0\r\n2,2,3\r\n".into()),("events.csv","sequence,timestamp_utc,type,payload_json\r\n1,2026-10-27T12:00:02.000Z,RESULT_PUBLISHED,\"{\"\"answers\"\":{}}\"\r\n".into())]{zip.start_file(name,zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated)).unwrap();zip.write_all(data.as_bytes()).unwrap();}
    zip.finish().unwrap();
    let tests: Vec<_> =
        std::fs::read_dir(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests"))
            .unwrap()
            .flatten()
            .map(|e| e.path())
            .filter(|p| {
                p.file_name()
                    .unwrap()
                    .to_string_lossy()
                    .ends_with(".test.cjs")
            })
            .collect();
    let output = Command::new("node")
        .arg("--test")
        .args(tests)
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .env("SENSE_RUST_LEGACY_ZIP", &legacy)
        .env("SENSE_RUST_PRODUCTION_ZIP", &production)
        .output()
        .expect("Se necesita Node.js para las pruebas de frontend");
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    println!("{}", String::from_utf8_lossy(&output.stdout));
}
