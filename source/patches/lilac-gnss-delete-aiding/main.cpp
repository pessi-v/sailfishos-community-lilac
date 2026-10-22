// Cold-start helper: connect to the GNSS HAL (android.hardware.gnss@2.1 "default"),
// register a no-op callback, delete ALL aiding data (ephemeris, almanac, position, time,
// ...) and exit. Run it while nothing else is tracking, then time a normal start.
#include <android/hardware/gnss/2.1/IGnss.h>
#include <android/hardware/gnss/2.1/IGnssCallback.h>
#include <unistd.h>
#include <stdio.h>

using android::sp;
using android::hardware::Return;
using android::hardware::Void;
using android::hardware::hidl_vec;
using android::hardware::hidl_string;
namespace V1_0 = android::hardware::gnss::V1_0;
namespace V2_0 = android::hardware::gnss::V2_0;
namespace V2_1 = android::hardware::gnss::V2_1;

struct Cb : public V2_1::IGnssCallback {
    Return<void> gnssLocationCb(const V1_0::GnssLocation&) override { return Void(); }
    Return<void> gnssStatusCb(V1_0::IGnssCallback::GnssStatusValue) override { return Void(); }
    Return<void> gnssSvStatusCb(const V1_0::IGnssCallback::GnssSvStatus&) override { return Void(); }
    Return<void> gnssNmeaCb(int64_t, const hidl_string&) override { return Void(); }
    Return<void> gnssSetCapabilitesCb(uint32_t) override { return Void(); }
    Return<void> gnssAcquireWakelockCb() override { return Void(); }
    Return<void> gnssReleaseWakelockCb() override { return Void(); }
    Return<void> gnssRequestTimeCb() override { return Void(); }
    Return<void> gnssSetSystemInfoCb(const V1_0::IGnssCallback::GnssSystemInfo&) override { return Void(); }
    Return<void> gnssNameCb(const hidl_string&) override { return Void(); }
    Return<void> gnssRequestLocationCb(bool) override { return Void(); }
    Return<void> gnssSetCapabilitiesCb_2_0(uint32_t) override { return Void(); }
    Return<void> gnssLocationCb_2_0(const V2_0::GnssLocation&) override { return Void(); }
    Return<void> gnssRequestLocationCb_2_0(bool, bool) override { return Void(); }
    Return<void> gnssSvStatusCb_2_0(const hidl_vec<V2_0::IGnssCallback::GnssSvInfo>&) override { return Void(); }
    Return<void> gnssSetCapabilitiesCb_2_1(uint32_t) override { return Void(); }
    Return<void> gnssSvStatusCb_2_1(const hidl_vec<V2_1::IGnssCallback::GnssSvInfo>&) override { return Void(); }
};

int main() {
    sp<V2_1::IGnss> gnss = V2_1::IGnss::getService();
    if (gnss == nullptr) { fprintf(stderr, "no IGnss 2.1 service\n"); return 1; }
    auto r = gnss->setCallback_2_1(new Cb());
    printf("setCallback_2_1: %s\n", r.isOk() && r ? "ok" : "failed");
    auto d = gnss->deleteAidingData(static_cast<V1_0::IGnss::GnssAidingData>(0xFFFF));
    printf("deleteAidingData(ALL): %s\n", d.isOk() ? "ok" : "failed");
    usleep(500000);
    gnss->cleanup();
    return d.isOk() ? 0 : 2;
}
