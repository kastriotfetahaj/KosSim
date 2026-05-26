from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field

ResourceName = Annotated[str, Field(pattern=r"[a-zA-Z0-9-_]+")]
Resource = dict[str, Any]

class ElasticConfiguration(BaseModel):
    indexLifecyclePolicies: Optional[dict[ResourceName, Resource]] = None
    componentTemplates: Optional[dict[ResourceName, Resource]] = None
    indexTemplates: Optional[dict[ResourceName, Resource]] = None
    ingestPipelines: Optional[dict[ResourceName, Resource]] = None
    snapshotLifecyclePolicies: Optional[dict[ResourceName, Resource]] = None
    snapshotRepositories: Optional[dict[ResourceName, Resource]] = None

URLS = {
    "indexLifecyclePolicies": "/_ilm/policy/",
    "componentTemplates": "/_component_template/",
    "indexTemplate": "/_index_template/",
    "ingestPipelines": "/_ingest/pipeline/",
    "snapshotLifecyclePolicies": "/_slm/policy/",
    "snapshotRepositories": "/_snapshot/",
}

ELASTIC_USER_ENV = "ELASTIC_USER"
ELASTIC_PASSWORD = "ELASTIC_PASSWORD"


# Poll until cluster accessible and healthy,
# Apply resources in order specified, if code good print OK.
# else print full error message and resource
# exit 1 if any request failed


def hello() -> str:
    return "Hello from elastic-configurator!"
