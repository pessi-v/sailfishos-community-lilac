/*
 * Minimal compat implementation of AOSP's libdmabufheap BufferAllocator, for
 * a tree that doesn't have the real library. See BufferAllocator.h for why,
 * including why the ION fallback path below is real, load-bearing code and
 * not a stub for dead code.
 *
 * Real DMA-BUF Heaps UAPI (stable since upstream Linux 5.6, standard
 * <linux/dma-heap.h> -- not present in this 4.14 kernel's own UAPI headers,
 * so the ioctl numbers are reproduced directly here rather than included).
 *
 * ION legacy-ABI UAPI: reproduced from patches/ion-legacy/ion_legacy.h (the
 * kernel-side compat patch that makes this ABI available at all on this
 * tree) -- kept independent rather than #include-ing across the kernel/
 * userspace boundary, same as that file's own approach.
 */
#include "BufferAllocator/BufferAllocator.h"
#include "BufferAllocator/BufferAllocatorWrapper.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {

struct dma_heap_allocation_data {
    uint64_t len;
    uint32_t fd;
    uint32_t fd_flags;
    uint64_t heap_flags;
};

#define DMA_HEAP_IOC_MAGIC 'H'
#define DMA_HEAP_IOCTL_ALLOC _IOWR(DMA_HEAP_IOC_MAGIC, 0x0, struct dma_heap_allocation_data)

typedef int ion_user_handle_t;

struct ion_legacy_allocation_data {
    uint64_t len;
    uint64_t align;
    uint32_t heap_id_mask;
    uint32_t flags;
    ion_user_handle_t handle;
};

struct ion_legacy_fd_data {
    ion_user_handle_t handle;
    int fd;
};

#define ION_LEGACY_IOC_MAGIC 'I'
#define ION_LEGACY_IOC_ALLOC _IOWR(ION_LEGACY_IOC_MAGIC, 0, struct ion_legacy_allocation_data)
#define ION_LEGACY_IOC_MAP _IOWR(ION_LEGACY_IOC_MAGIC, 2, struct ion_legacy_fd_data)

// msm8998-ion.dtsi's own DT node comment/reg for the heap we need:
//   qcom,ion-heap@27 { /* QSEECOM HEAP */ reg = <27>; ... };
constexpr unsigned int kQseecomIonHeapId = 27;

}  // namespace

BufferAllocator::~BufferAllocator() {
    if (heap_fd >= 0) {
        close(heap_fd);
    }
}

int BufferAllocator::AllocFromIon(unsigned int ion_heap_id, size_t len, unsigned int flags) {
    int ion_fd = open("/dev/ion", O_RDONLY | O_CLOEXEC);
    if (ion_fd < 0) {
        return -errno;
    }

    struct ion_legacy_allocation_data alloc_data = {};
    alloc_data.len = len;
    alloc_data.align = 0;
    alloc_data.heap_id_mask = 1u << ion_heap_id;
    alloc_data.flags = flags;

    if (ioctl(ion_fd, ION_LEGACY_IOC_ALLOC, &alloc_data) < 0) {
        int err = errno;
        close(ion_fd);
        return -err;
    }

    struct ion_legacy_fd_data map_data = {};
    map_data.handle = alloc_data.handle;
    if (ioctl(ion_fd, ION_LEGACY_IOC_MAP, &map_data) < 0) {
        int err = errno;
        close(ion_fd);
        return -err;
    }

    close(ion_fd);
    return map_data.fd;
}

int BufferAllocator::Alloc(const std::string &heap_name, size_t len, unsigned int heap_flags,
                            unsigned int alloc_flags) {
    (void)alloc_flags;

    auto it = ion_heap_ids.find(heap_name);
    if (it != ion_heap_ids.end()) {
        return AllocFromIon(it->second, len, heap_flags);
    }

    std::string heap_path = "/dev/dma_heap/" + heap_name;
    int fd = open(heap_path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        // No CONFIG_DMABUF_HEAPS on this kernel and no recorded ION mapping
        // for this heap name -- the real library would fail exactly the
        // same way on a kernel lacking both.
        return -errno;
    }

    struct dma_heap_allocation_data data = {};
    data.len = len;
    data.fd_flags = O_RDWR | O_CLOEXEC;
    data.heap_flags = heap_flags;

    int ret = ioctl(fd, DMA_HEAP_IOCTL_ALLOC, &data);
    close(fd);
    if (ret < 0) {
        return -errno;
    }
    return static_cast<int>(data.fd);
}

bool BufferAllocator::CheckIonSupport() {
    int fd = open("/dev/ion", O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return false;
    }
    close(fd);
    return true;
}

int BufferAllocator::MapNameToIonHeap(const std::string &heap_name,
                                       const std::string &ion_heap_name, unsigned int,
                                       unsigned int, unsigned int) {
    // See BufferAllocator.h: this codebase only ever asks for one mapping
    // ("qcom,qseecom" -> "qsecom"), which is the only one this shim knows.
    if (ion_heap_name != "qsecom") {
        return -ENOSYS;
    }
    ion_heap_ids[heap_name] = kQseecomIonHeapId;
    return 0;
}

// C wrapper (BufferAllocatorWrapper.h) -- for QSEEComFunc.c, a plain-C file.
extern "C" {

BufferAllocator *CreateDmabufHeapBufferAllocator(void) {
    return new BufferAllocator();
}

void FreeDmabufHeapBufferAllocator(BufferAllocator *buffer_allocator) {
    delete buffer_allocator;
}

int DmabufHeapAlloc(BufferAllocator *buffer_allocator, const char *heap_name, size_t len,
                     unsigned int heap_flags, unsigned int alloc_flags) {
    if (!buffer_allocator) {
        return -EINVAL;
    }
    return buffer_allocator->Alloc(heap_name, len, heap_flags, alloc_flags);
}

int CheckIonSupport(void) {
    return BufferAllocator().CheckIonSupport() ? 1 : 0;
}

int MapDmabufHeapNameToIonHeap(BufferAllocator *buffer_allocator, const char *heap_name,
                                const char *ion_heap_name, unsigned int ion_heap_flags,
                                unsigned int mapped_heap_flags, unsigned int mapped_alloc_flags) {
    if (!buffer_allocator) {
        return -EINVAL;
    }
    return buffer_allocator->MapNameToIonHeap(heap_name, ion_heap_name, ion_heap_flags,
                                               mapped_heap_flags, mapped_alloc_flags);
}

}  // extern "C"
