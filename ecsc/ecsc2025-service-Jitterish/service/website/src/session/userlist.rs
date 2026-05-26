use crate::db_connector::DbConnection;
use crate::Queries;
use interface::frontend::UserSession;
use rocket::response::{Flash, Redirect};
use rocket::State;
use rocket_dyn_templates::{context, Template};
use serde_json::json;

#[get("/customers")]
pub async fn userlist(session: Option<UserSession>, queries: &State<Queries>) -> Result<Template, Flash<Redirect>> {
    let mut db = DbConnection::open("_")
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Database not reachable"))?;
    let public_users: Vec<String> = db
        .execute(&queries.user, "public_users", &json!("null"), false)
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Could not query public users"))?;
    let api_users: Vec<String> = db
        .execute(&queries.user, "api_users", &json!("null"), false)
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Could not query public users"))?;

    Ok(Template::render(
        "customers",
        context! {
            username: session.map(|session| session.user.username),
            public_users: public_users,
            api_users: api_users,
        },
    ))
}
