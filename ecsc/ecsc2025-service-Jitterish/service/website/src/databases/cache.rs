use crate::db_connector::DbConnection;
use crate::Queries;
use interface::frontend::UserModel;
use lazy_static::lazy_static;
use rocket::tokio::sync::RwLock;
use std::collections::HashMap;

pub struct UserCache {
    cache: RwLock<HashMap<String, UserModel>>,
}

lazy_static! {
    pub static ref USER_CACHE: UserCache = UserCache {
        cache: RwLock::new(HashMap::new()),
    };
}

impl UserCache {
    pub async fn get(&self, username: &str) -> Option<UserModel> {
        self.cache.read().await.get(username).map(|x| x.clone())
    }

    pub async fn set(&self, user: UserModel) {
        let mut map = self.cache.write().await;
        if map.len() > 16384 {
            map.clear();
        }
        map.insert(user.username.to_string(), user);
    }
}

pub async fn user_by_username(queries: &Queries, name: &str) -> std::io::Result<Option<UserModel>> {
    match USER_CACHE.get(name).await {
        Some(x) => Ok(Some(x)),
        None => {
            let mut db = DbConnection::open("_").await?;
            let users: Vec<UserModel> = db.execute(&queries.user, "user_by_username", &name, false).await?;
            match users.into_iter().nth(0) {
                Some(x) => {
                    USER_CACHE.set(x.clone()).await;
                    Ok(Some(x))
                }
                None => Ok(None),
            }
        }
    }
}
