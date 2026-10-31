use crate::{Result, agents::Adapters, contracts::*, inference};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};
use ultralytics_inference::{Device, InferenceConfig, YOLOModel};
pub struct Hardware {
    pub yolo: Mutex<Option<YOLOModel>>,
    root: PathBuf,
    url: String,
    model: String,
}
impl Hardware {
    pub fn new(root: &Path) -> Arc<Self> {
        Arc::new(Self {
            yolo: Mutex::new(None),
            root: root.into(),
            url: std::env::var("LITERT_URL")
                .unwrap_or("http://127.0.0.1:8080/v1/chat/completions".into()),
            model: std::env::var("LITERT_MODEL").unwrap_or("gemma4-e2b".into()),
        })
    }
    pub fn adapters(self: &Arc<Self>) -> Adapters {
        let detector = self.clone();
        let completion = self.clone();
        Adapters {
            capture: Arc::new(capture_evidence),
            detector: Arc::new(move |image| detector.count_people(image)),
            completion: Arc::new(move |p, image, c| completion.complete(p, image, c)),
            model: self.model.clone(),
        }
    }
    pub fn warm_yolo(&self) -> Result<usize> {
        let config = InferenceConfig::new()
            .with_device(Device::Cpu)
            .with_confidence(0.15)
            .with_classes(vec![0])
            .with_imgsz(640, 640);
        let model = YOLOModel::load_with_config(self.root.join("yolo26n.onnx"), config)?;
        *self.yolo.lock().map_err(|_| "YOLO no disponible")? = Some(model);
        self.count_people(&std::fs::read(self.root.join("public/prepare_image.png"))?)
    }
    pub fn count_people(&self, bytes: &[u8]) -> Result<usize> {
        let mut guard = self.yolo.lock().map_err(|_| "YOLO no disponible")?;
        let model = guard.as_mut().ok_or("YOLO todavía no está listo")?;
        let image = image::load_from_memory(bytes)?;
        let results = model.predict_image(&image, "capture".into())?;
        let result = results.first().ok_or("YOLO no devolvió un resultado")?;
        Ok(count_people_boxes(result.boxes.as_ref()))
    }
    pub fn complete(&self, prompt: &str, image: Option<&[u8]>, options: &Value) -> Result<Value> {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?
            .block_on(inference::request_completion(
                &self.url,
                &self.model,
                prompt,
                image.map(|b| (b, "image/jpeg")),
                options,
            ))
    }
    pub fn warm_text(&self) -> Result<String> {
        Ok(text(&self.complete("Responde exactamente OK.", None, &json!({}))?["content"]).into())
    }
    pub fn warm_vision(&self) -> Result<String> {
        let bytes = std::fs::read(self.root.join("public/prepare_image.png"))?;
        let response = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?
            .block_on(inference::request_completion(
                &self.url,
                &self.model,
                "¿Cuántas personas hay? Responde solo con el número.",
                Some((&bytes, "image/png")),
                &json!({}),
            ))?;
        Ok(text(&response["content"]).into())
    }
}
fn count_people_boxes(boxes: Option<&ultralytics_inference::Boxes>) -> usize {
    boxes.map_or(0, |b| b.cls().iter().filter(|&&class| class == 0.).count())
}
pub fn capture_evidence() -> Result<(Vec<u8>, String)> {
    let photo = tempfile::Builder::new().suffix(".jpg").tempfile()?;
    let mut command = if cfg!(target_os = "linux") {
        let mut c = std::process::Command::new("rpicam-still");
        c.args([
            "--nopreview",
            "--width",
            "1280",
            "--height",
            "960",
            "--timeout",
            "2000",
            "--encoding",
            "jpg",
            "--output",
        ]);
        c.arg(photo.path());
        c
    } else if cfg!(target_os = "macos") {
        let mut c = std::process::Command::new("ffmpeg");
        c.args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "avfoundation",
            "-framerate",
            "30",
            "-i",
            "0:none",
            "-ss",
            "2",
            "-frames:v",
            "1",
            "-y",
        ]);
        c.arg(photo.path());
        c
    } else {
        return Err("Captura no disponible en este sistema.".into());
    };
    let output = command.output()?;
    if !output.status.success() {
        return Err(format!(
            "No se pudo capturar: {}",
            String::from_utf8_lossy(&output.stderr)
        )
        .into());
    }
    let captured_at: chrono::DateTime<chrono::Utc> = photo.as_file().metadata()?.modified()?.into();
    let bytes = std::fs::read(photo.path())?;
    if bytes.is_empty() {
        return Err("La cámara no devolvió una imagen.".into());
    }
    Ok((
        bytes,
        captured_at.to_rfc3339_opts(chrono::SecondsFormat::Micros, false),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn counts_only_people_and_preserves_zero() {
        use ultralytics_inference::Boxes;
        let boxes = Boxes::new(
            ndarray::array![
                [0., 0., 20., 20., 0.9, 0.],
                [0., 0., 20., 20., 0.8, 2.],
                [0., 0., 20., 20., 0.7, 0.]
            ],
            (480, 640),
        );
        assert_eq!(count_people_boxes(Some(&boxes)), 2);
        assert_eq!(
            count_people_boxes(Some(&Boxes::new(
                ndarray::Array2::zeros((0, 6)),
                (480, 640)
            ))),
            0
        );
        assert_eq!(count_people_boxes(None), 0);
    }
}
