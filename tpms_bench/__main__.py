#!/usr/bin/env python3
"""Launch the one-click UI by default. Use --cli for the headless runner."""

from __future__ import annotations

import sys

from tpms_bench.paths import app_root, sdk_src

ROOT = app_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SDK = sdk_src()
if SDK.exists() and str(SDK) not in sys.path:
    sys.path.insert(0, str(SDK))


def main() -> int:
    if "--cli" in sys.argv:
        from tpms_bench.runner import BenchRunner

        def _print(event) -> None:
            if event.kind == "row_start":
                print(
                    f"[{event.excel_row}] {event.make} {event.model}  "
                    f"{event.code_a} {event.code_b} {event.code_c}  "
                    f"pending={event.pending}",
                    flush=True,
                )
            elif event.kind == "row_done":
                print(
                    f"  -> {event.performance} id={event.sensor_id} "
                    f"T={event.temperature} V={event.voltage}  {event.pending} pending",
                    flush=True,
                )
            elif event.message:
                print(event.message, flush=True)

        return BenchRunner(on_progress=_print).run()

    from tpms_bench.gui import main as gui_main

    gui_main(autostart="--autostart" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
