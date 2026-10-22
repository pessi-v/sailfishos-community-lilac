#!/usr/bin/env python3
"""Stop HybridBackendHal::initialize() from calling QCoreApplication::exit(EXIT_FAILURE) on any
failure path -- instead, leave the backend in its already-existing "nothing loaded" state and
return normally, letting the whole daemon survive.

Why this is safe, not just hopeful: HybrisManager::initManager() (which allocates m_sensorState
and populates the type/handle index maps every adaptor's own HybridAdaptor::handleForType()
lookup depends on) is only ever called from the tail of a *fully successful* initialize() --
never on any of these failure paths today, and still never on them after this patch. Returning
early simply means initManager() never runs and those index maps stay empty (their ordinary
default-constructed state, not a new or partially-initialized one). Every HybrisAdaptor's own
constructor already handles a failed handleForType() lookup gracefully and non-fatally --
`if (m_sensorHandle == -1) { ...; setValid(false); return; }` -- that is the *existing*,
already-proven-safe pattern this patch relies on, for every sensor type, not a new one invented
here.

Context: this probe is a process-wide, one-time singleton
construction (HybrisManager), not per-sensor-type -- today, if it fails for *any* reason, for
whichever sensor type happens to trigger it first (confirmed in section 140 to not even be
hardware-type-specific: accelerometer, independently known-working, fails exactly the same way
light/ALS always has), the *entire* sensorfwd daemon is killed via QCoreApplication::exit(),
not just that one sensor. Section 141 traced the actual, low-level reason this probe currently
fails on this device at all the way to a QMI service (SMGR) on the remote SLPI DSP not
responding in time, over an otherwise-healthy GLINK/QRTR link to an otherwise-healthy,
ONLINE DSP -- a genuine platform/firmware characteristic, not a sensorfw bug, and not
something this project can fix by patching this file. What this patch *can* do, regardless of
whether that deeper cause is ever fixed: stop one failed probe from taking the whole daemon
down, so every *other* part of sensorfwd's job (every sensor type that doesn't depend on this
HAL path, and simply staying alive and D-Bus-responsive instead of crash-looping) keeps working
regardless.

Idempotent. Run from the root of a sensorfw source checkout, or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
cpp = root / 'core/hybrisbackend_hal.cpp'
if not cpp.is_file():
    sys.exit(f'not found: {cpp}')

cs = cpp.read_text()
MARK = 'lilac-v2 change 141'
if MARK in cs:
    print('already patched')
    sys.exit(0)

replacements = [
    # 1. fork() failure
    ('''        if (child_pid == -1) {
            qCWarning(lcSensorFw) << "w_get_module() probe, fork failed:" << strerror(errno);
            QCoreApplication::exit(EXIT_FAILURE);
            return;
        }''',
     '''        if (child_pid == -1) {
            qCWarning(lcSensorFw) << "w_get_module() probe, fork failed:" << strerror(errno);
            giveUpGracefully();
            return;
        }'''),
    # 2. waitpid() failure
    ('''        int status = 0;
        if (waitpid(child_pid, &status, 0) == -1) {
            qCWarning(lcSensorFw) << "w_get_module() probe, waitpid failed:" << strerror(errno);
            QCoreApplication::exit(EXIT_FAILURE);
            return;
        }''',
     '''        int status = 0;
        if (waitpid(child_pid, &status, 0) == -1) {
            qCWarning(lcSensorFw) << "w_get_module() probe, waitpid failed:" << strerror(errno);
            giveUpGracefully();
            return;
        }'''),
    # 3. real hw_get_module() failure (after a successful probe)
    ('''            qCWarning(lcSensorFw) << "hw_get_module() failed:" << strerror(-err);
            m_halModule = nullptr;
            QCoreApplication::exit(EXIT_FAILURE);
            return;
        }''',
     '''            qCWarning(lcSensorFw) << "hw_get_module() failed:" << strerror(-err);
            giveUpGracefully();
            return;
        }'''),
    # 4. retries exhausted
    ('''        if (--retries < 0) {
            qCWarning(lcSensorFw) << "hw_get_module() probe failed - giving up";
            QCoreApplication::exit(EXIT_FAILURE);
            return;
        }''',
     '''        if (--retries < 0) {
            qCWarning(lcSensorFw) << "hw_get_module() probe failed - giving up";
            giveUpGracefully();
            return;
        }'''),
    # 5. sensors_open_1() failure
    ('''    err = sensors_open_1(&m_halModule->common, &m_halDevice);
    if (err != 0) {
        m_halDevice = 0;
        qCWarning(lcSensorFw) << "sensors_open() failed:" << strerror(-err);
        QCoreApplication::exit(EXIT_FAILURE);
        return;
    }''',
     '''    err = sensors_open_1(&m_halModule->common, &m_halDevice);
    if (err != 0) {
        m_halDevice = 0;
        qCWarning(lcSensorFw) << "sensors_open() failed:" << strerror(-err);
        giveUpGracefully();
        return;
    }'''),
    # 6. empty sensor list
    ('''    m_sensorCount = m_halModule->get_sensors_list(m_halModule, &m_sensorArray);
    if (m_sensorCount <= 0) {
        qCWarning(lcSensorFw) << "no sensors found";
        QCoreApplication::exit(EXIT_FAILURE);
        return;
    }''',
     '''    m_sensorCount = m_halModule->get_sensors_list(m_halModule, &m_sensorArray);
    if (m_sensorCount <= 0) {
        qCWarning(lcSensorFw) << "no sensors found";
        giveUpGracefully();
        return;
    }'''),
]

missing = [old for old, _ in replacements if old not in cs]
if missing:
    sys.exit('expected block(s) not found -- has hybrisbackend_hal.cpp changed?\n' + missing[0])

for old, new in replacements:
    cs = cs.replace(old, new)

# Insert the shared helper + its doc comment right before HybridBackendHal::initialize().
old_sig = 'void HybrisBackendHal::initialize()\n{'
new_helper = '''// lilac-v2: every failure path in initialize() below used to
// call QCoreApplication::exit(EXIT_FAILURE), killing the *entire* sensorfwd daemon over a
// single failed probe for whichever sensor type happened to trigger this process-wide,
// one-time singleton construction first -- confirmed in section 140 to not even be
// hardware-type-specific (accelerometer, independently known-working, failed exactly the same
// way light/ALS always has), and traced in section 141 to a QMI service (SMGR) on the remote
// SLPI DSP not responding in time, over an otherwise-healthy link to an otherwise-healthy,
// ONLINE DSP -- a platform/firmware characteristic this file cannot fix directly. This helper
// leaves m_halModule/m_halDevice/m_sensorCount/m_sensorArray in the same "nothing loaded" state
// a brand-new HybrisBackendHal already starts in, and simply returns instead of exiting:
// HybrisManager::initManager() (which populates every type/handle index lookup) is only ever
// reached from the tail of a *successful* initialize(), so skipping it here leaves those maps
// empty -- their ordinary default state, not a new one -- and every HybrisAdaptor's own
// constructor already handles that gracefully and non-fatally (`if (m_sensorHandle == -1) {
// ...; setValid(false); return; }`, the existing, already-proven-safe pattern for every sensor
// type, not something invented here). The daemon survives; the sensor types depending on this
// particular HAL path individually, gracefully report themselves unavailable, exactly as any
// single already-unsupported sensor type already does today.
void HybrisBackendHal::giveUpGracefully()
{
    m_halModule = nullptr;
    m_halDevice = nullptr;
    m_sensorCount = 0;
    m_sensorArray = nullptr;
}

void HybrisBackendHal::initialize()
{'''

if old_sig not in cs:
    sys.exit('expected initialize() signature not found -- has hybrisbackend_hal.cpp changed?')
cs = cs.replace(old_sig, new_helper, 1)

cpp.write_text(cs)

# Declare the new private helper in the header.
hdr = root / 'core/hybrisbackend_hal.h'
if not hdr.is_file():
    sys.exit(f'not found: {hdr}')
hs = hdr.read_text()
if 'giveUpGracefully' in hs:
    print(f'patched {cpp}; {hdr} already had the declaration')
    sys.exit(0)

old_initialize_decl = 'void initialize() override;'
new_initialize_decl = ('void initialize() override;\n'
                        '    void giveUpGracefully();  // lilac-v2: see the .cpp')
if old_initialize_decl not in hs:
    sys.exit('expected "void initialize() override;" declaration not found in header -- has it changed?')
hs = hs.replace(old_initialize_decl, new_initialize_decl, 1)
hdr.write_text(hs)

print(f'patched {cpp} and {hdr}: HybridBackendHal::initialize() failures are now non-fatal to the whole daemon')
