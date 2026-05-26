use lazy_static::lazy_static;
use nix::libc::{RLIMIT_AS, RLIMIT_CPU, RLIMIT_NICE, RLIMIT_NOFILE, RLIMIT_NPROC, RLIMIT_RSS};
use nix::unistd::{getgid, getuid};
use std::env::current_exe;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::time::Duration;
use std::{env, path};
use tokio::time::timeout;
use unshare::{wait_async, GidMap, Namespace, UidMap};

const COMPILER_PATH_CANDIDATES: [&str; 4] = ["/app/compiler", "../jit/cmake-build-debug", "../jit/build", "../jit"];

fn find_compiler() -> PathBuf {
    if let Ok(custom_path) = env::var("COMPILER_PATH") {
        return path::absolute(custom_path).unwrap();
    }

    let mut basepath = path::absolute(current_exe().unwrap()).unwrap().parent().unwrap().to_owned();
    if basepath.parent().and_then(|p| p.file_name()).and_then(OsStr::to_str) == Some("target") {
        basepath.pop();
        basepath.pop();
    }
    for p in COMPILER_PATH_CANDIDATES {
        let path = if p.starts_with("/") {
            PathBuf::from_str(p).unwrap()
        } else {
            basepath.join(p)
        };
        if path.join("jit").exists() {
            return path;
        }
    }
    panic!("Could not find jit compiler");
}

lazy_static! {
    static ref sandbox_mutex: tokio::sync::Mutex<i32> = tokio::sync::Mutex::new(0i32);
    pub static ref compiler_path: PathBuf = find_compiler();
}

pub async fn run_sandboxed<P: AsRef<Path>>(
    mut cmd: unshare::Command,
    executable: Option<P>,
    data_folder: Option<P>,
    runtime: Duration,
    memory: u64,
) -> Result<unshare::Child, Box<dyn std::error::Error>> {
    let my_uid = getuid();
    let my_gid = getgid();

    cmd.unshare(&[
        Namespace::User,
        Namespace::Mount,
        Namespace::Ipc,
        Namespace::Pid,
        Namespace::Net,
        Namespace::Uts,
        Namespace::Cgroup,
    ]);
    cmd.set_id_maps(
        [UidMap {
            inside_uid: 0,
            outside_uid: my_uid.into(),
            count: 1,
        }]
        .into(),
        [GidMap {
            inside_gid: 99999,
            outside_gid: my_gid.into(),
            count: 1,
        }]
        .into(),
    );
    cmd.uid(0);
    cmd.gid(99999);

    cmd.set_rlimit(RLIMIT_NOFILE, 32);
    cmd.set_rlimit(RLIMIT_CPU, 1);
    cmd.set_rlimit(RLIMIT_NPROC, 5);
    cmd.set_rlimit(RLIMIT_AS, memory * 1024 * 1024);
    cmd.set_rlimit(RLIMIT_RSS, memory * 1024 * 1024);
    cmd.set_rlimit(RLIMIT_NICE, 0);

    cmd.fakeroot_enable("/dev/shm/sandbox_root");
    cmd.fakeroot_mount("/bin", "/bin", true);
    cmd.fakeroot_mount("/etc", "/etc", true);
    cmd.fakeroot_mount("/lib", "/lib", true);
    cmd.fakeroot_mount("/lib64", "/lib64", true);
    cmd.fakeroot_mount("/usr", "/usr", true);
    cmd.fakeroot_filesystem("tmpfs", "/tmp");
    cmd.fakeroot_mount(compiler_path.as_path(), "/app/compiler", true);
    if let Some(data_folder) = data_folder {
        cmd.fakeroot_mount(path::absolute(data_folder)?, "/data", true);
        cmd.current_dir("/data");
    } else {
        cmd.current_dir("/");
    }
    if let Some(executable) = executable {
        cmd.fakeroot_mount_file(path::absolute(executable)?, "/app/executable", true);
    }

    let guard = sandbox_mutex.lock().await;
    let mut child = cmd.spawn().map_err(|e| format!("spawn {}", e))?;
    drop(guard);

    let wait_result = timeout(runtime, wait_async(&mut child)).await;
    if let Err(_) = wait_result {
        child.kill()?;
        wait_async(&mut child).await?;
    }

    Ok(child)
}

// BEGIN REMOVE IN PROD
#[cfg(test)]
#[path = "./sandbox_test.rs"]
mod test;
// END REMOVE IN PROD
