/* SPDX-License-Identifier: GPL-2.0 */
/*
 * The pre-4.12 ("legacy") ION ioctl ABI, for vendor blobs compiled against it.
 *
 * msm8998's Android 9 blobs -- gralloc, camera, video,
 * audio, everything that allocates -- speak the ION ABI that 4.4 had. 4.14
 * replaced it wholesale: allocation now returns a dma_buf fd directly, and the
 * opaque per-client `ion_user_handle_t` and its ioctls are gone.
 *
 * _IOWR() encodes sizeof(struct) into the command number, so the two ABIs do
 * not merely differ in behaviour, they produce *different ioctl numbers*, and
 * 4.14's dispatcher rejects the old ones before it even looks at the command:
 *
 *     ioctl(5, _IOC(_IOC_READ|_IOC_WRITE, 0x49, 0, 0x20), ...) = -1 EINVAL
 *
 * because `_IOC_SIZE(cmd) > sizeof(union ion_ioctl_arg)` is 32 > 24.
 *
 * The structs below are therefore spelled with fixed-width types chosen to
 * reproduce the 4.4 layouts exactly, not to be pretty:
 *
 *   4.4:  struct ion_allocation_data { size_t len; size_t align;
 *                                      unsigned int heap_id_mask;
 *                                      unsigned int flags;
 *                                      ion_user_handle_t handle; };
 *
 * On LP64 that is 8+8+4+4+4 padded to 32; on ILP32 it is 20. A 32-bit caller
 * therefore issues a *different* command for the same operation, which is why
 * the 32-bit variants below exist rather than being folded in. (`compat_ioctl`
 * points at the same dispatcher, so both arrive here.)
 */
#ifndef _ION_LEGACY_H
#define _ION_LEGACY_H

#include <linux/fs.h>
#include <linux/types.h>

typedef int ion_user_handle_t;

struct ion_legacy_allocation_data {
	__u64 len;
	__u64 align;
	__u32 heap_id_mask;
	__u32 flags;
	ion_user_handle_t handle;
};

struct ion_legacy_allocation_data32 {
	__u32 len;
	__u32 align;
	__u32 heap_id_mask;
	__u32 flags;
	ion_user_handle_t handle;
};

struct ion_legacy_handle_data {
	ion_user_handle_t handle;
};

struct ion_legacy_fd_data {
	ion_user_handle_t handle;
	int fd;
};

struct ion_legacy_custom_data {
	__u32 cmd;
	__aligned_u64 arg;
};

struct ion_legacy_custom_data32 {
	__u32 cmd;
	__u32 arg;
};

/* msm cache-maintenance payload, reached through ION_IOC_CUSTOM */
struct ion_legacy_flush_data {
	ion_user_handle_t handle;
	int fd;
	__aligned_u64 vaddr;
	__u32 offset;
	__u32 length;
};

struct ion_legacy_flush_data32 {
	ion_user_handle_t handle;
	int fd;
	__u32 vaddr;
	__u32 offset;
	__u32 length;
};

#define ION_LEGACY_IOC_MAGIC		'I'
#define ION_LEGACY_IOC_MSM_MAGIC	'M'

/*
 * nr 0 collides with 4.14's ION_IOC_ALLOC *by number only* -- the sizes differ
 * (32/20 vs 24), so the full commands are distinct. 4.14 uses nr 8 for
 * HEAP_QUERY and 'M' nr 3/4 for PREFETCH/DRAIN; nrs 1,2,4,5,6,7 are unused
 * there, so nothing below can shadow a live command.
 */
#define ION_LEGACY_IOC_ALLOC \
	_IOWR(ION_LEGACY_IOC_MAGIC, 0, struct ion_legacy_allocation_data)
#define ION_LEGACY_IOC_ALLOC32 \
	_IOWR(ION_LEGACY_IOC_MAGIC, 0, struct ion_legacy_allocation_data32)
#define ION_LEGACY_IOC_FREE \
	_IOWR(ION_LEGACY_IOC_MAGIC, 1, struct ion_legacy_handle_data)
#define ION_LEGACY_IOC_MAP \
	_IOWR(ION_LEGACY_IOC_MAGIC, 2, struct ion_legacy_fd_data)
#define ION_LEGACY_IOC_SHARE \
	_IOWR(ION_LEGACY_IOC_MAGIC, 4, struct ion_legacy_fd_data)
#define ION_LEGACY_IOC_IMPORT \
	_IOWR(ION_LEGACY_IOC_MAGIC, 5, struct ion_legacy_fd_data)
#define ION_LEGACY_IOC_CUSTOM \
	_IOWR(ION_LEGACY_IOC_MAGIC, 6, struct ion_legacy_custom_data)
#define ION_LEGACY_IOC_CUSTOM32 \
	_IOWR(ION_LEGACY_IOC_MAGIC, 6, struct ion_legacy_custom_data32)
#define ION_LEGACY_IOC_SYNC \
	_IOWR(ION_LEGACY_IOC_MAGIC, 7, struct ion_legacy_fd_data)

/* ION_IOC_CUSTOM sub-commands */
#define ION_LEGACY_IOC_CLEAN_CACHES \
	_IOWR(ION_LEGACY_IOC_MSM_MAGIC, 0, struct ion_legacy_flush_data)
#define ION_LEGACY_IOC_INV_CACHES \
	_IOWR(ION_LEGACY_IOC_MSM_MAGIC, 1, struct ion_legacy_flush_data)
#define ION_LEGACY_IOC_CLEAN_INV_CACHES \
	_IOWR(ION_LEGACY_IOC_MSM_MAGIC, 2, struct ion_legacy_flush_data)
#define ION_LEGACY_IOC_CLEAN_CACHES32 \
	_IOWR(ION_LEGACY_IOC_MSM_MAGIC, 0, struct ion_legacy_flush_data32)
#define ION_LEGACY_IOC_INV_CACHES32 \
	_IOWR(ION_LEGACY_IOC_MSM_MAGIC, 1, struct ion_legacy_flush_data32)
#define ION_LEGACY_IOC_CLEAN_INV_CACHES32 \
	_IOWR(ION_LEGACY_IOC_MSM_MAGIC, 2, struct ion_legacy_flush_data32)

/**
 * ion_legacy_is_legacy_cmd - does this command belong to the pre-4.12 ABI?
 *
 * Must be consulted by ion_ioctl() *before* its `_IOC_SIZE(cmd) > sizeof(data)`
 * guard, which is what currently turns the blobs' ALLOC into -EINVAL. The
 * smaller legacy commands would otherwise reach the switch and fall out of it
 * as -ENOTTY, so every one of them has to be claimed here.
 */
static inline bool ion_legacy_is_legacy_cmd(unsigned int cmd)
{
	if (_IOC_TYPE(cmd) != ION_LEGACY_IOC_MAGIC)
		return false;

	switch (cmd) {
	case ION_LEGACY_IOC_ALLOC:
	case ION_LEGACY_IOC_ALLOC32:
	case ION_LEGACY_IOC_FREE:
	case ION_LEGACY_IOC_MAP:
	case ION_LEGACY_IOC_SHARE:
	case ION_LEGACY_IOC_IMPORT:
	case ION_LEGACY_IOC_SYNC:
	case ION_LEGACY_IOC_CUSTOM:
	case ION_LEGACY_IOC_CUSTOM32:
		return true;
	default:
		return false;
	}
}

long ion_legacy_ioctl(struct file *filp, unsigned int cmd, unsigned long arg);
int ion_legacy_open(struct inode *inode, struct file *filp);
int ion_legacy_release(struct inode *inode, struct file *filp);

#endif /* _ION_LEGACY_H */
