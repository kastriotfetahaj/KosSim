from flask import Flask, json
from werkzeug.exceptions import HTTPException


class SNMPException(Exception):
    pass


def handle_exception(e):
    response = e.get_response()
    response.data = json.dumps(
        {
            "code": e.code,
            "name": e.name,
            "description": e.description,
        }
    )
    response.content_type = "application/json"
    return response


def handle_snmp_exception(e):
    description, code = e.args
    return {
        "code": code,
        "name": "SNMP error",
        "description": description,
    }, code


def register(app: Flask):
    app.register_error_handler(HTTPException, handle_exception)
    app.register_error_handler(SNMPException, handle_snmp_exception)
