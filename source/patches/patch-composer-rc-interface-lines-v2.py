#!/usr/bin/env python3
"""
Add the missing `interface <fqname> <instance>` declarations to our vendor.img's real
composer service .rc, so hwservicemanager's lazy on-demand HAL activation
(ctl.interface_start) can actually find and launch it.

Root cause, `lipstick`'s hwcomposer bridge polls
`android.hardware.graphics.composer@2.1::IComposer/default` forever
(strace-confirmed, section 29) because nothing ever starts the real provider,
`vendor.hwcomposer-2-3` (hardware/interfaces/graphics/composer/2.3/default/
android.hardware.graphics.composer@2.3-service.rc) -- confirmed directly in dmesg:
`hwservicemanager: Control message: Could not find
'android.hardware.graphics.composer@2.1::IComposer/default' for ctl.interface_start`,
repeating once a second, forever.

This is *not* a `class_start hal`/`class_start core` problem after all -- extensive
debug-instrumented testing (section 30) proved neither of those `.rc` commands ever fires
at all in this hybris-patched init, under *either* vendor. Real AOSP's actual mechanism
for starting most HAL daemons is the lazy, interface-triggered `ctl.interface_start`
control message hwservicemanager itself issues the moment a client asks for a service
that isn't running yet -- and init only knows how to route that request to a real
service if that service's own `.rc` declares a matching `interface <fqname> <instance>`
line. The real Sony stock /vendor's own composer@2.1-service.rc has exactly this line;
our own from-source vendor.img's composer@2.3-service.rc has none at all.

The fix is standard, real-AOSP practice, not a hybris-specific workaround: HIDL's
IComposer@2.3 interface extends 2.2, which extends 2.1 -- a single 2.3-built binary is a
valid, real implementation of all three, and declaring `interface` lines for each lets
older clients (like this build's own /system side, built against the older
mer-hybris Android-11 manifest, expecting 2.1) reach the same real service.
"""
import sys

HADK = sys.argv[1] if len(sys.argv) > 1 else '.'

path = (HADK + '/hardware/interfaces/graphics/composer/2.3/default/'
        'android.hardware.graphics.composer@2.3-service.rc')

old = """service vendor.hwcomposer-2-3 /vendor/bin/hw/android.hardware.graphics.composer@2.3-service
    class hal animation
"""
new = """service vendor.hwcomposer-2-3 /vendor/bin/hw/android.hardware.graphics.composer@2.3-service
    interface android.hardware.graphics.composer@2.1::IComposer default
    interface android.hardware.graphics.composer@2.2::IComposer default
    interface android.hardware.graphics.composer@2.3::IComposer default
    class hal animation
"""

src = open(path).read()
if src.count(old) != 1:
    print('ANCHOR MISS in %s' % path)
    sys.exit(1)
open(path, 'w').write(src.replace(old, new))
print('patched %s' % path)
