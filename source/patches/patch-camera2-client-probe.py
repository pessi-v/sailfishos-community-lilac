#!/usr/bin/env python3
"""Create device/sony/lilac/camera2-client-probe: a standalone Camera2 client
that talks to CameraService directly through libcamera_client's
ICameraDeviceUser -- no droidmedia, no app, no proprietary blobs.

WHY THIS EXISTS

While chasing a real, intermittent autofocus bug (section 121), the
investigation drifted into a much bigger, riskier idea: sourcing this
device's whole proprietary Sony "excalibur"/"cacao" camera HAL stack from
its own LineageOS install to replace the generic qcom HAL this project's
own from-source build already produces and already has working (section
122). The user pushed back correctly: that plan was a complete HAL
replacement gambled against a camera that already works, not a gap-fill --
and the sibling XZ1 Compact port's own notes show that having the *full*
Sony stack was never, on its own, a working camera for them either (many
sessions fixing their own calibration pipeline, stills still ending in a
0-byte JPEG and a bus error afterward).

The user's own better question: does Camera2 API access work at all on
*this* build's current, already-working generic qcom HAL -- avoiding the
whole Sony-stack gamble? The sibling port had already proven the Camera2
"route" fully open, but only
against their Sony HAL, never a generic one. This probe answers that
question for real, with nothing new deployed: `libcamera_client.so` is
already on this device (droidmedia already links it for Camera1), and it
exports the Camera2 client interfaces too.

RESULT: the route is open here as well, no permission wall, and this
build's generic qcom HAL is if anything *more* capable on paper than the
sibling port's own tuned Sony HAL on one real axis -- it advertises RAW,
which the sibling port's own investigation established Sony's excalibur HAL
never does for this device, under any camera id.

ADAPTED, NOT COPIED, from the sibling port's own patch-camera2-client-probe.py.
Their version targets a much newer Android (AttributionSourceState,
ROTATION_OVERRIDE_NONE, sharedMode -- all post-Android-11 API additions).
This project is Android 11, and the real signatures below were read
directly out of this project's own *generated* AIDL headers
(out/soong/.intermediates/frameworks/av/camera/libcamera_client/.../gen/aidl/,
already built from an earlier session), not assumed: plain String16 camera
ids, no attribution/targetSdk/rotation/policy parameters anywhere,
connectDevice(callbacks, cameraId, opPackageName, featureId, clientUid,
&device).

Deliberately NO Surface, NO BufferQueue, NO capture. Streams need a
consumer and a consumer needs decisions; this probe exists to find out
whether it is worth making them.

Build with:  make -j4 lilac-camera2-client-probe
Deploy:      copy directly to /system/bin/ on the device (NOT
             /usr/libexec/droid-hybris/system/bin/ -- that path is not
             itself bind-mounted to /system/bin; write to the real,
             already-mounted /system directly). chmod 755. Needs
             /dev/binder (the framework path, not the HAL path).
Run:         lilac-camera2-client-probe [cameraId]   (default: tries 0 then 1)

⚠️ Diagnostic only -- never shipped in the image, and not part of any
droid-hal-prepare.sh overlay. A live-tested binary is not left on the
device between sessions (see section 123: a live experiment that isn't
reverted before the session ends is a real, persistent change to
vendor.img/system.img, not ephemeral RAM state -- this file's own comment
above is the reminder).
"""
import os
import sys

DEST = "device/sony/lilac/camera2-client-probe"

BP = """// Diagnostic only -- never shipped in the image.
//    make -j4 lilac-camera2-client-probe
cc_binary {
    name: "lilac-camera2-client-probe",
    srcs: ["main.cpp"],
    shared_libs: [
        "libbinder",
        "libcamera_client",
        "libcamera_metadata",
        "libcutils",
        "libgui",
        "liblog",
        "libui",
        "libutils",
    ],
    cflags: [
        "-Wall",
        "-Wno-unused-parameter",
    ],
}
"""

CPP = r"""// Reach the camera the way a Camera2 app does: through CameraService, over
// /dev/binder, using libcamera_client -- the library this port already has,
// and that droidmedia already links for its own (Camera1-only) purposes.
//
// See device/sony/lilac/camera2-client-probe (patch-camera2-client-probe.py)
// for why this exists. Adapted from the sibling XZ1 Compact port's own probe of the same
// name, for THIS project's own, much older Android 11 ICameraService/
// ICameraDeviceUser AIDL surface -- confirmed against this project's own
// generated headers, not assumed.
//
// Stages are printed one per line with [ok] / [FAIL] so that a run that dies
// halfway is still worth reading. connectDevice is stage 5; everything
// before it is context, everything after it is the prize.

#include <android/hardware/ICameraService.h>
#include <android/hardware/camera2/BnCameraDeviceCallbacks.h>
#include <android/hardware/camera2/ICameraDeviceUser.h>

#include <binder/IServiceManager.h>
#include <binder/IPCThreadState.h>
#include <binder/ProcessState.h>
#include <camera/CameraMetadata.h>
#include <system/camera_metadata.h>
#include <utils/String16.h>

#include <cstdarg>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
#include <unistd.h>

using android::sp;
using android::String16;
using android::CameraMetadata;
using android::binder::Status;
using android::hardware::ICameraService;
using android::hardware::camera2::ICameraDeviceUser;
using android::hardware::camera2::BnCameraDeviceCallbacks;
using android::hardware::camera2::impl::CameraMetadataNative;
using android::hardware::camera2::impl::CaptureResultExtras;
using android::hardware::camera2::impl::PhysicalCaptureResultInfo;

static int gStage = 0;

static void ok(const char *fmt, ...)
{
    va_list ap;
    printf("[ok]   %d. ", ++gStage);
    va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    printf("\n");
    fflush(stdout);
}

static void fail(const char *fmt, ...)
{
    va_list ap;
    printf("[FAIL] %d. ", ++gStage);
    va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    printf("\n");
    fflush(stdout);
}

static void note(const char *fmt, ...)
{
    va_list ap;
    printf("         ");
    va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    printf("\n");
    fflush(stdout);
}

static void explain(const char *what, const Status &s)
{
    fail("%s: %s", what, s.toString8().c_str());
    if (s.exceptionCode() == Status::EX_SECURITY)
        note("^ EX_SECURITY -- CameraService rejected us as a caller, not as a "
             "request. This is the permission wall.");
    if (s.serviceSpecificErrorCode() == ICameraService::ERROR_PERMISSION_DENIED)
        note("^ ERROR_PERMISSION_DENIED from CameraService.");
    if (s.serviceSpecificErrorCode() == ICameraService::ERROR_CAMERA_IN_USE)
        note("^ camera already open elsewhere -- stop the running camera app.");
    if (s.serviceSpecificErrorCode() == ICameraService::ERROR_DISCONNECTED)
        note("^ provider not reachable from cameraserver.");
}

static const char *kCap[] = {
    "BACKWARD_COMPATIBLE", "MANUAL_SENSOR", "MANUAL_POST_PROCESSING", "RAW",
    "PRIVATE_REPROCESSING", "READ_SENSOR_SETTINGS", "BURST_CAPTURE",
    "YUV_REPROCESSING", "DEPTH_OUTPUT", "CONSTRAINED_HIGH_SPEED_VIDEO",
    "MOTION_TRACKING", "LOGICAL_MULTI_CAMERA", "MONOCHROME",
};

static void dumpCaps(CameraMetadata &m)
{
    camera_metadata_entry_t e = m.find(ANDROID_REQUEST_AVAILABLE_CAPABILITIES);
    if (!e.count) { note("capabilities: <absent>"); return; }
    std::string s;
    for (size_t i = 0; i < e.count; i++) {
        uint8_t v = e.data.u8[i];
        s += (v < sizeof(kCap) / sizeof(kCap[0])) ? kCap[v] : "?";
        if (i + 1 < e.count) s += " ";
    }
    note("capabilities: %s", s.c_str());
}

static void dumpI64(CameraMetadata &m, uint32_t tag, const char *label)
{
    camera_metadata_entry_t e = m.find(tag);
    if (!e.count) { note("%-28s <absent>", label); return; }
    std::string s;
    char buf[32];
    for (size_t i = 0; i < e.count; i++) {
        snprintf(buf, sizeof(buf), "%lld", (long long)e.data.i64[i]);
        s += buf;
        if (i + 1 < e.count) s += " .. ";
    }
    note("%-28s %s", label, s.c_str());
}

static void dumpI32(CameraMetadata &m, uint32_t tag, const char *label)
{
    camera_metadata_entry_t e = m.find(tag);
    if (!e.count) { note("%-28s <absent>", label); return; }
    std::string s;
    char buf[32];
    for (size_t i = 0; i < e.count; i++) {
        snprintf(buf, sizeof(buf), "%d", e.data.i32[i]);
        s += buf;
        if (i + 1 < e.count) s += " .. ";
    }
    note("%-28s %s", label, s.c_str());
}

static void dumpU8(CameraMetadata &m, uint32_t tag, const char *label)
{
    camera_metadata_entry_t e = m.find(tag);
    if (!e.count) { note("%-28s <absent>", label); return; }
    note("%-28s %u", label, (unsigned)e.data.u8[0]);
}

// CameraService requires a callbacks object even when nothing will be
// captured. All of these are oneway; none should fire during this probe
// except possibly onDeviceError, which is worth seeing.
class Callbacks : public BnCameraDeviceCallbacks {
public:
    Status onDeviceError(int32_t errorCode, const CaptureResultExtras &) override {
        note("callback: onDeviceError(%d)", errorCode);
        return Status::ok();
    }
    Status onDeviceIdle() override { return Status::ok(); }
    Status onCaptureStarted(const CaptureResultExtras &, int64_t) override { return Status::ok(); }
    Status onResultReceived(const CameraMetadataNative &, const CaptureResultExtras &,
                            const std::vector<PhysicalCaptureResultInfo> &) override {
        return Status::ok();
    }
    Status onPrepared(int32_t) override { return Status::ok(); }
    Status onRepeatingRequestError(int64_t, int32_t) override { return Status::ok(); }
    Status onRequestQueueEmpty() override { return Status::ok(); }
};

struct Template { int id; const char *name; };
static const Template kTemplates[] = {
    { ICameraDeviceUser::TEMPLATE_MANUAL,        "TEMPLATE_MANUAL" },
    { ICameraDeviceUser::TEMPLATE_STILL_CAPTURE, "TEMPLATE_STILL_CAPTURE" },
    { ICameraDeviceUser::TEMPLATE_PREVIEW,       "TEMPLATE_PREVIEW" },
};

int main(int argc, char **argv)
{
    // We hand a binder object to CameraService, so we must be able to serve it.
    android::ProcessState::self()->startThreadPool();

    printf("lilac Camera2 client probe -- libcamera_client via CameraService\n");
    printf("uid=%d pid=%d\n\n", (int)getuid(), (int)getpid());

    // --- 1. the service ---------------------------------------------------
    sp<android::IBinder> b =
        android::defaultServiceManager()->checkService(String16("media.camera"));
    if (b == nullptr) {
        fail("media.camera is not registered");
        return 1;
    }
    sp<ICameraService> cs = android::interface_cast<ICameraService>(b);
    if (cs == nullptr) { fail("media.camera did not cast to ICameraService"); return 1; }
    ok("media.camera found and cast to ICameraService");

    // On this Android 11 base, getCameraServiceProxy() (CameraService.cpp)
    // simply returns null and every caller checks for that -- there is no
    // "isCameraDisabled() fails closed" gate here (that is a later Android
    // addition), so media.camera.proxy is not expected to matter. Check it
    // anyway, since droidmedia's own FakeCameraServiceProxy commit is in
    // this tree's history for a reason worth confirming live.
    sp<android::IBinder> pb =
        android::defaultServiceManager()->checkService(String16("media.camera.proxy"));
    if (pb == nullptr) note("media.camera.proxy is not registered (expected to be harmless here)");
    else               ok("media.camera.proxy is registered");

    const String16 opPackageName("lilac-camera2-client-probe");
    const int32_t clientUid = ICameraService::USE_CALLING_UID;

    // --- 2. how many cameras ------------------------------------------------
    int32_t count = 0;
    Status s = cs->getNumberOfCameras(ICameraService::CAMERA_TYPE_ALL, &count);
    if (!s.isOk()) {
        explain("getNumberOfCameras", s);
        note("A failure THIS early is already the permission wall -- "
             "connectDevice will not be reached.");
        return 1;
    }
    ok("getNumberOfCameras = %d", count);

    // --- 3. static metadata, through the framework this time ---------------
    std::vector<std::string> ids;
    if (argc > 1) ids.push_back(argv[1]);
    else { ids.push_back("0"); ids.push_back("1"); }

    std::string useId;
    for (const std::string &id : ids) {
        CameraMetadata chars;
        s = cs->getCameraCharacteristics(String16(id.c_str()), &chars);
        if (!s.isOk()) { explain(("getCameraCharacteristics(" + id + ")").c_str(), s); continue; }
        ok("getCameraCharacteristics(%s)", id.c_str());
        dumpCaps(chars);
        dumpI64(chars, ANDROID_SENSOR_INFO_EXPOSURE_TIME_RANGE, "exposure range (ns)");
        dumpI32(chars, ANDROID_SENSOR_INFO_SENSITIVITY_RANGE,   "sensitivity range");
        if (useId.empty()) useId = id;
    }
    if (useId.empty()) { fail("no camera answered getCameraCharacteristics"); return 1; }

    // --- 4. THE DECISIVE CALL -----------------------------------------------
    printf("\n--- connectDevice(%s): the call this probe exists for ---\n", useId.c_str());
    sp<Callbacks> cb = new Callbacks();
    sp<ICameraDeviceUser> dev;
    s = cs->connectDevice(cb, String16(useId.c_str()), opPackageName,
                          std::unique_ptr<String16>(), clientUid, &dev);
    if (!s.isOk() || dev == nullptr) {
        explain("connectDevice", s);
        printf("\nVERDICT: the Camera2 route through CameraService is CLOSED to a "
               "native client as-is, on THIS build's generic qcom HAL.\n");
        return 1;
    }
    ok("connectDevice -> ICameraDeviceUser  *** the route is open ***");

    // --- 5. the prize: per-request manual controls ---------------------------
    for (const Template &t : kTemplates) {
        CameraMetadata req;
        s = dev->createDefaultRequest(t.id, &req);
        if (!s.isOk()) { explain(t.name, s); continue; }
        ok("createDefaultRequest(%s)", t.name);
        dumpU8 (req, ANDROID_CONTROL_MODE,          "control.mode");
        dumpU8 (req, ANDROID_CONTROL_AE_MODE,       "control.aeMode");
        dumpI64(req, ANDROID_SENSOR_EXPOSURE_TIME,  "sensor.exposureTime (ns)");
        dumpI32(req, ANDROID_SENSOR_SENSITIVITY,    "sensor.sensitivity");
    }

    // --- 6. and what the open device says about itself -----------------------
    CameraMetadata info;
    s = dev->getCameraInfo(&info);
    if (s.isOk()) ok("getCameraInfo (%zu entries)", (size_t)info.entryCount());
    else          explain("getCameraInfo", s);

    dev->disconnect();
    ok("disconnect");

    printf("\nVERDICT: CameraService accepted a native client and opened a HAL3 "
           "device on this build's generic qcom HAL.\n"
           "         Remaining work is buffer plumbing, not access.\n");
    return 0;
}
"""


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: patch-camera2-client-probe.py <ANDROID_ROOT>")
    root = sys.argv[1]
    dest = os.path.join(root, DEST)
    os.makedirs(dest, exist_ok=True)
    for name, body in (("Android.bp", BP), ("main.cpp", CPP)):
        path = os.path.join(dest, name)
        with open(path, "w") as f:
            f.write(body)
        print("wrote %s" % path)


if __name__ == "__main__":
    main()
