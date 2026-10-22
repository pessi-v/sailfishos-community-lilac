#!/usr/bin/env python3
"""Add one diagnostic log line to HybrisAdaptor's constructor, logging which adaptor id/sensor
type is under construction right before the first call to hybrisManager() -- the lazy singleton
accessor whose first-ever call constructs HybrisManager and triggers HybridBackendHal::
initialize()'s hw_get_module() probe.

Why this exists: §137 built and live-tested §136's "just needs more patience" theory for real
and disproved it -- the probe genuinely, permanently fails, retried 40x instead of 4x, not a
timing race. Left open: *why* does it always fail, when gyroscope/accelerometer/proximity/
magnetometer are independently confirmed working (§133)? Two live possibilities, neither
checked yet: (1) those sensor types don't actually route through this singleton/backend at all,
contradicting the §136 static trace's own assumption; (2) the forked child probe (which only
tests loadability, discarding the result) succeeds, but the second, real, non-forked
hw_get_module() call right after it fails for a reason specific to the parent process's own
state. Logging the id/type right before the first-ever hybrisManager() call settles which
adaptor actually triggers construction, and the output's own order relative to the existing
"hw_get_module() probe failed" messages shows whether *that* construction is what's failing.

Log-only, no behavior change -- safe to build and test the same careful way as every other live
test this session (one restart, watch /proc/<pid>/stat and wchan immediately after, re-mask
sensorfwd.service fast on any `D` state / `do_mount` wchan sign, given this exact code path has
already hung the device three times this session).

Idempotent. Run from the root of a sensorfw source checkout, or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
cpp = root / 'core/hybrisadaptor.cpp'
if not cpp.is_file():
    sys.exit(f'not found: {cpp}')

cs = cpp.read_text()
MARK = 'lilac-v2 change 137'
if MARK in cs:
    print('already patched')
    sys.exit(0)

old = '''    , m_sensorHandle(-1)
    , m_sensorType(type)
{
    m_sensorHandle = hybrisManager()->handleForType(m_sensorType);'''

new = '''    , m_sensorHandle(-1)
    , m_sensorType(type)
{
    // lilac-v2: diagnostic only, no behavior change. Logs
    // which adaptor construction is the first to ever call hybrisManager() (the lazy singleton
    // accessor whose first call constructs HybrisManager and runs HybridBackendHal::
    // initialize()'s hw_get_module() probe) -- settles which sensor type actually triggers
    // that probe, and whether *that* construction is the one that fails.
    qCWarning(lcSensorFw) << "lilac-v2 diag: HybrisAdaptor construct id=" << id
                            << "type=" << type << "sensorTypeName=" << sensorTypeName(type);
    m_sensorHandle = hybrisManager()->handleForType(m_sensorType);'''

if old not in cs:
    sys.exit('expected constructor header not found -- has hybrisadaptor.cpp changed?')

cpp.write_text(cs.replace(old, new))
print(f'patched {cpp}: HybrisAdaptor constructor now logs id/type before first hybrisManager() call')
