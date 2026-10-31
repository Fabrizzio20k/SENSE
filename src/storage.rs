use crate::{Result, context::timestamp, contracts::*, protocol::validate_observation};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
pub struct ExperimentLog {
    pub path: PathBuf,
    pub db: Connection,
}
impl ExperimentLog {
    pub fn save_image(&self, run: &str, image: &str, bytes: &[u8]) -> Result<()> {
        self.db.execute(
            "INSERT INTO images(run_id,image_id,jpeg) VALUES (?,?,?)",
            params![run, image, bytes],
        )?;
        Ok(())
    }
    pub fn reader(path: &Path) -> Result<Self> {
        let db = Connection::open(path)?;
        db.busy_timeout(std::time::Duration::from_secs(5))?;
        Ok(Self {
            path: path.into(),
            db,
        })
    }
    pub fn new(path: &Path) -> Result<Self> {
        if let Some(p) = path.parent() {
            std::fs::create_dir_all(p)?;
        }
        let log = Self::reader(path)?;
        log.db.execute_batch("PRAGMA journal_mode=WAL;")?;
        log.db.execute_batch(include_str!("../sense/schema.sql"))?;
        let ids: Vec<String> = log
            .db
            .prepare("SELECT run_id FROM runs WHERE status='RUNNING'")?
            .query_map([], |r| r.get(0))?
            .collect::<std::result::Result<_, _>>()?;
        log.transaction(||{for id in ids{log.event(&id,"RUN_INTERRUPTED",&json!({"reason":"PROCESS_RESTART"}))?;let mut meta=log.run(&id)?.unwrap();let duration=meta["duration_seconds"].as_f64().or(meta["config"]["runtime"]["max_run_seconds"].as_f64()).unwrap_or(1800.);let elapsed=(wall_time()-timestamp(&meta["start_time"])?).max(0.).min(duration);let expected=duration.ceil().min(elapsed.ceil().max(1.)) as i64;let last:Option<i64>=log.db.query_row("SELECT max(second) FROM samples_1s WHERE run_id=?",[&id],|r|r.get(0))?;if let Some(last)=last.filter(|s|s+1<expected){log.event(&id,"SAMPLE_GAP",&json!({"from_second":last+1,"to_second":expected-1,"reason":"PROCESS_RESTART"}))?;}
            meta["elapsed_s"]=json!(elapsed);meta["expected_samples"]=json!(expected);meta["finish_reason"]=json!("PROCESS_RESTART");meta["interruption_detected_at"]=json!(utc_now());meta["end_time_uncertain"]=json!(true);if truth(&meta["guided"]){log.request_observer(&id,"RUN_FINAL",&["power_w","visible_people","action"],None,None,None)?;}log.finish(&id,"INTERRUPTED",Some(&meta))?;}Ok(())})?;
        Ok(log)
    }
    pub fn transaction<T>(&self, f: impl FnOnce() -> Result<T>) -> Result<T> {
        let own = self.db.is_autocommit();
        if own {
            self.db.execute_batch("BEGIN")?;
        }
        match f() {
            Ok(v) => {
                if own {
                    self.db.execute_batch("COMMIT")?;
                }
                Ok(v)
            }
            Err(e) => {
                if own {
                    let _ = self.db.execute_batch("ROLLBACK");
                }
                Err(e)
            }
        }
    }
    pub fn begin(&self, m: &Value) -> Result<()> {
        self.transaction(|| {
            self.db.execute(
                "INSERT INTO runs VALUES (?, ?, NULL, 'RUNNING', ?)",
                params![text(&m["run_id"]), text(&m["start_time"]), m.to_string()],
            )?;
            Ok(())
        })
    }
    pub fn finish(&self, id: &str, status: &str, meta: Option<&Value>) -> Result<()> {
        self.transaction(|| {
            self.db.execute(
                "UPDATE runs SET ended_at=?, status=? WHERE run_id=?",
                params![utc_now(), status, id],
            )?;
            if let Some(m) = meta {
                self.db.execute(
                    "UPDATE runs SET metadata=? WHERE run_id=?",
                    params![m.to_string(), id],
                )?;
            }
            Ok(())
        })
    }
    pub fn event(&self, id: &str, kind: &str, p: &Value) -> Result<()> {
        self.transaction(|| {
            self.db.execute(
                "INSERT INTO events(run_id,timestamp,type,payload) VALUES (?,?,?,?)",
                params![id, utc_now(), kind, p.to_string()],
            )?;
            Ok(())
        })
    }
    pub fn run(&self, id: &str) -> Result<Option<Value>> {
        let row: Option<(String, Option<String>, String)> = self
            .db
            .query_row(
                "SELECT metadata,ended_at,status FROM runs WHERE run_id=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        row.map(|(m, end, status)| {
            let mut m: Value = serde_json::from_str(&m)?;
            m["end_time"] = json!(end);
            m["status"] = json!(status);
            Ok(m)
        })
        .transpose()
    }
    pub fn runs(&self) -> Result<Value> {
        let rows:Vec<(String,String,Option<String>,String,String)>=self.db.prepare("SELECT run_id,started_at,ended_at,status,metadata FROM runs ORDER BY started_at DESC LIMIT 100")?.query_map([],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?)))?.collect::<std::result::Result<_,_>>()?;
        let mut out = vec![];
        for (id, start, end, status, meta) in rows {
            let m: Value = serde_json::from_str(&meta)?;
            let mut row = json!({"run_id":id,"start_time":start,"end_time":end,"status":status,"quality":self.quality(&id)?});
            for k in ["mode", "scenario_id", "repetition", "guided"] {
                if let Some(v) = m.get(k) {
                    row[k] = v.clone();
                }
            }
            out.push(row);
        }
        Ok(json!(out))
    }
    pub fn events(&self, id: &str, after: i64, limit: usize) -> Result<Vec<Value>> {
        let rows:Vec<(i64,String,String,String)>=self.db.prepare("SELECT sequence,timestamp,type,payload FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?")?.query_map(params![id,after,limit.min(200) as i64],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?)))?.collect::<std::result::Result<_,_>>()?;
        rows.into_iter().map(|(seq,at,kind,p)|Ok(json!({"sequence":seq,"timestamp":at,"type":kind,"payload":serde_json::from_str::<Value>(&p)?}))).collect()
    }
    pub fn human_record(&self, id: &str, kind: &str, p: &Value) -> Result<String> {
        let record = identifier();
        self.transaction(|| {
            self.db.execute(
                "INSERT INTO human_records VALUES (?,?,?,?,?)",
                params![record, id, utc_now(), kind, p.to_string()],
            )?;
            Ok(())
        })?;
        Ok(record)
    }
    pub fn sample(&self, id: &str, second: i64, p: &Value) -> Result<()> {
        self.transaction(|| {
            self.db.execute(
                "INSERT INTO samples_1s VALUES (?,?,?,?)",
                params![id, second, text(&p["timestamp_utc"]), p.to_string()],
            )?;
            Ok(())
        })
    }
    pub fn request_observer(
        &self,
        id: &str,
        reason: &str,
        fields: &[&str],
        task: Option<&str>,
        event_id: Option<&str>,
        requested: Option<&str>,
    ) -> Result<String> {
        let request = identifier();
        let at = requested.map(str::to_owned).unwrap_or_else(utc_now);
        self.transaction(||{self.db.execute("INSERT INTO observer_requests VALUES (?,?,?,?,?,?,?,'PENDING',NULL)",params![request,id,at,reason,task,event_id,json!(fields).to_string()])?;self.event(id,"OBSERVER_REQUESTED",&json!({"request_id":request,"reason":reason,"task_id":task,"event_id":event_id,"fields":fields,"requested_at":at}))})?;
        Ok(request)
    }
    pub fn observer_requests(&self, id: &str, pending: bool) -> Result<Vec<Value>> {
        let sql = format!(
            "SELECT request_id,requested_at,reason,task_id,event_id,fields,status,record_id FROM observer_requests WHERE run_id=? {} ORDER BY rowid",
            if pending { "AND status='PENDING'" } else { "" }
        );
        let mut stmt = self.db.prepare(&sql)?;
        let mut rows = stmt.query([id])?;
        let mut out = vec![];
        while let Some(r) = rows.next()? {
            out.push(json!({"request_id":r.get::<_,String>(0)?,"run_id":id,"requested_at":r.get::<_,String>(1)?,"reason":r.get::<_,String>(2)?,"task_id":r.get::<_,Option<String>>(3)?,"event_id":r.get::<_,Option<String>>(4)?,"fields":serde_json::from_str::<Value>(&r.get::<_,String>(5)?)?,"status":r.get::<_,String>(6)?,"record_id":r.get::<_,Option<String>>(7)?}));
        }
        Ok(out)
    }
    pub fn resolve_observer(&self, id: &str, request_id: &str, p: &Value) -> Result<String> {
        self.transaction(|| {
            let request = self
                .observer_requests(id, false)?
                .into_iter()
                .find(|r| r["request_id"] == request_id && r["status"] == "PENDING")
                .ok_or("Solicitud inexistente o ya resuelta. Actualiza los pendientes.")?;
            let fields: Vec<_> = list(&request["fields"])
                .iter()
                .map(|v| text(v).to_owned())
                .collect();
            validate_observation(p, &fields)?;
            let run = self.run(id)?.ok_or("Ejecución no encontrada.")?;
            let mut record = p.clone();
            for k in ["task_id", "event_id", "requested_at", "reason"] {
                record[k] = request[k].clone();
            }
            record["request_id"] = json!(request_id);
            record["event_at"] = request["requested_at"].clone();
            record["scope"] = json!("connected_equipment");
            for k in ["observer", "instrument", "equipment"] {
                record[k] = p.get(k).unwrap_or(&run[k]).clone();
            }
            let record_id = self.human_record(id, "OBSERVER_RECORD", &record)?;
            self.db.execute(
                "UPDATE observer_requests SET status='RESOLVED',record_id=? WHERE request_id=?",
                params![record_id, request_id],
            )?;
            self.event(
                id,
                "OBSERVER_RECORDED",
                &json!({"request_id":request_id,"record_id":record_id}),
            )?;
            Ok(record_id)
        })
    }
    pub fn observer_previous(&self, id: &str) -> Result<Value> {
        let mut out = json!({});
        for field in ["power_w", "visible_people"] {
            let sql = format!(
                "SELECT h.payload FROM human_records h WHERE h.run_id=? AND h.kind='OBSERVER_RECORD' AND json_type(h.payload,'$.{field}') IN ('integer','real') AND EXISTS(SELECT 1 FROM observer_requests r,json_each(r.fields) f WHERE r.record_id=h.record_id AND r.run_id=h.run_id AND f.value=?) ORDER BY h.rowid DESC LIMIT 1"
            );
            let row: Option<String> = self
                .db
                .query_row(&sql, params![id, field], |r| r.get(0))
                .optional()?;
            if let Some(row) = row {
                out[field] = serde_json::from_str::<Value>(&row)?[field].clone();
            }
        }
        Ok(out)
    }
    pub fn quality(&self, id: &str) -> Result<Value> {
        let (samples, last): (i64, Option<i64>) = self.db.query_row(
            "SELECT count(*),max(second) FROM samples_1s WHERE run_id=?",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        let count = |sql: &str| -> Result<i64> { Ok(self.db.query_row(sql, [id], |r| r.get(0))?) };
        let pending =
            count("SELECT count(*) FROM observer_requests WHERE run_id=? AND status='PENDING'")?;
        let missing = count(
            "SELECT count(*) FROM human_records WHERE run_id=? AND kind='OBSERVER_RECORD' AND json_array_length(payload,'$.unavailable_fields')>0",
        )?;
        let incomplete = count(
            "SELECT count(*) FROM samples_1s WHERE run_id=? AND json_extract(payload,'$.sensor_data_status')!='VALID'",
        )?;
        let failed = count("SELECT count(*) FROM events WHERE run_id=? AND type='TASK_FAILED'")?;
        let timeout = count("SELECT count(*) FROM events WHERE run_id=? AND type='TASK_TIMEOUT'")?;
        let run = self.run(id)?.unwrap_or(json!({}));
        let expected = run["expected_samples"]
            .as_i64()
            .unwrap_or(last.map(|s| s + 1).unwrap_or(0));
        Ok(
            json!({"samples":samples,"expected_samples":expected,"missing_samples":(expected-samples).max(0),"pending_observations":pending,"unavailable_observations":missing,"task_failures":failed,"task_timeouts":timeout,"sensor_incomplete_samples":incomplete,"duration_completed":run["finish_reason"]=="MAX_RUN_DURATION","record_complete":samples>0&&run["status"]!="INTERRUPTED"&&pending==0&&missing==0&&samples==expected}),
        )
    }
    pub fn export_ndjson(&self, id: &str, mut output: impl std::io::Write) -> Result<()> {
        writeln!(output, "{}", json!({"type":"RUN","payload":self.run(id)?}))?;
        let mut seq = 0;
        loop {
            let batch = self.events(id, seq, 200)?;
            if batch.is_empty() {
                break;
            }
            for e in &batch {
                writeln!(output, "{e}")?;
            }
            seq = batch.last().unwrap()["sequence"].as_i64().unwrap();
        }
        let mut stmt=self.db.prepare("SELECT record_id,timestamp,kind,payload FROM human_records WHERE run_id=? ORDER BY rowid")?;
        let mut rows = stmt.query([id])?;
        while let Some(r) = rows.next()? {
            writeln!(
                output,
                "{}",
                json!({"type":r.get::<_,String>(2)?,"record_id":r.get::<_,String>(0)?,"timestamp":r.get::<_,String>(1)?,"payload":serde_json::from_str::<Value>(&r.get::<_,String>(3)?)?})
            )?;
        }
        for request in self.observer_requests(id, false)? {
            writeln!(
                output,
                "{}",
                json!({"type":"OBSERVER_REQUEST","payload":request})
            )?;
        }
        let mut stmt = self
            .db
            .prepare("SELECT payload FROM samples_1s WHERE run_id=? ORDER BY second")?;
        let mut rows = stmt.query([id])?;
        while let Some(r) = rows.next()? {
            writeln!(
                output,
                "{}",
                json!({"type":"SAMPLE_1S","payload":serde_json::from_str::<Value>(&r.get::<_,String>(0)?)?})
            )?;
        }
        Ok(())
    }
}
