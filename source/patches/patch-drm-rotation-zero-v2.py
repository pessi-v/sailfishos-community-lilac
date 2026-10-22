#!/usr/bin/env python3
"""Accept rotation=0 as ROTATE_0 in atomic commits.

With ION fixed (10.147), SDM's atomic commit still failed with EINVAL and the
CRTC was never programmed -- backlight on, nothing drawn. Instrumenting
drm_mode_atomic_ioctl named the culprit exactly:

    lilac: atomic set_property failed: obj 102 type 0xeeeeeeee prop 103
           "rotation" value 0x0 -> -22

i.e. setting `rotation = 0` on a plane. 4.14's core does:

    } else if (property == plane->rotation_property) {
            if (!is_power_of_2(val & DRM_MODE_ROTATE_MASK))
                    return -EINVAL;

The DRM ABI wants exactly one rotate bit set, and "no rotation" is
DRM_MODE_ROTATE_0 (== 1), not 0. is_power_of_2(0) is false, so 0 is refused.

The blob is not misbehaving by its own lights: 4.4's drm_atomic.c has NO such
check --

    } else if (property == config->rotation_property) {
            state->rotation = val;

-- so msm8998's Android 9 SDM was never taught the distinction, and 0 has always
meant "none" to it. The check was added upstream after 4.4, alongside the
DRM_ROTATE_* -> DRM_MODE_ROTATE_* rename.

So: read a value with no rotate bits as ROTATE_0, which is precisely what the
caller means, and keep rejecting genuinely ambiguous multi-bit values. This is a
narrower change than dropping the check, and it restores 4.4's accepted
behaviour for exactly the case that occurs.

Idempotent. Run from the 4.14 kernel root, or pass argv[1].
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
p = root / 'drivers/gpu/drm/drm_atomic.c'
if not p.is_file():
    sys.exit(f'not found: {p}')

s = p.read_text()
# Test for the actual code change, NOT a section marker: the 10.148 DIAGNOSTIC
# patch also mentions "lilac 10.148" in this same file, and guarding on that
# string made this script report "already patched" and silently do nothing.
if 'if (!(val & DRM_MODE_ROTATE_MASK))' in s:
    print('already patched')
    sys.exit(0)

old = """	} else if (property == plane->rotation_property) {
		if (!is_power_of_2(val & DRM_MODE_ROTATE_MASK))
			return -EINVAL;
		state->rotation = val;"""

new = """	} else if (property == plane->rotation_property) {
		/*
		 * lilac 10.148: msm8998's Android 9 SDM sends rotation=0 to
		 * mean "no rotation". The ABI spells that DRM_MODE_ROTATE_0
		 * (== 1) and wants exactly one rotate bit, so is_power_of_2(0)
		 * refuses it and the whole atomic commit fails EINVAL -- which
		 * is why the display was never programmed at all.
		 *
		 * 4.4, which these blobs were built against, had no check here
		 * and simply stored the value, so the distinction was never
		 * forced on them. Read "no bits" as ROTATE_0, which is what the
		 * caller means; ambiguous multi-bit values are still refused.
		 */
		if (!(val & DRM_MODE_ROTATE_MASK))
			val |= DRM_MODE_ROTATE_0;
		if (!is_power_of_2(val & DRM_MODE_ROTATE_MASK))
			return -EINVAL;
		state->rotation = val;"""

if old not in s:
    sys.exit('anchor not found in drm_atomic_plane_set_property -- re-derive')

p.write_text(s.replace(old, new, 1))
print(f'patched {p}: rotation=0 now means ROTATE_0')
