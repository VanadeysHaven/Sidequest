"""Sidequest: a Discord to-do bot."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sidequest")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
