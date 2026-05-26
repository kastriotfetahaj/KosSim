__all__ = [
    "LocalContext",
    "external",
    "internal",
]

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LocalContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    self_id: str
    metrics: bool = False
    metrics_file: Optional[Path] = None
