from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    try:
        with path.open() as source:
            config = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise ValueError("Configuración YAML inválida: " + str(error)) from error
    if not isinstance(config, dict):
        raise ValueError("La configuración debe ser un objeto YAML.")
    validate_config(config)
    config["config_hash"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    return config


def validate_config(config: dict) -> None:
    for section in ("environment", "vision", "interpretation", "runtime", "sensors", "modes", "regions"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"Falta la sección de configuración {section}.")
    positive = {
        "environment": ("window_seconds", "reference_tolerance_seconds", "confirmation_samples", "max_confirmation_gap_seconds", "history_capacity",
                        "temperature_rise_c", "humidity_rise_pp", "aqi_increase_levels", "eco2_threshold_ppm_equiv"),
        "vision": ("ttl_seconds", "cooldown_seconds", "max_requests_per_window", "request_window_seconds", "timeout_seconds", "image_ttl_seconds", "max_image_bytes"),
        "interpretation": ("queue_capacity", "relationship_alignment_seconds"),
        "runtime": ("tick_seconds", "evaluation_interval_seconds", "publish_interval_seconds", "cycle_timeout_seconds", "max_cycle_requests", "max_run_seconds", "inbox_capacity", "min_available_mb", "max_rss_mb", "max_cpu_percent", "resource_interval_seconds", "max_database_mb", "min_disk_free_mb"),
        "sensors": ("environment_ttl_seconds", "presence_ttl_seconds", "max_future_skew_seconds"),
        "modes": ("periodic_interval_seconds", "reactive_debounce_samples", "reactive_min_interval_seconds", "reactive_enter_below_cm", "reactive_exit_at_or_above_cm"),
        "regions": ("comparison_max_skew_seconds",),
    }
    for section, names in positive.items():
        for name in names:
            value = config.get(section, {}).get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Falta un límite positivo: {section}.{name}")
    if config["modes"]["reactive_exit_at_or_above_cm"] <= config["modes"]["reactive_enter_below_cm"]:
        raise ValueError("El umbral de salida reactiva debe superar al de entrada.")
    for section, name in (("environment", "confirmation_samples"), ("environment", "history_capacity"),
                          ("vision", "max_requests_per_window"), ("vision", "max_image_bytes"),
                          ("interpretation", "queue_capacity"), ("runtime", "inbox_capacity"),
                          ("runtime", "max_cycle_requests"), ("modes", "reactive_debounce_samples")):
        if type(config[section][name]) is not int:
            raise ValueError(f"Se requiere un entero: {section}.{name}")
    env = config["environment"]
    for name, threshold in (("temperature_rearm_c", "temperature_rise_c"), ("humidity_rearm_pp", "humidity_rise_pp"),
                            ("aqi_rearm_levels", "aqi_increase_levels"), ("eco2_rearm_threshold", "eco2_threshold_ppm_equiv")):
        value = env.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < env[threshold]:
            raise ValueError(f"Defina environment.{name} por debajo de {threshold} antes de iniciar.")
    if config["interpretation"].get("max_concurrent") != 1:
        raise ValueError("El piloto admite una sola inferencia Gemma activa.")
    for kind in ("textual", "multimodal"):
        budget = config["interpretation"].get(kind)
        if not isinstance(budget, dict):
            raise ValueError(f"Falta interpretation.{kind}.")
        for name in ("timeout_seconds", "cooldown_seconds", "max_requests_per_window", "request_window_seconds", "max_tokens"):
            value = budget.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Falta un límite positivo: interpretation.{kind}.{name}")
            if name in ("max_requests_per_window", "max_tokens") and type(value) is not int:
                raise ValueError(f"Se requiere un entero: interpretation.{kind}.{name}")
    if not config.get("config_version") or not config.get("hardware_profile"):
        raise ValueError("Faltan config_version o hardware_profile.")
    if not isinstance(config.get("enabled_modes"), list) or not config["enabled_modes"] or any(not isinstance(m, str) or m not in list("ABCDEF") for m in config["enabled_modes"]):
        raise ValueError("enabled_modes debe contener modos A–F.")
    for name in ("radar_region", "camera_region", "environment_region"):
        if not isinstance(config.get("regions", {}).get(name), str) or not config["regions"][name]:
            raise ValueError(f"Falta regions.{name}.")
    if type(config["regions"].get("radar_camera_comparable")) is not bool:
        raise ValueError("regions.radar_camera_comparable debe ser booleano.")
