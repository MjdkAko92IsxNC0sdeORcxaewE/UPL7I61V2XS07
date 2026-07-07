"""Refresh or re-materialize the BridgeIndex UPV2 live context."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from live_context_schema import build_bridgeindex_upv2_context, load_and_validate


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _default_source_paths() -> list[Path]:
    configured = os.environ.get("BRIDGEINDEX_LIVE_CONTEXT_PATH")
    paths = []
    if configured:
        paths.append(Path(configured))
    paths.extend(
        [
            Path("../BridgeIndex/live_context.json"),
            Path("BridgeIndex/live_context.json"),
            Path("setup/source_live_context.json"),
        ]
    )
    return paths


def _find_source(explicit_path: str) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"explicit source context path does not exist: {path}")
        return path

    candidates = _default_source_paths()
    for path in candidates:
        if path.exists():
            return path
    return None


def refresh_context(source_path: str = "", out: str = "setup/live_context_v2.json", compat_out: str = "setup/live_context.json") -> dict:
    source = _find_source(source_path)
    if source is not None:
        context = build_bridgeindex_upv2_context(_load_json(source))
        _write_json(Path(out), context)
        _write_json(Path(compat_out), context)
        print(f"refreshed UPV2 live context from {source}")
    else:
        context = load_and_validate(out)
        _write_json(Path(compat_out), context)
        print(f"no source live_context found; preserved validated UPV2 context from {out}")

    context = load_and_validate(out)
    history_dir = Path("setup/live_context_history")
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / f"bridgeindex__{context['block_number']}.json"
    shutil.copy2(out, history_file)
    print(f"wrote live context history snapshot: {history_file}")
    return context


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh BridgeIndex UPV2 live context.")
    parser.add_argument("--source", default="", help="Optional ACTE/BridgeIndex live_context.json source path.")
    parser.add_argument("--out", default="setup/live_context_v2.json")
    parser.add_argument("--compat-out", default="setup/live_context.json")
    args = parser.parse_args()

    refresh_context(source_path=args.source, out=args.out, compat_out=args.compat_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
