mod complaint;

pub fn routes() -> Vec<rocket::Route> {
    routes![complaint::support, complaint::no_auth_support, complaint::save_complaint,]
}
