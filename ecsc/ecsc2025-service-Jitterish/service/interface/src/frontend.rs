use rocket::{
    http::Status,
    outcome::IntoOutcome,
    request::{self, FromRequest},
    FromForm, Request,
};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(FromForm, Serialize, Deserialize, Debug)]
pub struct Query<'r> {
    pub target: &'r str,
    pub query_str: &'r str,
}

#[derive(FromForm, Serialize, Deserialize)]
pub struct Register<'r> {
    pub username: &'r str,
    pub password: &'r str,
    firstname: &'r str,
    lastname: &'r str,
    pub status: &'r str,
    pub account_type: &'r str,
}

#[derive(FromForm, Serialize, Deserialize, Debug, Clone)]
pub struct Login<'r> {
    pub username: &'r str,
    password: &'r str,
}

impl Login<'_> {
    pub fn username(&self) -> &str {
        self.username
    }
    pub fn password(&self) -> &str {
        self.password
    }
}

#[rocket::async_trait]
impl<'r> FromRequest<'r> for UserSession {
    type Error = std::convert::Infallible;

    async fn from_request(request: &'r Request<'_>) -> request::Outcome<UserSession, Self::Error> {
        request
            .cookies()
            .get_private("user")
            .and_then(|cookie| {
                serde_json::from_str(&cookie.value())
                    .map(|user| UserSession { user })
                    .ok()
            })
            .or_forward(Status::Unauthorized)
    }
}

#[derive(FromForm, Serialize, Deserialize, Debug, Clone)]
pub struct DbForm<'r> {
    pub db: &'r str,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct UserModel {
    pub username: String,
    pub password_hash: String,
    pub ts: u64,
    pub status: serde_json::Value,

    pub allow_public_queries: bool, 
    pub allow_public_kv: bool,     
}

#[derive(Debug)]
pub struct UserSession {
    pub user: UserModel,
}

#[derive(FromForm, Serialize, Deserialize, Debug, Clone)]
pub struct AppendForm<'r> {
    pub collection: &'r str,
    pub data: &'r str,
}

#[derive(FromForm, Serialize, Deserialize, Debug, Clone)]
pub struct QueryForm<'r> {
    pub query: &'r str,
    pub query_name: &'r str,
    pub params: &'r str,
}

#[derive(FromForm, Serialize, Deserialize, Debug, Clone)]
pub struct SupportForm<'r> {
    pub target_user: &'r str,
    pub description: &'r str,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Complaint {
    pub target_user: UserModel,
    pub reporting_user: UserModel,
    pub ts: u64,
    pub description: String,
}

pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}
