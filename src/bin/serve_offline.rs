use sense_people_counter::{Result, api::offline_router};
#[tokio::main]
async fn main() -> Result<()> {
    let mut bind = "127.0.0.1".to_owned();
    let mut port = 8000u16;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--bind" => bind = args.next().ok_or("Falta --bind")?,
            "--port" => port = args.next().ok_or("Falta --port")?.parse()?,
            "--help" | "-h" => {
                println!("serve_offline [--bind 127.0.0.1] [--port 8000]");
                return Ok(());
            }
            _ => return Err(format!("Argumento desconocido: {arg}").into()),
        }
    }
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let listener = tokio::net::TcpListener::bind((bind.as_str(), port)).await?;
    println!("UI simulada: http://{bind}:{port}/offline");
    axum::serve(listener, offline_router(root))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
