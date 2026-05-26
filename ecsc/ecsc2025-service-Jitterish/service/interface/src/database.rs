use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

#[derive(Serialize, Deserialize, Debug)]
pub enum Command<'r> {
    Select {
        database: &'r str,
    },
    List,
    Append {
        collection: &'r str,
        data: Box<RawValue>,
    },
    Prepare {
        code: String,
    },
    Execute {
        code_ref: &'r str,
        query: &'r str,
        param: Box<RawValue>,
        privileged: bool,
    },
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Collection {
    pub name: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct CodeRef {
    pub code_ref: String,
}
