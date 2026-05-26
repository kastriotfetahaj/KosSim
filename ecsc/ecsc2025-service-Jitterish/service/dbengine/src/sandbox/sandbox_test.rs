use super::*;
use std::error::Error;
use std::io::Read;
use unshare::ExitStatus;

// REMOVE IN PROD

async fn run_cmd_with_params(
    s: &str,
    executable: Option<&str>,
    data_dir: Option<&str>,
) -> Result<(i32, String), Box<dyn Error>> {
    let mut cmd = unshare::Command::new("/bin/sh");
    cmd.arg("-c").arg(s);
    cmd.stdout(unshare::Stdio::piped());
    let mut child = run_sandboxed(cmd, executable, data_dir, Duration::from_millis(350), 64).await?;
    let result = child.wait()?;

    let mut buffer = String::new();
    child.stdout.unwrap().read_to_string(&mut buffer)?;

    match result {
        ExitStatus::Exited(rc) => Ok((rc.into(), buffer)),
        ExitStatus::Signaled(sig, _) => Ok((128 + sig as i32, buffer)),
    }
}

async fn run_cmd(s: &str) -> Result<(i32, String), Box<dyn Error>> {
    run_cmd_with_params(s, None, Some(".")).await
}

#[tokio::test]
async fn test_run_simple() {
    let (code, output) = run_cmd("echo 'A' 'B'").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("A B\n", output);
}

#[tokio::test]
async fn test_run_id() {
    let (code, output) = run_cmd("id").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("uid=0(root) gid=99999 Gruppen=99999,65534(nogroup)\n", output);
}

#[tokio::test]
async fn test_run_pwd() {
    let (code, output) = run_cmd("pwd").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("/data\n", output);
}

#[tokio::test]
async fn test_run_ls_1() {
    let (code, output) = run_cmd("ls -l /").await.unwrap();
    assert_eq!(0, code);
    assert!(output.contains(" bin"));
    assert!(output.contains(" data"));
    // assert!(output.contains(" proc"));
    assert!(output.contains(" tmp"));
    assert!(!output.contains(" srv"));
    assert!(!output.contains(" var"));
    assert!(!output.contains(" boot"));
}

#[tokio::test]
async fn test_run_ls_2() {
    let (code, output) = run_cmd("ls -l .").await.unwrap();
    assert_eq!(0, code);
    println!("{}", output);
    assert!(output.contains(" src"));
    assert!(output.contains(" Cargo.toml"));
}

#[tokio::test]
async fn test_run_ip_link() {
    let (code, output) = run_cmd("ip link | wc -l").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("2\n", output);
}

#[tokio::test]
async fn test_run_file_descriptors() {
    // fails because we do not share /proc anymore
    let (code, output) = run_cmd("ls -l /proc/1/fd | wc -l").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("4\n", output); // 0-2 + header line
}

#[tokio::test]
async fn test_run_ulimit() {
    let (code, output) = run_cmd("ulimit -aH").await.unwrap();
    assert_eq!(0, code);
    assert!(output.contains("memory(kbytes)       65536"));
    assert!(output.contains("vmemory(kbytes)      65536"));
    assert!(output.contains("nofiles              32"));
    assert!(output.contains("process              5"));
}

#[tokio::test]
async fn test_run_sleep() {
    let (code, output) = run_cmd("sleep 5").await.unwrap();
    assert_eq!(137, code);
    assert_eq!("", output); // 0-2 + header line
}

#[tokio::test]
async fn test_run_touch() {
    let (code, output) = run_cmd("touch test.txt").await.unwrap();
    assert_eq!(1, code);
    assert_eq!("", output); // 0-2 + header line
}

#[tokio::test]
async fn test_run_mount() {
    let (code, output) = run_cmd("mount").await.unwrap();
    assert_eq!(0, code);
    println!("{}", output);
    assert!(output.contains("none on / type tmpfs"));
    assert!(output.contains("none on /proc type proc"));
    assert_eq!(10, output.matches(" type ").count());
    assert_eq!(8, output.matches("(ro,").count());
    assert_eq!(2, output.matches("(rw,").count());
}

#[tokio::test]
async fn test_run_ps_aux() {
    // does not work anymore - no /proc means no "ps"
    let (code, output) = run_cmd("ps -aux | wc -l").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("4\n", output); // 0-2 + header line
}

#[tokio::test]
async fn test_run_getpcaps() {
    let (code, output) = run_cmd("getpcaps $$").await.unwrap();
    assert_eq!(0, code);
    assert_eq!("1: =ep\n", output); // 0-2 + header line
}

#[tokio::test]
async fn test_run_executable() {
    let (code, output) = run_cmd_with_params("/app/executable", Some("/usr/bin/id"), None)
        .await
        .unwrap();
    assert_eq!(0, code);
    assert_eq!("uid=0(root) gid=99999 Gruppen=99999,65534(nogroup)\n", output);
}
