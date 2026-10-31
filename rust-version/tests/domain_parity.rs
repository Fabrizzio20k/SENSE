use sense_people_counter::{
    acquisition, config,
    context::ContextStore,
    contracts::*,
    policy::{self, PolicyEngine},
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet};
fn norm(v: &Value) -> Value {
    match v {
        Value::Object(m) => Value::Object(
            m.iter()
                .filter(|(k, _)| !["event_id", "snapshot_id", "created_at"].contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), norm(v)))
                .collect(),
        ),
        Value::Array(a) => json!(a.iter().map(norm).collect::<Vec<_>>()),
        Value::Number(_) => json!(v.as_f64().unwrap()),
        _ => v.clone(),
    }
}
fn run_case(name: &str) {
    static FIXTURE: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    let fixture = FIXTURE.get_or_init(|| {
        use std::io::Read;
        let mut archive = zip::ZipArchive::new(std::io::Cursor::new(
            include_bytes!("fixtures/python_domain.zip").as_slice(),
        ))
        .unwrap();
        let mut data = String::new();
        archive
            .by_name("python_domain.json")
            .unwrap()
            .read_to_string(&mut data)
            .unwrap();
        serde_json::from_str(&data).unwrap()
    });
    let ops = list(&fixture["cases"][name]);
    assert!(!ops.is_empty(), "{name}");
    let mut contexts: BTreeMap<String, ContextStore> = BTreeMap::new();
    let mut policies: BTreeMap<String, PolicyEngine> = BTreeMap::new();
    for (index, op) in ops.iter().enumerate() {
        let id = text(&op["id"]);
        let a = list(&op["args"]);
        let arg = |i: usize| a.get(i).cloned().unwrap_or(Value::Null);
        let result: sense_people_counter::Result<Value> = match text(&op["op"]) {
            "validate_config" => config::validate_config(&op["config"]).map(|_| Value::Null),
            "context_new" => {
                contexts.insert(id.into(), ContextStore::new(arg(0)));
                continue;
            }
            "policy_new" => {
                policies.insert(
                    id.into(),
                    PolicyEngine::new(arg(0), text(&arg(1)), number(&arg(2))),
                );
                continue;
            }
            "acquisition" => {
                let p = arg(0);
                let received = arg(1);
                let region = arg(2);
                let mut result = if op["kind"] == "EnvironmentAgent" {
                    acquisition::environment(&p, text(&received), text(&region))
                } else {
                    acquisition::presence(&p, text(&received), text(&region))
                };
                let mut expected = op["result"].clone();
                if op["kind"] == "EnvironmentAgent" {
                    for v in result.as_object_mut().unwrap().values_mut() {
                        v.as_object_mut().unwrap().remove("observation_id");
                    }
                    for v in expected.as_object_mut().unwrap().values_mut() {
                        v.as_object_mut().unwrap().remove("observation_id");
                    }
                } else {
                    result.as_object_mut().unwrap().remove("observation_id");
                    expected.as_object_mut().unwrap().remove("observation_id");
                }
                assert_eq!(
                    norm(&result),
                    norm(&expected),
                    "{name} operation {index} acquisition"
                );
                continue;
            }
            "context_call" => {
                let c = contexts.get_mut(id).unwrap();
                if !op["config"].is_null() {
                    c.config = op["config"].clone();
                    c.environment.config = c.config["environment"].clone();
                }
                match text(&op["method"]) {
                    "ingest" => {
                        let radar = arg(1);
                        let captured = op["kwargs"]["captured_at"].clone();
                        c.ingest(
                            &arg(0),
                            if radar.is_null() { None } else { Some(&radar) },
                            number(&arg(2)),
                            number(&arg(3)),
                            if captured.is_null() {
                                None
                            } else {
                                Some(&captured)
                            },
                        )
                        .map(|v| json!(v))
                    }
                    "put" => {
                        c.put(
                            text(&arg(0)),
                            arg(1),
                            number(&arg(2)),
                            a.get(3).map(number).unwrap_or(0.),
                        );
                        Ok(Value::Null)
                    }
                    "snapshot" => Ok(c.snapshot(number(&arg(0))).document),
                    m => panic!("Unknown context {m}"),
                }
            }
            "policy_call" => {
                let p = policies.get_mut(id).unwrap();
                if !op["config"].is_null() {
                    p.config = op["config"].clone();
                }
                match text(&op["method"]) {
                    "observe_presence" => p
                        .observe_presence(&arg(0), number(&arg(1)))
                        .map(|v| json!(v)),
                    "vision" => {
                        let resource = arg(5);
                        let d = p.vision(
                            &arg(0),
                            number(&arg(1)),
                            &list(&arg(2)),
                            truth(&arg(3)),
                            truth(&arg(4)),
                            resource.as_str(),
                        );
                        Ok(json!({"action":d.action,"question_id":d.question_id,"reason":d.reason}))
                    }
                    "accepted_vision" => {
                        p.accepted_vision(number(&arg(0)));
                        Ok(Value::Null)
                    }
                    "request_visual_count" => {
                        p.request_visual_count();
                        Ok(Value::Null)
                    }
                    "interpretation" => {
                        let attempted: HashSet<_> =
                            list(&arg(4)).iter().map(|s| text(s).into()).collect();
                        let resource = arg(6);
                        let d = p.interpretation(
                            text(&arg(0)),
                            &arg(1),
                            number(&arg(2)),
                            text(&arg(3)),
                            &attempted,
                            truth(&arg(5)),
                            resource.as_str(),
                        );
                        Ok(json!({"action":d.action,"question_id":d.question_id,"reason":d.reason}))
                    }
                    "accepted_interpretation" => {
                        p.accepted_interpretation(text(&arg(0)), number(&arg(1)));
                        Ok(Value::Null)
                    }
                    "information_needs" => Ok(p.information_needs(&arg(0), &arg(1))),
                    "reset_reactive" => {
                        p.reset_reactive();
                        Ok(Value::Null)
                    }
                    "reactive_view" => Ok(p.reactive_view(&arg(0))),
                    "visual_need" => Ok(json!(p.visual_need(&arg(0), &list(&arg(1))))),
                    m => panic!("Unknown policy {m}"),
                }
            }
            "answer_questions" => {
                let d = arg(0);
                let s = Snapshot {
                    snapshot_id: text(&d["snapshot_id"]).into(),
                    created_at: text(&d["created_at"]).into(),
                    document: d,
                };
                Ok(policy::answer_questions(
                    &s,
                    text(&arg(1)),
                    a.get(2).map(number).unwrap_or(60.),
                ))
            }
            "semantic_key" => {
                let image = arg(3);
                Ok(json!(policy::semantic_key(
                    text(&arg(0)),
                    &arg(1),
                    text(&arg(2)),
                    image.as_str()
                )))
            }
            other => panic!("Unknown op {other}"),
        };
        if truth(&op["error"]) {
            assert!(result.is_err(), "{name} op {index} expected error {op}");
        } else {
            let actual = result.unwrap_or_else(|e| panic!("{name} op {index}: {e}"));
            assert_eq!(
                norm(&actual),
                norm(&op["result"]),
                "{name} op {index} {}",
                text(&op["method"])
            );
        }
    }
}
#[test]
fn contexttests_test_actual_mqtt_shape_and_scope() {
    run_case("ContextTests__test_actual_mqtt_shape_and_scope");
}
#[test]
fn contexttests_test_aqi_plateau_and_humidity_full_rise_confirm_once() {
    run_case("ContextTests__test_aqi_plateau_and_humidity_full_rise_confirm_once");
}
#[test]
fn contexttests_test_comparable_regions_still_require_temporal_alignment() {
    run_case("ContextTests__test_comparable_regions_still_require_temporal_alignment");
}
#[test]
fn contexttests_test_coverage_not_comparable_unless_declared() {
    run_case("ContextTests__test_coverage_not_comparable_unless_declared");
}
#[test]
fn contexttests_test_eco2_crossing_can_start_just_below_threshold() {
    run_case("ContextTests__test_eco2_crossing_can_start_just_below_threshold");
}
#[test]
fn contexttests_test_eco2_crossing_rearm_and_no_startup_crossing() {
    run_case("ContextTests__test_eco2_crossing_rearm_and_no_startup_crossing");
}
#[test]
fn contexttests_test_gaps_break_environment_and_radar_confirmation() {
    run_case("ContextTests__test_gaps_break_environment_and_radar_confirmation");
}
#[test]
fn contexttests_test_histories_bounded() {
    run_case("ContextTests__test_histories_bounded");
}
#[test]
fn contexttests_test_humidity_percentage_points() {
    run_case("ContextTests__test_humidity_percentage_points");
}
#[test]
fn contexttests_test_invalid_reading_cannot_confirm() {
    run_case("ContextTests__test_invalid_reading_cannot_confirm");
}
#[test]
fn contexttests_test_q4_distinguishes_warmup_from_no_confirmed_change() {
    run_case("ContextTests__test_q4_distinguishes_warmup_from_no_confirmed_change");
}
#[test]
fn contexttests_test_radar_debounce() {
    run_case("ContextTests__test_radar_debounce");
}
#[test]
fn contexttests_test_reject_duplicate_old_and_future_timestamps() {
    run_case("ContextTests__test_reject_duplicate_old_and_future_timestamps");
}
#[test]
fn contexttests_test_snapshot_immutable_and_stale() {
    run_case("ContextTests__test_snapshot_immutable_and_stale");
}
#[test]
fn contexttests_test_three_valid_readings_confirm_exactly_one_episode() {
    run_case("ContextTests__test_three_valid_readings_confirm_exactly_one_episode");
}
#[test]
fn contexttests_test_unknown_is_not_zero_and_invalid_breaks_confirmation() {
    run_case("ContextTests__test_unknown_is_not_zero_and_invalid_breaks_confirmation");
}
#[test]
fn policytests_test_a_schedule_and_missed_period() {
    run_case("PolicyTests__test_a_schedule_and_missed_period");
}
#[test]
fn policytests_test_b_never_uses_unknown_count_as_trigger() {
    run_case("PolicyTests__test_b_never_uses_unknown_count_as_trigger");
}
#[test]
fn policytests_test_budget_and_duplicates_skip() {
    run_case("PolicyTests__test_budget_and_duplicates_skip");
}
#[test]
fn policytests_test_cde_capture_only_for_a_visual_need() {
    run_case("PolicyTests__test_cde_capture_only_for_a_visual_need");
}
#[test]
fn policytests_test_dedup_ignores_timestamps_and_observation_ids() {
    run_case("PolicyTests__test_dedup_ignores_timestamps_and_observation_ids");
}
#[test]
fn policytests_test_environment_event_reuses_fresh_count() {
    run_case("PolicyTests__test_environment_event_reuses_fresh_count");
}
#[test]
fn policytests_test_explicit_count_request_uses_stale_or_missing_evidence() {
    run_case("PolicyTests__test_explicit_count_request_uses_stale_or_missing_evidence");
}
#[test]
fn policytests_test_no_text_slm_for_rule_resolved_question() {
    run_case("PolicyTests__test_no_text_slm_for_rule_resolved_question");
}
#[test]
fn policytests_test_required_limits_not_null() {
    run_case("PolicyTests__test_required_limits_not_null");
}
#[test]
fn reactivedistancetests_test_absence_confirms_exit_without_treating_missing_distance_as_zero() {
    run_case(
        "ReactiveDistanceTests__test_absence_confirms_exit_without_treating_missing_distance_as_zero",
    );
}
#[test]
fn reactivedistancetests_test_hysteresis_exit_cooldown_and_no_periodic_refresh() {
    run_case("ReactiveDistanceTests__test_hysteresis_exit_cooldown_and_no_periodic_refresh");
}
#[test]
fn reactivedistancetests_test_invalid_missing_zero_or_stale_distance_never_means_near() {
    run_case("ReactiveDistanceTests__test_invalid_missing_zero_or_stale_distance_never_means_near");
}
#[test]
fn reactivedistancetests_test_invalid_readings_and_gaps_break_confirmation() {
    run_case("ReactiveDistanceTests__test_invalid_readings_and_gaps_break_confirmation");
}
#[test]
fn reactivedistancetests_test_motion_and_both_targets_choose_only_relevant_valid_distances() {
    run_case(
        "ReactiveDistanceTests__test_motion_and_both_targets_choose_only_relevant_valid_distances",
    );
}
#[test]
fn reactivedistancetests_test_near_at_start_triggers_after_three_fresh_samples() {
    run_case("ReactiveDistanceTests__test_near_at_start_triggers_after_three_fresh_samples");
}
#[test]
fn reactivedistancetests_test_persistent_far_presence_never_triggers_even_if_count_stale() {
    run_case(
        "ReactiveDistanceTests__test_persistent_far_presence_never_triggers_even_if_count_stale",
    );
}
#[test]
fn reactivedistancetests_test_raw_presence_events_do_not_bypass_distance_rule() {
    run_case("ReactiveDistanceTests__test_raw_presence_events_do_not_bypass_distance_rule");
}
#[test]
fn reactivedistancetests_test_repeated_evaluation_does_not_count_as_new_sensor_samples() {
    run_case(
        "ReactiveDistanceTests__test_repeated_evaluation_does_not_count_as_new_sensor_samples",
    );
}
#[test]
fn reactivedistancetests_test_threshold_is_strict_and_invalid_rearm_blocks_start() {
    run_case("ReactiveDistanceTests__test_threshold_is_strict_and_invalid_rearm_blocks_start");
}
#[test]
fn reactivedistancetests_test_uses_active_target_distance_and_preserves_raw_measurements() {
    run_case(
        "ReactiveDistanceTests__test_uses_active_target_distance_and_preserves_raw_measurements",
    );
}
#[test]
fn reactivedistancetests_test_zero_total_distance_does_not_turn_absence_into_presence() {
    run_case("ReactiveDistanceTests__test_zero_total_distance_does_not_turn_absence_into_presence");
}
#[test]
fn environment_history_stays_bounded() {
    let mut config = config::load_config(
        &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("sense/pilot.yaml"),
    )
    .unwrap();
    config["environment"]["history_capacity"] = json!(4);
    let mut context = ContextStore::new(config);
    for second in 0..550 {
        let p = json!({"timestamp":"2026-10-24T00:00:00Z","environment":{"sht40":{"temperature_c":26.,"humidity_percent":70.},"ens160":{"aqi":2,"tvoc_ppb":70,"eco2_ppm":500}}});
        let observations = acquisition::environment(&p, "2026-10-24T00:00:00Z", "sensor_location");
        context.environment.update(&observations, second as f64);
    }
    for history in context.environment.history.values() {
        assert_eq!(history.len(), 4);
    }
    assert_eq!(
        context.environment.baseline["temperature"]["captured_epoch_s"],
        0.0
    );
}
