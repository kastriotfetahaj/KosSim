use crate::databases::api::get_database_permissions;
use crate::db_connector::DbConnection;
use crate::Queries;
use interface::database::Collection;
use interface::frontend::{AppendForm, QueryForm, UserSession};
use rocket::form::Form;
use rocket::request::FlashMessage;
use rocket::response::{Flash, Redirect};
use rocket::State;
use rocket_dyn_templates::{context, Template};
use serde_json::Value;
use std::fs;

struct DatabasePageContext {
    user_owns_db: bool,
    allow_public_kv: bool,
    conn: DbConnection,
    collections: Vec<Collection>,
    err: Option<String>,
    msgs: Vec<String>,
}

async fn database_page_basics(
    queries: &State<Queries>,
    database: &str,
    session: &UserSession,
) -> Result<DatabasePageContext, Flash<Redirect>> {
    let (allow_public_queries, allow_public_kv) = get_database_permissions(queries, database)
        .await
        .map_err(|_| Flash::error(Redirect::to("/"), "Cannot check database permissions"))?;
    let user_owns_db = database == session.user.username;
    if !allow_public_queries && !user_owns_db {
        return Err(Flash::error(Redirect::to("/"), "Not authorized or no such db"));
    }

    let mut conn = DbConnection::open(database)
        .await
        .map_err(|_| Flash::error(Redirect::to(format!("/database/{}", database)), "Database offline"))?;
    let collections = conn
        .list_collections()
        .await
        .map_err(|_| Flash::error(Redirect::to(format!("/database/{}", database)), "Cannot list collections"))?;

    Ok(DatabasePageContext {
        user_owns_db,
        allow_public_kv,
        conn,
        collections,
        err: None,
        msgs: Vec::new(),
    })
}

#[get("/database/<database>")]
pub async fn database_page(
    queries: &State<Queries>,
    flash: Option<FlashMessage<'_>>,
    database: &str,
    session: UserSession,
) -> Result<Template, Flash<Redirect>> {
    let ctx = database_page_basics(queries, database, &session).await?;

    Ok(Template::render(
        "database",
        context! {
            flash: flash,
            username: session.user.username,
            database: database,
            collections: ctx.collections,
            allow_public_kv: ctx.allow_public_kv,
            user_owns_db: ctx.user_owns_db,
            form: QueryForm{
                query: "query q on XXX;",
                query_name: "q",
                params: "{}",
            },
        },
    ))
}

#[post("/database/<database>/append", data = "<form>")]
pub async fn database_append(
    queries: &State<Queries>,
    flash: Option<FlashMessage<'_>>,
    database: &str,
    session: UserSession,
    form: Form<AppendForm<'_>>,
) -> Result<Template, Flash<Redirect>> {
    let mut ctx = database_page_basics(queries, database, &session).await?;
    if !ctx.user_owns_db {
        return Err(Flash::error(
            Redirect::to(format!("/database/{}", database)),
            "No write access",
        ));
    }

    let parsed = serde_json::from_str::<Value>(form.data);
    match parsed {
        Ok(parsed_data) => match ctx.conn.append(form.collection, parsed_data).await {
            Ok(_) => {
                ctx.msgs.push(format!("{} successfully appended.", form.data));
                ctx.collections = ctx
                    .conn
                    .list_collections()
                    .await
                    .map_err(|_| Flash::error(Redirect::to("/"), "Error in connection listing"))?;
            }
            Err(e) => {
                ctx.err = Some(format!("cannot append: {}", e));
            }
        },
        Err(e) => {
            ctx.err = Some(format!("Incorrect json supplied: {}", e));
        }
    }
    Ok(Template::render(
        "database",
        context! {
            flash: flash,
            username: session.user.username,
            database: database,
            collections: ctx.collections,
            allow_public_kv: ctx.allow_public_kv,
            user_owns_db: ctx.user_owns_db,
            form: form.into_inner(),
            err: ctx.err,
            msgs: ctx.msgs,
        },
    ))
}

#[post("/database/<database>/customquery", data = "<form>")]
pub async fn database_query_custom(
    queries: &State<Queries>,
    flash: Option<FlashMessage<'_>>,
    database: &str,
    session: UserSession,
    form: Form<QueryForm<'_>>,
) -> Result<Template, Flash<Redirect>> {
    let mut ctx = database_page_basics(queries, database, &session).await?;

    match ctx.conn.prepare(&form.query).await {
        Ok(code_ref) => match serde_json::from_str::<Value>(form.params) {
            Ok(params) => match ctx
                .conn
                .execute::<Value, Value>(&code_ref, form.query_name, &params, ctx.user_owns_db)
                .await
            {
                Ok(result) => {
                    for r in &result {
                        let s = serde_json::to_string(&r)
                            .map_err(|_| Flash::error(Redirect::to(format!("/database/{}", database)), "Query error"))?;
                        ctx.msgs.push(s)
                    }
                }
                Err(e) => {
                    ctx.err = Some(format!("{}", e));
                }
            },
            Err(e) => {
                ctx.err = Some(format!("{}", e));
            }
        },
        Err(e) => {
            ctx.err = Some(format!("{}", e));
        }
    }

    Ok(Template::render(
        "database",
        context! {
            flash: flash,
            username: session.user.username,
            database: database,
            collections: ctx.collections,
            allow_public_kv: ctx.allow_public_kv,
            user_owns_db: ctx.user_owns_db,
            form: form.into_inner(),
            err: ctx.err,
            msgs: ctx.msgs,
        },
    ))
}

#[get("/database/<database>/script")]
pub async fn database_script(
    queries: &State<Queries>,
    database: &str,
    session: UserSession,
) -> Result<String, Flash<Redirect>> {
    let ctx = database_page_basics(queries, database, &session).await?;
    if !ctx.allow_public_kv {
        return Err(Flash::error(
            Redirect::to(format!("/database/{}", database)),
            "No script attached",
        ));
    }
    Ok(fs::read_to_string("queries/api.qry").expect("API queries file is missing!"))
}
