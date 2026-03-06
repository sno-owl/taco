"""Allow `python -m taco_tool` and PyOxidizer run_module to invoke the CLI."""
from taco_tool.cli import main

raise SystemExit(main())
