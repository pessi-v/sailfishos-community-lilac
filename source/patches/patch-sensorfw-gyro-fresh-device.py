#!/usr/bin/env python3
"""Fix a real gap in patch-sensorfw-gyro-autocal.py's own convergence logic, found by the user
asking a good design-review question: what happens on a genuinely different physical device
that inherits this project's own checked-in seed config?

The seed file (device-integration/hybris/droid-configs/sparse/etc/sensorfw/sensord.conf.d/
90-lilac-gyro-calibration.conf) holds THIS specific physical unit's own measured bias values.
patch-sensorfw-gyro-autocal.py's `everCalibrated` flag was set from "does a config file with
non-zero values already exist" -- true immediately on any device that inherits this seed, even
one whose real gyroscope bias is completely different. That routed every one of its own real
convergences through the gentle 30%-per-update refinement path meant for polishing an
*already-good* estimate, not replacing a wrong one -- each blend only closes 30% of the gap, so
a genuinely different device would take roughly 6-7 real stationary periods (minutes to days of
ordinary use, since it only runs while something is actively reading gyro data) to converge
close to its own true bias, silently wrong in the meantime, rather than adopting its own real
measurement immediately.

Fix: stop asking "does a persisted value already exist" and ask "how many real convergences has
*this boot* actually witnessed" instead -- a new `convergenceCountThisBoot` counter (reset every
boot, not persisted). The first few real convergences each boot use a fast, full-replacement
weight (alpha 1.0); only once several real per-boot samples have accumulated does it settle into
the gentle 30% blend. This treats "new device with an inherited wrong seed" and "first-ever
device with no seed at all" identically and correctly, with no need to distinguish them: a
genuinely new device replaces the wrong seed within its first ~15 seconds of real stationary
time, while an already-well-calibrated device's "fast" updates just reconfirm the same good
value each time (estimate ~= already-correct value either way, no regression).

Idempotent, and depends on patch-sensorfw-gyro-autocal.py having been applied first. Run from
the root of a sensorfw source checkout, or pass that root as argv[1]. Written and tested against
the 0.15.1 tag, same as its predecessors.
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
hdr = root / 'adaptors/hybrisgyroscopeadaptor/hybrisgyroscopeadaptor.h'
cpp = root / 'adaptors/hybrisgyroscopeadaptor/hybrisgyroscopeadaptor.cpp'
for p in (hdr, cpp):
    if not p.is_file():
        sys.exit(f'not found: {p}')

hs = hdr.read_text()
cs = cpp.read_text()
PREREQ_MARK = 'lilac-v2 change 113'
MARK = 'lilac-v2 change 114'
if PREREQ_MARK not in hs or PREREQ_MARK not in cs:
    sys.exit('patch-sensorfw-gyro-autocal.py (section 113) must be applied first')
hdr_done = MARK in hs
cpp_done = MARK in cs
if hdr_done and cpp_done:
    print('already patched')
    sys.exit(0)

old_hdr = '''    int stationaryCount;
    bool everCalibrated;
    void maybeUpdateCalibration(qreal rawX, qreal rawY, qreal rawZ);'''

new_hdr = '''    int stationaryCount;
    bool everCalibrated;
    // lilac-v2: per-boot, not persisted; see
    // maybeUpdateCalibration()'s own comment for why this exists.
    int convergenceCountThisBoot;
    void maybeUpdateCalibration(qreal rawX, qreal rawY, qreal rawZ);'''

if not hdr_done:
    if old_hdr not in hs:
        sys.exit('expected header private: section not found -- has section 113 changed?')
    hdr.write_text(hs.replace(old_hdr, new_hdr))

old_ctor = '''    sumX = sumY = sumZ = 0.0;
    stationaryCount = 0;
    // lilac-v2: a real prior measurement (this project checks
    // one in with the config file itself) counts as "already calibrated"; only a device that
    // has genuinely never had any bias written starts from a from-scratch first convergence.
    everCalibrated = (biasX != 0.0 || biasY != 0.0 || biasZ != 0.0);'''

new_ctor = '''    sumX = sumY = sumZ = 0.0;
    stationaryCount = 0;
    convergenceCountThisBoot = 0;
    // lilac-v2: kept only for the startup log line below;
    // maybeUpdateCalibration() no longer uses this to decide how strongly to trust a new
    // measurement (see that function's own comment for why: a config file with real-looking
    // numbers doesn't mean THIS device produced them).
    everCalibrated = (biasX != 0.0 || biasY != 0.0 || biasZ != 0.0);'''

old_maybe_body = '''    if (!everCalibrated) {
        biasX = estimateX;
        biasY = estimateY;
        biasZ = estimateZ;
        everCalibrated = true;
    } else {
        biasX = biasX * (1.0 - REFINEMENT_ALPHA) + estimateX * REFINEMENT_ALPHA;
        biasY = biasY * (1.0 - REFINEMENT_ALPHA) + estimateY * REFINEMENT_ALPHA;
        biasZ = biasZ * (1.0 - REFINEMENT_ALPHA) + estimateZ * REFINEMENT_ALPHA;
    }'''

new_maybe_body = '''    // lilac-v2: "has this device ever been calibrated" used
    // to gate a fast, direct-replacement update vs. a gentle 30%-blend refinement, but that was
    // decided from "does a config file with non-zero values exist", which a genuinely different
    // physical device inheriting this project's own checked-in seed would satisfy immediately --
    // routing its own first real measurements through the *gentle* path meant for polishing an
    // already-good estimate, taking ~6-7 real convergences (not just one) to displace a wrong
    // inherited value. Use a fast weight for this boot's own first few real convergences
    // instead, regardless of what was loaded at startup: correctly and identically handles a
    // brand new device (no seed at all) and one that inherited a wrong seed from a different
    // physical unit, with no need to tell those two cases apart. An already-well-calibrated
    // device's "fast" updates just reconfirm the same good value each time -- no regression.
    const int FAST_CONVERGENCES_PER_BOOT = 5;
    qreal alpha = (convergenceCountThisBoot < FAST_CONVERGENCES_PER_BOOT) ? 1.0 : REFINEMENT_ALPHA;
    biasX = biasX * (1.0 - alpha) + estimateX * alpha;
    biasY = biasY * (1.0 - alpha) + estimateY * alpha;
    biasZ = biasZ * (1.0 - alpha) + estimateZ * alpha;
    convergenceCountThisBoot++;
    everCalibrated = true;'''

if not cpp_done:
    if old_ctor not in cs:
        sys.exit('expected constructor body not found -- has section 113 changed?')
    if old_maybe_body not in cs:
        sys.exit('expected maybeUpdateCalibration body not found -- has section 113 changed?')
    cs = cs.replace(old_ctor, new_ctor).replace(old_maybe_body, new_maybe_body)
    cpp.write_text(cs)

print(f'patched {hdr} and {cpp}: fast per-boot convergence for the first {5} real measurements, correctly handling a device with an inherited seed the same as one with no seed at all')
