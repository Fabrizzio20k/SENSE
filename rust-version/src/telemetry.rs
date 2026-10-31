use crate::contracts::*;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use sysinfo::{Disks, Pid, System};
pub fn budget_reason(r: &Value, c: &Value) -> Option<&'static str> {
    if number(&r["available_mb"]) < number(&c["min_available_mb"])
        || number(&r["main"]["rss_mb"]) > number(&c["max_rss_mb"])
    {
        Some("INSUFFICIENT_MEMORY")
    } else if number(&r["cpu_total_percent"]) >= number(&c["max_cpu_percent"]) {
        Some("CPU_BUDGET")
    } else if number(&r["database_mb"]) >= number(&c["max_database_mb"])
        || number(&r["disk_free_mb"]) < number(&c["min_disk_free_mb"])
    {
        Some("STORAGE_BUDGET")
    } else {
        None
    }
}
pub struct ResourceMonitor {
    database: PathBuf,
    system: System,
    peak_rss: u64,
}
impl ResourceMonitor {
    pub fn new(database: &Path) -> Self {
        Self {
            database: database.into(),
            system: System::new_all(),
            peak_rss: 0,
        }
    }
    pub fn sample(&mut self) -> Value {
        self.system.refresh_all();
        let pid = Pid::from_u32(std::process::id());
        let p = self.system.process(pid);
        let rss = p.map(|p| p.memory()).unwrap_or(0);
        let cpu = p.map(|p| p.cpu_usage()).unwrap_or(0.);
        self.peak_rss = self.peak_rss.max(rss);
        let mb = |bytes: u64| rounded(bytes as f64 / 1048576., 2);
        let workers:Vec<_>=self.system.processes().iter().filter(|(id,p)|**id!=pid&&(p.name().to_string_lossy().to_lowercase().contains("litert")||p.cmd().iter().any(|s|s.to_string_lossy().contains("litert-lm")))).map(|(id,p)|json!({"pid":id.as_u32(),"name":p.name().to_string_lossy(),"cpu_percent":rounded(f64::from(p.cpu_usage()),2),"rss_mb":mb(p.memory())})).collect();
        let mut swap = None;
        let mut peak = None;
        if let Ok(status) = std::fs::read_to_string("/proc/self/status") {
            for line in status.lines() {
                if let Some(value) = line
                    .split_whitespace()
                    .nth(1)
                    .and_then(|v| v.parse::<f64>().ok())
                {
                    if line.starts_with("VmSwap:") {
                        swap = Some(value / 1024.);
                    }
                    if line.starts_with("VmHWM:") {
                        peak = Some(value / 1024.);
                    }
                }
            }
        }
        let temp = std::fs::read_to_string("/sys/class/thermal/thermal_zone0/temp")
            .ok()
            .and_then(|s| s.trim().parse::<f64>().ok())
            .map(|n| n / 1000.);
        let throttled = if cfg!(target_os = "linux") {
            std::process::Command::new("vcgencmd")
                .arg("get_throttled")
                .stdout(std::process::Stdio::piped())
                .spawn()
                .ok()
                .and_then(|mut child| {
                    let start = std::time::Instant::now();
                    loop {
                        if child.try_wait().ok().flatten().is_some() {
                            return child
                                .wait_with_output()
                                .ok()
                                .and_then(|o| String::from_utf8(o.stdout).ok())
                                .filter(|s| !s.trim().is_empty())
                                .map(|s| s.trim().to_owned());
                        }
                        if start.elapsed().as_millis() >= 500 {
                            let _ = child.kill();
                            let _ = child.wait();
                            return None;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(10));
                    }
                })
        } else {
            None
        };
        let parent = self.database.parent().unwrap_or(Path::new("."));
        let name = self.database.file_name().unwrap().to_string_lossy();
        let size: u64 = std::fs::read_dir(parent)
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().starts_with(name.as_ref()))
            .filter_map(|e| e.metadata().ok())
            .filter(|m| m.is_file())
            .map(|m| m.len())
            .sum();
        let disks = Disks::new_with_refreshed_list();
        let canonical = parent.canonicalize().unwrap_or(parent.into());
        let disk = disks
            .iter()
            .filter(|d| canonical.starts_with(d.mount_point()))
            .max_by_key(|d| d.mount_point().as_os_str().len());
        json!({"sampled_at":utc_now(),"sampled_monotonic":monotonic(),"cpu_total_percent":rounded(f64::from(self.system.global_cpu_usage()),2),"available_mb":rounded(self.system.available_memory() as f64/1048576.,2),"ram_used_mb":mb(self.system.used_memory()),"ram_total_mb":mb(self.system.total_memory()),"main":{"pid":std::process::id(),"cpu_percent":rounded(f64::from(cpu),2),"rss_mb":mb(rss),"peak_rss_mb":peak.map(|v|rounded(v,2)).unwrap_or(mb(self.peak_rss)),"swap_mb":swap.map(|v|rounded(v,2))},"gemma_processes":workers,"swap_used_mb":mb(self.system.used_swap()),"temperature_c":temp,"throttled":throttled,"database_mb":rounded(size as f64/1048576.,2),"disk_free_mb":disk.map(|d|(d.available_space() as f64/1048576.).round_ties_even())})
    }
}
