"""World-resolution library surface for Cadis."""

from cadis.version import __version__

from .cgd_world_resolver import CGDWorldResolver
from .global_lookup import GlobalLookup

__all__ = ["GlobalLookup", "CGDWorldResolver", "__version__"]
