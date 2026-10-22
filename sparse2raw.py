#!/usr/bin/env python3
"""Convert an Android sparse image to a raw image (a minimal simg2img). A raw input is copied unchanged.

    sparse2raw.py IN OUT
"""
import shutil
import struct
import sys

SPARSE_MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE, CRC32 = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4


def convert(src, dst):
    with open(src, 'rb') as f, open(dst, 'wb') as o:
        head = f.read(28)
        if len(head) < 28 or struct.unpack('<I', head[:4])[0] != SPARSE_MAGIC:
            f.seek(0)
            shutil.copyfileobj(f, o, 1 << 20)
            return
        _, major, _, file_hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, _ = struct.unpack('<IHHHHIIII', head)
        if major != 1:
            sys.exit('unsupported sparse format version %d' % major)
        f.seek(file_hdr_sz)
        for _ in range(total_chunks):
            ch = f.read(chunk_hdr_sz)
            ctype, _, chunk_blks, total_sz = struct.unpack('<HHII', ch[:12])
            out_sz = chunk_blks * blk_sz
            if ctype == RAW:
                left = out_sz
                while left:
                    buf = f.read(min(left, 1 << 20))
                    if not buf:
                        sys.exit('%s: truncated' % src)
                    o.write(buf)
                    left -= len(buf)
            elif ctype == FILL:
                pattern = f.read(4) * (blk_sz // 4)
                for _ in range(chunk_blks):
                    o.write(pattern)
            elif ctype == DONT_CARE:
                o.seek(out_sz, 1)
            elif ctype == CRC32:
                f.read(total_sz - chunk_hdr_sz)
            else:
                sys.exit('%s: unknown chunk type 0x%x' % (src, ctype))
        o.truncate(total_blks * blk_sz)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    convert(sys.argv[1], sys.argv[2])
