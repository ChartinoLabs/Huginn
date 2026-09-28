# Installation

## Requirements

- Python 3.10 or later
- Network devices reachable via SSH (or another supported transport)

## Install from PyPI

```bash
pip install huginn-framework
```

Or using [uv](https://docs.astral.sh/uv/):

```bash
uv add huginn-framework
```

## Install from source

For development or to track the latest unreleased changes:

```bash
pip install git+https://github.com/ChartinoLabs/Huginn.git
```

Or clone and install in editable mode:

```bash
git clone https://github.com/ChartinoLabs/Huginn.git
cd Huginn
uv sync --group dev
```

## Verify installation

```bash
huginn version
```

You should see output like:

```
huginn v0.2.0
```

## Key dependencies

Huginn pulls in a small set of runtime dependencies automatically:

- **scrapli** - async SSH transport for device connections
- **scrapli-netconf** - async NETCONF transport for device connections
- **aiohttp** - async HTTP client for the HTTP broker
- **typer** - CLI framework
- **jinja2** - template rendering for test metadata and reports
- **markdown** - Markdown rendering for HTML report sections
- **pyyaml / ruamel.yaml** - testbed and test plan YAML parsing
- **tomli** - TOML parsing on Python 3.10 only (Python 3.11 and later use the standard library `tomllib`)
