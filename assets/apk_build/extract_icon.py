#!/usr/bin/env python3
"""extract_icon.py — 从 Uncrashed.exe 里提取最大的图标，导出为 PNG。

PE 资源里 RT_GROUP_ICON 描述一组 RT_ICON；按组内条目拼成标准 .ico
再交给 PIL 打开，取最大尺寸存 PNG（APK 的桌面图标就用它）。
"""

import io
import struct
import sys
from pathlib import Path

from PIL import Image

EXE = Path(r"D:/穿越机模拟器/Uncrashed免安装/Uncrashed.FPV/Uncrashed.exe")
OUT = Path(__file__).resolve().parent / "app/res/drawable/ic.png"


def parse_rsrc(data):
    """返回 [(type_id, name_id, lang, bytes)]，只处理数字 id 资源。"""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    ddoff = pe + 24 + (112 if magic == 0x20B else 96)
    rsrc_rva, _ = struct.unpack_from("<II", data, ddoff + 2 * 8)

    sec = pe + 24 + optsz
    base = None
    for i in range(nsec):
        o = sec + i * 40
        vsz, vaddr, rsz, rptr = struct.unpack_from("<IIII", data, o + 8)
        if vaddr <= rsrc_rva < vaddr + vsz:
            base = rptr + (rsrc_rva - vaddr)
            break
    if base is None:
        raise SystemExit("找不到资源段")

    out = []

    def walk(off, level, t=None, n=None, lang=None):
        nnamed, nid = struct.unpack_from("<HH", data, base + off + 12)
        for i in range(nnamed + nid):
            e = base + off + 16 + i * 8
            name, ptr = struct.unpack_from("<II", data, e)
            if ptr & 0x80000000:
                walk(ptr & 0x7FFFFFFF, level + 1,
                     name if level == 0 else t,
                     name if level == 1 else n, None)
            else:
                doff = base + ptr
                drva, dsz = struct.unpack_from("<II", data, doff)
                # 资源数据条目里存的是 RVA，要按资源段基址换算成文件偏移
                foff = base + (drva - rsrc_rva)
                blob = data[foff:foff + dsz]
                out.append((t, n, name, blob))

    walk(0, 0)
    return out


def build_ico(group_blob, icons):
    """RT_GROUP_ICON → 标准 ICO 字节流。"""
    cnt = struct.unpack_from("<H", group_blob, 4)[0]
    entries = []
    datas = []
    for i in range(cnt):
        o = 6 + i * 14
        w, h, cc, res, planes, bits, size, iid = struct.unpack_from(
            "<BBBBHHIH", group_blob, o)
        blob = icons.get(iid)
        if blob is None:
            continue
        entries.append(struct.pack("<BBBBHHII", w, h, cc, res, planes, bits,
                                   len(blob), len(datas) and 0 or 0))
        datas.append((w or 256, h or 256, blob))

    # 重新计算偏移
    hdr = struct.pack("<HHH", 0, 1, len(datas))
    offset = 6 + 16 * len(datas)
    ent = b""
    body = b""
    for i, (w, h, blob) in enumerate(datas):
        ent += struct.pack("<BBBBHHII", 0 if w >= 256 else w, 0 if h >= 256 else h,
                           0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        body += blob
    return hdr + ent + body


def main():
    data = EXE.read_bytes()
    res = parse_rsrc(data)
    groups = [r for r in res if r[0] == 14]
    icons = {r[1]: r[3] for r in res if r[0] == 3}
    if not groups:
        sys.exit("exe 里没有图标资源")

    best = None
    for _, _, _, blob in groups:
        ico = build_ico(blob, icons)
        try:
            im = Image.open(io.BytesIO(ico))
        except Exception:
            continue
        # 逐帧找最大
        sizes = []
        try:
            while True:
                sizes.append((im.size, im.convert("RGBA").tobytes()))
                im.seek(im.tell() + 1)
        except EOFError:
            pass
        for size, _ in sizes:
            if best is None or size[0] * size[1] > best[0][0] * best[0][1]:
                best = (size, ico)

    size, ico = best
    im = Image.open(io.BytesIO(ico))
    # 取该尺寸那一帧
    for idx in range(getattr(im, "n_frames", 1)):
        im.seek(idx)
        if im.size == size:
            break
    im = im.convert("RGBA")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT)
    print(f"提取成功: {OUT}  {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()
