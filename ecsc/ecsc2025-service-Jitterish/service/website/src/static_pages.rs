use interface::frontend::UserSession;
use rocket::{
    request::FlashMessage,
    response::{Flash, Redirect},
};
use rocket_dyn_templates::{context, Template};

#[get("/")]
fn index(flash: Option<FlashMessage<'_>>, session: Option<UserSession>) -> Result<Template, Flash<Redirect>> {
    Ok(Template::render(
        "index",
        context! {
            flash: flash,
            username: session.map(|s| s.user.username),
        },
    ))
}

#[get("/docs")]
fn docs(flash: Option<FlashMessage<'_>>, session: Option<UserSession>) -> Result<Template, Flash<Redirect>> {
    Ok(Template::render(
        "docs",
        context! {
            flash: flash,
            username: session.map(|s| s.user.username),
        },
    ))
}

pub fn routes() -> Vec<rocket::Route> {
    routes![index, docs]
}
