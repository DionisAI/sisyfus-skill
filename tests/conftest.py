import os

# Never let the test suite spawn detached Observatory daemons; the dedicated
# live-observatory tests re-enable this with a monkeypatched spawner.
os.environ["SISYFUS_AUTO_SERVE"] = "0"

# Never open a real browser during tests.
os.environ["SISYFUS_AUTO_OPEN"] = "0"
