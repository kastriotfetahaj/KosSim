/// VPN logging modules.

use std::error::Error;

pub(crate) mod postgres;

/// Logging errors.
#[derive(Debug, thiserror::Error)]
pub(crate) enum LogError {
    #[error("backend error: {0}")]
    BackendError(Box<dyn Error + Send + Sync>),
}

/// A logging module.
#[async_trait::async_trait]
pub(crate) trait Logger: Send + Sync {
    /// Logs a dropped packet for the given user.
    async fn log_packet(&self, user: &str, packet: &[u8]) -> Result<(), LogError>;
}
