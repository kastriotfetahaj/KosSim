#[macro_use]
extern crate rocket;

mod complaint;
mod databases;
mod db_connector;
mod session;
mod static_pages;

use crate::db_connector::DbConnection;
use base64::prelude::BASE64_STANDARD;
use base64::Engine;
use interface::database::CodeRef;
use rocket::fs::FileServer;
use rocket_dyn_templates::Template;
use std::error::Error;
use std::fs;
use std::fs::create_dir_all;
use std::path::Path;

#[derive(Debug)]
pub struct Queries {
    pub user: CodeRef,
    pub api: CodeRef,
    pub complaint: CodeRef,
}

async fn prepare_queries() -> Queries {
    let code_user = fs::read_to_string("queries/user.qry").expect("cannot read user.qry");
    let code_api = fs::read_to_string("queries/api.qry").expect("cannot read api.qry");
    let code_complaint = fs::read_to_string("queries/complaint.qry").expect("cannot read complaint.qry");

    let mut conn = DbConnection::open("_").await.expect("Connection to database failed");
    Queries {
        user: conn.prepare(&code_user).await.expect("Could not prepare queries"),
        api: conn.prepare(&code_api).await.expect("Could not prepare queries"),
        complaint: conn.prepare(&code_complaint).await.expect("Could not prepare queries"),
    }
}

fn get_secret_key() -> Result<String, Box<dyn Error>> {
    let secret_file = Path::new("data/secret.txt");
    if secret_file.exists() {
        Ok(fs::read_to_string(secret_file)?)
    } else {
        let mut buf = [0u8; 32];
        getrandom::fill(&mut buf).expect("getrandom failed");
        let key = BASE64_STANDARD.encode(buf);
        create_dir_all("data")?;
        fs::write(secret_file, &key)?;
        Ok(key)
    }
}

#[launch]
async fn rocket() -> _ {
    let queries = prepare_queries().await;
    let secret_key = get_secret_key().expect("failed to get secret key");
    rocket::build()
        .configure(rocket::Config::figment().merge(("secret_key", secret_key)))
        .manage(queries)
        .attach(Template::fairing())
        .mount("/static", FileServer::from("static/"))
        .mount("/", static_pages::routes())
        .mount("/", session::routes())
        .mount("/", databases::routes())
        .mount("/", complaint::routes())
}
