#!/usr/bin/env python3
"""Let the `sphal` linker namespace pull in `libbinder.so`, so `lipstick` can actually load
`hwcomposer.msm8998.so` (direct continuation of the
`WifiService` fix -- fixing that crash let boot progress far enough to expose this next, real,
previously-hidden bug: `lipstick`'s own compositor crash loop, which is why an Android system
dialog was visible on screen instead of Sailfish's own UI -- `lipstick` never wins the display).

Root cause, read directly off the live journal (not guessed):

    lipstick[NNNNN]: library "libbinder.so" not found
    lipstick[NNNNN]: failed to create composer client
    (SIGABRT, every single launch attempt)

and, from the matching logcat capture at the same timestamp/pid:

    vndksupport: Could not load /vendor/lib64/hw/hwcomposer.msm8998.so from sphal namespace:
      dlopen failed: .

Confirmed directly with `readelf -d` against the actual built blob
(out/target/product/lilac/vendor/lib64/hw/hwcomposer.msm8998.so): `libbinder.so` is a genuine,
direct `NEEDED` entry -- this is a pre-Treble-style HWC1 blob that talks binder IPC itself
rather than going through a stable HIDL/AIDL passthrough boundary, so it depends on the
framework's own `libbinder.so` directly, which real VNDK/SP-HAL policy deliberately never
exposes to vendor code (`system/linkerconfig/contents/namespace/sphal.cc`'s own comment: this
namespace only ever links `LLNDK_LIBRARIES_VENDOR` and `VNDK_SAMEPROCESS_LIBRARIES_VENDOR` to
the default/vndk namespaces -- neither list has ever included `libbinder.so`, on purpose).
`SurfaceFlinger` loads the exact same `.so` successfully because it's a genuine Android system
process with its own, unrestricted route to `libbinder.so` -- `lipstick`, reached entirely
through libhybris's own `android_load_sphal_library()` (the API a non-Android process like this
one must use to load a vendor SP-HAL directly), gets the fully-restricted `sphal` namespace and
has no such route.

Real fix belongs upstream in this specific vendor blob (rebuild it against the stable HIDL
composer interface instead of raw binder) -- not something this project can do, it's a closed-
source Sony prebuilt. This device can never have a second, competing consumer of `libbinder.so`
inside the `sphal` namespace to worry about isolating from, so explicitly widening the two
existing allow-lists this narrowly (one more named library, not a wildcard) carries no real
downside here. Patches both the ApexBinaryConfig/VNDK-available branch and the plain (non-APEX,
almost certainly the one that actually governs a foreign, non-`/system`, non-`/vendor` binary
like `/usr/bin/lipstick`) branch, since which one governs `lipstick`'s own linker config section
was not independently confirmed live before this patch was written -- covering both is safe
either way, since dlopen requests are per-library-name and nothing else will exercise this path.

Idempotent. Run from the root of this AOSP source tree (needs
`system/linkerconfig/contents/namespace/sphal.cc` underneath), or pass that root as argv[1].
"""
import sys, pathlib

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
sphal_cc = root / 'system/linkerconfig/contents/namespace/sphal.cc'
if not sphal_cc.is_file():
    sys.exit(f'not found: {sphal_cc}')

s = sphal_cc.read_text()
MARK = '// lilac: hwcomposer.msm8998.so is a pre-Treble HWC1 blob'

if MARK in s:
    print('already patched')
    sys.exit(0)

old_apex = (
    '      ns.GetLink("vndk").AddSharedLib(\n'
    '          Var("VNDK_SAMEPROCESS_LIBRARIES_VENDOR", ""));\n'
    '      ns.GetLink(ctx.GetSystemNamespaceName())\n'
    '          .AddSharedLib(Var("LLNDK_LIBRARIES_VENDOR", ""));\n'
    '    }\n'
    '  } else {\n'
)
new_apex = (
    '      ns.GetLink("vndk").AddSharedLib(\n'
    '          Var("VNDK_SAMEPROCESS_LIBRARIES_VENDOR", ""));\n'
    '      ns.GetLink(ctx.GetSystemNamespaceName())\n'
    '          .AddSharedLib(Var("LLNDK_LIBRARIES_VENDOR", ""));\n'
    f'      {MARK} that\n'
    '      // directly needs libbinder.so, which is never in LLNDK/VNDK-SP on purpose --\n'
    '      // widened narrowly (one named library) so lipstick can load it via libhybris.\n'
    '      ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("libbinder.so");\n'
    '    }\n'
    '  } else {\n'
)

old_else = (
    '    ns.GetLink(ctx.GetSystemNamespaceName())\n'
    '        .AddSharedLib(Var("LLNDK_LIBRARIES_VENDOR", ""));\n'
    '    ns.GetLink("vndk").AddSharedLib(\n'
    '        Var("VNDK_SAMEPROCESS_LIBRARIES_VENDOR", ""));\n'
    '    ns.AddRequires(std::vector{"libneuralnetworks.so"});\n'
)
new_else = (
    '    ns.GetLink(ctx.GetSystemNamespaceName())\n'
    '        .AddSharedLib(Var("LLNDK_LIBRARIES_VENDOR", ""));\n'
    f'    {MARK}, same widening as above, in whichever branch\n'
    "    // actually governs a foreign (non-/system, non-/vendor) binary like lipstick.\n"
    '    ns.GetLink(ctx.GetSystemNamespaceName()).AddSharedLib("libbinder.so");\n'
    '    ns.GetLink("vndk").AddSharedLib(\n'
    '        Var("VNDK_SAMEPROCESS_LIBRARIES_VENDOR", ""));\n'
    '    ns.AddRequires(std::vector{"libneuralnetworks.so"});\n'
)

for old, new, label in ((old_apex, new_apex, 'apex/vndk-available branch'),
                        (old_else, new_else, 'plain (non-apex) branch')):
    if s.count(old) != 1:
        sys.exit(f'anchor not found or not unique for {label} (found {s.count(old)} times), tree changed')
    s = s.replace(old, new, 1)

sphal_cc.write_text(s)
print(f'patched {sphal_cc}: sphal namespace now also links libbinder.so, both branches')
