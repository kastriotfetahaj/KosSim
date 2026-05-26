use crate::sandbox::sandbox::run_sandboxed;
use nix::sys::memfd::{memfd_create, MemFdCreateFlag};
use nix::unistd::{lseek, write, Whence};
use std::error::Error;
use std::ffi::CString;
use std::fs::{read_to_string, remove_file, OpenOptions};
use std::os::fd::{AsFd, AsRawFd, BorrowedFd};
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;
use unshare::{Command, ExitStatus, Stdio};

fn check_exit_status(status: ExitStatus) -> Result<(), Box<dyn Error>> {
    match status {
        ExitStatus::Exited(0) => Ok(()),
        ExitStatus::Exited(rc) => Err(format!("error code {}", rc).into()),
        ExitStatus::Signaled(sig, _) => Err(format!("terminated by signal {}", sig).into()),
    }
}

pub async fn compile<P: AsRef<Path>>(code: &str, output: P) -> Result<(), Box<dyn Error>> {
    let mut cmd = Command::new("/app/compiler/jit");
    cmd.arg("-").arg("-");

    let memfd = memfd_create(CString::new(b"code").unwrap().as_c_str(), MemFdCreateFlag::MFD_CLOEXEC)?;
    write(memfd.as_fd(), &code.as_bytes())?;
    lseek(memfd.as_fd(), 0, Whence::SeekSet)?;
    cmd.stdin(Stdio::from_file(memfd));

    cmd.stdout(Stdio::from_file(
        OpenOptions::new().mode(0o755).create(true).write(true).open(&output)?,
    ));

    let mut child = run_sandboxed::<&str>(cmd, None, None, Duration::from_millis(1837), 1536).await?;
    check_exit_status(child.wait()?).map_err(|e| {
        let msg = read_to_string(&output);
        let _ = remove_file(output);
        if let Ok(msg) = msg {
            if msg.chars().count() > 0 && msg.chars().count() < 1024 {
                return msg.into();
            }
        }
        return e;
    })
}

pub async fn run<P: AsRef<Path>>(
    binary: P,
    directory: P,
    query: &str,
    param: &str,
    privileged: bool,
    output: BorrowedFd<'_>,
) -> Result<(), Box<dyn Error>> {
    let mut cmd = Command::new("/app/executable");
    cmd.arg(query).arg(param);
    if privileged {
        cmd.arg("--privileged");
    }
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::dup_file(&output)?);

    let mut child = run_sandboxed(cmd, Some(binary), Some(directory), Duration::from_millis(1388), 96).await?;
    check_exit_status(child.wait()?)
}
