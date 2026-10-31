use sense_people_counter::{
    Result,
    api::{self, AppState},
};
use std::net::SocketAddr;

fn listen_address(port: Option<&str>) -> Result<SocketAddr> {
    let default = if cfg!(target_os = "macos") {
        5001
    } else {
        5000
    };
    let port = match port {
        Some(value) => value
            .parse::<u16>()
            .ok()
            .filter(|port| *port != 0)
            .ok_or("SENSE_PORT debe ser un entero entre 1 y 65535.")?,
        None => default,
    };
    Ok(([0, 0, 0, 0], port).into())
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();
    let address = listen_address(std::env::var("SENSE_PORT").ok().as_deref())?;
    // Reserve the port before starting native model initialization or MQTT.
    let listener = tokio::net::TcpListener::bind(address)
        .await
        .map_err(|error| {
            std::io::Error::new(
                error.kind(),
                format!(
                    "No se pudo abrir {address}: {error}. Selecciona otro puerto con SENSE_PORT."
                ),
            )
        })?;
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let state = AppState::new(&root);
    let mqtt = state.start_background();
    tracing::info!("Panel: http://localhost:{}", address.port());
    let result = axum::serve(listener, api::router(state.clone()))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await;
    mqtt.abort();
    tokio::task::spawn_blocking(move || state.close()).await?;
    result?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_avoids_macos_control_center_port() {
        assert_eq!(
            listen_address(None).unwrap().port(),
            if cfg!(target_os = "macos") {
                5001
            } else {
                5000
            }
        );
    }

    #[test]
    fn accepts_an_explicit_port_and_rejects_invalid_values() {
        assert_eq!(listen_address(Some("5050")).unwrap().port(), 5050);
        for invalid in ["", "0", "-1", "65536", "http"] {
            assert!(listen_address(Some(invalid)).is_err());
        }
    }
}
