# Installation

## Requirements

- Python 3.11 or later
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
Huginn version 0.1.0
```

## Key dependencies

Huginn pulls in a small set of runtime dependencies automatically:

- **scrapli** - async SSH and NETCONF transport for device connections
- **typer** - CLI framework
- **jinja2** - template rendering for test metadata and reports
- **pyyaml / ruamel.yaml** - testbed and test plan YAML parsing
