mod db;
mod sandbox;

use crate::db::{cleanup, execute_query};
use crate::sandbox::sandbox::compiler_path;
use interface::database::{CodeRef, Collection, Command};
use serde::Serialize;
use std::error::Error;
use std::io::ErrorKind;
use std::os::fd::AsFd;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};
use tokio::time::sleep;
use tokio::{select, signal};
use tokio_util::sync::CancellationToken;

async fn write_json<T: Serialize>(stream: &mut BufReader<TcpStream>, data: &T) -> std::io::Result<()> {
    let data = serde_json::to_vec(data)?;
    stream.write_all(data.as_slice()).await?;
    stream.write_all(b"\n").await
}

async fn connection(socket: TcpStream) -> std::io::Result<()> {
    let mut stream = BufReader::new(socket);
    let mut buffer = String::new();
    let mut current_database = "none".to_string();

    loop {
        if stream.read_line(&mut buffer).await? <= 0 {
            return Ok(());
        }

        match serde_json::from_str::<Command>(buffer.as_str()) {
            Ok(cmd) => {
                match command(&mut stream, &mut current_database, cmd).await {
                    Ok(()) => stream.write_all("OK\n".as_bytes()).await?,
                    Err(e) => stream.write_all(format!("Failed command: {}\n", e).as_bytes()).await?,
                }
                buffer.clear();
            }
            Err(e) => {
                if !e.is_eof() {
                    stream.write_all(format!("Invalid command: {}\n", e).as_bytes()).await?;
                    return Err(std::io::Error::new(ErrorKind::Other, e));
                }
            }
        }
    }
}

async fn command(
    stream: &mut BufReader<TcpStream>,
    current_database: &mut String,
    command: Command<'_>,
) -> std::io::Result<()> {
    match command {
        Command::Select { database } => {
            current_database.clear();
            current_database.push_str(database);
        }

        Command::List => {
            for collection in db::list_collections(current_database)? {
                let result = &Collection { name: collection };
                write_json(stream, result).await?;
            }
        }

        Command::Append { collection, data } => {
            db::append(current_database.as_str(), collection, &data).await?;
        }

        Command::Prepare { code } => {
            let code_ref = db::prepare_query(&code).await?;
            let result = &CodeRef { code_ref };
            write_json(stream, result).await?;
        }

        Command::Execute {
            code_ref,
            query,
            param,
            privileged,
        } => {
            execute_query(
                current_database,
                code_ref,
                query,
                &param,
                privileged,
                stream.get_ref().as_fd(),
            )
            .await?;
        }
    }
    Ok(())
}

async fn server(cancel: CancellationToken) -> std::io::Result<()> {
    let listener = TcpListener::bind("0.0.0.0:9401").await?;

    loop {
        select! {
            Ok(( socket, _addr)) = listener.accept() => {
                tokio::spawn(connection(socket));
            }
            _ = cancel.cancelled() => {
                return Ok(());
            }
        }
    }
}

async fn cleanup_loop() {
    loop {
        for collection in ["users", "complaints"] {
            if let Err(e) = cleanup("_", collection).await {
                eprintln!("cleanup of _/{}.ndjson failed: {:?}", collection, e);
            }
        }

        sleep(Duration::from_secs(120)).await;
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    eprintln!("Compiler path: {}", compiler_path.to_str().unwrap());
    let token = CancellationToken::new();
    let cleanup_handle = tokio::spawn(cleanup_loop());
    let mut server_handle = tokio::spawn(server(token.clone()));

    select! {
        _ = signal::ctrl_c() => {}
        _ = &mut server_handle => {}
    }

    eprintln!("Shutting down...");
    token.cancel();
    cleanup_handle.abort();
    server_handle.await?.expect("Error waiting for termination signal");
    eprintln!("Server terminated.");
    Ok(())
}
