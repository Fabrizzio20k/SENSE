mod common;
use axum::{
    body::{Body, to_bytes},
    http::Request,
};
use common::*;
use tower::ServiceExt;
#[tokio::test]
async fn routes_only_serve_the_shared_ui_and_public_assets() {
    let h = ApiHarness::new();
    let app = sense_people_counter::api::offline_router(h.temp.path());
    for path in ["/offline", "/offline/", "/public/app.js?v=1"] {
        let r = app
            .clone()
            .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(r.status(), 200);
        assert!(
            !to_bytes(r.into_body(), 10_000_000)
                .await
                .unwrap()
                .is_empty()
        );
    }
    for path in [
        "/api/experiments/start",
        "/sense/pilot.yaml",
        "/public/../sense/pilot.yaml",
    ] {
        let r = app
            .clone()
            .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(r.status(), 404);
    }
    assert!(!h.temp.path().join("data").exists());
}
#[tokio::test]
async fn root_redirects_to_the_explicit_offline_mode() {
    let h = ApiHarness::new();
    let r = sense_people_counter::api::offline_router(h.temp.path())
        .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(r.status(), 302);
    assert_eq!(r.headers()["location"], "/offline");
}
