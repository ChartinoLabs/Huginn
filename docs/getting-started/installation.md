# Installation

## Requirements

- Python 3.11 or later
- Network devices reachable via SSH (or another supported transport)

## Install from source

Huginn is not yet published to PyPI. Install directly from the repository:

```bash
git clone https://github.com/ChartinoLabs/Huginn.git
cd Huginn
pip install -e .
```

Or using [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ChartinoLabs/Huginn.git
cd Huginn
uv sync
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

- **scrapli** — async SSH and NETCONF transport for device connections
- **typer** — CLI framework
- **jinja2** — template rendering for test metadata and reports
- **pyyaml / ruamel.yaml** — testbed and test plan YAML parsing
