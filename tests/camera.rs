mod common;
use common::*;
use sense_people_counter::{agents, api::AppState, contracts::*, trace::export_csv_zip};
use serde_json::{Value, json};
use std::{
    io::Read,
    sync::{Arc, Mutex, atomic::Ordering},
};

fn photo() -> Vec<u8> {
    let image = image::RgbImage::from_fn(80, 40, |x, y| {
        image::Rgb(match (x < 40, y < 20) {
            (true, true) => [255, 0, 0],
            (false, true) => [0, 255, 0],
            (true, false) => [0, 0, 255],
            _ => [255, 255, 255],
        })
    });
    let mut out = std::io::Cursor::new(Vec::new());
    image.write_to(&mut out, image::ImageFormat::Png).unwrap();
    out.into_inner()
}

#[test]
fn quarter_turns_rotate_pixels_clockwise_and_reject_invalid_angles() {
    let original = photo();
    assert_eq!(agents::rotate_image(original.clone(), 0).unwrap(), original);
    for (degrees, size, corner) in [
        (90, (40, 80), [0, 0, 255]),
        (180, (80, 40), [255, 255, 255]),
        (270, (40, 80), [0, 255, 0]),
    ] {
        let rotated =
            image::load_from_memory(&agents::rotate_image(original.clone(), degrees).unwrap())
                .unwrap()
                .to_rgb8();
        assert_eq!(rotated.dimensions(), size);
        assert!(
            rotated
                .get_pixel(5, 5)
                .0
                .iter()
                .zip(corner)
                .all(|(a, b)| (*a as i32 - b).abs() < 20)
        );
    }
    for value in [json!(45), json!(-90), json!(90.5), json!("90"), Value::Null] {
        assert!(agents::camera_rotation(&value).is_err());
    }
    assert!(agents::rotate_image(original, 360).is_err());
    assert!(agents::rotate_image(b"broken".to_vec(), 90).is_err());
}

#[test]
fn yolo_gemma_database_and_zip_share_the_same_oriented_bytes() {
    let mut h = Harness::new();
    let input = photo();
    let captured = stamp(h.wall);
    h.c.adapters.capture = Arc::new(move || Ok((input.clone(), captured.clone())));
    let detected = Arc::new(Mutex::new(Vec::new()));
    let seen = detected.clone();
    h.c.adapters.detector = Arc::new(move |bytes| {
        *seen.lock().unwrap() = bytes.to_vec();
        Ok(2)
    });
    h.c.start(
        "E",
        h.now,
        "session",
        "scenario",
        &json!({"camera_rotation_degrees":90}),
    )
    .unwrap();
    h.ingest(0., None);
    h.finish_vision();
    h.finish_lane("gemma", 0.2);
    let yolo = detected.lock().unwrap().clone();
    assert_eq!(image::load_from_memory(&yolo).unwrap().width(), 40);
    assert_eq!(h.completions.lock().unwrap()[0], Some(yolo.clone()));
    let obs = &h.c.context.observations["count"];
    assert_eq!(obs["metadata"]["camera_rotation_degrees"], 90);
    let image_id = text(&obs["metadata"]["image_id"]);
    let saved: Vec<u8> =
        h.c.log
            .db
            .query_row(
                "SELECT jpeg FROM images WHERE image_id=?",
                [image_id],
                |r| r.get(0),
            )
            .unwrap();
    assert_eq!(saved, yolo);
    let mut zip =
        zip::ZipArchive::new(export_csv_zip(&h.c.log.path, text(&h.c.run["run_id"])).unwrap())
            .unwrap();
    let mut exported = Vec::new();
    zip.by_name(&format!("images/{image_id}.jpg"))
        .unwrap()
        .read_to_end(&mut exported)
        .unwrap();
    assert_eq!(exported, yolo);
    let metadata: Value = serde_json::from_reader(zip.by_name("metadata.json").unwrap()).unwrap();
    assert_eq!(metadata["camera_rotation_degrees"], 90);
}

#[tokio::test]
async fn preview_works_before_models_and_changes_are_exclusive_and_frozen_per_run() {
    let mut h = ApiHarness::new();
    let mut adapters = h.app.adapters.clone();
    let input = photo();
    adapters.capture = Arc::new(move || Ok((input.clone(), utc_now())));
    h.app = AppState::with_adapters(h.temp.path(), adapters);
    let (status, _, bytes) = h.request("POST", "/api/camera/preview", json!({})).await;
    assert_eq!(status, 200);
    assert_eq!(bytes, photo());
    assert!(h.app.last_capture.lock().unwrap().is_none());
    for bad in [
        json!({}),
        json!({"rotation_degrees":45}),
        json!({"rotation_degrees":"90"}),
    ] {
        assert_eq!(h.request("POST", "/api/camera", bad).await.0, 400);
    }
    *h.app.last_capture.lock().unwrap() = Some(photo());
    assert_eq!(
        h.request("POST", "/api/camera", json!({"rotation_degrees":270}))
            .await
            .0,
        200
    );
    assert!(h.app.last_capture.lock().unwrap().is_none());
    for name in ["yolo", "text", "vision"] {
        h.app.set_phase(name, "ready", "test");
    }
    h.app.enqueue("capture", String::new()).unwrap();
    for _ in 0..200 {
        if !truth(&h.app.snapshot()["sandbox"]["busy"]) {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    }
    let sandbox = h.app.last_capture.lock().unwrap().clone().unwrap();
    assert_eq!(image::load_from_memory(&sandbox).unwrap().width(), 40);
    let id = h.start("A").await;
    let (_, run, _) = h
        .request("GET", &format!("/api/experiments/{id}"), Value::Null)
        .await;
    assert_eq!(run["run"]["camera_rotation_degrees"], 270);
    for path in ["/api/camera", "/api/camera/preview"] {
        assert_eq!(
            h.request("POST", path, json!({"rotation_degrees":0}))
                .await
                .0,
            409
        );
    }
    assert_eq!(h.app.snapshot()["camera_rotation_degrees"], 270);
    h.app.close();
    // A reserved worker must block changes even when there is no active run.
    h.app
        .get_service()
        .unwrap()
        .reserved
        .store(true, Ordering::SeqCst);
    assert_eq!(
        h.request("POST", "/api/camera", json!({"rotation_degrees":0}))
            .await
            .0,
        409
    );
}
