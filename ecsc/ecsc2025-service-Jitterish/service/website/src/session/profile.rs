use interface::frontend::UserSession;
use rocket::response::{Flash, Redirect};

use rocket_dyn_templates::{context, Template};

#[get("/session/profile")]
pub(super) fn index(session: UserSession) -> Result<Template, Flash<Redirect>> {
    match session.user.status {
        serde_json::Value::Object(map) => {
            let num_reports = map
                .get("num_reports")
                .ok_or(Flash::error(Redirect::to("/"), "User decode error"))?;
            let num_reports = if let serde_json::Value::Number(inner) = num_reports {
                Ok(inner
                    .as_u64()
                    .ok_or(Flash::error(Redirect::to("/"), "Insane number of reports"))?)
            } else {
                Err(Flash::error(
                    Redirect::to(uri!("/")),
                    "Could not extract number of reports value from status",
                ))
            }?;
            let looking_for_jobs = map
                .get("looking_for_job")
                .ok_or(Flash::error(Redirect::to("/"), "User decode error"))?;
            let looking_for_jobs = if let serde_json::Value::Bool(inner) = looking_for_jobs {
                Ok(inner)
            } else {
                Err(Flash::error(
                    Redirect::to(uri!("/")),
                    "Could not extract job hunt status from status",
                ))
            }?;
            let current_salary = map
                .get("current_salary")
                .ok_or(Flash::error(Redirect::to("/"), "User decode error"))?;
            let current_salary = if let serde_json::Value::Number(inner) = current_salary {
                Ok(inner.as_u64().ok_or(Flash::error(Redirect::to("/"), "Insane salary"))?)
            } else {
                Err(Flash::error(
                    Redirect::to(uri!("/")),
                    "Could not extract current salary from status",
                ))
            }?;
            let custom = map
                .get("custom")
                .ok_or(Flash::error(Redirect::to("/"), "User decode error"))?;
            let custom = if let serde_json::Value::String(inner) = custom {
                Ok(inner)
            } else {
                Err(Flash::error(
                    Redirect::to(uri!("/")),
                    "Could not extract custom value from status",
                ))
            }?;

            Ok(Template::render(
                "profile",
                context! {
                    username: session.user.username,
                    num_reports: num_reports,
                    looking_for_jobs: looking_for_jobs,
                    current_salary: current_salary,
                    custom: custom,
                },
            ))
        }
        _ => Err(Flash::error(Redirect::to("/"), "Could not decode status!")),
    }
}

#[get("/session/profile", rank = 2)]
pub(super) fn no_auth_index() -> Redirect {
    Redirect::to(uri!(crate::session::login::login_page))
}
