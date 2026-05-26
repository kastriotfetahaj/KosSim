use crate::databases::cache::{user_by_username};
use interface::frontend::{now, Complaint, SupportForm, UserModel, UserSession};
use rocket::{
    form::Form,
    http::CookieJar,
    request::FlashMessage,
    response::{Flash, Redirect},
    State,
};
use rocket_dyn_templates::{context, Template};

use crate::session::login::update_session;
use crate::{db_connector::DbConnection, Queries};

#[get("/support")]
pub async fn support<'a>(
    queries: &State<Queries>,
    flash: Option<FlashMessage<'_>>,
    mut session: UserSession,
    jar: &CookieJar<'a>,
) -> Result<Template, Flash<Redirect>> {
    let mut db = DbConnection::open("_")
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Database not reachable"))?;

    let all_target_complaints: Vec<UserModel> = db
        .execute(&queries.complaint, "get_reported_users", &session.user.username, false)
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Get complaints query error 1"))?;

    let updated_user: UserModel = db
        .execute(&queries.complaint, "get_user_numreports", &session.user.username, false)
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Get complaints query error 2"))?
        .pop()
        .ok_or(Flash::error(Redirect::to("/"), "Could not update my usermodel!"))?;
    session.user.status = updated_user.status.clone();
    update_session(jar, &session.user)?;
    Ok(Template::render(
        "complaints",
        context! {
            flash: flash,
            username: session.user.username,
            user_status: session.user.status,
            reported_targets: all_target_complaints.len(),
        },
    ))
}

#[get("/support", rank = 2)]
pub async fn no_auth_support() -> Redirect {
    Redirect::to(uri!(crate::session::login::login_page))
}

#[post("/support", data = "<form>")]
pub async fn save_complaint(
    queries: &State<Queries>,
    session: UserSession,
    form: Form<SupportForm<'_>>,
) -> Result<Flash<Redirect>, Flash<Redirect>> {
    let mut db = DbConnection::open("_")
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Database not reachable"))?;
    let target_user: UserModel = user_by_username(queries, &form.target_user).await
        .map_err(|_| Flash::error(Redirect::to("/"), "User by username query error"))?
        .ok_or(Flash::error(Redirect::to(uri!(support)), "Database does not exist!"))?;

    let logged_in_user: UserModel = user_by_username(queries, &session.user.username).await
        .map_err(|_| Flash::error(Redirect::to("/"), "User by username query error"))?
        .ok_or(Flash::error(Redirect::to(uri!(support)), "Your account is missing!"))?;
    let complaint = Complaint {
        reporting_user: logged_in_user,
        target_user: target_user,
        ts: now(),
        description: form.description.to_string(),
    };
    db.append("complaints", complaint)
        .await
        .map_err(|e| Flash::error(Redirect::to(uri!(support)), format!("Append failed: {}", e)))?;
    Ok(Flash::success(
        Redirect::to(uri!(support)),
        "your complaint has been submitted, we'll get back to you soon.", // TODO add LLM to generate replies
    ))
}
