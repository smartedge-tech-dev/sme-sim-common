# sme-sim-common

[English](README.md) | [日本語](README.ja.md) | **简体中文**

smart-edge 模拟器系列（SME BACnetSim、SME ModbusSim、SME OCPPSim、SME SerialHub）的共通运行时：
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

### 扩展点

均为可选；产品传入这些参数，而不是重写标准路由。

- 设备 key：`key_type`（默认取 `device_key` 字段的类型，`int` 或 `str`）用于转换路径参数
  —— `make_base_app(engine, device_key="device_id")` 把 `/api/devices/1001/config` 解析为 `1001`。
- `create_hook(engine, body) -> dict`：在校验前补全新设备
  （`create_hook=lambda e, b: {**b, "device_id": b.get("device_id") or free_id(e)}`）。
- `duplicate_hook(engine, dev, new_key, body) -> dict`：在「已存在」检查之前调用，可以改 key
  （`duplicate_hook=lambda e, d, k, b: {**d, "unit": free_unit(e)}`）。无 hook 时副本的 key 为
  `{key}_copy`（`str` key）或当前最大值 + 1（`int` key）。
- `simulation_hook(engine, rest) -> dict | None`：接收 `POST /api/simulation` 中 `running` / `time_scale` 以外的字段，
  返回的 dict 合并进响应（`simulation_hook=lambda e, rest: e.apply_set_time(rest)`）。
- `TemplateRegistry(..., extra_keys=("identification",))`：允许用户模板带额外的顶层 key；
  `registry.expand_device_extras(dev)` 返回与设备自身字段合并后的值（设备的非空值优先，dict 做浅合并），
  `device_as_template` 也会导出它们。
- `import_hooks={".csv": import_ede, ".zip": import_ede, ".yaml": import_text}`（`POST /api/config/import`）：
  `hook(engine, files: dict[name, bytes]) -> (config | None, messages[, config_text])`；`.xlsx`（及其它扩展名）仍由
  `XlsxSchema` 处理。事件日志记录 warning 件数和前 5 条。
- `add_common_args(ap, ..., open_browser=False)`：默认不打开浏览器（`--browser` 强制打开，`--no-browser` 保留）。
- `engine.wake()`：立即执行一轮 `_on_tick`（扫描、推送），不推进模拟时间、不打乱 tick 节奏；线程安全
  （`stack.on_write = lambda *a: engine.wake()`）。
- `BaseEngine` 子类的 `logger_name = "sme_my_sim.engine"`：作为 `self.logger` 的名字，引擎内部日志全部走它。
- 接受 `src_key` 关键字（或 `**kwargs`）的 `duplicate_hook` 还会拿到源设备的 key
  （例「源 key + 1 起第一个空闲」：`def dup(engine, dev, new_key, body, *, src_key)`）。不接受的 hook 照旧调用；
  `dev` 是新拷贝（源设备 dump + 新 key），源设备本身不会传入。
- 未知设备的 404 显示转换后的 key：`unknown device 1008`（`int` key 不带引号）。
- `Sheet(..., open_columns=True)`：导出时没有对应列的标量字段按出现顺序作为动态列排在已知列之后，
  `text_1`〜`text_12` 往返不丢；`export_rows` 也可以返回 `(rows, {sheet: [(header, help), ...]})` 显式指定额外列
  （显式的排在前面）。
- `export_rows` 还可以返回 `(rows, extra_columns, warnings)`（`extra_columns` 可为 `None`）：产品自己的导出警告
  （例如引用不存在）由 `export_xlsx` 返回，排在共通包警告（单元格长度上限等）之前。
- `Sheet(..., required_headers=("value",))`：只要求表头有该列，单元格可空（`required` 仍是「存在且非空」）；
  `skip_blank=("value",)`：`value` 为空的行直接跳过、不报错（适用于 `Network` 这类 key / value 表）。

### 配置写回

结果用 `atomic_write_text` 写入。两者都保留未改动部分的注释，布局特殊时退回到更大范围的重写。

- `replace_yaml_block(text, "network", value)`：替换一个顶层块。
- `replace_yaml_list_item(text, "chargers", "id", "0123", item)`：只替换 `id` 等于 `"0123"`（按 `str`
  比较）的列表项；没有则把 `item` 追加到末尾；`item=None` 时删除该项。其它项的行和注释原样保留。

### 迁移注意事项

- `state` 是 `BaseEngine` 的实例属性（`_build` 的结果）；子类不能定义 `state()` 方法。
- `BaseEngine.event_history(limit)` 是共通事件日志，与产品自身的 history（如按点的 `history(device_id, key)` API）不冲突。
- `product_routers` 中 FastAPI `APIRouter` 的路由被平铺进 `app.routes`（不经 `include_router` 包一层）；
  它们仍是 `APIRoute`，依赖注入照常可用。

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
| SME OCPPSim | 8082 |
| SME SerialHub | 待定 |

## 系列主色表

| 产品 | `--accent` | `--accent-ink` | `--accent-weak` | 暗色主题 |
|---|---|---|---|---|
| SME BACnetSim | `#087def`（品牌蓝，外壳默认） | `#fff` | `#e7f2fe` | 外壳默认（`#3d9bff` / `#fff` / `#11304f`） |
| SME ModbusSim | `#0f766e`（teal） | `#ffffff` | `#ccfbf1` | `#2dd4bf` / `#042f2e` / `#134e4a` |
| SME OCPPSim | `#b45309`（amber） | `#ffffff` | `#fef3c7` | `#fbbf24` / `#451a03` / `#78350f` |
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
