# sme-sim-common

[English](README.md) | [日本語](README.ja.md) | **简体中文**

smart-edge 模拟器系列（SME BACnetSim、SME ModbusSim、OCPP 模拟器、SME SerialHub）的共通运行时：
Web 外壳（页头、菜单、主题、语言、关于）、厂商文案、`common.*` UI 词条，以及与协议无关的 Python 层
（Web 辅助、配置读写、行为、设备模板、测试辅助、PyInstaller hook）。
`templates/` 目录存放各产品手工复制的构建期骨架（CI、发布、打包、文档、页面），不进入 wheel。

MIT 许可，由 [smart-edge（智届科技）](https://smartedge-tech.com) 开发。

## 安装

```bash
pip install "sme-sim-common>=1.0,<2"          # 写入产品 pyproject.toml 的 dependencies
pip install "sme-sim-common[xlsx]>=1.0,<2"    # 含 .xlsx 导入 / 导出辅助（openpyxl）
pip install -e ../sme-sim-common              # 基于本地检出的开发
```

需要 Python 3.11 及以上。

## 在产品中使用

### 挂载共通静态文件

```python
from fastapi import FastAPI
from sme_sim_common.web import mount_common, mount_product_static

app = FastAPI()
mount_common(app)                          # 提供 /sme-sim-common/{shell,vendor,i18n,brand}/...
mount_product_static(app, STATIC_DIR)      # 产品自己的 /static（目录不存在时跳过）
```

共通文件使用独立前缀 `/sme-sim-common`，不放在 `/static` 下：Starlette 按注册顺序匹配挂载点，
嵌套路径会被产品的 `/static` 吞掉。

### 最小应用

```python
import argparse
from pathlib import Path

from sme_sim_common.cli import add_common_args, run_web
from sme_sim_common.web import make_base_app

ap = add_common_args(argparse.ArgumentParser(), default_http_port=8080, app_name="sme-my-sim")
args = ap.parse_args()
engine = MyEngine(...)                     # 遵循 sme_sim_common.engine.EngineProtocol（或继承 BaseEngine）
app = make_base_app(engine, config_path=args.config, static_dir=Path(__file__).parent / "static")
run_web(app, args)                         # 用 uvicorn 在 args.host / args.http_port 启动并打开浏览器
```

### 页面骨架

从 `templates/static/index.html` 开始。加载顺序固定：

1. `/sme-sim-common/shell/shell.css`，然后产品的 `/static/style.css`
2. 在 `<head>` 中加载 `/sme-sim-common/shell/shell.js`（`data-storage="<dist 名>"` 为 localStorage 前缀；已保存的主题在首次绘制前生效）
3. `/sme-sim-common/vendor/vendor.js`，然后 `/sme-sim-common/i18n/common.js`
4. 产品词典 `/static/i18n/en.js`、`ja.js`、`zh.js`，最后 `/static/app.js`

共通资源带 `?v=` 版本参数，避免升级后浏览器继续使用旧的外壳文件；
`Shell.version` 返回 sme-sim-common 的版本，关于对话框中也会显示。

### 厂商

`vendor/vendor.js` 注册公司预设 `Shell.vendors.smartEdge` 和 `vendor.*` 词条。产品显式传入：

```js
Shell.init({ ...PRODUCT, vendor: Shell.vendors.smartEdge });
```

公司文案只在这里维护，下一次共通包发布后全系列同步生效。

### i18n 前缀

| 前缀 | 所有者 |
|---|---|
| `shell.*` | sme-sim-common：UI 框架（菜单、主题、语言、帮助、关于）— `shell.js` |
| `vendor.*` | sme-sim-common：公司文案 — `vendor/vendor.js` |
| `common.*` | sme-sim-common：共通层提供的功能 — `i18n/common.js` |
| 其它 | 产品 — `static/i18n/{en,ja,zh}.js` |

产品不得定义这三个保留前缀。在产品测试中检查：

```python
from sme_sim_common.testing import check_i18n_keys

def test_no_reserved_i18n_keys():
    check_i18n_keys(STATIC_DIR)
```

`common.*` 的 key 按功能命名而不是按菜单位置命名，并且在系列中任一产品里都不能有歧义
（例如用 `common.backend.connected`，而不是 `ws.on`）。

### 主色

每个产品有自己的主色。`shell.css` 默认为品牌蓝 `#087def`；产品在 `style.css` 的三处
（`:root`、`:root[data-theme="dark"]` 和 `prefers-color-scheme: dark` 块）覆盖 `--accent`、`--accent-ink`、`--accent-weak`
（见 `templates/static/style.css`）。厂商区域使用 `--vendor-accent`（始终为品牌蓝），不得覆盖。

### 测试与打包

- pytest 插件（asyncio 超时 + 挂起转储）通过 `pytest11` entry point 自动启用。
- PyInstaller hook（`pyinstaller40` entry point）自动收集共通静态文件和 uvicorn 的 hidden imports，
  产品 spec 只需列出自己的文件。

## 系列端口表

各产品 Web UI 的默认端口，保证姊妹产品可以同时运行。新产品先在此登记。

| 产品 | 默认 HTTP 端口 |
|---|---|
| SME BACnetSim | 8080 |
| SME ModbusSim | 8081 |
| OCPP 模拟器 | 待定 |
| SME SerialHub | 待定 |

## 系列主色表

| 产品 | `--accent` | `--accent-ink` | `--accent-weak` | 暗色主题 |
|---|---|---|---|---|
| SME BACnetSim | `#087def`（品牌蓝，外壳默认） | `#fff` | `#e7f2fe` | 外壳默认（`#3d9bff` / `#fff` / `#11304f`） |
| SME ModbusSim | `#0f766e`（teal） | `#ffffff` | `#ccfbf1` | 待定 |
| OCPP 模拟器 | 待定 | 待定 | 待定 | 待定 |
| SME SerialHub | 待定 | 待定 | 待定 | 待定 |

## 版本策略

- 语义化版本，首发 `1.0.0`。1.x 内只做向后兼容的增补（新 key、新可选参数、新模块）与修复；
  破坏性变更即 2.0，原则上不做。
- 产品依赖写 `sme-sim-common>=1.0,<2`。
- 唯一版本源是 `sme_sim_common.__version__`；`Shell.version` 与之同值。

## 模板

新产品接入或既有产品迁移时，按 [`templates/CHECKLIST.md`](templates/CHECKLIST.md) 操作
（占位符、端口 / 主色登记、i18n 规则、PyInstaller、PyPI trusted publishing）。

## 发布 sme-sim-common

1. 更新 `__version__` 与 `CHANGELOG.md` 中的 `## [x.y.z] - YYYY-MM-DD` 段落。
2. 推送 tag `vx.y.z`。`.github/workflows/release.yml` 会构建 sdist 与 wheel、用 `twine` 检查、
   通过 trusted publishing（environment `pypi`）发布到 PyPI，并以 CHANGELOG 段落为说明创建 GitHub Release。
   workflow 文件名 `release.yml` 与 environment 名 `pypi` 已在 PyPI 登记，请勿改名。

## 许可

MIT — 参见 [LICENSE](LICENSE)。
