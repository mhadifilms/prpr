"""Command-line interface for `prpr`.

The CLI is a thin wrapper around the library: every command is a
``Premiere()`` call followed by an ``output()`` call. All formatting,
serialization, and error rendering lives in :mod:`prpr.cli.output`.
"""
