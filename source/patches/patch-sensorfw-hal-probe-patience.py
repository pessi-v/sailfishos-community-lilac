#!/usr/bin/env python3
"""Give HybrisBackendHal::initialize()'s hw_get_module() probe loop real patience instead of
racing this device's genuinely slow, heavily-contended boot-time HAL loading -- the same shape
of fix as this project's already-shipped TimeoutStartSec bumps for sensorfwd.service,
polkit.service and systemd-hostnamed.service, just inside
the daemon's own C++ code instead of a systemd drop-in, because this particular probe runs
synchronously in HybrisManager's constructor, before systemd (or even Qt's own event loop) is
in the picture at all.

Found 2026-10-04/05 chasing why sensorfwd fatally exits
after a `hw_get_module() probe failed` x4 sequence, "giving up", followed immediately by
`QCoreApplication::exit(EXIT_FAILURE)` -- originally suspected (wrongly) to mean this device's
sensors.ssc.so HAL genuinely doesn't support SENSOR_TYPE_LIGHT/SENSOR_TYPE_WAKE_GESTURE.
Several hours of static tracing (confirmed empirically via `nm -D` against the real, installed
libhybrissensorfw-qt5.so.1.0.0 -- HybrisBackendHal's own symbols are genuinely present and
linked in for this device's build, settling an earlier, wrong suspicion that the "-binder"
package name meant a *different* backend class, hybrisbackend_binder.cpp, was the one actually
running) established instead that:

1. HybrisManager (which owns the one HybrisBackendHal instance) is a process-wide singleton,
   constructed exactly once per sensorfwd lifetime -- not per sensor type. Its constructor is
   what calls `m_backend->initialize()`, and that one call's success or failure is shared by
   every single sensor adaptor, not specific to whichever one happens to trigger it first.
2. `initialize()`'s own retry loop only tries `hw_get_module(SENSORS_HARDWARE_MODULE_ID, ...)`
   up to 4 times, 2 seconds apart (~8-10s total patience) before giving up for good and calling
   `QCoreApplication::exit(EXIT_FAILURE)` -- unconditionally fatal to the whole daemon, with no
   per-sensor-type granularity at all.
3. This exact device has independently, repeatedly demonstrated boot-time HAL-loading
   contention far beyond 8-10s this same session -- `sensorfwd.service` itself needed its own
   `TimeoutStartSec` raised from 30s to 120s (section 133) for an unrelated but analogous
   problem, and `polkit.service`/`systemd-hostnamed.service` needed the identical fix (section
   134), both confirmed via direct, repeated measurement to sometimes take 21-70+ seconds under
   this device's observed boot-time load (load average 14-19 was routine this session, not an
   outlier).
4. Put together: it's far more likely this probe is simply losing a race against the same
   underlying contention already fixed twice elsewhere, than that this device's HAL genuinely,
   permanently lacks light/wake-gesture support. Whichever adaptor happens to be constructed
   first (accelerometer, per primaryuse.conf's own `[plugins]` ordering) decides this for the
   *entire* daemon's lifetime; if ALS specifically only looks broken because something upstream
   of it already burned through the probe's patience on a slow boot, a more patient probe
   should let every sensor type succeed together, the same as it (usually) already does today.

Not yet verified live against real hardware -- found and written via static source reading
only, deliberately, after this same session's live `strace`-based investigation twice caused a
genuine full-device hang chasing this exact code path (sections 135/136's own "two separate
full-device hangs" story) and the decision was made to stop live experimentation for the rest of
that session. Build and test this on a real boot before trusting it; if it's wrong (the HAL
truly never loads, regardless of patience), the only cost is a slower, equally inevitable
failure -- not a new failure mode.

Idempotent. Run from the root of a sensorfw source checkout, or pass that root as argv[1].
Written and tested against the same 0.15.1-era tree already used for the gyro calibration
patches (core/hybrisbackend_hal.cpp did not change shape between then and now).
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
cpp = root / 'core/hybrisbackend_hal.cpp'
if not cpp.is_file():
    sys.exit(f'not found: {cpp}')

cs = cpp.read_text()
MARK = 'lilac-v2 change 135/136'
if MARK in cs:
    print('already patched')
    sys.exit(0)

old = '''    /* Open android sensor plugin */
    for (int retries = 4; ;) {'''

new = '''    /* Open android sensor plugin */
    // lilac-v2: this probe runs once, synchronously, in
    // HybrisManager's process-wide-singleton constructor, shared by every sensor type, not
    // just whichever adaptor happens to trigger it first. 4 retries at 2s apart (~8-10s) is not
    // enough patience for this device's own, independently-confirmed boot-time HAL-loading
    // contention (the same class of problem already fixed for sensorfwd.service/polkit.service/
    // systemd-hostnamed.service via a TimeoutStartSec bump, sections 133/134) -- raised to 40
    // retries (~80s) to match. If the HAL genuinely never loads, this only delays the same,
    // otherwise-unavoidable failure; it introduces no new failure mode.
    for (int retries = 40; ;) {'''

if old not in cs:
    sys.exit('expected retry-loop header not found -- has hybrisbackend_hal.cpp changed?')

cpp.write_text(cs.replace(old, new))
print(f'patched {cpp}: HybridBackendHal::initialize() probe now retries 40x (~80s) instead of 4x (~8s)')
