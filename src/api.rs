use crate::{
    Result, agents::Adapters, context::timestamp, contracts::*, hardware::Hardware, protocol,
    service::ExperimentService, storage::ExperimentLog,
};
use axum::{
    Json, Router,
    body::{Body, Bytes, to_bytes},
    extract::{Request, State},
    http::{Method, StatusCode, header},
    response::{IntoResponse, Response, Sse, sse::Event},
};
use serde_json::{Value, json};
use std::{
    convert::Infallible,
    io::Read,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio_stream::{
    StreamExt,
    wrappers::{IntervalStream, ReceiverStream},
};
pub struct AppState {
    pub root: PathBuf,
    pub state: Arc<Mutex<Value>>,
    pub last_capture: Mutex<Option<Vec<u8>>>,
    pub adapters: Adapters,
    pub hardware: Option<Arc<Hardware>>,
    service: Mutex<Option<Arc<ExperimentService>>>,
    gate: Mutex<()>,
    system: Mutex<sysinfo::System>,
    shutting_down: AtomicBool,
}
impl AppState {
    pub fn new(root: &Path) -> Arc<Self> {
        let hardware = Hardware::new(root);
        Self::create(root, hardware.adapters(), Some(hardware))
    }
    pub fn with_adapters(root: &Path, adapters: Adapters) -> Arc<Self> {
        Self::create(root, adapters, None)
    }
    fn create(root: &Path, adapters: Adapters, hardware: Option<Arc<Hardware>>) -> Arc<Self> {
        Arc::new(Self {
            root: root.into(),
            state: Arc::new(Mutex::new(
                json!({"camera_rotation_degrees":0,"telemetry":{},"telemetry_at":null,"phases":{"yolo":{"status":"waiting","detail":"Pendiente"},"text":{"status":"waiting","detail":"Pendiente"},"vision":{"status":"waiting","detail":"Pendiente"}},"tasks":{},"sandbox_busy":false}),
            )),
            last_capture: Mutex::new(None),
            adapters,
            hardware,
            service: Mutex::new(None),
            gate: Mutex::new(()),
            system: Mutex::new(sysinfo::System::new_all()),
            shutting_down: AtomicBool::new(false),
        })
    }
    pub fn get_service(&self) -> Result<Arc<ExperimentService>> {
        let mut service = self.service.lock().unwrap();
        if let Some(s) = service.as_ref() {
            return Ok(s.clone());
        }
        let shared = self.state.clone();
        let readiness = Arc::new(move || {
            let state = shared.lock().unwrap();
            json!(
                state["phases"]
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(k, v)| (k.clone(), v["status"].clone()))
                    .collect::<serde_json::Map<_, _>>()
            )
        });
        let data = std::env::var_os("SENSE_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or(self.root.join("data"));
        let config = std::env::var_os("SENSE_CONFIG")
            .map(PathBuf::from)
            .unwrap_or(self.root.join("sense/pilot.yaml"));
        let s =
            ExperimentService::new(&self.root, &data, &config, self.adapters.clone(), readiness)?;
        *service = Some(s.clone());
        Ok(s)
    }
    pub fn begin_shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
    }
    pub fn close(&self) {
        self.begin_shutdown();
        if let Some(s) = self.service.lock().unwrap().as_ref() {
            s.close();
        }
    }
    pub fn set_phase(&self, name: &str, status: &str, detail: &str) {
        self.state.lock().unwrap()["phases"][name] = json!({"status":status,"detail":detail});
    }
    fn set_task(&self, name: &str, status: &str, detail: &str, seconds: Option<f64>) {
        let mut state = self.state.lock().unwrap();
        let tasks = state["tasks"].as_object_mut().unwrap();
        tasks.shift_remove(name);
        tasks.insert(
            name.into(),
            json!({"status":status,"detail":detail,"seconds":seconds}),
        );
    }
    pub fn snapshot(&self) -> Value {
        let mut payload = self.state.lock().unwrap().clone();
        let ready = payload["phases"]
            .as_object()
            .unwrap()
            .values()
            .all(|v| v["status"] == "ready");
        payload["sandbox"] = json!({"ready":ready,"busy":payload["sandbox_busy"]});
        payload["has_capture"] = json!(self.last_capture.lock().unwrap().is_some());
        {
            let mut sys = self.system.lock().unwrap();
            sys.refresh_cpu_usage();
            sys.refresh_memory();
            let total = sys.total_memory();
            let used = sys.used_memory();
            payload["system"] = json!({"cpu_percent":rounded(f64::from(sys.global_cpu_usage()),2),"memory_percent":if total>0{rounded(used as f64*100./total as f64,2)}else{0.},"memory_used_mb":rounded(used as f64/1048576.,2)});
        }
        payload["measurement"] = self
            .service
            .lock()
            .unwrap()
            .as_ref()
            .map(|s| s.snapshot())
            .unwrap_or(json!({"running":false,"enabled_modes":["A","B","C","D","E","F"]}));
        payload
    }
    pub fn mqtt_message(&self, raw: &[u8]) {
        if raw.len() > 65536 {
            return;
        }
        let Ok(telemetry) = serde_json::from_slice::<Value>(raw) else {
            return;
        };
        if !telemetry.is_object() {
            return;
        }
        let received = monotonic();
        let wall = wall_time();
        {
            let mut state = self.state.lock().unwrap();
            state["telemetry"] = telemetry.clone();
            state["telemetry_at"] = json!(wall);
        }
        if let Some(s) = self.service.lock().unwrap().as_ref() {
            s.ingest(telemetry, received, wall);
        }
    }
    pub fn enqueue(self: &Arc<Self>, name: &str, prompt: String) -> Result<()> {
        let _gate = self.gate.lock().unwrap();
        if self
            .service
            .lock()
            .unwrap()
            .as_ref()
            .is_some_and(|s| s.reserved.load(Ordering::SeqCst))
        {
            return Err("Finaliza la medición y espera a que terminen sus workers antes de usar el sandbox.".into());
        }
        {
            let mut state = self.state.lock().unwrap();
            if !state["phases"]
                .as_object()
                .unwrap()
                .values()
                .all(|p| p["status"] == "ready")
            {
                return Err(
                    "El sandbox estará disponible cuando terminen las tres preparaciones.".into(),
                );
            }
            if truth(&state["sandbox_busy"]) {
                return Err("Ya hay una operación en proceso.".into());
            }
            state["sandbox_busy"] = json!(true);
        }
        let app = self.clone();
        let name = name.to_owned();
        std::thread::spawn(move || {
            app.set_task(&name, "loading", "En proceso…", None);
            let started = monotonic();
            let result =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<String> {
                    match name.as_str() {
                        "capture" => {
                            let rotation = app.state.lock().unwrap()["camera_rotation_degrees"]
                                .as_u64()
                                .unwrap_or(0);
                            let (image, _) =
                                app.adapters.capture_oriented(rotation, 8 * 1024 * 1024)?;
                            *app.last_capture.lock().unwrap() = Some(image);
                            Ok("Foto lista.".into())
                        }
                        "yolo" => {
                            let image = app
                                .last_capture
                                .lock()
                                .unwrap()
                                .clone()
                                .ok_or("Primero toma una foto.")?;
                            Ok(format!(
                                "{} persona(s) detectada(s).",
                                (app.adapters.detector)(&image)?
                            ))
                        }
                        "chat" => Ok(text(
                            &(app.adapters.completion)(&prompt, None, &json!({}))?["content"],
                        )
                        .into()),
                        "vision" => {
                            let image = app
                                .last_capture
                                .lock()
                                .unwrap()
                                .clone()
                                .ok_or("Primero toma una foto.")?;
                            Ok(
                                text(
                                    &(app.adapters.completion)(&prompt, Some(&image), &json!({}))?
                                        ["content"],
                                )
                                .into(),
                            )
                        }
                        _ => Err("Operación no reconocida".into()),
                    }
                }))
                .unwrap_or_else(|_| Err("El worker terminó por pánico.".into()));
            match result {
                Ok(detail) => app.set_task(&name, "ready", &detail, Some(monotonic() - started)),
                Err(e) => app.set_task(
                    &name,
                    "error",
                    &error_detail(&e),
                    Some(monotonic() - started),
                ),
            }
            app.state.lock().unwrap()["sandbox_busy"] = json!(false);
        });
        Ok(())
    }
    pub fn start_background(self: &Arc<Self>) -> tokio::task::JoinHandle<()> {
        let warm = self.clone();
        std::thread::spawn(move || {
            let Some(hardware) = warm.hardware.as_ref() else {
                return;
            };
            warm.set_phase("yolo", "loading", "Cargando el modelo ONNX…");
            match hardware.warm_yolo() {
                Ok(n) => warm.set_phase(
                    "yolo",
                    "ready",
                    &format!("Listo; imagen de prueba: {n} persona(s)."),
                ),
                Err(e) => warm.set_phase("yolo", "error", &error_detail(&e)),
            };
            for (name, vision) in [("text", false), ("vision", true)] {
                warm.set_phase(
                    name,
                    "loading",
                    if vision {
                        "Calentando Gemma con imagen…"
                    } else {
                        "Calentando Gemma de texto…"
                    },
                );
                match if vision {
                    hardware.warm_vision()
                } else {
                    hardware.warm_text()
                } {
                    Ok(s) => {
                        let part: String = s.chars().take(80).collect();
                        warm.set_phase(
                            name,
                            "ready",
                            &if vision {
                                format!("Listo; prueba: {part}")
                            } else {
                                format!("Listo; respondió: {part}")
                            },
                        );
                    }
                    Err(e) => warm.set_phase(name, "error", &error_detail(&e)),
                }
            }
        });
        let app = self.clone();
        tokio::spawn(async move {
            let host = std::env::var("MQTT_HOST").unwrap_or("127.0.0.1".into());
            let topic = std::env::var("MQTT_TOPIC").unwrap_or("rustio/rpi5-01/telemetry".into());
            let mut options =
                rumqttc::MqttOptions::new(format!("sense-{}", identifier()), host, 1883);
            options.set_keep_alive(std::time::Duration::from_secs(60));
            options.set_max_packet_size(65536 + 1024, 65536 + 1024);
            let (client, mut events) = rumqttc::AsyncClient::new(options, 32);
            loop {
                match events.poll().await {
                    Ok(rumqttc::Event::Incoming(rumqttc::Packet::ConnAck(_))) => {
                        let _ = client.subscribe(&topic, rumqttc::QoS::AtMostOnce).await;
                    }
                    Ok(rumqttc::Event::Incoming(rumqttc::Packet::Publish(p))) => {
                        app.mqtt_message(&p.payload)
                    }
                    Ok(_) => {}
                    Err(e) => {
                        tracing::warn!("MQTT: {e}");
                        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                    }
                }
            }
        })
    }
}
fn error_detail(e: &crate::Error) -> String {
    if e.downcast_ref::<reqwest::Error>()
        .is_some_and(|e| e.is_connect() || e.is_timeout())
    {
        "El modelo no está ejecutándose. Inicia run.sh y vuelve a intentar.".into()
    } else {
        e.to_string()
    }
}
fn response(status: u16, value: Value) -> Response {
    (StatusCode::from_u16(status).unwrap(), Json(value)).into_response()
}
fn error(status: u16, message: impl ToString) -> Response {
    response(status, json!({"error":message.to_string()}))
}
fn file_response(mut file: std::fs::File, mime: &str, filename: &str) -> Response {
    let (tx, rx) = tokio::sync::mpsc::channel::<std::io::Result<Bytes>>(2);
    tokio::task::spawn_blocking(move || {
        loop {
            let mut bytes = vec![0; 65536];
            match file.read(&mut bytes) {
                Ok(0) => break,
                Ok(n) => {
                    bytes.truncate(n);
                    if tx.blocking_send(Ok(Bytes::from(bytes))).is_err() {
                        break;
                    }
                }
                Err(e) => {
                    let _ = tx.blocking_send(Err(e));
                    break;
                }
            }
        }
    });
    let mut out = Body::from_stream(ReceiverStream::new(rx)).into_response();
    out.headers_mut()
        .insert(header::CONTENT_TYPE, mime.parse().unwrap());
    if let Ok(value) = format!("attachment; filename=\"{filename}\"").parse() {
        out.headers_mut().insert(header::CONTENT_DISPOSITION, value);
    }
    out
}
pub fn router(state: Arc<AppState>) -> Router {
    use axum::routing::{get, post};
    let mut router = Router::new().nest_service(
        "/public",
        tower_http::services::ServeDir::new(state.root.join("public")),
    );
    for path in [
        "/",
        "/offline",
        "/offline/",
        "/events",
        "/api/experiments",
        "/api/experiments/{run_id}",
        "/api/experiments/{run_id}/export",
    ] {
        router = router.route(path, get(dispatch).options(dispatch));
    }
    for path in [
        "/api/yolo",
        "/api/chat",
        "/api/vision",
        "/api/camera",
        "/api/camera/preview",
        "/api/experiments/start",
        "/api/experiments/stop",
        "/api/experiments/query",
        "/api/experiments/presence",
        "/api/experiments/faults",
        "/api/experiments/{run_id}/observer-requests",
        "/api/experiments/{run_id}/observer-requests/{request_id}",
        "/api/experiments/{run_id}/human-records",
    ] {
        router = router.route(path, post(dispatch).options(dispatch));
    }
    router
        .route(
            "/api/capture",
            get(dispatch).post(dispatch).options(dispatch),
        )
        .with_state(state)
}
async fn dispatch(State(app): State<Arc<AppState>>, request: Request) -> Response {
    let method = if request.method() == Method::HEAD {
        Method::GET
    } else {
        request.method().clone()
    };
    let path = request.uri().path().to_owned();
    let query = request.uri().query().unwrap_or("").to_owned();
    if method == Method::OPTIONS {
        let allow = if path == "/api/capture" {
            "GET, HEAD, POST, OPTIONS"
        } else if ["/", "/offline", "/offline/", "/events", "/api/experiments"]
            .contains(&path.as_str())
            || (path.starts_with("/api/experiments/")
                && (path.matches('/').count() == 3 || path.ends_with("/export")))
        {
            "GET, HEAD, OPTIONS"
        } else {
            "POST, OPTIONS"
        };
        return (StatusCode::OK, [(header::ALLOW, allow)]).into_response();
    }
    if method == Method::GET && path == "/events" {
        let stream = IntervalStream::new(tokio::time::interval(std::time::Duration::from_secs(1)))
            .map_while(move |_| {
                if app.shutting_down.load(Ordering::SeqCst) {
                    return None;
                }
                Some(Ok::<_, Infallible>(
                    Event::default().data(app.snapshot().to_string()),
                ))
            });
        return Sse::new(stream).into_response();
    }
    if method == Method::GET && ["/", "/offline", "/offline/"].contains(&path.as_str()) {
        return match tokio::fs::read(app.root.join("public/index.html")).await {
            Ok(bytes) => {
                ([(header::CONTENT_TYPE, "text/html; charset=utf-8")], bytes).into_response()
            }
            Err(_) => StatusCode::NOT_FOUND.into_response(),
        };
    }
    let json_content = request
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|h| h.to_str().ok())
        .map(|s| {
            s.split(';')
                .next()
                .unwrap_or("")
                .trim()
                .to_ascii_lowercase()
        })
        .is_some_and(|s| {
            s == "application/json" || (s.starts_with("application/") && s.ends_with("+json"))
        });
    let raw = match to_bytes(request.into_body(), 65536).await {
        Ok(v) => v,
        Err(_) => return error(413, "La petición excede 64 kB."),
    };
    let body = if json_content {
        serde_json::from_slice::<Value>(&raw).unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let result =
        tokio::task::spawn_blocking(move || api_request(&app, &method, &path, &query, body)).await;
    match result {
        Ok(Ok(r)) => r,
        Ok(Err(e)) => error(500, e),
        Err(e) => error(500, e),
    }
}
fn query_param(query: &str, key: &str) -> Option<String> {
    reqwest::Url::parse(&format!("http://localhost/?{query}"))
        .ok()?
        .query_pairs()
        .find_map(|(k, v)| if k == key { Some(v.into_owned()) } else { None })
}
fn call(app: &AppState, action: &str, payload: Value) -> Response {
    match app.get_service().and_then(|s| s.call(action, payload)) {
        Ok(v) => response(202, v),
        Err(e) => error(409, e),
    }
}
fn api_request(
    app: &Arc<AppState>,
    method: &Method,
    path: &str,
    query: &str,
    body: Value,
) -> Result<Response> {
    if method == Method::POST && ["/api/camera", "/api/camera/preview"].contains(&path) {
        let rotation = if path == "/api/camera" {
            match crate::agents::camera_rotation(&body["rotation_degrees"]) {
                Ok(v) => Some(v),
                Err(e) => return Ok(error(400, e)),
            }
        } else {
            None
        };
        let _gate = app.gate.lock().unwrap();
        if truth(&app.state.lock().unwrap()["sandbox_busy"])
            || app
                .service
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|s| s.reserved.load(Ordering::SeqCst))
        {
            return Ok(error(
                409,
                "Finaliza la ejecución y espera a sus workers antes de ajustar la cámara.",
            ));
        }
        if let Some(rotation) = rotation {
            app.state.lock().unwrap()["camera_rotation_degrees"] = json!(rotation);
            *app.last_capture.lock().unwrap() = None;
            app.state.lock().unwrap()["tasks"]
                .as_object_mut()
                .unwrap()
                .shift_remove("capture");
            return Ok(response(200, json!({"rotation_degrees":rotation})));
        }
        let (bytes, _) = app.adapters.capture_oriented(0, 8 * 1024 * 1024)?;
        return Ok((
            [
                (header::CONTENT_TYPE, "image/jpeg"),
                (header::CACHE_CONTROL, "no-store"),
            ],
            bytes,
        )
            .into_response());
    }
    if method == Method::GET && path == "/api/capture" {
        return Ok(match app.last_capture.lock().unwrap().clone() {
            Some(bytes) => (
                [
                    (header::CONTENT_TYPE, "image/jpeg"),
                    (header::CACHE_CONTROL, "no-cache, max-age=0"),
                ],
                bytes,
            )
                .into_response(),
            None => error(404, "No hay foto disponible."),
        });
    }
    if method == Method::POST
        && ["/api/capture", "/api/yolo", "/api/chat", "/api/vision"].contains(&path)
    {
        let name = path.trim_start_matches("/api/");
        let mut prompt = String::new();
        if ["chat", "vision"].contains(&name) {
            let value = body.get("question").cloned().unwrap_or(json!(""));
            prompt = if let Some(s) = value.as_str() {
                s.into()
            } else {
                value.to_string()
            };
            prompt = prompt.chars().take(1000).collect::<String>().trim().into();
            if prompt.is_empty() {
                return Ok(error(
                    400,
                    if name == "vision" {
                        "Escribe una pregunta sobre la foto."
                    } else {
                        "Escribe una pregunta."
                    },
                ));
            }
        }
        return Ok(match app.enqueue(name, prompt) {
            Ok(()) => response(202, json!({"ok":true})),
            Err(e) => error(409, e),
        });
    }
    if method == Method::POST && path == "/api/experiments/start" {
        if !body.is_object() || !["A", "B", "C", "D", "E", "F"].contains(&text(&body["mode"])) {
            return Ok(error(400, "Selecciona un modo A–F."));
        }
        for k in ["session_id", "scenario_id"] {
            if let Some(v) = body.get(k)
                && v.as_str()
                    .is_none_or(|s| !(1..=100).contains(&s.chars().count()))
            {
                return Ok(error(
                    400,
                    format!("{k} debe contener entre 1 y 100 caracteres."),
                ));
            }
        }
        if let Err(e) = protocol::validate_guided_start(&body) {
            return Ok(error(400, e));
        }
        let s = match app.get_service() {
            Ok(s) => s,
            Err(e) => return Ok(error(409, e)),
        };
        {
            let _gate = app.gate.lock().unwrap();
            if truth(&app.state.lock().unwrap()["sandbox_busy"]) {
                return Ok(error(409, "Espera a que termine la operación del sandbox."));
            }
            if let Err(e) = s.reserve() {
                return Ok(error(409, e));
            }
        }
        let mut body = body;
        body["camera_rotation_degrees"] =
            app.state.lock().unwrap()["camera_rotation_degrees"].clone();
        return Ok(match s.call("start", body) {
            Ok(run) => response(202, json!({"run_id":run["run_id"]})),
            Err(e) => error(409, e),
        });
    }
    if method == Method::POST && path == "/api/experiments/stop" {
        return Ok(call(app, "stop", json!({})));
    }
    if method == Method::POST && path == "/api/experiments/query" {
        if !body.is_object() {
            return Ok(error(400, "Se requiere question_id."));
        }
        return Ok(call(app, "query", body));
    }
    if method == Method::POST && path == "/api/experiments/presence" {
        if !body.is_object() || !["auto", "manual"].contains(&text(&body["mode"])) {
            return Ok(error(400, "Usa mode auto o manual."));
        }
        if body["mode"] == "manual" && !body["detected"].is_boolean() {
            return Ok(error(400, "El modo manual requiere detected booleano."));
        }
        if body.get("near").is_some() && (body["mode"] != "manual" || !body["near"].is_boolean()) {
            return Ok(error(400, "near debe ser booleano en modo manual."));
        }
        let mut p =
            json!({"detected":if body["mode"]=="auto"{Value::Null}else{body["detected"].clone()}});
        if let Some(v) = body.get("near") {
            p["near"] = v.clone();
        }
        return Ok(call(app, "presence", p));
    }
    if method == Method::POST && path == "/api/experiments/faults" {
        if !body.is_object() || !["availability", "timeout"].contains(&text(&body["action"])) {
            return Ok(error(
                400,
                "Selecciona una falla de disponibilidad o timeout.",
            ));
        }
        if body["action"] == "availability"
            && (!["sht40", "ens160", "radar", "camera"].contains(&text(&body["component"]))
                || !body["enabled"].is_boolean())
        {
            return Ok(error(400, "Selecciona componente y enabled booleano."));
        }
        if body["action"] == "timeout" && !["vision", "gemma"].contains(&text(&body["lane"])) {
            return Ok(error(400, "Selecciona el worker vision o gemma."));
        }
        return Ok(call(app, "fault", body));
    }
    if method == Method::GET && path == "/api/experiments" {
        let service = app.get_service()?;
        let log = ExperimentLog::reader(&service.path)?;
        return Ok(response(
            200,
            json!({"runs":log.runs()?,"completed_repetitions":log.completed_repetitions()?}),
        ));
    }
    let parts: Vec<_> = path.trim_matches('/').split('/').collect();
    if parts.len() < 3 || parts[0] != "api" || parts[1] != "experiments" {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }
    let id = parts[2];
    let service = app.get_service()?;
    let log = ExperimentLog::reader(&service.path)?;
    let Some(run) = log.run(id)? else {
        return Ok(error(404, "Ejecución no encontrada."));
    };
    if method == Method::GET && parts.len() == 3 {
        let after = match query_param(query, "after")
            .unwrap_or("0".into())
            .parse::<i64>()
        {
            Ok(n) => n.max(0),
            Err(_) => return Ok(error(400, "Cursor inválido.")),
        };
        return Ok(response(
            200,
            json!({"run":run,"events":log.events(id,after,200)?,"observer_requests":log.observer_requests(id,true)?,"observer_previous":log.observer_previous(id)?,"quality":log.quality(id)?,"completed_repetitions":log.completed_repetitions()?}),
        ));
    }
    if method == Method::GET && parts.len() == 4 && parts[3] == "export" {
        if query_param(query, "format").as_deref() == Some("csv") {
            let file = crate::trace::export_csv_zip(&service.path, id)?;
            return Ok(file_response(
                file,
                "application/zip",
                &format!("sense-{id}.zip"),
            ));
        }
        let mut file = tempfile::tempfile()?;
        log.export_ndjson(id, &mut file)?;
        use std::io::{Seek, SeekFrom};
        file.seek(SeekFrom::Start(0))?;
        return Ok(file_response(
            file,
            "application/x-ndjson",
            &format!("sense-{id}.ndjson"),
        ));
    }
    if method == Method::POST && parts.len() == 4 && parts[3] == "observer-requests" {
        if let Err(e) = log.request_observer(
            id,
            "OBSERVER_EVENT",
            &["power_w", "visible_people", "action"],
            None,
            None,
            None,
        ) {
            return Ok(error(409, e));
        }
        return Ok(response(
            201,
            json!({"observer_requests":log.observer_requests(id,true)?}),
        ));
    }
    if method == Method::POST && parts.len() == 5 && parts[3] == "observer-requests" {
        if !body.is_object() || python_json(&body).len() > 10000 {
            return Ok(error(400, "Se requiere una observación de hasta 10 kB."));
        }
        return Ok(match log.resolve_observer(id, parts[4], &body) {
            Ok(record) => response(
                201,
                json!({"record_id":record,"observer_requests":log.observer_requests(id,true)?,"observer_previous":log.observer_previous(id)?,"quality":log.quality(id)?,"completed_repetitions":log.completed_repetitions()?}),
            ),
            Err(e) => error(400, e),
        });
    }
    if method == Method::POST && parts.len() == 4 && parts[3] == "human-records" {
        let kind = text(&body["kind"]);
        if !body.is_object()
            || !["GROUND_TRUTH", "EXTERNAL_ENERGY", "EXTERNAL_POWER"].contains(&kind)
        {
            return Ok(error(
                400,
                "Usa kind GROUND_TRUTH, EXTERNAL_POWER o EXTERNAL_ENERGY y un payload separado.",
            ));
        }
        let p = &body["payload"];
        if !p.is_object() || python_json(p).len() > 10000 {
            return Ok(error(400, "payload debe ser un objeto de hasta 10 kB."));
        }
        let result = (|| -> Result<String> {
            timestamp(&p["observed_at"])?;
            if ["EXTERNAL_ENERGY", "EXTERNAL_POWER"].contains(&kind) {
                let units: &[&str] = if kind == "EXTERNAL_POWER" {
                    &["W"]
                } else {
                    &["Wh", "J"]
                };
                if !p["value"]
                    .as_f64()
                    .is_some_and(|v| v >= 0. && v.is_finite())
                    || !units.contains(&text(&p["unit"]))
                    || p["scope"] != "whole_run"
                {
                    return Err("Lectura externa: valor finito no negativo, unidad W (potencia) o Wh/J (energía) y scope whole_run.".into());
                }
            } else if text(&p["region"]).is_empty() {
                return Err("El ground truth debe indicar su región.".into());
            } else if p
                .get("visible_people")
                .is_some_and(|v| v.as_u64().is_none())
            {
                return Err("visible_people debe ser un entero no negativo.".into());
            }
            log.human_record(id, kind, p)
        })();
        return Ok(match result {
            Ok(record) => response(201, json!({"record_id":record})),
            Err(e) => error(400, e),
        });
    }
    Ok(StatusCode::NOT_FOUND.into_response())
}
pub fn offline_router(root: &Path) -> Router {
    let public = root.join("public");
    let index = public.join("index.html");
    Router::new()
        .route(
            "/",
            axum::routing::get(|| async { (StatusCode::FOUND, [(header::LOCATION, "/offline")]) }),
        )
        .route(
            "/offline",
            axum::routing::get({
                let index = index.clone();
                move || serve_index(index.clone())
            }),
        )
        .route(
            "/offline/",
            axum::routing::get(move || serve_index(index.clone())),
        )
        .nest_service("/public", tower_http::services::ServeDir::new(public))
}
async fn serve_index(path: PathBuf) -> Response {
    match tokio::fs::read(path).await {
        Ok(bytes) => ([(header::CONTENT_TYPE, "text/html; charset=utf-8")], bytes).into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}
