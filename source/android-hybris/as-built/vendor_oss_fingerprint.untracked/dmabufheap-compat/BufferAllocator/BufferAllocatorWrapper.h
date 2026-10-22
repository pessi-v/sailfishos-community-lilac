/*
 * Minimal compat header for AOSP libdmabufheap's C wrapper API around
 * BufferAllocator -- needed because QSEEComFunc.c (Sony's own file) is
 * plain C, not C++. Same rationale as BufferAllocator.h; see there.
 */
#pragma once

#include <stddef.h>

// QSEEComFunc.c includes this as plain C, which can't parse BufferAllocator.h's
// C++ `class` -- opaque-typedef it there instead, same trick real AOSP's own
// wrapper header uses.
#ifdef __cplusplus
#include "BufferAllocator/BufferAllocator.h"
extern "C" {
#else
typedef struct BufferAllocator BufferAllocator;
#endif

BufferAllocator *CreateDmabufHeapBufferAllocator(void);
void FreeDmabufHeapBufferAllocator(BufferAllocator *buffer_allocator);
int DmabufHeapAlloc(BufferAllocator *buffer_allocator, const char *heap_name, size_t len,
                     unsigned int heap_flags, unsigned int alloc_flags);
int CheckIonSupport(void);
int MapDmabufHeapNameToIonHeap(BufferAllocator *buffer_allocator, const char *heap_name,
                                const char *ion_heap_name, unsigned int ion_heap_flags,
                                unsigned int mapped_heap_flags, unsigned int mapped_alloc_flags);

#ifdef __cplusplus
}
#endif
