/// VPN authentication modules.

use std::{error::Error, net::{IpAddr, Ipv4Addr, Ipv6Addr}};

pub(crate) mod http;

/// Authentication data for a user.
#[derive(Clone)]
pub(crate) struct Auth {
    pub name: String,
    pub ips: Vec<IpAddr>,
}

impl Auth {
    /// Returns the first assigned IPv4 address, if any.
    pub fn ipv4(&self) -> Option<Ipv4Addr> {
        self.ips.iter().filter_map(|ip| match ip {
            IpAddr::V4(addr) => Some(addr),
            IpAddr::V6(_)    => None,
        }).next().copied()
    }

    /// Returns the first assigned IPv6 address, if any.
    pub fn ipv6(&self) -> Option<Ipv6Addr> {
        self.ips.iter().filter_map(|ip| match ip {
            IpAddr::V4(_)    => None,
            IpAddr::V6(addr) => Some(addr),
        }).next().copied()
    }
}

/// Authentication errors.
#[derive(Debug, thiserror::Error)]
pub(crate) enum AuthError {
    #[error("authentication failed")]
    Failed,
    #[error("invalid request")]
    InvalidRequest,
    #[error("network error")]
    NetworkError,
    #[error("internal error: {0}")]
    InternalError(String),
    #[error("backend error: {0}")]
    BackendError(Box<dyn Error + Send + Sync>),
    #[error("configuration error: {0}")]
    ConfigurationError(String),
}

/// An authenticator module.
#[async_trait::async_trait]
pub(crate) trait Authenticator: Send + Sync {
    /// Attempts to authenticate with the given user/password combination.
    async fn authenticate(&self, user: &str, password: &str) -> Result<Auth, AuthError>;
}
