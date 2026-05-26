pub mod login;
pub mod logout;
pub mod profile;
pub mod register;
pub mod userlist;

pub fn routes() -> Vec<rocket::Route> {
    routes![
        profile::index,
        profile::no_auth_index,
        login::login,
        login::login_page,
        login::post_login,
        logout::logout,
        register::register,
        register::register_page,
        register::post_register,
        userlist::userlist,
    ]
}
