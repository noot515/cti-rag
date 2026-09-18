"""Read-only OpenCTI capture integration."""

from .reader import OpenCTIReader, RecordedOpenCTITransport

__all__ = ["OpenCTIReader", "RecordedOpenCTITransport"]
