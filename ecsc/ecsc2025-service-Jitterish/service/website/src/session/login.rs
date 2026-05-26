use crate::Queries;
use interface::frontend::{Login, UserModel, UserSession};
use rocket::form::Form;
use rocket::http::CookieJar;
use rocket::request::FlashMessage;
use rocket::response::{Flash, Redirect};
use rocket::State;
use rocket_dyn_templates::{context, Template};
use sha2::{Digest, Sha256};
use crate::databases::cache::user_by_username;

#[get("/session/login")]
pub(super) fn login(_session: UserSession) -> Redirect {
    Redirect::to(uri!(crate::session::profile::index))
}

#[get("/session/login", rank = 2)]
pub(super) fn login_page(flash: Option<FlashMessage<'_>>) -> Template {
    Template::render(
        "login",
        context! {
            flash: &flash,
        },
    )
}

pub fn update_session(jar: &CookieJar, user: &UserModel) -> Result<(), Flash<Redirect>> {
    jar.remove_private("user");
    let user =
        serde_json::to_string(user).map_err(|_| Flash::error(Redirect::to(uri!(login_page)), "Could not serialize user!"))?;
    jar.add_private(("user", user));
    Ok(())
}

#[post("/session/login", data = "<login>")]
pub(super) async fn post_login(
    queries: &State<Queries>,
    jar: &CookieJar<'_>,
    login: Form<Login<'_>>,
) -> Result<Redirect, Flash<Redirect>> {
    let user = user_by_username(queries, &login.username()).await
        .map_err(|_| Flash::error(Redirect::to(uri!(login_page)), "Query error"))?
        .ok_or(Flash::error(Redirect::to(uri!(login_page)), "Invalid username"))?;
    if hex::encode(Sha256::digest(login.password().as_bytes())) != user.password_hash {
        return Err(Flash::error(Redirect::to(uri!(login_page)), "Invalid password"));
    }
    update_session(jar, &user)?;
    Ok(Redirect::to(uri!(crate::session::profile::index)))
}
