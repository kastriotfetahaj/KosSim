mod accounts;
mod admin;
mod apitokens;
mod audit_log;
mod crypto;
mod db;
mod eno;
mod indexer;
mod ledger;
mod ops;
mod policies;
mod query;
mod ratelimit;
mod replicas;
mod routes;
mod settlements;
mod state;
mod treasury;

use std::{env, net::SocketAddr, sync::Arc};

use tokio::{
    signal::unix::{signal, SignalKind},
    sync::Mutex,
};

use crate::state::AppState;

#[tokio::main]
async fn main() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .try_init();

    let team = env::var("TEAM_NAME").unwrap_or_else(|_| "team".to_string());
    let service = env::var("SERVICE_NAME").unwrap_or_else(|_| "svc1".to_string());
    let secret = env::var("SERVICE_PUSH_SECRET").unwrap_or_else(|_| "rotate-secret".to_string());
    let boot_flag = env::var("BOOT_FLAG").unwrap_or_else(|_| "FLAG{BOOT_LEDGERFORGE}".to_string());

    let state = Arc::new(Mutex::new(AppState::new(team, service, secret)));
    {
        let mut guard = state.lock().await;
        let already: i64 = guard
            .db
            .query_row("SELECT COUNT(*) FROM flag_index WHERE tick = 0 AND variant = 0", [], |r| r.get(0))
            .unwrap_or(0);
        if already == 0 {
            guard.put_flag(0, 0, &boot_flag);
            guard.put_flag(0, 1, &format!("{boot_flag}_SETTLEMENT"));
            guard.put_flag(0, 2, &format!("{boot_flag}_TREASURY"));
        }
    }

    indexer::spawn(state.clone());

    let app = routes::router(state.clone());

    let addr = SocketAddr::from(([0, 0, 0, 0], 8080));
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind ledgerforge");
    let server_state = state.clone();
    let server = axum::serve(listener, app).with_graceful_shutdown(async move {
        let mut term = signal(SignalKind::terminate()).expect("signal");
        let mut int = signal(SignalKind::interrupt()).expect("signal");
        tokio::select! {
            _ = term.recv() => {},
            _ = int.recv() => {},
        }
        let guard = server_state.lock().await;
        guard.checkpoint();
    });
    if let Err(err) = server.await {
        eprintln!("serve_error: {err}");
    }
}
