use rocket::http::CookieJar;
use rocket::response::{Flash, Redirect};

#[post("/session/logout")]
pub fn logout(jar: &CookieJar<'_>) -> Flash<Redirect> {
    jar.remove_private("user");
    Flash::success(Redirect::to(uri!("/")), "Successfully logged out.")
}
