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


def _base_type(hint):
    """Strip Optional[X] -> X so argparse gets a concrete converter."""
    if typing.get_origin(hint) is typing.Union:
        non_none = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return hint


def add_dataclass_arguments(parser: argparse.ArgumentParser, cls) -> None:
    """Add one argparse argument per dataclass field, named ``--kebab-case``."""
    hints = typing.get_type_hints(cls)
    for field in dataclasses.fields(cls):
        flag = _flag(field.name)
        meta = field.metadata
        action = meta.get("action")
        help_text = meta.get("help", "")
        if action == "store_true":
            parser.add_argument(flag, dest=field.name, action="store_true",
                                default=field.default, help=help_text)
        elif action == "boolean_optional":
            parser.add_argument(flag, dest=field.name,
                                action=argparse.BooleanOptionalAction,
                                default=field.default, help=help_text)
        else:
            kwargs = dict(dest=field.name, default=field.default,
                          type=_base_type(hints[field.name]), help=help_text)
            if meta.get("choices"):
                kwargs["choices"] = meta["choices"]
            parser.add_argument(flag, **kwargs)


def config_from_namespace(args: argparse.Namespace, cls):
    """Build a config dataclass from a parsed namespace (fields read by name)."""
    return cls(**{f.name: getattr(args, f.name) for f in dataclasses.fields(cls)})


def config_from_prefixed(args: argparse.Namespace, cls, prefix: str, overrides: dict | None = None):
    """Build a config dataclass from a parsed namespace whose attrs are ``<prefix><field>``.

    Lets the orchestrator keep its own flag surface (e.g. ``--qwen-batch-size`` ->
    ``args.qwen_batch_size``) while still mapping onto the sub-script's config in one call.
    ``overrides`` supplies fields that do not follow the prefix convention (e.g. a shared,
    unprefixed arg, or a value the orchestrator transforms first).
    """
    overrides = overrides or {}
    values = {}
    for field in dataclasses.fields(cls):
        if field.name in overrides:
            values[field.name] = overrides[field.name]
        else:
            values[field.name] = getattr(args, prefix + field.name)
    return cls(**values)


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
