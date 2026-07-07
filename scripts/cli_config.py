"""Single-source-of-truth bridge between a config dataclass and argparse.

A stage's tunable knobs live in one dataclass (the source of truth). Sub-scripts build
their parser from it with ``add_dataclass_arguments``; the orchestrator turns a populated
config back into the exact CLI flags the sub-script expects with ``config_to_cli_args``.
Adding a knob is then a one-line dataclass change — the sub-script gains the flag and the
orchestrator forwards it automatically, so the two can never drift out of sync.

Kept deliberately tiny and dependency-free (stdlib only) so config modules built on it stay
importable without the GPU/model stack, e.g. in the orchestrator and the pytest suite.
"""
from __future__ import annotations

import argparse
import dataclasses
import typing
from pathlib import Path


def arg_field(default, *, help: str = "", choices=None, action: str | None = None):
    """A dataclass field carrying its argparse metadata.

    ``action`` is one of None (a typed value flag), "store_true" (presence-only bool), or
    "boolean_optional" (``--x`` / ``--no-x``). Bool fields must set one of the two bool
    actions; ``type=bool`` is never used because ``bool("false")`` is True.
    """
    return dataclasses.field(
        default=default,
        metadata={"help": help, "choices": choices, "action": action},
    )


def _flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def _prefixed_flag(prefix: str, name: str) -> str:
    return "--" + (prefix + name).replace("_", "-")


def _base_type(hint):
    """Strip Optional[X] -> X so argparse gets a concrete converter."""
    if typing.get_origin(hint) is typing.Union:
        non_none = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return hint


def add_dataclass_arguments(parser: argparse.ArgumentParser, cls) -> None:
    """Add one argparse argument per dataclass field, named ``--kebab-case``."""
    _add_dataclass_arguments(parser, cls, prefix="", skip=set())


def add_prefixed_dataclass_arguments(
    parser: argparse.ArgumentParser,
    cls,
    prefix: str,
    *,
    skip: set[str] | tuple[str, ...] = (),
    default_none: bool = False,
) -> None:
    """Add one argparse argument per dataclass field, named ``--<prefix>kebab-case``."""
    _add_dataclass_arguments(parser, cls, prefix=prefix, skip=set(skip), default_none=default_none)


def _add_dataclass_arguments(
    parser: argparse.ArgumentParser,
    cls,
    prefix: str,
    skip: set[str],
    default_none: bool = False,
) -> None:
    hints = typing.get_type_hints(cls)
    for field in dataclasses.fields(cls):
        if field.name in skip:
            continue
        flag = _prefixed_flag(prefix, field.name) if prefix else _flag(field.name)
        dest = prefix + field.name if prefix else field.name
        meta = field.metadata
        action = meta.get("action")
        help_text = meta.get("help", "")
        default = None if default_none else field.default
        if action == "store_true":
            parser.add_argument(flag, dest=dest, action="store_true",
                                default=default, help=help_text)
        elif action == "boolean_optional":
            parser.add_argument(flag, dest=dest,
                                action=argparse.BooleanOptionalAction,
                                default=default, help=help_text)
        else:
            kwargs = dict(dest=dest, default=default,
                          type=_base_type(hints[field.name]), help=help_text)
            if meta.get("choices"):
                kwargs["choices"] = meta["choices"]
            parser.add_argument(flag, **kwargs)


def config_from_namespace(args: argparse.Namespace, cls):
    """Build a config dataclass from a parsed namespace (fields read by name)."""
    return cls(**{f.name: getattr(args, f.name) for f in dataclasses.fields(cls)})


_MISSING = object()


def config_from_prefixed(
    args: argparse.Namespace,
    cls,
    prefix: str,
    overrides: dict | None = None,
    *,
    none_means_default: bool = False,
):
    """Build a config dataclass from a parsed namespace whose attrs are ``<prefix><field>``.

    Lets the orchestrator keep its own flag surface (e.g. ``--qwen-batch-size`` ->
    ``args.qwen_batch_size``) while still mapping onto the sub-script's config in one call.
    ``overrides`` supplies fields that do not follow the prefix convention (e.g. a shared,
    unprefixed arg, or a value the orchestrator transforms first).
    """
    overrides = overrides or {}
    # Fall back to the dataclass's own default for any field the orchestrator did not
    # expose as a --<prefix><field> arg. Without this, adding a QwenAsrConfig field
    # without also adding the matching orchestrator flag makes this call raise
    # AttributeError and takes down the whole pipeline (regression guard).
    defaults = cls()
    values = {}
    for field in dataclasses.fields(cls):
        if field.name in overrides:
            values[field.name] = overrides[field.name]
        else:
            value = getattr(args, prefix + field.name, _MISSING)
            if value is _MISSING or (none_means_default and value is None):
                value = getattr(defaults, field.name)
            values[field.name] = value
    return cls(**values)


def apply_config_file(parser: argparse.ArgumentParser, path: Path) -> dict:
    """Overlay a flat TOML file onto a parser's defaults (code default < file < CLI).

    Keys are flag/dest names (hyphens or underscores), values their TOML-typed values;
    they are validated against the parser's options and coerced with each option's own
    type before becoming the new defaults, so an explicit CLI flag still wins. Nested
    tables are rejected — the orchestrator's flag namespace is flat and irregular, so a
    section convention would mislead. Returns the applied {dest: value} mapping.
    """
    import tomllib

    with path.open("rb") as handle:
        data = tomllib.load(handle)

    actions_by_dest = {a.dest: a for a in parser._actions if a.dest != "help"}
    overrides: dict = {}
    for key, value in data.items():
        if isinstance(value, dict):
            raise SystemExit(
                f"Config {path}: nested tables/sections are not supported; use flat keys "
                f"like 'qwen_batch_size = 24' (offending section: [{key}])"
            )
        dest = key.replace("-", "_")
        action = actions_by_dest.get(dest)
        if action is None:
            raise SystemExit(f"Config {path}: unknown key '{key}' (no matching option)")
        # set_defaults bypasses argparse's own type/choices validation, so re-create it
        # here: an on/off switch (nargs==0) needs a bool; a value option must not get one,
        # is coerced with its own type, then checked against any choices.
        if action.nargs == 0:
            if not isinstance(value, bool):
                raise SystemExit(f"Config {path}: '{key}' is an on/off switch; use true or false, got {value!r}")
        else:
            if isinstance(value, bool):
                raise SystemExit(f"Config {path}: '{key}' expects a value, not a boolean")
            if action.type is not None:
                try:
                    value = action.type(value)
                except (ValueError, TypeError) as exc:
                    raise SystemExit(f"Config {path}: '{key}' = {value!r} is not valid: {exc}")
            if action.choices is not None and value not in action.choices:
                raise SystemExit(f"Config {path}: '{key}' must be one of {tuple(action.choices)}, got {value!r}")
        overrides[dest] = value

    parser.set_defaults(**overrides)
    return overrides


def format_config_toml(values: dict) -> str:
    """Serialize a {dest: value} mapping to flat TOML (the inverse of apply_config_file).

    Used by --print-config to emit the effective configuration as a reusable template.
    None-valued and skipped keys are omitted; Paths render as quoted strings.
    """
    lines: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = repr(value)
        else:
            text = str(value).replace("\\", "\\\\").replace('"', '\\"')
            rendered = f'"{text}"'
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + "\n"


def config_to_cli_args(cfg) -> list[str]:
    """Serialize a populated config dataclass back into sub-script CLI flags.

    bool actions round-trip to their flag form; other ``None`` values are omitted so the
    sub-script's own default applies. Field order follows the dataclass definition.
    """
    out: list[str] = []
    for field in dataclasses.fields(cfg):
        value = getattr(cfg, field.name)
        flag = _flag(field.name)
        action = field.metadata.get("action")
        if action == "store_true":
            if value:
                out.append(flag)
        elif action == "boolean_optional":
            out.append(flag if value else "--no-" + field.name.replace("_", "-"))
        elif value is not None:
            out += [flag, str(value)]
    return out
