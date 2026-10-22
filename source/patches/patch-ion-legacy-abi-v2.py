#!/usr/bin/env python3
"""Install the legacy ION ioctl ABI into the 4.14 kernel.

msm8998's vendor blobs allocate through the pre-4.12 ION ABI. 4.14 replaced it:
allocation now returns a dma_buf fd directly, and the opaque per-client
`ion_user_handle_t` and its ioctls are gone. Because _IOWR() encodes sizeof()
into the command number, the two ABIs generate *different ioctl numbers*, so the
blobs' calls do not merely misbehave -- 4.14's dispatcher rejects them on its
first line:

    ioctl(5, _IOC(_IOC_READ|_IOC_WRITE, 0x49, 0, 0x20), ...) = -1 EINVAL

`_IOC_SIZE(cmd) > sizeof(union ion_ioctl_arg)` is 32 > 24. That single EINVAL is
the whole black screen: it fails qdgralloc's AllocateMem, which returns
GRALLOC1_ERROR_NO_RESOURCES, which arrives in libhybris as ret=5 with a NULL
handle, which Adreno reports as "Buffer has a NULL handle".

This adds ion_legacy.{c,h} and wires them in at four points:

  1. ion-ioctl.c  -- claim legacy commands BEFORE the size guard that rejects
                     them. This has to come first in ion_ioctl(), because the
                     guard is what returns EINVAL today.
  2. ion.c        -- .open/.release on ion_fops, for the per-open handle table.
                     4.14's ion_fops has neither and leaves filp->private_data
                     unused, so there is nothing to collide with.
  3. ion.h        -- export ion_alloc_dmabuf(), which ion.c defines but does not
                     declare; it is the same entry point ion_alloc_fd() uses.
  4. Makefile     -- build it.

Deliberately NOT behind a Kconfig symbol. 10.142 was exactly the failure mode of
an ION feature that silently was not compiled in, and the whole point of this
file is that this device cannot work without it.

Idempotent. Run from the 4.14 kernel root, or pass argv[1]. The ion_legacy.c and
ion_legacy.h sources live in patches/ion-legacy/ next to this script.
"""
import pathlib
import shutil
import sys

root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('.')
ion = root / 'drivers/staging/android/ion'
src = pathlib.Path(__file__).resolve().parent / 'ion-legacy'

if not ion.is_dir():
    sys.exit(f'not an ION tree: {ion}')
for f in ('ion.c', 'ion.h', 'ion-ioctl.c', 'Makefile'):
    if not (ion / f).is_file():
        sys.exit(f'missing {ion / f} -- re-derive against the current tree')

changed = []


def edit(name, old, new, why):
    """Replace `old` with `new` in ion/<name>, or report it is already done."""
    p = ion / name
    s = p.read_text()
    if new in s:
        print(f'  {name}: already patched ({why})')
        return
    if old not in s:
        sys.exit(f'{name}: anchor not found for {why} -- re-derive:\n{old!r}')
    p.write_text(s.replace(old, new, 1))
    changed.append(name)
    print(f'  {name}: {why}')


# ---- 0. the sources themselves ------------------------------------------
for f in ('ion_legacy.c', 'ion_legacy.h'):
    s = (src / f).read_text()
    dst = ion / f
    if dst.is_file() and dst.read_text() == s:
        print(f'  {f}: already installed')
    else:
        shutil.copyfile(src / f, dst)
        changed.append(f)
        print(f'  {f}: installed ({len(s.splitlines())} lines)')

# ---- 1. dispatch, ahead of the size guard -------------------------------
edit('ion-ioctl.c',
     '#include "ion.h"\n#include "ion_system_secure_heap.h"',
     '#include "ion.h"\n#include "ion_legacy.h"\n'
     '#include "ion_system_secure_heap.h"',
     'include ion_legacy.h')

edit('ion-ioctl.c',
     '''	int ret = 0;
	unsigned int dir;
	union ion_ioctl_arg data;

	dir = ion_ioctl_dir(cmd);''',
     '''	int ret = 0;
	unsigned int dir;
	union ion_ioctl_arg data;

	/*
	 * The pre-4.12 ABI, which the msm8998 vendor blobs still speak. This
	 * MUST be tested before the size guard below: the legacy ALLOC carries a
	 * 32-byte struct against this union's 24, so the guard is exactly what
	 * turns it into -EINVAL today. The smaller legacy commands would instead
	 * fall out of the switch as -ENOTTY. Either way they never reach their
	 * implementation without this.
	 */
	if (ion_legacy_is_legacy_cmd(cmd))
		return ion_legacy_ioctl(filp, cmd, arg);

	dir = ion_ioctl_dir(cmd);''',
     'dispatch legacy commands before the size guard')

# ---- 2. per-open handle table -------------------------------------------
edit('ion.c',
     '#include "ion.h"',
     '#include "ion.h"\n#include "ion_legacy.h"',
     'include ion_legacy.h')

edit('ion.c',
     '''static const struct file_operations ion_fops = {
	.owner          = THIS_MODULE,
	.unlocked_ioctl = ion_ioctl,''',
     '''static const struct file_operations ion_fops = {
	.owner          = THIS_MODULE,
	/*
	 * The legacy ABI scopes its handles to the open file, so every open of
	 * /dev/ion needs a table. 4.14 had neither hook and left private_data
	 * unused, so nothing here displaces existing behaviour.
	 */
	.open           = ion_legacy_open,
	.release        = ion_legacy_release,
	.unlocked_ioctl = ion_ioctl,''',
     'open/release for the handle table')

# ---- 3. ion_alloc_dmabuf is defined but not declared --------------------
edit('ion.h',
     'int ion_alloc_fd(size_t len, unsigned int heap_id_mask, unsigned int flags);',
     '''int ion_alloc_fd(size_t len, unsigned int heap_id_mask, unsigned int flags);

/*
 * Defined in ion.c and used by ion_alloc_fd(), but never declared in a header.
 * The legacy ABI needs the dma_buf itself rather than an fd, and this is the
 * same entry point the modern allocation takes -- unlike ion_alloc(), which
 * rejects every heap type but SYSTEM/HYP_CMA/SYSTEM_SECURE.
 */
struct dma_buf;
struct dma_buf *ion_alloc_dmabuf(size_t len, unsigned int heap_id_mask,
				 unsigned int flags);''',
     'declare ion_alloc_dmabuf')

# ---- 4. build it --------------------------------------------------------
edit('Makefile',
     'obj-$(CONFIG_ION) +=\tion.o ion-ioctl.o ion_heap.o \\',
     'obj-$(CONFIG_ION) +=\tion.o ion-ioctl.o ion_heap.o ion_legacy.o \\',
     'build ion_legacy.o')

print()
print('changed: ' + (', '.join(changed) if changed else 'nothing (already applied)'))
