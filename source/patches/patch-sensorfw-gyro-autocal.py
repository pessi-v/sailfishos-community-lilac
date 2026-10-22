#!/usr/bin/env python3
"""Replace the static, one-shot gyroscope bias correction from
patch-sensorfw-gyro-bias-calibration.py with a live, continuous auto-calibration algorithm --
run entirely inside sensorfwd itself, the same way sensorfw's own magnetometer calibration
already works (chains/magcalibrationchain/calibrationfilter.cpp), rather than a one-time manual
measurement.

Found/decided 2026-09-29: the static fix worked (CSD's own
gyroscope verification test went from failing to passing), but it hardcoded one measurement
from one moment in time, and applying a *new* measurement required SSH + a manual sensorfwd
restart -- not something an end user could ever do. Looked at how sensorfw already solves this
exact class of problem for the magnetometer and found the answer isn't a privileged GUI tool at
all: CalibrationFilter runs continuously, in-process, inside sensorfwd (which is already root),
tracking live min/max as the phone gets moved around, with no separate app, no config write at
runtime, no privilege escalation of any kind. The classic "move your phone in a figure-8"
instruction IS that algorithm's own data-collection step.

A gyroscope measures angular *velocity*, not orientation -- unlike the magnetometer, "the phone
is currently stationary" is a valid, useful signal at literally any orientation, not just flat
on a table. That's a two-part win: (1) no accelerometer cross-reference is needed to detect a
useful calibration window, just "all three raw gyro axes have stayed near zero for the last few
seconds"; (2) it happens naturally and often, any time the phone is simply set down, not only
during a dedicated calibration ritual.

Algorithm (see HybrisGyroscopeAdaptor::maybeUpdateCalibration in the patched .cpp for the real
implementation): accumulate raw (pre-correction) samples while every axis stays within
STATIONARY_THRESHOLD_DEG_S of zero; once SAMPLES_NEEDED consecutive stationary samples have
accumulated (~3 seconds at this adaptor's own 50ms default interval), average them into a new
bias estimate. The very first successful convergence (when no calibration was ever persisted
before) sets the bias directly; every later convergence blends the new estimate in gently
(REFINEMENT_ALPHA) rather than overwriting, so one noisy window can't undo a good calibration.
Any meaningfully new value gets written straight back to
/etc/sensorfw/sensord.conf.d/90-lilac-gyro-calibration.conf (the same file
patch-sensorfw-gyro-bias-calibration.py's own config mechanism already reads at startup, and the
same file this project checks in with the one real measurement taken 2026-09-29 as a reasonable
seed) -- no separate marker file needed for "has this device ever been calibrated": the
persisted file's own existence random this device up already carrying its own answer.

A companion small Silica app (harbour-lilac-gyro-status, not yet written as of this patch) will
give the user visible confirmation and instructions ("place the phone screen-up on a flat, still
surface for a few seconds") -- it does not need to write anything or hold any special
privilege, since sensorfwd already does the actual calibration and persistence on its own; the
app only needs to read live gyro values (the same, already-proven QtSensors mechanism CSD's own
GyroTest already uses) and the persisted config file's own current values.

Idempotent, and depends on patch-sensorfw-gyro-bias-calibration.py already having been applied
first (this patch's own MARK won't be found otherwise, and it exits with a clear error rather
than silently doing nothing). Run from the root of a sensorfw source checkout, or pass that
root as argv[1]. Written and tested against the 0.15.1 tag, same as its predecessor.
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
PREREQ_MARK = 'lilac-v2 change 112'
MARK = 'lilac-v2 change 113'
if PREREQ_MARK not in hs or PREREQ_MARK not in cs:
    sys.exit('patch-sensorfw-gyro-bias-calibration.py (section 112) must be applied first')
hdr_done = MARK in hs
cpp_done = MARK in cs
if hdr_done and cpp_done:
    print('already patched')
    sys.exit(0)

old_hdr = '''private:
    DeviceAdaptorRingBuffer<TimedXyzData>* buffer;
    int sensorType;
    QByteArray powerStatePath;
    // lilac-v2: zero-rate bias correction this platform's own
    // vendor HAL never applies (see that section for why); degrees/second, matching what
    // clients see, read once at startup from a userspace calibration tool's config write.
    qreal biasX;
    qreal biasY;
    qreal biasZ;

};'''

new_hdr = '''private:
    DeviceAdaptorRingBuffer<TimedXyzData>* buffer;
    int sensorType;
    QByteArray powerStatePath;
    // lilac-v2: zero-rate bias correction this platform's own
    // vendor HAL never applies (see that section for why); degrees/second, matching what
    // clients see, read once at startup from a userspace calibration tool's config write.
    qreal biasX;
    qreal biasY;
    qreal biasZ;
    // lilac-v2: live auto-calibration, the same shape as this
    // tree's own chains/magcalibrationchain/calibrationfilter.cpp: runs continuously, entirely
    // in-process, inside this already-root daemon.
    qreal lastPersistedX;
    qreal lastPersistedY;
    qreal lastPersistedZ;
    qreal sumX;
    qreal sumY;
    qreal sumZ;
    int stationaryCount;
    bool everCalibrated;
    void maybeUpdateCalibration(qreal rawX, qreal rawY, qreal rawZ);
    void persistCalibration();

};'''

if not hdr_done:
    if old_hdr not in hs:
        sys.exit('expected header private: section not found -- has section 112 changed?')
    hdr.write_text(hs.replace(old_hdr, new_hdr))

old_includes = '#include "config.h"\n#include <math.h>'
new_includes = '#include "config.h"\n#include <math.h>\n#include <QFile>\n#include <QTextStream>'

old_ctor_tail = '''    biasX = SensorFrameworkConfig::configuration()->value("gyroscope/bias_x").toDouble();
    biasY = SensorFrameworkConfig::configuration()->value("gyroscope/bias_y").toDouble();
    biasZ = SensorFrameworkConfig::configuration()->value("gyroscope/bias_z").toDouble();
    if (biasX != 0.0 || biasY != 0.0 || biasZ != 0.0)
        // NodeBase::id(), not id() -- this constructor's own parameter is also named "id"
        // and shadows the base class method here (the same reason the powerstate_path
        // warning two lines above already had to qualify it the same way).
        qCInfo(lcSensorFw) << NodeBase::id() << "HybrisGyroscopeAdaptor applying bias correction:"
                            << biasX << biasY << biasZ << "deg/s";
    unsigned int interval_us = 50 * 1000;'''

new_ctor_tail = '''    biasX = SensorFrameworkConfig::configuration()->value("gyroscope/bias_x").toDouble();
    biasY = SensorFrameworkConfig::configuration()->value("gyroscope/bias_y").toDouble();
    biasZ = SensorFrameworkConfig::configuration()->value("gyroscope/bias_z").toDouble();
    lastPersistedX = biasX;
    lastPersistedY = biasY;
    lastPersistedZ = biasZ;
    sumX = sumY = sumZ = 0.0;
    stationaryCount = 0;
    // lilac-v2: a real prior measurement (this project checks
    // one in with the config file itself) counts as "already calibrated"; only a device that
    // has genuinely never had any bias written starts from a from-scratch first convergence.
    everCalibrated = (biasX != 0.0 || biasY != 0.0 || biasZ != 0.0);
    if (everCalibrated)
        // NodeBase::id(), not id() -- this constructor's own parameter is also named "id"
        // and shadows the base class method here (the same reason the powerstate_path
        // warning two lines above already had to qualify it the same way).
        qCInfo(lcSensorFw) << NodeBase::id() << "HybrisGyroscopeAdaptor starting from saved calibration:"
                            << biasX << biasY << biasZ << "deg/s -- will keep refining live";
    else
        qCInfo(lcSensorFw) << NodeBase::id() << "HybrisGyroscopeAdaptor has no saved calibration yet"
                            << "-- will auto-calibrate the first time the device is stationary";
    unsigned int interval_us = 50 * 1000;'''

old_sample = '''void HybrisGyroscopeAdaptor::processSample(const sensors_event_t& data)
{

    TimedXyzData *d = buffer->nextSlot();
    d->timestamp_ = quint64(data.timestamp * .001);
#ifdef USE_BINDER
    d->x_ = (data.u.vec3.x) * RADIANS_TO_DEGREES * 1000 - biasX * 1000;
    d->y_ = (data.u.vec3.y) * RADIANS_TO_DEGREES * 1000 - biasY * 1000;
    d->z_ = (data.u.vec3.z) * RADIANS_TO_DEGREES * 1000 - biasZ * 1000;
#else
    d->x_ = (data.gyro.x) * RADIANS_TO_DEGREES * 1000 - biasX * 1000;
    d->y_ = (data.gyro.y) * RADIANS_TO_DEGREES * 1000 - biasY * 1000;
    d->z_ = (data.gyro.z) * RADIANS_TO_DEGREES * 1000 - biasZ * 1000;
#endif
    buffer->commit();
    buffer->wakeUpReaders();
}'''

new_sample = '''void HybrisGyroscopeAdaptor::processSample(const sensors_event_t& data)
{

    TimedXyzData *d = buffer->nextSlot();
    d->timestamp_ = quint64(data.timestamp * .001);
#ifdef USE_BINDER
    qreal rawX = (data.u.vec3.x) * RADIANS_TO_DEGREES;
    qreal rawY = (data.u.vec3.y) * RADIANS_TO_DEGREES;
    qreal rawZ = (data.u.vec3.z) * RADIANS_TO_DEGREES;
#else
    qreal rawX = (data.gyro.x) * RADIANS_TO_DEGREES;
    qreal rawY = (data.gyro.y) * RADIANS_TO_DEGREES;
    qreal rawZ = (data.gyro.z) * RADIANS_TO_DEGREES;
#endif
    maybeUpdateCalibration(rawX, rawY, rawZ);
    d->x_ = rawX * 1000 - biasX * 1000;
    d->y_ = rawY * 1000 - biasY * 1000;
    d->z_ = rawZ * 1000 - biasZ * 1000;
    buffer->commit();
    buffer->wakeUpReaders();
}

void HybrisGyroscopeAdaptor::maybeUpdateCalibration(qreal rawX, qreal rawY, qreal rawZ)
{
    // lilac-v2: A gyroscope reads angular velocity, not
    // orientation -- "stationary" is a valid, useful signal at any orientation, not only flat
    // on a table (that instruction is for the human, to hold genuinely still -- not a technical
    // requirement of this check). Same idea as chains/magcalibrationchain's CalibrationFilter
    // just above in this tree: run continuously, in-process, inside this already-root daemon.
    const qreal STATIONARY_THRESHOLD_DEG_S = 3.0;
    const int SAMPLES_NEEDED = 60; // ~3s at this adaptor's own 50ms default interval
    const qreal REFINEMENT_ALPHA = 0.3;
    const qreal PERSIST_EPSILON_DEG_S = 0.01;

    if (qAbs(rawX) > STATIONARY_THRESHOLD_DEG_S || qAbs(rawY) > STATIONARY_THRESHOLD_DEG_S
            || qAbs(rawZ) > STATIONARY_THRESHOLD_DEG_S) {
        sumX = sumY = sumZ = 0.0;
        stationaryCount = 0;
        return;
    }

    sumX += rawX;
    sumY += rawY;
    sumZ += rawZ;
    if (++stationaryCount < SAMPLES_NEEDED)
        return;

    qreal estimateX = sumX / stationaryCount;
    qreal estimateY = sumY / stationaryCount;
    qreal estimateZ = sumZ / stationaryCount;
    sumX = sumY = sumZ = 0.0;
    stationaryCount = 0;

    if (!everCalibrated) {
        biasX = estimateX;
        biasY = estimateY;
        biasZ = estimateZ;
        everCalibrated = true;
    } else {
        biasX = biasX * (1.0 - REFINEMENT_ALPHA) + estimateX * REFINEMENT_ALPHA;
        biasY = biasY * (1.0 - REFINEMENT_ALPHA) + estimateY * REFINEMENT_ALPHA;
        biasZ = biasZ * (1.0 - REFINEMENT_ALPHA) + estimateZ * REFINEMENT_ALPHA;
    }

    if (qAbs(biasX - lastPersistedX) > PERSIST_EPSILON_DEG_S
            || qAbs(biasY - lastPersistedY) > PERSIST_EPSILON_DEG_S
            || qAbs(biasZ - lastPersistedZ) > PERSIST_EPSILON_DEG_S) {
        persistCalibration();
    }
}

void HybrisGyroscopeAdaptor::persistCalibration()
{
    // lilac-v2: the same path
    // patch-sensorfw-gyro-bias-calibration.py's config-read mechanism already reads at startup,
    // and the same file this project checks in with a real, live-measured seed value.
    static const QString path = QStringLiteral("/etc/sensorfw/sensord.conf.d/90-lilac-gyro-calibration.conf");
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text)) {
        qCWarning(lcSensorFw) << NodeBase::id() << "Could not write gyroscope calibration to" << path;
        return;
    }
    QTextStream out(&f);
    out << "# lilac-v2: auto-calibrated live by sensorfwd\\n";
    out << "# itself; do not edit by hand, it will be overwritten the next time the device\\n";
    out << "# is stationary for a few seconds.\\n";
    out << "[gyroscope]\\n";
    out << "bias_x = " << biasX << "\\n";
    out << "bias_y = " << biasY << "\\n";
    out << "bias_z = " << biasZ << "\\n";
    f.close();
    lastPersistedX = biasX;
    lastPersistedY = biasY;
    lastPersistedZ = biasZ;
    qCInfo(lcSensorFw) << NodeBase::id() << "HybrisGyroscopeAdaptor persisted gyroscope calibration:"
                        << biasX << biasY << biasZ << "deg/s";
}'''

if not cpp_done:
    if old_includes not in cs:
        sys.exit('expected includes not found -- has section 112 changed?')
    if old_ctor_tail not in cs:
        sys.exit('expected constructor tail not found -- has section 112 changed?')
    if old_sample not in cs:
        sys.exit('expected processSample body not found -- has section 112 changed?')
    cs = cs.replace(old_includes, new_includes)
    cs = cs.replace(old_ctor_tail, new_ctor_tail)
    cs = cs.replace(old_sample, new_sample)
    cpp.write_text(cs)

print(f'patched {hdr} and {cpp}: HybrisGyroscopeAdaptor now auto-calibrates gyroscope bias live, in-process')
