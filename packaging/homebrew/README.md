# Homebrew formula

`pmr.rb` is the tap formula for [mhadifilms/homebrew-tap](https://github.com/mhadifilms/homebrew-tap),
mirroring the `dvr` formula there.

Homebrew's Python formulas vendor every dependency as a `resource` with a
pinned sha256, and those are generated from the **published** sdist — so
the formula is finalized right after the PyPI upload:

```bash
# 1. publish pmr to PyPI (see the release checklist), then:
brew tap mhadifilms/tap
cp packaging/homebrew/pmr.rb "$(brew --repository mhadifilms/tap)/Formula/pmr.rb"

# 2. fill url + sha256 from the PyPI sdist
#    (https://pypi.org/project/pmr/#files → tarball → "Copy SHA256")

# 3. generate the resource stanzas (replaces the <<RESOURCES>> marker)
brew update-python-resources "$(brew --repository mhadifilms/tap)/Formula/pmr.rb"

# 4. verify, then commit to the tap
brew install --build-from-source mhadifilms/tap/pmr
brew test mhadifilms/tap/pmr
brew audit --strict --online mhadifilms/tap/pmr
```

`mcp` is intentionally left out of the vendored resources (the CLI and
library run without it); users who want the MCP server install via
`pip install pmr`.
