"""Excel (.xlsx) table import / export skeleton shared by the simulators (extra ``[xlsx]``: openpyxl).

Generalised from sme-bac-sim v0.4.0 ``sme_bacnet_sim/xlsx.py`` and sme-modbus-sim 085fe59 ``xlsx.py`` (helpers
``_flow`` / ``_scalar`` / ``_sheet`` / ``_workbook`` / ``_save`` / ``blank_template`` / ``_norm`` / ``_blank`` /
``_convert`` / ``_table`` / ``_pydantic_errors``). The product describes its workbook with an :class:`XlsxSchema`
and supplies two hooks: ``export_rows(cfg)`` (config -> rows per sheet) and ``build(tables, base, errors,
warnings)`` (rows per sheet -> config). Protocol specifics (Modicon addresses, BACnet units ...) stay in the
product as custom column converters.

Workbook layout: row 1 holds the column headers; row 2 starts with ``#`` and carries the help texts. Any row whose
first non-empty cell starts with ``#`` is ignored on import.

Contracts (design §7.1 / §8.2.1): ``export_xlsx(...) -> (bytes, warnings)``; ``import_xlsx(data, base, ...)``
returns ``(config, warnings)`` on success and ``(None, errors)`` on failure and never raises.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import yaml
from pydantic import BaseModel, ValidationError

__all__ = [
    "XLSX_TYPE",
    "CELL_LIMIT",
    "XlsxUnavailable",
    "Sheet",
    "SheetRow",
    "XlsxSchema",
    "export_xlsx",
    "import_xlsx",
    "to_yaml",
    "flow",
    "convert",
    "pydantic_errors",
]

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CELL_LIMIT = 32767  # Excel's maximum characters per cell
EXTRA = "extra"  # name of the catch-all YAML column (fields without a column of their own)

Converter = Callable[[Any], Any]
#: column kind name (see :func:`convert`) or a callable ``cell value -> config value`` raising ``ValueError``
Kind = Union[str, Converter]


class XlsxUnavailable(ImportError):
    """openpyxl is not installed (install the ``[xlsx]`` extra)."""


def _openpyxl():
    try:
        import openpyxl  # noqa: F401
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as e:  # pragma: no cover - exercised through monkeypatch in tests
        raise XlsxUnavailable("Excel support needs openpyxl: pip install 'sme-sim-common[xlsx]'") from e
    return openpyxl, Font, PatternFill, get_column_letter


# ---------------------------------------------------------------- small helpers

def flow(v: Any) -> str:
    """One-line YAML flow text of a value (``{a: 1, b: [2, 3]}``)."""
    return yaml.safe_dump(v, default_flow_style=True, sort_keys=False, allow_unicode=True, width=10 ** 9).strip()


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _norm(s: Any) -> str:
    return str(s).strip().lower().replace(" ", "_").replace("-", "_") if s is not None else ""


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def to_yaml(cfg: BaseModel) -> str:
    """YAML text of a config with only the fields that were set (keeps template overrides minimal)."""
    return yaml.safe_dump(cfg.model_dump(mode="json", exclude_unset=True, exclude_none=True),
                          allow_unicode=True, sort_keys=False)


def convert(kind: str, v: Any) -> Any:
    """Cell value -> config value for a built-in column kind; raises ``ValueError`` with a short reason.

    Kinds: ``str``, ``lower``, ``int``, ``float``, ``number`` (int when integral), ``bool`` (TRUE / FALSE / 1 / 0
    / yes / no), ``yaml`` (flow mapping), ``yaml_any`` (any YAML value), ``list`` (comma separated), ``port`` (int
    or text such as ``COM5``), ``value`` (as read).
    """
    if isinstance(v, str):
        v = v.strip()
    if kind == "int":
        if isinstance(v, bool):
            raise ValueError(f"not an integer: {v!r}")
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit()):
            return int(v)
        raise ValueError(f"not an integer: {v!r}")
    if kind in ("float", "number"):
        try:
            if isinstance(v, bool):
                raise ValueError
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"not a number: {v!r}") from None
        return int(f) if kind == "number" and f.is_integer() else f
    if kind == "bool":
        if isinstance(v, bool):
            return v
        s = str(int(v) if isinstance(v, float) and v.is_integer() else v).strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
        raise ValueError(f"not TRUE / FALSE: {v!r}")
    if kind == "port":
        return convert("int", v) if isinstance(v, (int, float)) or str(v).isdigit() else str(v)
    if kind in ("yaml", "yaml_any"):
        try:
            data = yaml.safe_load(str(v))
        except yaml.YAMLError as e:
            raise ValueError(f"invalid YAML: {str(e).splitlines()[0]}") from None
        if kind == "yaml" and not isinstance(data, dict):
            raise ValueError("expected a YAML mapping such as {key: value}")
        return data
    if kind == "list":
        return [x.strip() for x in str(v).split(",") if x.strip()]
    if kind in ("str", "lower"):
        s = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
        return s.lower() if kind == "lower" else s
    if kind == "value":
        return v
    raise ValueError(f"unknown column kind {kind!r}")


def pydantic_errors(e: ValidationError, prefix: str, columns: Optional[Sequence[str]] = None) -> List[str]:
    """``"<prefix>, column 'x': loc: message"`` lines; a location that is not a column is blamed on ``extra``."""
    cols = set(columns or ())
    out = []
    for err in e.errors():
        loc = [str(x) for x in err["loc"]]
        col = (loc[0] if loc[0] in cols else EXTRA if EXTRA in cols else None) if loc and cols else None
        msg = str(err["msg"]).removeprefix("Value error, ")
        out.append(f"{prefix}{', column ' + repr(col) if col else ''}: {'.'.join(loc) + ': ' if loc else ''}{msg}")
    return out


# ---------------------------------------------------------------- schema

@dataclass
class Sheet:
    """One worksheet: ``columns`` are ``(header, help)`` pairs in display order; ``kinds`` maps a header to a
    converter (kind name or callable, default ``str``); ``required`` columns must be present in the header row
    and non-empty in every data row. A sheet with an ``extra`` column round-trips fields without a column as a
    YAML flow mapping. ``optional`` sheets may be missing from an imported workbook. ``open_columns`` accepts
    unknown headers (dynamic columns such as ``text_N``) instead of warning about them and, on export, keeps the
    scalar fields without a column as dynamic columns after the known ones (see :meth:`XlsxSchema.row`).

    ``required_headers`` columns must be present in the header row but may be empty in data rows (``required``
    implies it). A data row with an empty cell in any ``skip_blank`` column is skipped silently: it is not
    converted, not checked and not returned (e.g. a ``key`` / ``value`` sheet whose rows without a ``value``
    keep the running setting)."""

    title: str
    columns: Sequence[Tuple[str, str]]
    kinds: Mapping[str, Kind] = field(default_factory=dict)
    required: Tuple[str, ...] = ()
    optional: bool = False
    open_columns: bool = False
    required_headers: Tuple[str, ...] = ()
    skip_blank: Tuple[str, ...] = ()

    @property
    def headers(self) -> List[str]:
        return [h for h, _ in self.columns]

    def kind(self, header: str) -> Kind:
        return self.kinds.get(header, "yaml" if header == EXTRA else "str")

    def convert(self, header: str, v: Any) -> Any:
        k = self.kind(header)
        return k(v) if callable(k) else convert(k, v)


@dataclass
class SheetRow:
    """A data row read from a sheet: 1-based ``row_no``, converted ``values`` (non-empty cells only; cells that
    failed conversion are absent), the ``raw`` cell values and ``ok`` (no conversion / required error)."""

    row_no: int
    values: Dict[str, Any]
    raw: Dict[str, Any]
    ok: bool = True

    def merged(self) -> Dict[str, Any]:
        """``values`` with the ``extra`` mapping spread in (explicit columns win)."""
        v = dict(self.values)
        return {**(v.pop(EXTRA, None) or {}), **v}


#: ``cfg -> {sheet: [dict, ...]}`` or ``cfg -> ({sheet: [dict, ...]}, {sheet: [(header, help), ...]})``
ExportRows = Callable[[Any], Union[Mapping[str, List[Dict[str, Any]]],
                                   Tuple[Mapping[str, List[Dict[str, Any]]],
                                         Mapping[str, Sequence[Tuple[str, str]]]]]]
Build = Callable[[Dict[str, List[SheetRow]], Any, List[str], List[str]], Any]


class XlsxSchema:
    """A product's workbook: its sheets plus the two config <-> rows hooks.

    ``export_rows(cfg)`` returns ``{sheet title: [model dump dict, ...]}``, or ``(rows, extra_columns)`` with
    ``{sheet title: [(header, help), ...]}`` dynamic columns; :meth:`row` moves the fields that have a column into
    cells and the rest into ``extra``. Dynamic columns of ``open_columns`` sheets are also collected from the rows. ``build(tables, base, errors, warnings)`` turns
    ``{sheet title: [SheetRow, ...]}`` into a config (model instance, or a dict validated with ``model``); it
    appends row-level messages to ``errors`` / ``warnings`` and may raise ``ValidationError`` / ``ValueError``.
    """

    def __init__(self, sheets: Sequence[Sheet], *, export_rows: Optional[ExportRows] = None,
                 build: Optional[Build] = None, model: Optional[type] = None,
                 template_file: str = "template.xlsx", export_file: str = "export.xlsx"):
        self.sheets: Dict[str, Sheet] = {s.title: s for s in sheets}
        self.export_rows = export_rows
        self.build = build
        self.model = model
        self.template_file = template_file
        self.export_file = export_file

    # ------------------------------------------------------------ writing

    def _sheet(self, wb, title: str, columns: Sequence[Tuple[str, str]], first: bool = False):
        _, Font, PatternFill, get_column_letter = _openpyxl()
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append([h for h, _ in columns])
        ws.append(["# " + d if i == 0 else d for i, (_, d) in enumerate(columns)])
        bold, grey = Font(bold=True), Font(italic=True, color="666666")
        fill = PatternFill("solid", fgColor="DDEBF7")
        for i, (name, _) in enumerate(columns, 1):
            ws.cell(1, i).font, ws.cell(1, i).fill = bold, fill
            ws.cell(2, i).font = grey
            ws.column_dimensions[get_column_letter(i)].width = max(12, min(40, len(name) + 6))
        ws.freeze_panes = "A3"
        return ws

    def workbook(self, extra_columns: Optional[Mapping[str, Sequence[Tuple[str, str]]]] = None):
        """A workbook with every sheet's header and help rows (``extra_columns`` appends dynamic columns)."""
        openpyxl = _openpyxl()[0]
        wb = openpyxl.Workbook()
        for i, s in enumerate(self.sheets.values()):
            self._sheet(wb, s.title, [*s.columns, *((extra_columns or {}).get(s.title, ()))], first=i == 0)
        return wb

    @staticmethod
    def save(wb) -> bytes:
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def blank_template(self) -> bytes:
        """An empty workbook with all sheets, column headers and help rows."""
        return self.save(self.workbook())

    def row(self, title: str, d: Dict[str, Any]) -> Dict[str, Any]:
        """Pop the fields that have a column out of a model dump; what is left goes to ``extra`` (if the sheet
        has one; otherwise it is dropped). ``yaml`` columns are written as flow text, ``list`` as a comma list.
        On an ``open_columns`` sheet the remaining scalar fields are kept as dynamic columns, in their order,
        after the known columns (only non-scalar leftovers go to ``extra``)."""
        sheet, d, row = self.sheets[title], dict(d), {}
        for col in sheet.headers:
            if col == EXTRA or col not in d:
                continue
            v, kind = d[col], sheet.kind(col)
            if kind in ("yaml", "yaml_any"):
                row[col] = flow(v) if v not in ({}, None) else None
            elif kind == "list" and isinstance(v, (list, tuple)):
                if any("," in str(x) for x in v):
                    continue  # not representable as a comma list: keep in extra
                row[col] = ",".join(map(str, v))
            elif _scalar(v):
                row[col] = v
            else:
                continue
            d.pop(col)
        if sheet.open_columns:
            for k in [k for k, v in d.items() if k not in sheet.headers and _scalar(v)]:
                row[k] = d.pop(k)
        if d and EXTRA in sheet.headers:
            row[EXTRA] = flow(d)
        return row

    def write(self, rows: Mapping[str, List[Dict[str, Any]]],
              extra_columns: Optional[Mapping[str, Sequence[Tuple[str, str]]]] = None) -> Tuple[bytes, List[str]]:
        """Workbook bytes for ``{sheet: [cell dict, ...]}``. A text longer than the Excel cell limit is left out
        with a warning."""
        wb = self.workbook(extra_columns)
        warnings: List[str] = []
        for title, sheet in self.sheets.items():
            ws = wb[title]
            headers = [*sheet.headers, *(h for h, _ in (extra_columns or {}).get(title, ()))]
            for i, r in enumerate(rows.get(title, ()), 3):
                cells = []
                for c in headers:
                    v = r.get(c)
                    if isinstance(v, str) and len(v) > CELL_LIMIT:
                        warnings.append(f"{title} row {i}, column {c!r}: longer than {CELL_LIMIT} characters "
                                        f"(Excel cell limit), left out")
                        v = None
                    cells.append(v)
                ws.append(cells)
        return self.save(wb), warnings

    def export_xlsx(self, cfg: Any) -> Tuple[bytes, List[str]]:
        if self.export_rows is None:
            raise ValueError("this workbook schema has no export_rows hook")
        res = self.export_rows(cfg)
        given: Mapping[str, Sequence[Tuple[str, str]]] = {}
        if isinstance(res, tuple):
            res, given = res[0], res[1] or {}
        rows = {t: [self.row(t, d) for d in ds] for t, ds in res.items()}
        return self.write(rows, self.extra_columns(rows, given))

    def extra_columns(self, rows: Mapping[str, List[Dict[str, Any]]],
                      given: Optional[Mapping[str, Sequence[Tuple[str, str]]]] = None
                      ) -> Dict[str, List[Tuple[str, str]]]:
        """Dynamic columns per sheet for :meth:`write`: the ``given`` ``(header, help)`` pairs first, then, on
        ``open_columns`` sheets, every cell key of ``rows`` that is neither a known header nor given, in order of
        first appearance (empty help)."""
        out: Dict[str, List[Tuple[str, str]]] = {}
        for title, sheet in self.sheets.items():
            cols = [(h, d) for h, d in (given or {}).get(title, ())]
            if sheet.open_columns:
                seen = {*sheet.headers, *(h for h, _ in cols)}
                for r in rows.get(title, ()):
                    for k in r:
                        if k not in seen:
                            seen.add(k)
                            cols.append((k, ""))
            if cols:
                out[title] = cols
        return out

    # ------------------------------------------------------------ reading

    def read_sheet(self, ws, errors: List[str], warnings: List[str], title: Optional[str] = None) -> List[SheetRow]:
        """Read a sheet as :class:`SheetRow` s (non-empty, non-comment rows). Conversion and required-column
        errors are appended to ``errors`` (``"<sheet> row N, column 'x': reason"``) and mark the row not ok."""
        sheet = self.sheets[title or ws.title]
        known = set(sheet.headers)
        header: Optional[Dict[int, str]] = None
        out: List[SheetRow] = []
        for row_no, values in enumerate(ws.iter_rows(values_only=True), 1):
            if all(_blank(v) for v in values):
                continue
            first = next((v for v in values if not _blank(v)), None)
            if isinstance(first, str) and first.lstrip().startswith("#"):
                continue
            if header is None:
                header = {}
                for i, v in enumerate(values):
                    name = _norm(v)
                    if not name:
                        continue
                    if name not in known and not sheet.open_columns:
                        warnings.append(f"{sheet.title}: unknown column {v!r} ignored")
                        continue
                    header[i] = name
                missing = [c for c in dict.fromkeys((*sheet.required, *sheet.required_headers))
                           if c not in header.values()]
                if missing:
                    errors.append(f"{sheet.title} row {row_no}: missing column(s) {', '.join(missing)}")
                    return []
                continue
            raw = {name: values[i] for i, name in header.items() if i < len(values) and not _blank(values[i])}
            if any(c not in raw for c in sheet.skip_blank):
                continue
            n = len(errors)
            conv: Dict[str, Any] = {}
            for col, v in raw.items():
                try:
                    conv[col] = sheet.convert(col, v)
                except ValueError as e:
                    errors.append(f"{sheet.title} row {row_no}, column {col!r}: {e}")
            for col in sheet.required:
                if col not in raw:
                    errors.append(f"{sheet.title} row {row_no}, column {col!r}: required")
            out.append(SheetRow(row_no, conv, raw, ok=len(errors) == n))
        return out

    def import_xlsx(self, data: bytes, base: Any = None) -> Tuple[Any, List[str]]:
        """``(config, warnings)`` on success, ``(None, errors)`` on failure; never raises."""
        try:
            openpyxl = _openpyxl()[0]
        except XlsxUnavailable as e:
            return None, [str(e)]
        if self.build is None:
            return None, ["this workbook schema has no build hook"]
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as e:  # not a zip / not a workbook
            return None, [f"not a readable .xlsx file: {e}"]
        errors: List[str] = []
        warnings: List[str] = []
        try:
            for title, s in self.sheets.items():
                if not s.optional and title not in wb.sheetnames:
                    errors.append(f"sheet {title!r} is missing")
            if errors:
                return None, errors
            tables = {t: (self.read_sheet(wb[t], errors, warnings, t) if t in wb.sheetnames else [])
                      for t in self.sheets}
            try:
                cfg = self.build(tables, base, errors, warnings)
                if errors:
                    return None, errors
                if isinstance(cfg, dict) and self.model is not None:
                    cfg = self.model.model_validate(cfg)
            except ValidationError as e:
                return None, errors + pydantic_errors(e, "workbook")
            except ValueError as e:
                return None, errors + [f"workbook: {e}"]
            if errors or cfg is None:
                return None, errors or ["workbook: no configuration built"]
            return cfg, warnings
        except Exception as e:  # a product hook bug must not escape the never-raises contract
            return None, errors + [f"workbook: {type(e).__name__}: {e}"]
        finally:
            wb.close()


def export_xlsx(cfg: Any, *, schema: XlsxSchema) -> Tuple[bytes, List[str]]:
    """Export ``cfg`` with ``schema``: ``(bytes, warnings)``. Raises :class:`XlsxUnavailable` without openpyxl."""
    return schema.export_xlsx(cfg)


def import_xlsx(data: bytes, base: Any = None, *, schema: XlsxSchema) -> Tuple[Any, List[str]]:
    """Import a workbook: ``(config, warnings)`` on success, ``(None, errors)`` on failure; never raises."""
    return schema.import_xlsx(data, base)
