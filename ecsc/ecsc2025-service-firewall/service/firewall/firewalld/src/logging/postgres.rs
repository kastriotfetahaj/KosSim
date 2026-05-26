/// A PostgreSQL-backed logging module.

use crate::logging::{Logger, LogError};
use rustls::{ClientConfig, RootCertStore};
use rustls_pki_types::{pem::PemObject, CertificateDer};
use std::{error::Error, path::PathBuf, sync::{Arc, Weak}, time::Duration};
use tokio::{sync::RwLock, task::JoinHandle};
use tokio_postgres::{Client, NoTls};
use tokio_postgres_rustls::MakeRustlsConnect;

/// Errors in PostgreSQL-based logging.
#[derive(Debug, thiserror::Error)]
pub(crate) enum PgsqlLogError {
    #[error("failed to load CA certificate: {0}")]
    CertificateLoadFailed(Box<dyn Error + Send + Sync>),
    #[error("internal TLS error: {0}")]
    TlsError(Box<dyn Error + Send + Sync>),
    #[error("internal PostgreSQL error: {0}")]
    PostgresError(Box<dyn Error + Send + Sync>),
}

impl Into<LogError> for PgsqlLogError {
    fn into(self) -> LogError { LogError::BackendError(Box::new(self)) }
}

impl PgsqlLogError {
    /// Loading the CA certificate failed.
    pub fn ca_load_error<E: Error + Send + Sync + 'static>(e: E) -> LogError {
        Self::CertificateLoadFailed(Box::new(e)).into()
    }
    /// Unknown TLS error.
    pub fn tls_error<E: Error + Send + Sync + 'static>(e: E) -> LogError {
        Self::TlsError(Box::new(e)).into()
    }
    /// A PostgreSQL error.
    pub fn postgres_error<E: Error + Send + Sync + 'static>(e: E) -> LogError {
        Self::PostgresError(Box::new(e)).into()
    }
}

/// PostgreSQL connection info.
#[derive(Clone, Debug)]
struct PgsqlInfo {
    db: String,
    ca_certificate: Option<PathBuf>,
}

impl PgsqlInfo {
    /// Creates the connection info object.
    pub fn new(db: impl Into<String>, ca_certificate: &Option<PathBuf>) -> Self {
        Self { db: db.into(), ca_certificate: ca_certificate.clone() }
    }

    /// Creates a client and connection.
    pub(crate) async fn connect(&self) -> Result<(Client, JoinHandle<Result<(), LogError>>), LogError> {
        match &self.ca_certificate {
            Some(path) => {
                let cert = CertificateDer::from_pem_file(path).map_err(PgsqlLogError::ca_load_error)?;

                let mut store = RootCertStore::empty();
                store.add(cert).map_err(PgsqlLogError::tls_error)?;

                let config = ClientConfig::builder()
                    .with_root_certificates(store)
                    .with_no_client_auth();

                let tls = MakeRustlsConnect::new(config);
                let (client, connection) = tokio_postgres::connect(&self.db, tls)
                    .await
                    .map_err(PgsqlLogError::postgres_error)?;

                let handle = tokio::spawn(async move { connection.await.map_err(PgsqlLogError::postgres_error) });
                Ok((client, handle))
            },
            None => {
                let (client, connection) = tokio_postgres::connect(&self.db, NoTls)
                    .await
                    .map_err(PgsqlLogError::postgres_error)?;

                let handle = tokio::spawn(async move { connection.await.map_err(PgsqlLogError::postgres_error) });
                Ok((client, handle))
            },
        }
    }
}


pub(crate) struct PgsqlLogger {
    client: Client,
    log_query: String,
}

impl PgsqlLogger {
    /// Creates a new logger with the given database connection and query string.
    pub async fn new(db: impl Into<String>, log_query: impl Into<String>, ca_certificate: &Option<PathBuf>) -> Result<Arc<RwLock<Self>>, LogError> {
        let info = PgsqlInfo::new(db, ca_certificate);
        let (client, handle) = info.connect().await?;
        let logger = Arc::new(RwLock::new(Self { client, log_query: log_query.into() }));
        Self::register_reconnect(Arc::downgrade(&logger), handle, info);
        Self::keepalive(Arc::downgrade(&logger));
        Ok(logger)
    }

    /// Spawns a keepalive task.
    fn keepalive(weak: Weak<RwLock<Self>>) {
        const KEEPALIVE_INTERVAL: Duration = Duration::from_secs(15);
        const KEEPALIVE_QUERY: &'static str = "SELECT 1";
        tokio::spawn(async move {
            loop {
                match weak.upgrade() {
                    Some(logger) => {
                        let reader = logger.read().await;
                        if let Err(error) = reader.client.execute(KEEPALIVE_QUERY, &[]).await {
                            tracing::warn!("Keepalive query failed: {error}");
                        }
                    },
                    None => break,
                };
                tokio::time::sleep(KEEPALIVE_INTERVAL).await;
            }
        });
    }

    /// Spawns the reconnect task.
    fn register_reconnect(weak: Weak<RwLock<Self>>, handle: JoinHandle<Result<(), LogError>>, info: PgsqlInfo) {
        tokio::spawn(Self::reconnect(weak, handle, info));
    }

    /// Respawns the connection after the previous one failed.
    async fn reconnect(weak: Weak<RwLock<Self>>, handle: JoinHandle<Result<(), LogError>>, info: PgsqlInfo) {
        match handle.await {
            Ok(Ok(_)) => tracing::warn!("Database connection exited cleanly, but unexpectedly"),
            Ok(Err(error)) if format!("{error}").contains("terminating connection due to idle-session timeout") => tracing::debug!("Database connection timed out, reconnecting"),
            Ok(Err(error)) => tracing::error!("Database connection failed: {error}"),
            Err(error) => tracing::error!("Failed to wait for database connection to terminate: {error}"),
        };
        if let Some(logger) = weak.upgrade() {
            const BACKOFF: Duration = Duration::from_secs(5);
            loop {
                match info.connect().await {
                    Ok((client, handle)) => {
                        {
                            let mut writer = logger.write().await;
                            writer.client = client;
                        }
                        return Self::register_reconnect(weak, handle, info);
                    },
                    Err(error) => {
                        tracing::error!("Failed to reconnect to database, retrying in {BACKOFF:?}: {error}");
                        tokio::time::sleep(BACKOFF).await;
                    }
                }
            }
        }
    }
}

#[async_trait::async_trait]
impl Logger for PgsqlLogger {
    async fn log_packet(&self, user: &str, packet: &[u8]) -> Result<(), LogError> {
        self.client.execute(&self.log_query, &[&user, &packet])
            .await
            .map_err(PgsqlLogError::postgres_error)
            .map(drop)
    }
}

#[async_trait::async_trait]
impl Logger for RwLock<PgsqlLogger> {
    async fn log_packet(&self, user: &str, packet: &[u8]) -> Result<(), LogError> {
        let reader = self.read().await;
        reader.log_packet(user, packet).await
    }
}
