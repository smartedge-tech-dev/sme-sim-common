# {{display_name}}

[English](README.md) | [日本語](README.ja.md) | **简体中文**

{{description_zh}}

{{display_name}} 是免费的 MIT 许可软件，由 [smart-edge（智届科技）](https://smartedge-tech.com) 开发。
如需定制开发，请参阅 [商业支持与定制开发](#商业支持与定制开发)。

## 快速入门

```powershell
python -m venv .venv
.venv\Scripts\pip install {{dist_name}}
.venv\Scripts\{{dist_name}} --config configs/demo.yaml
```

打开 http://127.0.0.1:{{default_http_port}}/ 。通用选项（由 sme-sim-common 提供）：

| 选项 | 含义 |
|---|---|
| `-c, --config FILE` | YAML 配置文件 |
| `--host 127.0.0.1` | Web UI 监听地址（默认仅本机） |
| `--http-port {{default_http_port}}` | Web UI 端口 |
| `--no-browser` | 启动时不打开浏览器 |
| `--version`, `-v` | 显示版本 / 详细日志 |

## 配置

TODO

## HTTP API

TODO

## 开发

TODO

## 商业支持与定制开发

TODO（从 SME BACnetSim 的 README.zh-CN.md 转载）

## 许可

MIT — 参见 [LICENSE](LICENSE)。
