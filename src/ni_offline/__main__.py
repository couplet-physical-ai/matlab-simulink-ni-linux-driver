"""Run the offline inspector or synthetic simulation; neither accesses hardware."""

import sys

from . import replay, simulation

if len(sys.argv) > 1 and sys.argv[1] == "simulate":
    raise SystemExit(simulation.main(sys.argv[2:]))
if len(sys.argv) > 1 and sys.argv[1] == "inspect":
    raise SystemExit(replay.main(sys.argv[2:]))
# Preserve the original `python3 -m ni_offline <capture.json>` invocation.
raise SystemExit(replay.main(sys.argv[1:]))
