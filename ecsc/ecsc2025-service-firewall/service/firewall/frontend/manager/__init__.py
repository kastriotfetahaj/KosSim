from flask import Blueprint

import os
import pathlib


from .agent_interface import init as init_agent_interface
from .exception import register as register_e
from .routes import register as register_r


def create_manager(config):
    # Derive auth community
    auth_community = config.auth_community
    placeholder = "__COMMUNITY__" in auth_community
    community = os.getenv("SNMP_AUTH_COMMUNITY")
    community_file = os.getenv("SNMP_AUTH_COMMUNITY_FILE")
    if community_file and community:
        raise RuntimeError("SNMP auth community specified both inline and via secrets file")
    elif community_file:
        community = pathlib.Path(community_file).read_text().strip()

    if community and placeholder:
        auth_community = auth_community.replace("__COMMUNITY__", community)
    elif community:
        raise RuntimeError("SNMP auth community specified separately, but no placeholder found")
    elif placeholder:
        raise RuntimeError('SNMP auth community is missing (placeholder "__COMMUNITY__" found)')

    bp = Blueprint('manager', __name__, url_prefix=config.path)
    init_agent_interface(config.default_community, auth_community)
    register_r(bp)
    register_e(bp)
    return bp
