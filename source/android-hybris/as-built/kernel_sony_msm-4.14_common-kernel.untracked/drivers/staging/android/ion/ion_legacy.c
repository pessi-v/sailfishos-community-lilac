// SPDX-License-Identifier: GPL-2.0
/*
 * The pre-4.12 ION ioctl ABI, reimplemented on top of 4.14's dma_buf-fd ION.
 *
 *
 *
 * The two ABIs differ in their object model, not just their structs. 4.4 handed
 * userspace an opaque per-client `ion_user_handle_t` and made it ask separately
 * for a shareable fd; 4.14 returns the dma_buf fd from the allocation itself and
 * has no handles at all. So this is not a struct-shuffling shim: it has to
 * re-create the handle namespace, which is what the per-open idr below is.
 *
 * The mapping is:
 *
 *     legacy handle  ->  struct dma_buf *   (one reference held by the table)
 *
 * ALLOC   allocate a dma_buf, park it in the table, return its handle
 * IMPORT  dma_buf_get(fd), park it, return a handle
 * MAP     look the handle up, hand out an fd for the same dma_buf
 * SHARE   identical to MAP in the legacy ABI -- both just produce an fd
 * FREE    drop the table's reference
 * SYNC    the CPU-access bracket, which is where 4.14 put cache maintenance
 * CUSTOM  msm's CLEAN/INV/CLEAN_INV cache ops
 *
 * The refcounting is the part worth being careful about, and it is commented
 * where it happens.
 */

#include <linux/dma-buf.h>
#include <linux/dma-direction.h>
#include <linux/err.h>
#include <linux/fs.h>
#include <linux/idr.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/uaccess.h>

#include "ion.h"
#include "ion_legacy.h"

/**
 * struct ion_legacy_client - the handle namespace for one open of /dev/ion
 *
 * The legacy ABI scoped handles to the open file, and blobs rely on that: two
 * processes may hold the same handle value meaning different buffers. So this
 * hangs off filp->private_data, which 4.14's ion leaves unused.
 */
struct ion_legacy_client {
	struct idr handles;
	struct mutex lock;
};

int ion_legacy_open(struct inode *inode, struct file *filp)
{
	struct ion_legacy_client *client;

	client = kzalloc(sizeof(*client), GFP_KERNEL);
	if (!client)
		return -ENOMEM;

	idr_init(&client->handles);
	mutex_init(&client->lock);
	filp->private_data = client;

	return 0;
}

int ion_legacy_release(struct inode *inode, struct file *filp)
{
	struct ion_legacy_client *client = filp->private_data;
	struct dma_buf *dmabuf;
	int id;

	if (!client)
		return 0;

	/*
	 * 4.4 cleaned a client's handles up on close and callers depend on it --
	 * gralloc, for one, leaks handles deliberately on some error paths.
	 * Anything still in the table owns a dma_buf reference that nothing else
	 * will ever drop, so this is not optional tidiness.
	 */
	mutex_lock(&client->lock);
	idr_for_each_entry(&client->handles, dmabuf, id)
		dma_buf_put(dmabuf);
	idr_destroy(&client->handles);
	mutex_unlock(&client->lock);

	mutex_destroy(&client->lock);
	kfree(client);
	filp->private_data = NULL;

	return 0;
}

static struct dma_buf *ion_legacy_lookup(struct ion_legacy_client *client,
					 ion_user_handle_t handle)
{
	struct dma_buf *dmabuf;

	mutex_lock(&client->lock);
	dmabuf = idr_find(&client->handles, handle);
	mutex_unlock(&client->lock);

	return dmabuf;
}

static int ion_legacy_insert(struct ion_legacy_client *client,
			     struct dma_buf *dmabuf)
{
	int id;

	mutex_lock(&client->lock);
	/* 0 is the legacy ABI's "no handle", so ids start at 1 */
	id = idr_alloc(&client->handles, dmabuf, 1, 0, GFP_KERNEL);
	mutex_unlock(&client->lock);

	return id;
}

static int ion_legacy_drop(struct ion_legacy_client *client,
			   ion_user_handle_t handle)
{
	struct dma_buf *dmabuf;

	mutex_lock(&client->lock);
	dmabuf = idr_remove(&client->handles, handle);
	mutex_unlock(&client->lock);

	if (!dmabuf)
		return -EINVAL;

	dma_buf_put(dmabuf);

	return 0;
}

static int ion_legacy_do_alloc(struct ion_legacy_client *client, u64 len,
			       u32 heap_id_mask, u32 flags,
			       ion_user_handle_t *out_handle)
{
	struct dma_buf *dmabuf;
	int id;

	/*
	 * @align is accepted and ignored. 4.12 dropped it from the ABI and no
	 * 4.14 heap honours it; the callers here pass the page size, which the
	 * allocator already guarantees.
	 *
	 * ion_alloc_dmabuf() rather than ion_alloc(): the latter rejects every
	 * heap type except SYSTEM/HYP_CMA/SYSTEM_SECURE, and the blobs allocate
	 * from carveout and qsecom heaps too. ion_alloc_fd() -- the new ABI's
	 * own path -- uses ion_alloc_dmabuf, so this behaves identically to a
	 * modern allocation.
	 */
	dmabuf = ion_alloc_dmabuf(len, heap_id_mask, flags);
	if (IS_ERR(dmabuf))
		return PTR_ERR(dmabuf);

	id = ion_legacy_insert(client, dmabuf);
	if (id < 0) {
		dma_buf_put(dmabuf);
		return id;
	}

	*out_handle = id;

	return 0;
}

static int ion_legacy_do_share(struct ion_legacy_client *client,
			       ion_user_handle_t handle, int *out_fd)
{
	struct dma_buf *dmabuf;
	int fd;

	dmabuf = ion_legacy_lookup(client, handle);
	if (!dmabuf)
		return -EINVAL;

	/*
	 * dma_buf_fd() CONSUMES a reference: fd_install() takes over the file
	 * reference the caller held. Take a fresh one for the fd so the table
	 * keeps its own -- otherwise closing the fd frees a buffer the handle
	 * still points at, which is precisely the use-after-free that the
	 * legacy handle model invites.
	 */
	get_dma_buf(dmabuf);

	fd = dma_buf_fd(dmabuf, O_CLOEXEC);
	if (fd < 0) {
		dma_buf_put(dmabuf);
		return fd;
	}

	*out_fd = fd;

	return 0;
}

static int ion_legacy_do_import(struct ion_legacy_client *client, int fd,
				ion_user_handle_t *out_handle)
{
	struct dma_buf *dmabuf;
	int id;

	/* dma_buf_get() returns a new reference, which the table then owns */
	dmabuf = dma_buf_get(fd);
	if (IS_ERR(dmabuf))
		return PTR_ERR(dmabuf);

	id = ion_legacy_insert(client, dmabuf);
	if (id < 0) {
		dma_buf_put(dmabuf);
		return id;
	}

	*out_handle = id;

	return 0;
}

/*
 * Cache maintenance.
 *
 * 4.14 expresses it as a bracket -- begin_cpu_access() invalidates,
 * end_cpu_access() cleans -- and ION's implementation tracks state across the
 * pair. Issuing half a bracket to mimic a one-way legacy op would leave that
 * state inconsistent, so both halves are always issued and the *direction*
 * carries the meaning. That does marginally more work than 4.4 did for CLEAN
 * and INV; it is never less, so it is never wrong.
 */
static int ion_legacy_cache_op(struct dma_buf *dmabuf, unsigned int op,
			       u32 offset, u32 length)
{
	enum dma_data_direction dir;
	bool partial = length != 0;
	int ret;

	switch (op) {
	case ION_LEGACY_IOC_CLEAN_CACHES:
	case ION_LEGACY_IOC_CLEAN_CACHES32:
		dir = DMA_TO_DEVICE;
		break;
	case ION_LEGACY_IOC_INV_CACHES:
	case ION_LEGACY_IOC_INV_CACHES32:
		dir = DMA_FROM_DEVICE;
		break;
	case ION_LEGACY_IOC_CLEAN_INV_CACHES:
	case ION_LEGACY_IOC_CLEAN_INV_CACHES32:
		dir = DMA_BIDIRECTIONAL;
		break;
	default:
		return -ENOTTY;
	}

	if (partial) {
		ret = dma_buf_begin_cpu_access_partial(dmabuf, dir, offset,
						       length);
		if (ret)
			return ret;
		return dma_buf_end_cpu_access_partial(dmabuf, dir, offset,
						      length);
	}

	ret = dma_buf_begin_cpu_access(dmabuf, dir);
	if (ret)
		return ret;

	return dma_buf_end_cpu_access(dmabuf, dir);
}

static int ion_legacy_custom(struct ion_legacy_client *client, unsigned int op,
			     void __user *uarg, bool compat)
{
	struct dma_buf *dmabuf;
	ion_user_handle_t handle;
	u32 offset, length;
	bool put = false;
	int fd, ret;

	if (compat) {
		struct ion_legacy_flush_data32 data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;
		handle = data.handle;
		fd = data.fd;
		offset = data.offset;
		length = data.length;
	} else {
		struct ion_legacy_flush_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;
		handle = data.handle;
		fd = data.fd;
		offset = data.offset;
		length = data.length;
	}

	/*
	 * The payload carries both a handle and an fd, and callers set one or
	 * the other depending on vintage. Prefer the fd: it is unambiguous, and
	 * a buffer reached that way need not be in this client's table at all.
	 */
	if (fd >= 0) {
		dmabuf = dma_buf_get(fd);
		if (IS_ERR(dmabuf))
			return PTR_ERR(dmabuf);
		put = true;
	} else {
		dmabuf = ion_legacy_lookup(client, handle);
		if (!dmabuf)
			return -EINVAL;
	}

	ret = ion_legacy_cache_op(dmabuf, op, offset, length);

	if (put)
		dma_buf_put(dmabuf);

	return ret;
}

static int ion_legacy_sync(int fd)
{
	struct dma_buf *dmabuf;
	int ret;

	dmabuf = dma_buf_get(fd);
	if (IS_ERR(dmabuf))
		return PTR_ERR(dmabuf);

	/*
	 * Legacy ION_IOC_SYNC meant "the CPU touched this, make it coherent for
	 * devices". Bidirectional is the conservative reading, and matches what
	 * 4.4's msm ion did for this ioctl.
	 */
	ret = dma_buf_begin_cpu_access(dmabuf, DMA_BIDIRECTIONAL);
	if (!ret)
		ret = dma_buf_end_cpu_access(dmabuf, DMA_BIDIRECTIONAL);

	dma_buf_put(dmabuf);

	return ret;
}

long ion_legacy_ioctl(struct file *filp, unsigned int cmd, unsigned long arg)
{
	struct ion_legacy_client *client = filp->private_data;
	void __user *uarg = (void __user *)arg;
	int ret;

	if (!client)
		return -EINVAL;

	switch (cmd) {
	case ION_LEGACY_IOC_ALLOC: {
		struct ion_legacy_allocation_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		ret = ion_legacy_do_alloc(client, data.len, data.heap_id_mask,
					  data.flags, &data.handle);
		if (ret)
			return ret;

		if (copy_to_user(uarg, &data, sizeof(data))) {
			ion_legacy_drop(client, data.handle);
			return -EFAULT;
		}

		return 0;
	}
	case ION_LEGACY_IOC_ALLOC32: {
		struct ion_legacy_allocation_data32 data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		ret = ion_legacy_do_alloc(client, data.len, data.heap_id_mask,
					  data.flags, &data.handle);
		if (ret)
			return ret;

		if (copy_to_user(uarg, &data, sizeof(data))) {
			ion_legacy_drop(client, data.handle);
			return -EFAULT;
		}

		return 0;
	}
	case ION_LEGACY_IOC_FREE: {
		struct ion_legacy_handle_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		return ion_legacy_drop(client, data.handle);
	}
	case ION_LEGACY_IOC_MAP:
	case ION_LEGACY_IOC_SHARE: {
		struct ion_legacy_fd_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		ret = ion_legacy_do_share(client, data.handle, &data.fd);
		if (ret)
			return ret;

		if (copy_to_user(uarg, &data, sizeof(data))) {
			/*
			 * The fd is already installed in the caller's table and
			 * cannot be recalled from here; it will go when the
			 * process does. Nothing leaks in the kernel.
			 */
			return -EFAULT;
		}

		return 0;
	}
	case ION_LEGACY_IOC_IMPORT: {
		struct ion_legacy_fd_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		ret = ion_legacy_do_import(client, data.fd, &data.handle);
		if (ret)
			return ret;

		if (copy_to_user(uarg, &data, sizeof(data))) {
			ion_legacy_drop(client, data.handle);
			return -EFAULT;
		}

		return 0;
	}
	case ION_LEGACY_IOC_SYNC: {
		struct ion_legacy_fd_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		return ion_legacy_sync(data.fd);
	}
	case ION_LEGACY_IOC_CUSTOM: {
		struct ion_legacy_custom_data data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		return ion_legacy_custom(client, data.cmd,
					 (void __user *)(uintptr_t)data.arg,
					 false);
	}
	case ION_LEGACY_IOC_CUSTOM32: {
		struct ion_legacy_custom_data32 data;

		if (copy_from_user(&data, uarg, sizeof(data)))
			return -EFAULT;

		return ion_legacy_custom(client, data.cmd,
					 (void __user *)(uintptr_t)data.arg,
					 true);
	}
	default:
		return -ENOTTY;
	}
}
