use crate::Result;
use base64::prelude::*;
use serde_json::{Value, json};
pub fn request_payload(
    model: &str,
    prompt: &str,
    image: Option<(&[u8], &str)>,
    options: &Value,
) -> Value {
    let content = if let Some((raw, mime)) = image {
        json!([{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":format!("data:{mime};base64,{}",BASE64_STANDARD.encode(raw))}}])
    } else {
        json!(prompt)
    };
    let mut messages = vec![];
    if let Some(system) = options["system_prompt"].as_str() {
        messages.push(json!({"role":"system","content":system}));
    }
    messages.push(json!({"role":"user","content":content}));
    let mut payload = json!({"model":model,"messages":messages,"max_completion_tokens":options.get("max_tokens").unwrap_or(&json!(64))});
    for key in ["temperature", "response_format"] {
        if let Some(v) = options.get(key).filter(|v| !v.is_null()) {
            payload[key] = v.clone();
        }
    }
    payload
}
pub fn log_payload(p: &Value) -> Value {
    let mut redacted = p.clone();
    for m in redacted["messages"].as_array_mut().unwrap() {
        if let Some(items) = m["content"].as_array_mut() {
            for item in items {
                *item = json!({"type":item["type"],"text":item.get("text").unwrap_or(&json!("[imagen omitida]"))});
            }
        }
    }
    redacted
}
pub async fn request_completion(
    url: &str,
    model: &str,
    prompt: &str,
    image: Option<(&[u8], &str)>,
    options: &Value,
) -> Result<Value> {
    let payload = request_payload(model, prompt, image, options);
    tracing::warn!("SENSE_LLM_REQUEST {}", log_payload(&payload));
    let result=async{let response=reqwest::Client::new().post(url).timeout(std::time::Duration::from_secs_f64(options["timeout_seconds"].as_f64().unwrap_or(180.))).json(&payload).send().await?.error_for_status()?;let body:Value=response.json().await?;let content=body["choices"][0]["message"]["content"].as_str().ok_or("Gemma no devolvió texto.")?;let result=json!({"content":content.trim(),"usage":body["usage"],"finish_reason":body["choices"][0]["finish_reason"],"model":body.get("model").unwrap_or(&json!(model))});tracing::warn!("SENSE_LLM_RESPONSE {result}");Ok::<_,crate::Error>(result)}.await;
    if let Err(e) = &result {
        tracing::error!("SENSE_LLM_FAILURE {e}");
    }
    result
}
