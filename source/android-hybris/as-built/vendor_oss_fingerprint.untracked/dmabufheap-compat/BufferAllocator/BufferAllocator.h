/*
 * Minimal compat header for the real AOSP `libdmabufheap`'s `BufferAllocator`
 * class, absent from this Android-11 tree (it's a newer AOSP library).
 *
 * `Alloc()` is a REAL implementation of the real DMA-BUF Heaps ioctl protocol
 * (see BufferAllocator.cpp) -- on a kernel with CONFIG_DMABUF_HEAPS it would
 * actually work; this 4.14 tree never backported it (no linux/dma-heap.h UAPI
 * header anywhere), so /dev/dma_heap/<name> genuinely doesn't exist here.
 *
 * That alone isn't the end of the story, though: confirmed live (a direct
 * strace of the built fingerprint HAL) that `QSEEComFunc.c`'s own
 * `dmabuf_alloc()` -- needed on the real FPC1145 path, not just Egistec --
 * calls straight through this class's `Alloc()`, and this device's kernel
 * DOES have a real, working ION allocator (`/dev/ion`, confirmed via the same
 * strace: several successful legacy-ABI ION ioctls already happen elsewhere
 * in this exact binary, for its own QSEECom shared-memory needs -- see
 * patches/ion-legacy/ for why this kernel needs the *legacy* ABI
 * specifically). So the ION fallback path (`CheckIonSupport()`/
 * `MapNameToIonHeap()`, which an earlier version of this shim stubbed out as
 * "unreachable Egistec-only code") is real and load-bearing here too --
 * implemented for real below, not a stub.
 */
#pragma once

#include <string>
#include <unordered_map>
// The real libdmabufheap header transitively pulls in unistd.h (DmaBuffer.cpp,
// Sony's own file, calls close() without including it directly) -- match that.
#include <unistd.h>

class BufferAllocator {
   public:
    BufferAllocator() = default;
    ~BufferAllocator();

    BufferAllocator(const BufferAllocator &) = delete;
    BufferAllocator &operator=(const BufferAllocator &) = delete;

    // Real signature match: real AOSP's BufferAllocator::Alloc takes the same
    // four arguments, the last two defaulted. Returns a dmabuf fd on success,
    // a negative errno on failure. Tries /dev/dma_heap/<heap_name> first
    // (absent on this kernel); if `heap_name` has a recorded ION mapping
    // (see MapNameToIonHeap below), falls back to a real ION allocation
    // instead of failing.
    int Alloc(const std::string &heap_name, size_t len, unsigned int heap_flags = 0,
              unsigned int alloc_flags = 0);

    // Whether this device has a working /dev/ion to fall back to.
    bool CheckIonSupport();

    // Real AOSP resolves `ion_heap_name` by querying the kernel's own heap
    // list (ION_IOC_HEAP_QUERY) and matching by name. This kernel's ION
    // driver is old enough (see patches/ion-legacy/) that querying it isn't
    // worth relying on, and this codebase only ever asks for one specific
    // mapping ("qcom,qseecom" -> "qsecom") -- so this records that one
    // real, DT-confirmed heap ID (27, `qcom,ion-heap@27 { /* QSEECOM HEAP */
    // reg = <27>; ... }` in msm8998-ion.dtsi) directly rather than building a
    // general-purpose name resolver for a single caller.
    int MapNameToIonHeap(const std::string &heap_name, const std::string &ion_heap_name,
                          unsigned int ion_heap_flags = 0, unsigned int mapped_heap_flags = 0,
                          unsigned int mapped_alloc_flags = 0);

   private:
    int heap_fd = -1;
    std::unordered_map<std::string, unsigned int> ion_heap_ids;

    int AllocFromIon(unsigned int ion_heap_id, size_t len, unsigned int flags);
};
