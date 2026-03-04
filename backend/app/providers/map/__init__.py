"""Map provider package — abstract base, Amap/Google implementations, and factory."""

from .base import IMapProvider
from .factory import get_map_provider

__all__ = ["IMapProvider", "get_map_provider"]
