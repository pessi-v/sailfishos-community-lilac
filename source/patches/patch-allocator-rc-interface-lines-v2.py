#!/usr/bin/env python3
"""
Add the missing `interface <fqname> <instance>` declarations to our vendor.img's real
display-allocator service .rc, so hwservicemanager's lazy on-demand HAL activation
(ctl.interface_start) can actually find and launch it.

Root cause, `lipstick`'s main thread polls
`android.hardware.graphics.allocator@3.0::IAllocator/default` forever (strace-confirmed)
because nothing ever starts the real provider, `vendor.qti.hardware.display.allocator`
(vendor/qcom/opensource/display/sm8150/gralloc/
vendor.qti.hardware.display.allocator-service.rc) -- its own .rc has zero `interface` lines
at all, so hwservicemanager has nothing to lazily trigger on. Manually launching the binary
by hand confirmed it genuinely does provide `IAllocator@3.0` at runtime (HIDL's own
interface-inheritance machinery registers the base interface alongside the vendor's own
derived `IQtiAllocator` one, transparently -- the binary's own exported-symbol table only
shows the derived name, which is the wrong place to look for this).

Same fix, same reasoning, and the same real-AOSP mechanism as section 30's own
patch-composer-rc-interface-lines-v2.py: declaring `interface` lines for every version the
binary can plausibly satisfy (both the generic AOSP `IAllocator` interface real clients like
`lipstick` actually ask for, and the vendor's own `IQtiAllocator` versions, matching what its
symbol table shows it implements) lets hwservicemanager's `ctl.interface_start` route any of
those requests to this one binary.
"""
import sys

HADK = sys.argv[1] if len(sys.argv) > 1 else '.'

path = (HADK + '/vendor/qcom/opensource/display/sm8150/gralloc/'
        'vendor.qti.hardware.display.allocator-service.rc')

old = """service vendor.qti.hardware.display.allocator /vendor/bin/hw/vendor.qti.hardware.display.allocator-service
    class hal animation
"""
new = """service vendor.qti.hardware.display.allocator /vendor/bin/hw/vendor.qti.hardware.display.allocator-service
    interface android.hardware.graphics.allocator@2.0::IAllocator default
    interface android.hardware.graphics.allocator@3.0::IAllocator default
    interface vendor.qti.hardware.display.allocator@1.0::IQtiAllocator default
    interface vendor.qti.hardware.display.allocator@1.1::IQtiAllocator default
    interface vendor.qti.hardware.display.allocator@2.0::IQtiAllocator default
    interface vendor.qti.hardware.display.allocator@3.0::IQtiAllocator default
    class hal animation
"""

src = open(path).read()
if src.count(old) != 1:
    print('ANCHOR MISS in %s' % path)
    sys.exit(1)
open(path, 'w').write(src.replace(old, new))
print('patched %s' % path)
