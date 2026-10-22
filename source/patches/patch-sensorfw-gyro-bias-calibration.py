#!/usr/bin/env python3
"""Add a configurable per-axis zero-rate bias correction to sensorfw's hybris gyroscope
adaptor, read once at startup from /etc/sensorfw config keys a userspace calibration tool
writes.

Found 2026-09-29: every real sensor on this port needed
a separate fix (the missing vendor.sensors.qti AP-side SSC daemon, sections 109-111), but even
with that fixed, CSD's own gyroscope verification test still failed -- not because anything is
broken, but because the gyroscope has a genuine, uncalibrated zero-rate bias on the Z axis
(measured live: X +0.2180, Y +0.4271, both comfortably inside CSD's own +-1.3 deg/s pass
window; Z -2.2486, outside it). CSD's own calibration flow for this (SensorCalibrationResolver,
/usr/lib/sensor-calibration/calibrate_*) is genuinely proprietary, Jolla-internal tooling never
shipped for this device (lilac was never a real Jolla device) -- confirmed via a real search
(GitHub code/repo search, this device's own live zypper against every configured Sailfish
repo, a broader web search) turning up no public source, no installable package, nothing.

sensorfw itself is real, open source (unlike csd) and already has a native calibration
mechanism for one sensor -- the magnetometer (`needs_calibration`, libmagcalibrationchain-qt5.so)
-- but nothing equivalent for gyroscope, since Android's own convention assumes the vendor
HAL/SLPI already delivers bias-corrected gyro data, which this port's own SLPI pipeline
evidently doesn't do cleanly. This patch adds the missing piece directly, in the same spirit as
sensorfw's own existing per-sensor config keys (transformation_matrix, scale_coefficient, ...).

Mechanism: read gyroscope/bias_x, gyroscope/bias_y, gyroscope/bias_z (degrees/second, matching
what QtSensors/CSD clients see) once in the adaptor's constructor via the same
SensorFrameworkConfig API every other config key here already uses; default to 0.0 (a no-op) if
never set. Subtract from every raw sample in processSample(), in both the USE_BINDER and
non-binder code paths (this device builds with CONFIG+=binder, i.e. the #ifdef USE_BINDER
branch, per rpm/sensorfw-qt5-binder.spec -- patched both anyway since they're structurally
identical and either could matter on a different device sharing this same file).

A companion userspace calibration tool measures the live stationary bias and writes it to
/etc/sensorfw/sensord.conf.d/90-lilac-gyro-calibration.conf as:

    [gyroscope]
    bias_x = <measured average>
    bias_y = <measured average>
    bias_z = <measured average>

Config is read once at sensorfwd startup (same as every other sensor's config, and the same
limitation already documented for sensor enumeration itself) -- a sensorfwd restart is needed to pick up a
new value.

Idempotent. Run from the root of a sensorfw source checkout (the directory containing
adaptors/), or pass that root as argv[1]. Written and tested against the 0.15.1 tag
(github.com/sailfishos/sensorfw), matching this device's own installed
hybris-libsensorfw-qt5-binder-0.15.1 package exactly.
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
MARK = 'lilac-v2 change 112'
hdr_done = MARK in hs
cpp_done = MARK in cs
if hdr_done and cpp_done:
    print('already patched')
    sys.exit(0)

old_hdr = '''private:
    DeviceAdaptorRingBuffer<TimedXyzData>* buffer;
    int sensorType;
    QByteArray powerStatePath;

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

};'''

if not hdr_done:
    if old_hdr not in hs:
        sys.exit('expected header private: section not found -- hybrisgyroscopeadaptor.h may have changed')
    hdr.write_text(hs.replace(old_hdr, new_hdr))

old_ctor = '''    powerStatePath = SensorFrameworkConfig::configuration()->value("gyroscope/powerstate_path").toByteArray();
    if (!powerStatePath.isEmpty() && !QFile::exists(powerStatePath)) {
        qCWarning(lcSensorFw) << NodeBase::id() << "Path does not exists: " << powerStatePath;
    	powerStatePath.clear();
    }
    unsigned int interval_us = 50 * 1000;'''

new_ctor = '''    powerStatePath = SensorFrameworkConfig::configuration()->value("gyroscope/powerstate_path").toByteArray();
    if (!powerStatePath.isEmpty() && !QFile::exists(powerStatePath)) {
        qCWarning(lcSensorFw) << NodeBase::id() << "Path does not exists: " << powerStatePath;
    	powerStatePath.clear();
    }
    // lilac-v2: see hybrisgyroscopeadaptor.h's own comment.
    // Absent keys default to 0.0 (QVariant::toDouble() on an invalid/empty QVariant), so this
    // is a no-op everywhere this config key was never written.
    biasX = SensorFrameworkConfig::configuration()->value("gyroscope/bias_x").toDouble();
    biasY = SensorFrameworkConfig::configuration()->value("gyroscope/bias_y").toDouble();
    biasZ = SensorFrameworkConfig::configuration()->value("gyroscope/bias_z").toDouble();
    if (biasX != 0.0 || biasY != 0.0 || biasZ != 0.0)
        // NodeBase::id(), not id() -- this constructor's own parameter is also named "id"
        // and shadows the base class method here (the same reason the powerstate_path
        // warning two lines above already had to qualify it the same way).
        qCInfo(lcSensorFw) << NodeBase::id() << "HybrisGyroscopeAdaptor applying bias correction:"
                            << biasX << biasY << biasZ << "deg/s";
    unsigned int interval_us = 50 * 1000;'''

old_sample = '''#ifdef USE_BINDER
    d->x_ = (data.u.vec3.x) * RADIANS_TO_DEGREES * 1000;
    d->y_ = (data.u.vec3.y) * RADIANS_TO_DEGREES * 1000;
    d->z_ = (data.u.vec3.z) * RADIANS_TO_DEGREES * 1000;
#else
    d->x_ = (data.gyro.x) * RADIANS_TO_DEGREES * 1000;
    d->y_ = (data.gyro.y) * RADIANS_TO_DEGREES * 1000;
    d->z_ = (data.gyro.z) * RADIANS_TO_DEGREES * 1000;
#endif'''

new_sample = '''#ifdef USE_BINDER
    d->x_ = (data.u.vec3.x) * RADIANS_TO_DEGREES * 1000 - biasX * 1000;
    d->y_ = (data.u.vec3.y) * RADIANS_TO_DEGREES * 1000 - biasY * 1000;
    d->z_ = (data.u.vec3.z) * RADIANS_TO_DEGREES * 1000 - biasZ * 1000;
#else
    d->x_ = (data.gyro.x) * RADIANS_TO_DEGREES * 1000 - biasX * 1000;
    d->y_ = (data.gyro.y) * RADIANS_TO_DEGREES * 1000 - biasY * 1000;
    d->z_ = (data.gyro.z) * RADIANS_TO_DEGREES * 1000 - biasZ * 1000;
#endif'''

if not cpp_done:
    if old_ctor not in cs:
        sys.exit('expected constructor body not found -- hybrisgyroscopeadaptor.cpp may have changed')
    if old_sample not in cs:
        sys.exit('expected processSample body not found -- hybrisgyroscopeadaptor.cpp may have changed')
    cs = cs.replace(old_ctor, new_ctor).replace(old_sample, new_sample)
    cpp.write_text(cs)

print(f'patched {hdr} and {cpp}: HybrisGyroscopeAdaptor now applies a configurable gyroscope/bias_{{x,y,z}} correction')
