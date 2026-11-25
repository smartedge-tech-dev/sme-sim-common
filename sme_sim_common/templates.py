"""Device template mechanism shared by the SME simulators (no template content lives here).

Generalised from sme-modbus-sim ``sme_modbus_sim/templates.py`` @ 085fe59 (itself following sme-bac-sim
``sme_bacnet_sim/templates.py`` @ ebd27ec). A product creates one ``TemplateRegistry`` for its item model
(Modbus ``PointConfig``, BACnet ``ObjectConfig`` ...) and registers its built-in templates on it::

    registry = TemplateRegistry(PointConfig, validate_hook=..., finalize_hook=..., app_name="sme-modbus-sim")

    @registry.template("env_sensor", "Temperature / humidity sensor", {"temp": 25})
    def _env(p):
        return [{"name": "temperature", ...}]

A template is a function ``params -> list[item dict]``. A device references a template by name, may
override ``params``, add or override items by name, and drop items with ``removed``.

Protocol-specific steps are injected as hooks (all optional):

``finalize_hook(owner, items) -> items``
    Runs on the merged item list (after ``removed``); fills in derived fields such as Modbus addresses or
    BACnet instance numbers. Must return the (possibly new) list.
``validate_hook(owner, items) -> None``
    Runs after ``finalize_hook``; raises ``ValueError`` for an invalid layout (overlapping registers,
    missing table ...). Also applied to user templates (with their default params) when they are loaded.
``export_hook(device, item_dict) -> item_dict``
    ``device_as_template`` only: adjusts each exported item mapping (e.g. copy device-level byte order).

User-local templates are YAML files in a directory resolved as: explicit argument -> environment variable
``SME_<APP>_TEMPLATES`` (derived from ``app_name``) -> ``~/.<app_name>/templates/``. A user template
overrides the built-in template of the same name. File format::

    name: my_inverter            # default: the file name without extension
    title: My inverter           # default: name
    description: free text
    params: {rated_kw: 10}       # defaults, overridable per device with ``params:``
    points: [...]                # key = ``items_attr``; same schema as a device's items

``extra_keys=("identification", ...)`` (constructor) additionally allows those top-level keys in a user template
(any value; ``{param}`` substitution applies). They are not items: ``expand_extras`` / ``expand_device_extras``
return them merged with the device's own fields (a non-empty device value wins; two dicts are merged shallowly
with the device's keys winning), and ``device_as_template`` writes the device's fields of those names back.

Parameter substitution happens only inside string values: ``str.format`` with the merged params
(``"clamp(p, 0, {rated_kw})"``). A string that is exactly one placeholder (``max: "{rated_kw}"``) takes the
parameter value with its type. Literal braces are written ``{{`` / ``}}``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, Tuple, Type, TypeVar, Union

import yaml
from pydantic import BaseModel, ValidationError

Item = TypeVar("Item", bound=BaseModel)
ItemDict = Dict[str, Any]
BuildFn = Callable[[Dict[str, Any]], List[ItemDict]]
FinalizeHook = Callable[[str, List[Any]], List[Any]]
ValidateHook = Callable[[str, List[Any]], None]
ExportHook = Callable[[Any, ItemDict], ItemDict]

NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
_ONE_PLACEHOLDER = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def env_var_for(app_name: str) -> str:
    """``sme-modbus-sim`` -> ``SME_MODBUS_SIM_TEMPLATES``."""
    return re.sub(r"\W", "_", app_name).upper() + "_TEMPLATES"


def substitute(v: Any, params: Dict[str, Any]) -> Any:
    """``{param}`` substitution inside string values (recursively through lists / mappings)."""
    if isinstance(v, str):
        m = _ONE_PLACEHOLDER.match(v)
        if m:
            if m.group(1) not in params:
                raise ValueError(f"unknown parameter {m.group(1)!r} in {v!r}")
            return params[m.group(1)]
        try:
            return v.format(**params)
        except KeyError as e:
            raise ValueError(f"unknown parameter {e.args[0]!r} in {v!r}") from None
        except (IndexError, ValueError) as e:
            raise ValueError(f"bad placeholder in {v!r}: {e} (write literal braces as {{{{ and }}}})") from None
    if isinstance(v, list):
        return [substitute(x, params) for x in v]
    if isinstance(v, dict):
        return {k: substitute(x, params) for k, x in v.items()}
    return v


def escape_braces(v: Any) -> Any:
    """Inverse of ``substitute`` for literal values: ``{`` -> ``{{`` inside strings (recursively)."""
    if isinstance(v, str):
        return v.replace("{", "{{").replace("}", "}}")
    if isinstance(v, list):
        return [escape_braces(x) for x in v]
    if isinstance(v, dict):
        return {k: escape_braces(x) for k, x in v.items()}
    return v


def _validation_message(e: ValidationError, prefix: str) -> str:
    return "; ".join(f"{prefix}.{'.'.join(map(str, err['loc']))}: "
                     f"{str(err['msg']).removeprefix('Value error, ')}" for err in e.errors())


class TemplateRegistry(Generic[Item]):
    """Built-in + user-local device templates for one item model.

    ``item_model`` is the pydantic model of one item (needs a ``name`` field). ``items_attr`` is the
    device attribute holding its items and the user-template YAML key (``points`` / ``objects``).
    """

    def __init__(self, item_model: Type[Item], validate_hook: Optional[ValidateHook] = None, *,
                 app_name: str, items_attr: str = "points", finalize_hook: Optional[FinalizeHook] = None,
                 export_hook: Optional[ExportHook] = None, env_var: Optional[str] = None,
                 extra_keys: Tuple[str, ...] = ()):
        self.item_model = item_model
        self.validate_hook = validate_hook
        self.finalize_hook = finalize_hook
        self.export_hook = export_hook
        self.app_name = app_name
        self.items_attr = items_attr
        self.extra_keys = tuple(extra_keys)
        self.env_var = env_var or env_var_for(app_name)
        self.builtins: Dict[str, Dict[str, Any]] = {}
        self.user_templates: Dict[str, Dict[str, Any]] = {}
        self.user_errors: List[Dict[str, str]] = []
        self._user_dir: Optional[Path] = None

    # ------------------------------------------------------------ built-ins

    def register(self, name: str, title: str, params: Dict[str, Any], build: BuildFn,
                 description: Optional[str] = None) -> None:
        t: Dict[str, Any] = {"name": name, "title": title, "params": params, "build": build}
        if description:
            t["description"] = description
        self.builtins[name] = t

    def template(self, name: str, title: str, params: Dict[str, Any], *, description: Optional[str] = None):
        """Decorator registering ``fn(params) -> list[item dict]`` as a built-in template."""

        def deco(fn: BuildFn) -> BuildFn:
            self.register(name, title, params, fn, description)
            return fn

        return deco

    # ------------------------------------------------------------ lookup

    def names(self) -> List[str]:
        """Built-ins in registration order, then user-only templates."""
        return list(dict.fromkeys([*self.builtins, *self.user_templates]))

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """User template first (it overrides a built-in of the same name), then built-in."""
        return self.user_templates.get(name) or self.builtins.get(name)

    def catalog(self) -> List[Dict[str, Any]]:
        """Built-ins (replaced in place by a user template of the same name), then user-only templates."""
        out = []
        for name in self.names():
            t = self.get(name)
            e = {"name": name, "title": t["title"], "params": t["params"], "source": t.get("source", "builtin")}
            if t.get("description"):
                e["description"] = t["description"]
            if "path" in t:
                e["path"] = t["path"]
                e["overrides_builtin"] = name in self.builtins
            out.append(e)
        return out

    # ------------------------------------------------------------ expansion

    def _finish(self, owner: str, items: List[Item]) -> List[Item]:
        if self.finalize_hook:
            items = list(self.finalize_hook(owner, items))
        if self.validate_hook:
            self.validate_hook(owner, items)
        return items

    def expand(self, owner: str, template: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
               items: Iterable[Item] = (), removed: Optional[Iterable[str]] = None) -> List[Item]:
        """Template items merged with the device's own items (same name overrides), then hooks applied."""
        built: List[ItemDict] = []
        if template:
            t = self.get(template)
            if t is None:
                raise ValueError(f"{owner}: unknown template {template!r} (known: {', '.join(self.names())})")
            built = t["build"]({**t["params"], **(params or {})})
        result: Dict[str, Item] = {d["name"]: self.item_model.model_validate(d) for d in built}
        for it in items:
            if it.name in result:
                merged = {**result[it.name].model_dump(exclude_none=True), **it.model_dump(exclude_unset=True)}
                try:
                    result[it.name] = self.item_model.model_validate(merged)
                except ValueError as e:
                    raise ValueError(f"{owner}/{it.name}: {e}") from None
            else:
                result[it.name] = it
        for name in removed or []:
            result.pop(name, None)
        return self._finish(owner, list(result.values()))

    def expand_device(self, dev: Any) -> List[Item]:
        """``expand`` for a device model with ``name`` / ``template`` / ``params`` / ``<items_attr>`` / ``removed``."""
        return self.expand(dev.name, getattr(dev, "template", None), getattr(dev, "params", None) or {},
                           getattr(dev, self.items_attr, None) or [], getattr(dev, "removed", None))

    def expand_extras(self, owner: str, template: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
                      device_extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``extra_keys`` values of the template merged with ``device_extras`` (the device's own fields).

        A non-empty device value wins; if both sides are dicts they are merged shallowly (device keys win).
        Only keys present on either side are returned."""
        out: Dict[str, Any] = {}
        if template:
            t = self.get(template)
            if t is None:
                raise ValueError(f"{owner}: unknown template {template!r} (known: {', '.join(self.names())})")
            p = {**t["params"], **(params or {})}
            out = {k: substitute(v, p) for k, v in (t.get("extras") or {}).items()}
        for k, dv in (device_extras or {}).items():
            tv = out.get(k)
            if isinstance(tv, dict) and isinstance(dv, dict):
                out[k] = {**tv, **dv}
            elif dv not in (None, "", {}, []) or k not in out:
                out[k] = dv
        return out

    def expand_device_extras(self, dev: Any) -> Dict[str, Any]:
        """``expand_extras`` for a device model: its ``extra_keys`` attributes are the device-side values."""
        own = {k: getattr(dev, k) for k in self.extra_keys if getattr(dev, k, None) is not None}
        return self.expand_extras(dev.name, getattr(dev, "template", None), getattr(dev, "params", None) or {}, own)

    # ------------------------------------------------------------ user-local templates

    def default_templates_dir(self) -> Path:
        """``$SME_<APP>_TEMPLATES`` or ``~/.<app_name>/templates``."""
        env = os.environ.get(self.env_var)
        return Path(env).expanduser() if env else Path.home() / f".{self.app_name}" / "templates"

    def resolve_templates_dir(self, directory: Optional[Union[Path, str]] = None) -> Path:
        """Explicit directory -> environment variable -> home default."""
        return Path(directory).expanduser() if directory else self.default_templates_dir()

    def templates_dir(self) -> Path:
        """The directory last loaded (or the default one)."""
        return self._user_dir or self.default_templates_dir()

    def _user_template(self, data: Any, path: Path) -> Dict[str, Any]:
        key = self.items_attr
        allowed = {"name", "title", "description", "params", key, *self.extra_keys}
        if not isinstance(data, dict):
            raise ValueError(f"expected a mapping with name / title / params / {key}")
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown key(s) {unknown} (allowed: {', '.join(sorted(allowed))})")
        name = str(data.get("name") or path.stem)
        if not NAME_RE.match(name):
            raise ValueError(f"invalid template name {name!r} (letters, digits, _ . -)")
        params = data.get("params") or {}
        raw = data.get(key) or []
        if not isinstance(params, dict):
            raise ValueError("params must be a mapping")
        if not isinstance(raw, list) or not all(isinstance(p, dict) for p in raw):
            raise ValueError(f"{key} must be a list of mappings")

        def build(p: Dict[str, Any], _raw=raw) -> List[ItemDict]:
            return [substitute(d, p) for d in _raw]

        try:  # check with the default params: item schema, names, protocol hooks
            items = [self.item_model.model_validate(d) for d in build(dict(params))]
        except ValidationError as e:
            raise ValueError(_validation_message(e, key)) from None
        names = [it.name for it in items]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"duplicate {key[:-1] if key.endswith('s') else key} names {dup}")
        self._finish(name, items)
        extras = {k: data[k] for k in self.extra_keys if k in data}
        return {"name": name, "title": str(data.get("title") or name), "description": data.get("description"),
                "params": params, "build": build, "extras": extras, "source": "user", "path": str(path)}

    def clear_user_templates(self) -> None:
        """Forget all user templates (the directory is kept for a later reload)."""
        self.user_templates.clear()
        self.user_errors.clear()

    def load_user_templates(self, directory: Optional[Union[Path, str]] = None) -> List[Dict[str, str]]:
        """(Re)load the user template directory (default: ``templates_dir()``). Bad files are skipped and
        reported as ``{"path", "error"}``, never fatal; a missing directory is not an error."""
        self._user_dir = Path(directory).expanduser() if directory else self.templates_dir()
        d = self._user_dir
        loaded: Dict[str, Dict[str, Any]] = {}
        errs: List[Dict[str, str]] = []
        files = sorted([*d.glob("*.yaml"), *d.glob("*.yml")]) if d.is_dir() else []
        for f in files:
            try:
                t = self._user_template(yaml.safe_load(f.read_text(encoding="utf-8")), f)
                if t["name"] in loaded:
                    raise ValueError(f"template {t['name']!r} already defined in {loaded[t['name']]['path']}")
                loaded[t["name"]] = t
            except (OSError, yaml.YAMLError, ValueError) as e:
                errs.append({"path": str(f), "error": str(e)})
        self.user_templates.clear()
        self.user_templates.update(loaded)
        self.user_errors[:] = errs
        return errs

    def device_as_template(self, dev: Any, name: str, title: Optional[str] = None,
                           description: Optional[str] = None) -> str:
        """YAML text of a user template built from a device's expanded items (literal values, no params)."""
        if not NAME_RE.match(name):
            raise ValueError(f"invalid template name {name!r} (letters, digits, _ . -)")
        out = []
        for it in self.expand_device(dev):
            d = it.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            d = {"name": it.name, **{k: v for k, v in d.items() if k != "name"}}
            if self.export_hook:
                d = self.export_hook(dev, d)
            out.append({k: (v if k == "name" else escape_braces(v)) for k, v in d.items()})
        doc = {"name": name, "title": title or name,
               "description": description or f"Saved from device {dev.name}", "params": {}, self.items_attr: out}
        for k, v in self.expand_device_extras(dev).items():
            if k in self.extra_keys and v not in (None, "", {}, []):
                doc[k] = escape_braces(v.model_dump(mode="json", exclude_none=True) if isinstance(v, BaseModel) else v)
        return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
