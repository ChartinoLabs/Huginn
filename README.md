# Huginn

[![CI](https://github.com/ChartinoLabs/Huginn/actions/workflows/ci.yml/badge.svg)](https://github.com/ChartinoLabs/Huginn/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue?logo=python&logoColor=white)](https://www.python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

A Python-native, async-first test automation framework for network infrastructure, servers, and applications.

## Overview

Huginn is designed for skilled test engineers who need to validate infrastructure state at scale. Named after one of Odin's ravens who flies across the world gathering information, Huginn dispatches tests to observe your infrastructure, gather state, and report findings. The framework maintains a minimal core with optional plugins, handles test orchestration and connection management, and supports dual execution modes: learning current state from live infrastructure and testing against previously-learned parameters.

## Installation

```bash
pip install git+https://github.com/ChartinoLabs/Huginn.git
```

Or using [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/ChartinoLabs/Huginn.git
```

Requires Python 3.11 or later. See the [documentation](https://chartinolabs.github.io/Huginn/) for a full quickstart guide.

## License

Licensed under the Apache License 2.0.
