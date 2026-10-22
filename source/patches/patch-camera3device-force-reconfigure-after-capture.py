#!/usr/bin/env python3
"""Force a real HAL configure_streams() call after every still capture, to work
around a real, reproducible bug/limit in this device's own proprietary
QCamera3HWI vendor blob: exactly one still capture succeeds per HAL stream
configuration, and every later one in the same configuration permanently
fails, because the JPEG completion handler's own frame-number-to-buffer-index
bookkeeping breaks after the first success and never recovers.

Found and precisely narrowed 2026-09-29,
following up on the "camera capture stops working after a few shots" report.
Live evidence, not guesswork: every capture's JPEG hardware encode genuinely
succeeds every time (`jpegEvtHandle: Issue Jpeg Callback frameNumber = N
status = 0`), but starting with the *second* capture against one HAL stream
configuration, the very next line is `jpegEvtHandle: 5574: could not find the
input buf index, frame number N` -- the completed job's own result gets
dropped, and its JPEG job slot (capacity exactly 1) never frees, so every
capture after that queues behind a slot that will never open again
("mm_jpeg_jobmgr_thread: ongoing job already reach max 1").

Confirmed directly which operation resets this: killing and letting
`android.hardware.camera.provider@2.4-service` respawn gave a fresh HAL
configuration and let exactly one more capture through cleanly. A full
jolla-camera close/reopen of the camera device does the same (it tears down
and recreates the `Camera3Device`, which always configures streams fresh on
next open). A single well-spaced shot works for the same reason: jolla-camera
closes the camera when idle, so the *next* shot always gets a fresh
configuration too. What fails is several shots taken close together while the
camera stays open the whole time -- exactly AOSP's own `manageDone()` path in
CaptureSequencer.cpp, which (correctly, on a device without this bug) leaves
the camera "stopped" but still configured, ready for a fast next capture.

Root mechanism, read directly out of this same source tree:
Camera3Device::configureStreamsLocked() (device3/Camera3Device.cpp) has a
deliberate performance optimization -- `if (!mNeedConfig) { ... return OK; }`
-- that skips the real HAL configure_streams() call whenever the requested
stream set hasn't changed since the last configuration. That's exactly what
happens between two still captures taken close together in one session: the
capture stream is reused as-is, mNeedConfig stays false, and the vendor HAL
never gets a fresh configure_streams() call to reset whatever internal state
is breaking its own bookkeeping. A full close/reopen always sees mNeedConfig
freshly true (a brand new Camera3Device), which is the one difference that
lines up with every live test done so far.

Fix: add a new CameraDeviceBase method, forceNextConfigureStreams(), that
does nothing but set mNeedConfig = true under the same locking
waitUntilDrained() already uses (Camera3Device is the only real
implementation of CameraDeviceBase left in this Android 11 tree -- HALv2's
device2/Camera2Device was already removed upstream). CaptureSequencer's own
manageDone(), right where it already calls waitUntilDrained() to idle the
device after a STILL_CAPTURE, now also calls this -- so the *next* capture
request (whenever it comes) always triggers a real configure_streams() call
first, matching the one flow already proven to work every time, without
paying the cost of a full ICamera disconnect/reconnect on every single shot.

This is a real behavior change for every capture on this device (not gated to
"only if lilac's own blob is buggy") -- deliberately so, matching this
project's own convention (see patch-cameraservice-no-activitymanager.py) of
not trying to detect the bug at runtime when the fix is cheap and harmless
everywhere: a skipped configure_streams() call is purely a performance
optimization AOSP itself documents as optional, and forcing it once per still
capture costs a few tens of milliseconds against a several-second capture
cycle. Not yet confirmed live against consecutive rapid captures at the time
this patch was written --md for the actual test result.

Idempotent. Run from the root of this AOSP tree (the directory containing
frameworks/), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
base_h = root / 'frameworks/av/services/camera/libcameraservice/common/CameraDeviceBase.h'
dev3_h = root / 'frameworks/av/services/camera/libcameraservice/device3/Camera3Device.h'
dev3_cpp = root / 'frameworks/av/services/camera/libcameraservice/device3/Camera3Device.cpp'
seq_cpp = root / 'frameworks/av/services/camera/libcameraservice/api1/client2/CaptureSequencer.cpp'
for p in (base_h, dev3_h, dev3_cpp, seq_cpp):
    if not p.is_file():
        sys.exit(f'not found: {p}')

MARK = 'lilac-v2: force a fresh HAL configure_streams() after every still capture'

bh = base_h.read_text()
d3h = dev3_h.read_text()
d3c = dev3_cpp.read_text()
sc = seq_cpp.read_text()

if MARK in bh and MARK in d3h and MARK in d3c and MARK in sc:
    print('already patched')
    sys.exit(0)

# 1. CameraDeviceBase.h -- new pure virtual method, right after waitUntilDrained().
old_base = '''    virtual status_t waitUntilDrained() = 0;'''
new_base = '''    virtual status_t waitUntilDrained() = 0;

    /* %s --
     * see Camera3Device's own implementation for the full story. Callable any
     * time; takes effect on the next stream (re)configuration.
     */
    virtual void forceNextConfigureStreams() = 0;''' % MARK

if MARK not in bh:
    if old_base not in bh:
        sys.exit(f'expected waitUntilDrained() declaration not found in {base_h}')
    bh = bh.replace(old_base, new_base, 1)
    base_h.write_text(bh)

# 2. Camera3Device.h -- override declaration, right after waitUntilDrained() override.
old_dev3h = '''    // Transitions to the idle state on success
    status_t waitUntilDrained() override;'''
new_dev3h = '''    // Transitions to the idle state on success
    status_t waitUntilDrained() override;

    // %s
    void forceNextConfigureStreams() override;''' % MARK

if MARK not in d3h:
    if old_dev3h not in d3h:
        sys.exit(f'expected waitUntilDrained() override not found in {dev3_h}')
    d3h = d3h.replace(old_dev3h, new_dev3h, 1)
    dev3_h.write_text(d3h)

# 3. Camera3Device.cpp -- implementation, right after waitUntilDrained()/waitUntilDrainedLocked().
old_dev3c = '''status_t Camera3Device::waitUntilDrained() {
    ATRACE_CALL();
    Mutex::Autolock il(mInterfaceLock);
    nsecs_t maxExpectedDuration = getExpectedInFlightDuration();
    Mutex::Autolock l(mLock);

    return waitUntilDrainedLocked(maxExpectedDuration);
}'''
new_dev3c = old_dev3c + '''

/* %s --
 * configureStreamsLocked() below deliberately skips the real HAL
 * configure_streams() call whenever the requested stream set hasn't changed
 * since the last configuration (`if (!mNeedConfig) { ... return OK; }`) -- a
 * real AOSP performance optimization, but one that also means this device's
 * own vendor camera HAL blob never gets a chance to reset whatever internal
 * state is breaking its own JPEG-completion bookkeeping after the first
 * still capture in a session. Call this once a still capture is done (see
 * CaptureSequencer::manageDone()) to force the *next* stream configuration
 * to be a real one again, matching the one flow already confirmed to work
 * every time (a full camera close/reopen, which always configures fresh).
 */
void Camera3Device::forceNextConfigureStreams() {
    Mutex::Autolock l(mLock);
    mNeedConfig = true;
}''' % MARK

if MARK not in d3c:
    if old_dev3c not in d3c:
        sys.exit(f'expected waitUntilDrained() implementation not found in {dev3_cpp}')
    d3c = d3c.replace(old_dev3c, new_dev3c, 1)
    dev3_cpp.write_text(d3c)

# 4. CaptureSequencer.cpp -- call it from manageDone()'s STILL_CAPTURE case.
old_seq = '''            case Parameters::STILL_CAPTURE:
                res = client->getCameraDevice()->waitUntilDrained();
                if (res != OK) {
                    ALOGE("%s: Camera %d: Can't idle after still capture: "
                            "%s (%d)", __FUNCTION__, client->getCameraId(),
                            strerror(-res), res);
                }
                l.mParameters.state = Parameters::STOPPED;
                break;'''
new_seq = '''            case Parameters::STILL_CAPTURE:
                res = client->getCameraDevice()->waitUntilDrained();
                if (res != OK) {
                    ALOGE("%s: Camera %d: Can't idle after still capture: "
                            "%s (%d)", __FUNCTION__, client->getCameraId(),
                            strerror(-res), res);
                }
                // {mark}
                client->getCameraDevice()->forceNextConfigureStreams();
                l.mParameters.state = Parameters::STOPPED;
                break;'''.replace('{mark}', MARK)

if MARK not in sc:
    if old_seq not in sc:
        sys.exit(f'expected STILL_CAPTURE case not found in {seq_cpp}')
    sc = sc.replace(old_seq, new_seq, 1)
    seq_cpp.write_text(sc)

print(f'patched {base_h}, {dev3_h}, {dev3_cpp} and {seq_cpp}: every still '
      'capture now forces a real HAL configure_streams() call before the '
      'next one, instead of silently reusing a stream configuration the '
      "vendor HAL's own JPEG completion bookkeeping cannot survive twice")
