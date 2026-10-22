#!/usr/bin/env python3
"""Stop `system_server` from fatally crash-looping in `WifiService`'s constructor (2026-09-21 session: postmarketOS-SD-card / USB-net / TX-starvation investigation, root-caused via
a new `logcat-sdlog` continuous capture after live SSH access proved unreliable all night).

Root cause, read directly off a captured `logcat -b all` spanning the actual crash (not guessed):

    java.lang.RuntimeException: Failed to create service com.android.server.wifi.WifiService:
      service constructor threw an exception
    Caused by: java.lang.NullPointerException: Attempt to invoke virtual method
      'boolean java.lang.String.equals(java.lang.Object)' on a null object reference
        at android.app.ContextImpl.createPackageContextAsUser(ContextImpl.java:2300)
        at com.android.server.wifi.WifiContext.getResourcesApkContext(WifiContext.java:104)
        at com.android.server.wifi.WifiCarrierInfoManager.<init>(WifiCarrierInfoManager.java:295)
        at com.android.server.wifi.WifiInjector.<init>(WifiInjector.java:263)
        at com.android.server.wifi.WifiService.<init>(WifiService.java:48)

`SystemServer.startOtherServices()` treats any uncaught exception from a service constructor as
fatal -- `system_server` dies, zygote exits with it, and the whole userspace restarts. This
recurred identically on every single crash cycle captured (dozens, ~15-20s apart), i.e. this is
THE crash loop chased since an earlier session under the "BinderProxy race" theory, not a separate
issue -- that theory was never wrong about the symptom (constant zygote/system_server restarts),
just about the cause.

`WifiContext.getResourcesApkContext()` resolves the WiFi resources overlay package
(`ServiceWifiResources.apk`, genuinely present and correctly built at
`/apex/com.android.wifi/priv-app/ServiceWifiResources/ServiceWifiResources.apk` -- confirmed
directly on the device) via `queryIntentActivities()`, then filters the results with exactly one
check, this file's own `isAppInWifiApex()`:

    return appInfo.sourceDir.startsWith("/apex/com.android.wifi");

First fix attempt tonight copied the APK out to `/system/priv-app/` (the exact same technique
§59 already used successfully for `PermissionController.apk`, for the same underlying reason:
`ApexManagerFlattenedApex` -- the fallback this apexd-less hybris environment actually exercises
-- returns an empty package list unconditionally, so nothing with a real `/apex/...` `sourceDir`
is ever scanned by PackageManagerService at all). That fix does NOT work for the wifi resources
package specifically, and cannot: this exact `isAppInWifiApex()` check exists precisely to reject
a package installed anywhere other than the real APEX path, which is exactly where a copied-out
APK ends up. Confirmed via a second logcat capture after deploying the copy: byte-for-byte the
same crash, same stack trace.

Real fix belongs in `ApexManagerFlattenedApex` (make it actually scan `/apex/*/priv-app/` so
packages get a genuine `/apex/...` `sourceDir`), which is a bigger, more invasive change. This
patch takes the narrower, low-risk option instead: this device's PackageManagerService can never
have two competing candidates for the wifi resources package (one genuine-APEX, one an impostor)
to disambiguate between -- there is only ever the one, wherever it's actually scanned from -- so
the check has no protective value here and can simply be bypassed. Paired with copying
`ServiceWifiResources.apk` into `/system/priv-app/` the same way `droid-hal-prepare.sh` already
does for `PermissionController.apk` (§59).

Idempotent. Run from the root of this AOSP source tree (needs
`frameworks/opt/net/wifi/service/java/com/android/server/wifi/util/Environment.java`
underneath), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
env_java = root / 'frameworks/opt/net/wifi/service/java/com/android/server/wifi/util/Environment.java'
if not env_java.is_file():
    sys.exit(f'not found: {env_java}')

s = env_java.read_text()
MARK = '// lilac: no real apexd here -- this device can never have a'

if MARK in s:
    print('already patched')
    sys.exit(0)

old = (
    '    public static boolean isAppInWifiApex(ApplicationInfo appInfo) {\n'
    '        return appInfo.sourceDir.startsWith(WIFI_APEX_PATH);\n'
    '    }\n'
)
new = (
    '    public static boolean isAppInWifiApex(ApplicationInfo appInfo) {\n'
    f'        {MARK}\n'
    '        // genuine-APEX package to confuse with an impostor competing for the same intent\n'
    '        // filter -- ApexManagerFlattenedApex never scans /apex/*/priv-app/ here, so nothing\n'
    '        // installed ever has a real /apex/... sourceDir, and this check would otherwise\n'
    '        // reject ServiceWifiResources.apk unconditionally and fatally crash-loop\n'
    '        // system_server every ~15s in WifiService\'s constructor.\n'
    '        // was: return appInfo.sourceDir.startsWith(WIFI_APEX_PATH);\n'
    '        return true;\n'
    '    }\n'
)

if s.count(old) != 1:
    sys.exit(f'anchor not found or not unique, tree changed (found {s.count(old)} times)')

env_java.write_text(s.replace(old, new, 1))
print(f'patched {env_java}: isAppInWifiApex() now unconditionally true')
