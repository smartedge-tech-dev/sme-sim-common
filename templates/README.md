# {{display_name}}

**English** | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

{{description}}

{{display_name}} is free and MIT-licensed, developed by [smart-edge (智届科技)](https://smartedge-tech.com) —
custom development is available, see [Commercial support & custom development](#commercial-support--custom-development).

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\pip install {{dist_name}}
.venv\Scripts\{{dist_name}} --config configs/demo.yaml
```

Open http://127.0.0.1:{{default_http_port}}/ . Common options (from sme-sim-common):

| Option | Meaning |
|---|---|
| `-c, --config FILE` | YAML config |
| `--host 127.0.0.1` | Web UI bind address (default localhost only) |
| `--http-port {{default_http_port}}` | Web UI port |
| `--no-browser` | Do not open the browser on start |
| `--version`, `-v` | Show the version / verbose logging |

A Windows single-file executable is attached to every [release](https://github.com/smartedge-tech-dev/{{dist_name}}/releases).

## Configuration

TODO

## HTTP API

TODO

## Development

```powershell
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
```

## Commercial support & custom development

TODO: copy this section from the SME BACnetSim README.

## License

MIT — see [LICENSE](LICENSE).
