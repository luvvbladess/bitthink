"""Studio: structured presentations and infographics."""

from studio.build import build_studio_artifact
from studio.schema import StudioSpecError, normalize_spec

__all__ = ["build_studio_artifact", "normalize_spec", "StudioSpecError"]
