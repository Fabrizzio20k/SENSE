use crate::{Result, contracts::*, runtime::TaskOutput};
use serde::{
    Deserialize, Deserializer,
    de::{self, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Value, json};
use std::sync::Arc;
pub type Capture = Arc<dyn Fn() -> Result<(Vec<u8>, String)> + Send + Sync>;
pub type Detector = Arc<dyn Fn(&[u8]) -> Result<usize> + Send + Sync>;
pub type Completion = Arc<dyn Fn(&str, Option<&[u8]>, &Value) -> Result<Value> + Send + Sync>;
#[derive(Clone)]
pub struct Adapters {
    pub capture: Capture,
    pub detector: Detector,
    pub completion: Completion,
    pub model: String,
}
pub fn camera_rotation(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .filter(|v| [0, 90, 180, 270].contains(v))
        .ok_or_else(|| "La orientación debe ser 0, 90, 180 o 270 grados horarios.".into())
}
pub fn rotate_image(bytes: Vec<u8>, rotation: u64) -> Result<Vec<u8>> {
    camera_rotation(&json!(rotation))?;
    if rotation == 0 {
        return Ok(bytes);
    }
    let mut reader = image::ImageReader::new(std::io::Cursor::new(bytes)).with_guessed_format()?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(4096);
    limits.max_image_height = Some(4096);
    limits.max_alloc = Some(64 * 1024 * 1024);
    reader.limits(limits);
    let image = reader.decode()?;
    let image = match rotation {
        90 => image.rotate90(),
        180 => image.rotate180(),
        _ => image.rotate270(),
    };
    let mut out = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut out, 90).encode_image(&image)?;
    Ok(out)
}
struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Strict;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("JSON sin claves duplicadas")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut m: M,
            ) -> std::result::Result<Strict, M::Error> {
                let mut out = serde_json::Map::new();
                while let Some(k) = m.next_key::<String>()? {
                    if out.contains_key(&k) {
                        return Err(de::Error::custom(format!("Clave JSON duplicada: {k}")));
                    }
                    out.insert(k, m.next_value::<Strict>()?.0);
                }
                Ok(Strict(Value::Object(out)))
            }
            fn visit_seq<S: SeqAccess<'de>>(
                self,
                mut s: S,
            ) -> std::result::Result<Strict, S::Error> {
                let mut out = vec![];
                while let Some(v) = s.next_element::<Strict>()? {
                    out.push(v.0);
                }
                Ok(Strict(json!(out)))
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> std::result::Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> std::result::Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> std::result::Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> std::result::Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> std::result::Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_string<E: de::Error>(self, v: String) -> std::result::Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_unit<E: de::Error>(self) -> std::result::Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
        }
        d.deserialize_any(V)
    }
}
pub fn parse_json_object(s: &str) -> Result<Value> {
    Ok(serde_json::from_str::<Strict>(s)?.0)
}
pub fn prompt(question: &str, s: &Snapshot) -> String {
    let d = &s.document;
    let mut evidence = json!({});
    let mut statuses = json!({});
    if let Some(obs) = d["observations"].as_object() {
        for (k, v) in obs {
            evidence[k] = if v["status"] == "VALID" {
                v["value"].clone()
            } else {
                Value::Null
            };
            statuses[k] = v["status"].clone();
        }
    }
    let events: Vec<_> = list(&d["environment_events"])
        .into_iter()
        .rev()
        .take(4)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .map(|e| e["event_type"].clone())
        .collect();
    let source = if d["observations"]["presence"]["metadata"]["source_kind"] == "MANUAL_CONTROL" {
        "control manual"
    } else {
        "radar"
    };
    let mut health = json!({});
    if let Some(m) = d["component_health"].as_object() {
        for (k, v) in m {
            health[k] = v["status"].clone();
        }
    }
    if question == "Q6" {
        let ev = if events.is_empty() {
            "sin eventos ambientales confirmados".into()
        } else {
            events.iter().map(text).collect::<Vec<_>>().join(" y ")
        };
        let val = |k: &str| {
            if evidence[k].is_null() {
                "None".into()
            } else {
                evidence[k].to_string()
            }
        };
        format!(
            "Valores: <presence>={}; <presence_source>={source}; <count>={}; <events>={ev}. Estados: {}; salud observada: {}.",
            val("presence"),
            val("count"),
            python_json_ordered(&statuses),
            python_json_ordered(&health)
        )
    } else {
        format!(
            "Q7. Contexto: {}",
            python_json_compact(
                &json!({"observations":evidence,"events":events,"presence_source":source,"data_status":statuses,"component_health":health})
            )
        )
    }
}
pub fn system_prompt(q: &str) -> Option<&'static str> {
    match q {
        "Q6" => Some(
            "JSON: {\"inferences\":[\"\"],\"unknowns\":[\"\"],\"recommendations\":[\"\"]}. Una frase por lista. Copia esta estructura de inferencia: \"Presence=<presence> (fuente=<presence_source>); cámara count=<count>; eventos=<events> coinciden temporalmente, sin probar causalidad.\" No añadas etiquetas ni hechos. Unknowns: \"Estas fuentes no determinan la ocupación total ni la causa física de los fallos.\" Recomendación no crítica: monitorear los eventos listados.",
        ),
        "Q7" => Some(
            "JSON: {\"inferences\":[\"\"],\"unknowns\":[\"\"],\"recommendations\":[\"\"]}. Una frase breve por lista. La imagen adjunta es evidencia. Describe solo una observación visual no identificatoria; no nombres personas, no infieras cantidad ni reemplaces el conteo YOLO. No afirmes causalidad. Si la imagen no basta, indícalo en unknowns. Recomendación solo no crítica.",
        ),
        _ => None,
    }
}
impl Adapters {
    pub fn capture_oriented(&self, rotation: u64, max_bytes: usize) -> Result<(Vec<u8>, String)> {
        let (bytes, captured) = (self.capture)()?;
        if bytes.len() > max_bytes {
            return Err("La imagen excede el límite de memoria autorizado.".into());
        }
        let bytes = rotate_image(bytes, rotation)?;
        if bytes.len() > max_bytes {
            return Err("La imagen orientada excede el límite de memoria autorizado.".into());
        }
        Ok((bytes, captured))
    }
    pub fn vision(&self, command: &Value, max_bytes: usize) -> Result<TaskOutput> {
        let start = monotonic();
        let rotation = camera_rotation(
            command["parameters"]
                .get("camera_rotation_degrees")
                .unwrap_or(&json!(0)),
        )?;
        let (image, captured) = self.capture_oriented(rotation, max_bytes)?;
        let capture_seconds = monotonic() - start;
        let infer = monotonic();
        let count = (self.detector)(&image)?;
        Ok(TaskOutput {
            data: json!({"count":count,"image_id":identifier(),"captured_at":captured,"camera_rotation_degrees":rotation,"region":command["parameters"]["region"],"capture_seconds":capture_seconds,"inference_seconds":monotonic()-infer,"quality":"uncalibrated_camera_coverage"}),
            image: Some(Arc::new(image)),
        })
    }
    pub fn interpret(
        &self,
        command: &Value,
        s: &Snapshot,
        image: Option<&[u8]>,
        config: &Value,
        prompt: &str,
    ) -> Result<TaskOutput> {
        let started_at = utc_now();
        let start = monotonic();
        let mut options = config.clone();
        options["response_format"] = json!({"type":"json_object"});
        options["system_prompt"] =
            json!(system_prompt(text(&command["parameters"]["question_id"])));
        options["temperature"] = json!(0);
        let response = (self.completion)(prompt, image, &options)?;
        let mut result = json!({"interpretation_id":identifier(),"request_id":command["command_id"],"snapshot_id":s.snapshot_id,"image_id":command["parameters"]["image_id"],"model_id":self.model,"runtime_model_id":response.get("model").unwrap_or(&json!(self.model)),"started_at":started_at,"completed_at":utc_now(),"question_id":command["parameters"]["question_id"],"inference_seconds":monotonic()-start,"raw_output":response["content"],"tokens":response["usage"],"validation_status":"REJECTED"});
        let validated = (|| -> Result<Value> {
            let parsed = parse_json_object(text(&response["content"]))?;
            let fields = ["inferences", "unknowns", "recommendations"];
            if !parsed.is_object() || fields.iter().any(|f| !parsed[*f].is_array()) {
                return Err("Contrato de interpretación incompleto.".into());
            }
            if fields.iter().any(|f| {
                list(&parsed[*f])
                    .iter()
                    .any(|v| v.as_str().is_none_or(|s| s.chars().count() > 2000))
            }) {
                return Err("La interpretación contiene texto inválido.".into());
            }
            let facts: Vec<_> = s.document["observations"]
                .as_object()
                .unwrap()
                .values()
                .filter(|v| v["status"] == "VALID")
                .map(|v| json!({"evidence_id":v["observation_id"],"value":v["value"]}))
                .collect();
            let mut refs: Vec<_> = facts.iter().map(|f| f["evidence_id"].clone()).collect();
            if command["action"] == "multimodal" {
                if image.is_none() || !truth(&result["image_id"]) {
                    return Err("La interpretación multimodal requiere imagen autorizada.".into());
                }
                refs.push(result["image_id"].clone());
            }
            if refs.is_empty() {
                return Err("No hay evidencia válida para atribuir.".into());
            }
            let mut validated = parsed;
            validated["observed_facts"] = json!(facts);
            validated["evidence_references"] = json!(refs);
            Ok(validated)
        })();
        match validated {
            Ok(v) => {
                for field in [
                    "inferences",
                    "unknowns",
                    "recommendations",
                    "observed_facts",
                    "evidence_references",
                ] {
                    result[field] = v[field].clone();
                }
                result["validation_status"] = json!("VALIDATED");
            }
            Err(e) => {
                result["validation_error"] = json!(e.to_string());
            }
        }
        Ok(result.into())
    }
}
