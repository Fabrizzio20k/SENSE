mod common;
use common::{ApiHarness, config, resources};
use sense_people_counter::telemetry::{ResourceMonitor, budget_reason};
use serde_json::{Value, json};

#[test]
fn storage_budget_allows_up_to_ten_gib_and_keeps_free_space_guard() {
    let cfg = config();
    assert_eq!(cfg["runtime"]["max_database_mb"], 10240);
    let mut sample = resources();
    sample["database_mb"] = json!(10239.99);
    assert_eq!(budget_reason(&sample, &cfg["runtime"]), None);
    sample["database_mb"] = json!(10240);
    assert_eq!(
        budget_reason(&sample, &cfg["runtime"]),
        Some("STORAGE_BUDGET")
    );
    sample["database_mb"] = json!(512);
    sample["disk_free_mb"] = json!(255);
    assert_eq!(
        budget_reason(&sample, &cfg["runtime"]),
        Some("STORAGE_BUDGET")
    );
}

fn assert_two_decimal_numbers(document: &Value, keys: &[&str]) {
    for key in keys {
        let value = &document[*key];
        if value.is_null() {
            continue;
        }
        let serialized = serde_json::to_string(value).unwrap();
        assert!(value.is_number(), "{key}: {serialized}");
        assert!(!serialized.contains(['e', 'E']), "{key}: {serialized}");
        assert!(
            serialized
                .split_once('.')
                .is_none_or(|(_, fraction)| fraction.len() <= 2),
            "{key}: {serialized}"
        );
    }
}

#[test]
fn api_and_recorded_resources_keep_numeric_cpu_and_ram_with_at_most_two_decimals() {
    let harness = ApiHarness::new();
    assert_two_decimal_numbers(
        &harness.app.snapshot()["system"],
        &["cpu_percent", "memory_percent", "memory_used_mb"],
    );
    let mut monitor = ResourceMonitor::new(&harness.temp.path().join("experiments.sqlite3"));
    let resources = monitor.sample();
    assert_two_decimal_numbers(
        &resources,
        &[
            "cpu_total_percent",
            "available_mb",
            "ram_used_mb",
            "ram_total_mb",
            "swap_used_mb",
        ],
    );
    assert_two_decimal_numbers(
        &resources["main"],
        &["cpu_percent", "rss_mb", "peak_rss_mb", "swap_mb"],
    );
    for process in resources["gemma_processes"].as_array().unwrap() {
        assert_two_decimal_numbers(process, &["cpu_percent", "rss_mb"]);
    }
}
