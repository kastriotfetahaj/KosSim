use crate::sandbox::compiler;
use interface::frontend::now;
use lazy_static::lazy_static;
use regex::Regex;
use serde::Serialize;
use serde_json::value::RawValue;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{create_dir_all, read_dir, rename, OpenOptions};
use std::io;
use std::io::ErrorKind::InvalidInput;
use std::io::{BufRead, Seek, SeekFrom, Write};
use std::os::fd::BorrowedFd;
use std::os::unix::fs::MetadataExt;
use std::path::{absolute, Path, PathBuf};
use tokio::sync::Mutex;

lazy_static! {
    static ref base_data: PathBuf = absolute(Path::new("./data")).unwrap();
    static ref base_queries: PathBuf = absolute(Path::new("./queries")).unwrap();
    static ref COLLECTION_REGEX: Regex = Regex::new(r"^\w{2,32}$").unwrap();
    static ref write_lock: Mutex<i32> = Mutex::const_new(0);
}

pub fn dir(database: &str) -> PathBuf {
    base_data.join(database)
}

pub fn query_object(code_ref: &str) -> PathBuf {
    base_queries.join(format!("{}.so", code_ref))
}

pub fn list_collections(database: &str) -> std::io::Result<Vec<String>> {
    let dir = dir(database);
    create_dir_all(&dir)?;

    let mut vec: Vec<String> = Vec::new();
    for child in read_dir(dir)? {
        let child = child?;
        if child.file_type()?.is_file() {
            let path = child.path();
            if path.extension().map_or(false, |ext| ext == "ndjson") {
                vec.push(path.file_stem().unwrap().to_str().unwrap().to_string());
            }
        }
    }

    Ok(vec)
}

pub async fn append<T: Serialize>(database: &str, collection: &str, data: &T) -> std::io::Result<()> {
    if !COLLECTION_REGEX.is_match(collection) {
        return Err(std::io::Error::new(InvalidInput, "Invalid collection name."));
    }
    let dir = dir(database);
    create_dir_all(&dir)?;

    let _lock = write_lock.lock().await;
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .append(true)
        .open(dir.join(format!("{}.ndjson", collection)))?;
    serde_json::to_writer(&mut file, data)?;
    file.write_all("\n".as_bytes())
}

pub async fn prepare_query(code: &str) -> std::io::Result<String> {
    let code_ref = hex::encode(Sha256::digest(code.as_bytes()));
    let obj = query_object(&code_ref);

    if !obj.exists() {
        create_dir_all(base_queries.as_path())?;
        if let Err(e) = compiler::compile(code, obj).await {
            return Err(std::io::Error::new(InvalidInput, format!("compile error {}", e)));
        }
    }

    Ok(code_ref)
}

pub async fn execute_query(
    database: &str,
    code_ref: &str,
    query: &str,
    param: &RawValue,
    privileged: bool,
    output: BorrowedFd<'_>,
) -> std::io::Result<()> {
    let obj = query_object(code_ref);
    let dir = dir(database);
    create_dir_all(&dir)?;
    let param = serde_json::to_string(param)?;
    if let Err(e) = compiler::run(obj, dir, query, param.as_str(), privileged, output).await {
        return Err(std::io::Error::new(InvalidInput, format!("run error {}", e)));
    }
    Ok(())
}

pub async fn cleanup(database: &str, collection: &str) -> std::io::Result<()> {
    let filename = dir(database).join(format!("{}.ndjson", collection));
    let deadline = now() - 8 * 60;
    let _lock = write_lock.lock().await;

    let file = OpenOptions::new().read(true).write(true).open(&filename)?;
    let size = file.metadata()?.size();
    if size < 512 * 1024 {
        return Ok(());
    }

    let mut new_start_pos = 0;
    let mut reader = io::BufReader::new(file);
    for line in (&mut reader).lines().map_while(Result::ok) {
        let ts = serde_json::from_str(line.as_str())
            .ok()
            .and_then(|obj: Value| obj["ts"].as_u64())
            .unwrap_or(0);
        if ts >= deadline {
            break;
        }
        new_start_pos += (line.len() as u64) + 1;
    }

    if 128 * 1024 < new_start_pos && new_start_pos < size {
        let tmp_filename = dir(database).join(".tmp.ndjson");
        let mut tmp_file = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&tmp_filename)?;
        reader.seek(SeekFrom::Start(new_start_pos))?;
        io::copy(&mut reader, &mut tmp_file)?;
        rename(tmp_filename, filename)?;
    }

    Ok(())
}
