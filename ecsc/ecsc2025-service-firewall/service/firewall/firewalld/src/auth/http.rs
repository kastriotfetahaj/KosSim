/// An HTTP-backed authentication module.

use crate::auth::{Auth, AuthError, Authenticator};
use hyper::StatusCode;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::net::IpAddr;

/// Serializable object sent as data in authentication requests.
#[derive(Serialize)]
struct AuthenticationRequest<'data> {
    username: &'data str,
    password: &'data str,
}

/// Serializable object sent as data in (successful) authentication responses.
#[derive(Deserialize)]
struct AuthenticationResponse {
    ips: Vec<IpAddr>,
}

/// The HTTP-backed authenticator
pub(crate) struct HttpAuthenticator {
    client: Client,
    url: String,
}

impl HttpAuthenticator {
    /// Creates a new authenticator with the given remote URL
    pub async fn new(url: String) -> Result<Self, AuthError> {
        let client = Client::builder()
            .http1_only()
            .build()
            .map_err(|e| AuthError::BackendError(Box::new(e)))?;
        Ok(Self { client, url })
    }
}

#[async_trait::async_trait]
impl Authenticator for HttpAuthenticator {
    async fn authenticate(&self, user: &str, password: &str) -> Result<Auth, AuthError> {
        let response = self.client
            .post(&self.url)
            .json(&AuthenticationRequest { username: user, password })
            .send()
            .await
            .map_err(|e| AuthError::BackendError(Box::new(e)))?;
        match response.status() {
            StatusCode::OK => {},
            StatusCode::FORBIDDEN | StatusCode::UNAUTHORIZED => return Err(AuthError::Failed),
            _ => return Err(AuthError::ConfigurationError(format!("Authentication request returned unexpected status code {}", response.status()))),
        };
        let content: AuthenticationResponse = match response.json().await {
            Ok(content) => content,
            Err(error) => return Err(AuthError::ConfigurationError(format!("Failed to decode authentication response: {error}"))),
        };
        Ok(Auth {
            name: user.to_owned(),
            ips: content.ips
        })
    }
}
