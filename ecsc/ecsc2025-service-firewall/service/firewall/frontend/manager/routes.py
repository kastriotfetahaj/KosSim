from flask import Flask, redirect, request, render_template, session, url_for
from flask_pydantic import validate
from functools import wraps
from ipaddress import ip_address
from struct import pack


from .agent_interface import (
    get_custom_value,
    get_raw,
    set_custom_value,
    get_monitoring_value,
    get_monitoring_values,
    get_user_monitoring_labels,
    get_user_monitoring_value,
)
from .models import (
    AdvancedGet,
    AdvancedResponse,
    CustomGet,
    CustomPost,
    CustomResponse,
    MonitoringGet,
    MonitoringResponse,
    MonitoringInitResponse,
)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not "user" in session or not "identifier" in session:
            return redirect(url_for("main_view"))
        return f(*args, **kwargs)

    return decorated_function


@login_required
@validate()
def advanced_get(query: AdvancedGet):
    var = get_raw(bytes.fromhex(query.data))
    return AdvancedResponse(value=var.hex())


@login_required
@validate()
def custom_get(query: CustomGet):
    var = get_custom_value(bytes.fromhex(query.identifier), bytes.fromhex(query.secret))
    model = CustomResponse.model_construct(identifier=query.identifier, value=var)
    CustomResponse.model_validate(model, strict=True)
    return model


@login_required
@validate()
def custom_post(body: CustomPost):
    identifier = pack(">q", session["identifier"])
    var = set_custom_value(identifier, bytes.fromhex(body.secret), body.value)
    model = CustomResponse.model_construct(identifier=identifier.hex(), value=var)
    CustomResponse.model_validate(model, strict=True)
    return model


@login_required
@validate()
def monitoring_get(query: MonitoringGet):
    var = get_monitoring_value(query.label)
    return MonitoringResponse(value=var)


@login_required
@validate()
def user_monitoring_get(query: MonitoringGet):
    var = get_user_monitoring_value(pack(">q", session["identifier"]), query.label)
    return MonitoringResponse(value=var)


@login_required
@validate()
def monitoring_init_get():
    values = get_monitoring_values()
    return MonitoringInitResponse(values=values)


@login_required
@validate()
def user_monitoring_init_get():
    values = get_user_monitoring_labels()
    return MonitoringInitResponse(values={v: "" for v in values})


@login_required
def index():
    return redirect(url_for("manager.monitoring_view"))


@login_required
def monitoring_view():
    return render_template(
        "monitoring.html",
        function_name="monitoringInit",
        user=session["user"],
        endpoint=url_for("manager.monitoring_view"),
    )


@login_required
def user_monitoring_view():
    return render_template(
        "monitoring.html",
        function_name="userMonitoringInit",
        user=session["user"],
        endpoint=url_for("manager.user_monitoring_view"),
    )


@login_required
def custom_view():
    return render_template("custom.html", user=session["user"], endpoint=url_for("manager.custom_view"))


@login_required
def advanced_view():
    return render_template("advanced.html", user=session["user"], endpoint=url_for("manager.advanced_view"))


def register(app: Flask):
    app.add_url_rule("/api/advanced", view_func=advanced_get, methods=["GET"])
    app.add_url_rule("/api/custom", view_func=custom_get, methods=["GET"])
    app.add_url_rule("/api/custom", view_func=custom_post, methods=["POST"])
    app.add_url_rule("/api/monitoring", view_func=monitoring_get, methods=["GET"])
    app.add_url_rule("/api/monitoring_user", view_func=user_monitoring_get, methods=["GET"])
    app.add_url_rule("/api/monitoring_init", view_func=monitoring_init_get, methods=["GET"])
    app.add_url_rule("/api/monitoring_user_init", view_func=user_monitoring_init_get, methods=["GET"])
    app.add_url_rule("/", view_func=index)
    app.add_url_rule("/monitoring/", view_func=monitoring_view)
    app.add_url_rule("/monitoring_user/", view_func=user_monitoring_view)
    app.add_url_rule("/custom/", view_func=custom_view)
    app.add_url_rule("/advanced/", view_func=advanced_view)
