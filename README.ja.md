# sme-sim-common

[English](README.md) | **日本語** | [简体中文](README.zh-CN.md)

smart-edge のシミュレーターシリーズ（SME BACnetSim、SME ModbusSim、OCPP シミュレーター、SME SerialHub）の共通ランタイムです。
Web シェル（ヘッダー、メニュー、テーマ、言語、About）、ベンダー文言、`common.*` UI 文字列、プロトコルに依存しない Python 層
（Web ヘルパー、設定 I/O、ビヘイビア、デバイステンプレート、テスト補助、PyInstaller フック）を提供します。
`templates/` ディレクトリには、各製品が手作業でコピーするビルド時の雛形（CI、リリース、パッケージング、ドキュメント、ページ）を置いています。wheel には含まれません。

MIT ライセンス。開発は [smart-edge（智届科技）](https://smartedge-tech.com)。

## インストール

```bash
pip install "sme-sim-common>=1.0,<2"          # 製品の pyproject.toml の dependencies に記載
pip install "sme-sim-common[xlsx]>=1.0,<2"    # .xlsx インポート／エクスポート補助（openpyxl）付き
pip install -e ../sme-sim-common              # チェックアウトを使ったローカル開発
```

Python 3.11 以上。

## 製品での使い方

### 共通静的ファイルのマウント

```python
from fastapi import FastAPI
from sme_sim_common.web import mount_common, mount_product_static

app = FastAPI()
mount_common(app)                          # /sme-sim-common/{shell,vendor,i18n,brand}/... を配信
mount_product_static(app, STATIC_DIR)      # 製品自身の /static（ディレクトリが無ければスキップ）
```

共通ファイルは独自のプレフィックス `/sme-sim-common` で配信し、`/static` の下には置きません。
Starlette は登録順にマウントを照合するため、入れ子にすると製品の `/static` に吸い込まれます。

### 最小のアプリ

```python
import argparse
from pathlib import Path

from sme_sim_common.cli import add_common_args, run_web
from sme_sim_common.web import make_base_app

ap = add_common_args(argparse.ArgumentParser(), default_http_port=8080, app_name="sme-my-sim")
args = ap.parse_args()
engine = MyEngine(...)                     # sme_sim_common.engine.EngineProtocol に従う（または BaseEngine を継承）
app = make_base_app(engine, config_path=args.config, static_dir=Path(__file__).parent / "static")
run_web(app, args)                         # uvicorn を args.host / args.http_port で起動し、ブラウザを開く
```

### ページの骨格

`templates/static/index.html` から始めます。読み込み順は固定です：

1. `/sme-sim-common/shell/shell.css`、次に製品の `/static/style.css`
2. `<head>` 内で `/sme-sim-common/shell/shell.js`（`data-storage="<dist 名>"` は localStorage のプレフィックス。保存済みテーマを初回描画前に適用）
3. `/sme-sim-common/vendor/vendor.js`、次に `/sme-sim-common/i18n/common.js`
4. 製品の辞書 `/static/i18n/en.js`・`ja.js`・`zh.js`、最後に `/static/app.js`

共通アセットには `?v=` のバージョンクエリが付き、アップグレード後に古いシェルがキャッシュから使われるのを防ぎます。
`Shell.version` は sme-sim-common のバージョンを返し、About ダイアログにも表示されます。

### ベンダー

`vendor/vendor.js` は会社プリセット `Shell.vendors.smartEdge` と `vendor.*` 文字列を登録します。製品は明示的に渡します：

```js
Shell.init({ ...PRODUCT, vendor: Shell.vendors.smartEdge });
```

会社の文言はここだけで管理し、次の共通パッケージのリリースで全製品に反映されます。

### i18n プレフィックス

| プレフィックス | 所有者 |
|---|---|
| `shell.*` | sme-sim-common：UI フレームワーク（メニュー、テーマ、言語、ヘルプ、About）— `shell.js` |
| `vendor.*` | sme-sim-common：会社文言 — `vendor/vendor.js` |
| `common.*` | sme-sim-common：共通層が提供する機能 — `i18n/common.js` |
| その他 | 製品 — `static/i18n/{en,ja,zh}.js` |

製品は予約済みの 3 プレフィックスを定義してはいけません。製品のテストで確認します：

```python
from sme_sim_common.testing import check_i18n_keys

def test_no_reserved_i18n_keys():
    check_i18n_keys(STATIC_DIR)
```

`common.*` のキーはメニュー上の位置ではなく機能で命名し、シリーズのどの製品でも曖昧にならないようにします
（例：`ws.on` ではなく `common.backend.connected`）。

### 主色

製品ごとに主色を持ちます。`shell.css` の既定はブランドブルー `#087def` です。製品は `style.css` の 3 か所
（`:root`、`:root[data-theme="dark"]`、`prefers-color-scheme: dark` ブロック）で `--accent`・`--accent-ink`・`--accent-weak` を上書きします
（`templates/static/style.css` 参照）。ベンダー領域は `--vendor-accent`（常にブランドブルー）を使い、上書きしません。

### 拡張ポイント

いずれも任意です。製品は標準ルートを作り直さず、これらを渡します。

- デバイスキー：`key_type`（既定は `device_key` フィールドの型、`int` か `str`）でパスパラメーターを変換します
  —— `make_base_app(engine, device_key="device_id")` は `/api/devices/1001/config` を `1001` として扱います。
- `create_hook(engine, body) -> dict`：新規デバイスを検証前に補完します
  （`create_hook=lambda e, b: {**b, "device_id": b.get("device_id") or free_id(e)}`）。
- `duplicate_hook(engine, dev, new_key, body) -> dict`：「既に存在する」チェックの前に呼ばれ、キーを変更できます
  （`duplicate_hook=lambda e, d, k, b: {**d, "unit": free_unit(e)}`）。フックなしの場合、複製のキーは
  `{key}_copy`（`str` キー）または最大値 + 1（`int` キー）です。
- `simulation_hook(engine, rest) -> dict | None`：`POST /api/simulation` の `running` / `time_scale` 以外の
  フィールドを受け取り、dict の戻り値はレスポンスにマージされます（`simulation_hook=lambda e, rest: e.apply_set_time(rest)`）。
- `TemplateRegistry(..., extra_keys=("identification",))`：ユーザーテンプレートで追加のトップレベルキーを許可します。
  `registry.expand_device_extras(dev)` はデバイス側のフィールドとマージした値を返し（デバイスの非空値が優先、dict は浅くマージ）、
  `device_as_template` もそれを書き出します。
- `import_hooks={".csv": import_ede, ".zip": import_ede, ".yaml": import_text}`（`POST /api/config/import`）：
  `hook(engine, files: dict[name, bytes]) -> (config | None, messages[, config_text])`。`.xlsx`（およびその他の拡張子）は
  従来どおり `XlsxSchema` が処理します。イベントログには警告件数と先頭 5 件が記録されます。
- `add_common_args(ap, ..., open_browser=False)`：既定でブラウザーを開きません（`--browser` で開く。`--no-browser` も残ります）。
- `engine.wake()`：模擬時間を進めず、tick のリズムも崩さずに `_on_tick`（スキャン・プッシュ）を 1 回すぐ実行します。
  スレッドセーフです（`stack.on_write = lambda *a: engine.wake()`）。
- `BaseEngine` サブクラスの `logger_name = "sme_my_sim.engine"`：`self.logger` の名前になり、エンジン内部のログはすべてこれを使います。
- `src_key` キーワード（または `**kwargs`）を受け取る `duplicate_hook` には複製元のキーも渡されます
  （例「複製元 + 1 以降の最初の空き」：`def dup(engine, dev, new_key, body, *, src_key)`）。受け取らないフックは
  従来どおり呼ばれます。`dev` は新しいコピー（複製元のダンプ + 新キー）で、複製元そのものは渡されません。
- 存在しないデバイスの 404 は変換後のキーを表示します：`unknown device 1008`（`int` キーは引用符なし）。
- `Sheet(..., open_columns=True)`：エクスポート時、列のないスカラー項目を既知列の後ろに出現順で動的列として出力し、
  `text_1`〜`text_12` が往復で欠けません。`export_rows` は `(rows, {sheet: [(header, help), ...]})` を返して
  追加列を明示することもできます（明示分が先）。
- `export_rows` は `(rows, extra_columns, warnings)` も返せます（`extra_columns` は `None` 可）：製品独自の
  エクスポート警告（参照先なし等）が `export_xlsx` から共通パッケージの警告（セル文字数上限等）より先に返ります。
- `Sheet(..., required_headers=("value",))`：列の存在のみ必須でセルは空でも可（`required` は従来どおり
  「存在かつ非空」）。`skip_blank=("value",)`：`value` が空の行はエラーにせず読み飛ばします（`Network` のような
  key / value シート向け）。

### 移行時の注意

- `state` は `BaseEngine` のインスタンス属性（`_build` の結果）です。サブクラスで `state()` メソッドを定義してはいけません。
- `BaseEngine.event_history(limit)` は共通イベントログです。製品独自の履歴（例：ポイントごとの
  `history(device_id, key)` API）とは衝突しません。
- `product_routers` に渡した FastAPI `APIRouter` のルートは `app.routes` に平坦に展開されます（`include_router` で
  包みません）。`APIRoute` のままなので依存性注入は通常どおり使えます。

### テストとパッケージング

- pytest プラグイン（asyncio タイムアウト＋ハングダンプ）は `pytest11` エントリーポイントで自動的に有効になります。
- PyInstaller フック（`pyinstaller40` エントリーポイント）が共通静的ファイルと uvicorn の hidden imports を収集するため、
  製品の spec には自製品のファイルだけを書きます。

## シリーズのポート表

姉妹製品を同時に起動できるよう、Web UI の既定ポートをここで管理します。新製品はまずここに登録します。

| 製品 | 既定 HTTP ポート |
|---|---|
| SME BACnetSim | 8080 |
| SME ModbusSim | 8081 |
| OCPP シミュレーター | 未定 |
| SME SerialHub | 未定 |

## シリーズの主色表

| 製品 | `--accent` | `--accent-ink` | `--accent-weak` | ダークテーマ |
|---|---|---|---|---|
| SME BACnetSim | `#087def`（ブランドブルー、シェル既定） | `#fff` | `#e7f2fe` | シェル既定（`#3d9bff` / `#fff` / `#11304f`） |
| SME ModbusSim | `#0f766e`（ティール） | `#ffffff` | `#ccfbf1` | `#2dd4bf` / `#042f2e` / `#134e4a` |
| OCPP シミュレーター | 未定 | 未定 | 未定 | 未定 |
| SME SerialHub | 未定 | 未定 | 未定 | 未定 |

## バージョン方針

- セマンティックバージョニング。初回リリースは `1.0.0`。1.x では後方互換の追加（新しいキー、新しい任意引数、新しいモジュール）と修正のみ行い、
  破壊的変更は 2.0 となるため原則行いません。
- 製品の依存指定は `sme-sim-common>=1.0,<2`。
- バージョンの唯一の情報源は `sme_sim_common.__version__`。`Shell.version` も同じ値です。

## テンプレート

新製品・移行製品でのテンプレート導入手順は [`templates/CHECKLIST.md`](templates/CHECKLIST.md) を参照してください
（プレースホルダー、ポート／主色の登録、i18n ルール、PyInstaller、PyPI trusted publishing）。

## sme-sim-common のリリース

1. `__version__` と `CHANGELOG.md` の `## [x.y.z] - YYYY-MM-DD` セクションを更新します。
2. タグ `vx.y.z` を push します。`.github/workflows/release.yml` が sdist と wheel をビルドして `twine` で検査し、
   trusted publishing（environment `pypi`）で PyPI に公開し、CHANGELOG のセクションをノートとして GitHub Release を作成します。
   ワークフローのファイル名 `release.yml` と environment 名 `pypi` は PyPI に登録済みのため、変更しないでください。

## ライセンス

MIT — [LICENSE](LICENSE) を参照。
