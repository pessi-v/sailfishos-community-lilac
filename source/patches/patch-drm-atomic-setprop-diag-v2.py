#!/usr/bin/env python3
"""DIAGNOSTIC: name the property that makes an atomic commit fail with EINVAL.

Ported from the first port's own patch-drm-atomic-setprop-diag-414.py
 -- our own from-source kernel already has the
rotation=0 fix baked in (patch-drm-rotation-zero-v2.py), yet the DRM connector
still never goes active (/sys/class/drm/card0-DSI-1/enabled stays "disabled",
crtc-0 stays enable=0/active=0, every plane stays crtc=(null)/fb=0 -- checked
directly via /sys/kernel/debug/dri/0/state) even with lipstick and a real
Wayland client both genuinely rendering. Since dmesg shows zero EINVAL/atomic
errors at all, whatever's failing now is being swallowed exactly the same way
the first port's own rotation bug was, before they added this instrumentation.

In drm_mode_atomic_ioctl's property-setting loop, only one path returns
EINVAL: drm_atomic_set_property(). This adds one ratelimited DRM_ERROR on that
path, naming the object/property/value that failed -- the same technique, the
same anchor, applied fresh since we don't yet know what (if anything) is still
being rejected here.

⚠️ DIAGNOSTIC ONLY -- logs on a path any misbehaving userspace can legitimately
hit, not just ours; does not belong in a shipping kernel. Revert with --revert
once the failing property (if any) is identified, the same way the first port
did.

Idempotent both ways. Run from the 4.14 kernel root, or pass the root as an
argument.
"""
import pathlib
import sys

args = [a for a in sys.argv[1:] if a != '--revert']
revert = '--revert' in sys.argv[1:]
root = pathlib.Path(args[0]) if args else pathlib.Path('.')
p = root / 'drivers/gpu/drm/drm_atomic.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
if 'lilac-v2 41: this is the only EINVAL' in s and not revert:
    print('already patched')
    sys.exit(0)

old = """			ret = drm_atomic_set_property(state, obj, prop,
						      prop_value);
			if (ret) {
				drm_mode_object_put(obj);
				goto out;
			}"""

new = """			ret = drm_atomic_set_property(state, obj, prop,
						      prop_value);
			if (ret) {
				/*
				 * lilac-v2 41: this is the only EINVAL in this
				 * loop and the kernel otherwise says nothing,
				 * which is why the DRM connector never going
				 * active has been opaque.
				 * Ratelimited: userspace retries
				 * the commit repeatedly.
				 */
				DRM_ERROR_RATELIMITED(
					"lilac-v2: atomic set_property failed: obj %u type 0x%x prop %u \\"%s\\" value 0x%llx -> %d\\n",
					obj->id, obj->type, prop->base.id,
					prop->name, prop_value, ret);
				drm_mode_object_put(obj);
				goto out;
			}"""

if revert:
    if new not in s:
        print('not applied; nothing to revert')
        sys.exit(0)
    p.write_text(s.replace(new, old, 1))
    print(f'reverted {p}: diagnostic removed, rotation fix untouched')
    sys.exit(0)

if old not in s:
    sys.exit('anchor not found in drm_mode_atomic_ioctl -- re-derive')

p.write_text(s.replace(old, new, 1))
print(f'patched {p}: name the failing atomic property')
