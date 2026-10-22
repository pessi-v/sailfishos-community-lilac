#!/usr/bin/env python3
"""FrameProcessor::process3aState: report laser (ToF) focus as FOCUSED_LOCKED.

With the laser rangefinder in range, QCamera3HWI (Sony's ToF patch, QCamera3HWI.cpp ~14790) sets the
ISP focus mode OFF and drives the lens from the ToF distance every frame (`tof_focusing`). The
result then carries ANDROID_CONTROL_AF_MODE = OFF and ANDROID_CONTROL_AF_STATE = INACTIVE for every
frame, forever. Sony worked around the framework with a fake alternating 4/0 AF_STATE in the *urgent*
(partial) metadata, which relied on the Android 9 FrameProcessor taking each partial result on its own.
On this Android 11 service `updatePendingState()` keeps the first value for a tag, the merged result
holds the HAL's real final value (INACTIVE), and the fake 4 never arrives -- traced per frame:
    AF3A ... afs0=0 pendAfState=0 pendAfMode=0 trig=2 (thousands of frames, never 4)
So Camera2Client::autoFocus() (AUTO, or CONTINUOUS_PICTURE with a pending trigger) never gets
FOCUSED_LOCKED for its trigger id and the camera app's shutter blocks until the app exits; only a
tap-to-focus that happens to complete on a timeout recovers.

Fix: in process3aState(), when the result says AF_MODE_OFF but the API1 client asked for an
autofocus mode (AUTO, MACRO, CONTINUOUS_PICTURE, CONTINUOUS_VIDEO), the lens is being driven by the
laser and is already in position: report AF_STATE = FOCUSED_LOCKED. Notifications still need a
matching trigger id, so idle frames do nothing; a new autoFocus() trigger id changes
`afTriggerId`, which makes the existing "state/mode/trigger changed" check fire and completes the
request. FOCUS_MODE_INFINITY/FIXED/EDOF also map to AF_MODE_OFF but are excluded by the focus-mode
test.

Idempotent. Run from the Android tree root, or pass argv[1].
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'frameworks/av/services/camera/libcameraservice/api1/client2/FrameProcessor.cpp'
if not p.is_file():
    sys.exit(f'not found: {p}')
s = p.read_text()
if 'lilac: laser (ToF) focus' in s:
    print('already applied')
    sys.exit(0)

old = "    pendingState.afTriggerId = frame.mResultExtras.afTriggerId;\n"
new = '''    pendingState.afTriggerId = frame.mResultExtras.afTriggerId;

    // lilac: laser (ToF) focus. The HAL drives the lens from the laser distance, reports
    // AF_MODE_OFF and an INACTIVE AF_STATE forever, so an API1 autoFocus() trigger would never
    // complete. If the client asked for an autofocus mode, report the lens as locked.
    if (gotAFState && pendingState.afMode == ANDROID_CONTROL_AF_MODE_OFF &&
            pendingState.afState != ANDROID_CONTROL_AF_STATE_FOCUSED_LOCKED) {
        Parameters::focusMode_t clientFocusMode;
        {
            SharedParameters::Lock l(client->getParameters());
            clientFocusMode = l.mParameters.focusMode;
        }
        if (clientFocusMode == Parameters::FOCUS_MODE_AUTO ||
                clientFocusMode == Parameters::FOCUS_MODE_MACRO ||
                clientFocusMode == Parameters::FOCUS_MODE_CONTINUOUS_PICTURE ||
                clientFocusMode == Parameters::FOCUS_MODE_CONTINUOUS_VIDEO) {
            pendingState.afState = ANDROID_CONTROL_AF_STATE_FOCUSED_LOCKED;
        }
    }
'''
assert s.count(old) == 1
p.write_text(s.replace(old, new, 1))
print('applied')
