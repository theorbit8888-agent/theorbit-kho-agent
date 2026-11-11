#!/usr/bin/env python3
"""Đọc mã vạch / QR từ ảnh (tem vận đơn…) bằng Vision có sẵn trên macOS — không cần cài gì, không tốn tiền.
  doc(blob) -> ['SPXVN06373998997B', ...]   (lọc giữ mã kiểu MVĐ: chữ+số, 8–30 ký tự, bỏ link/QR dài)
Lần đầu tự biên dịch tools/mavach.swift → bin/mavach.   CLI: python3 tools/mavach.py anh.jpg
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BIN = os.path.join(ROOT, "bin", "mavach")
SRC = os.path.join(ROOT, "tools", "mavach.swift")


def _bin():
    if not os.path.exists(BIN) or os.path.getmtime(BIN) < os.path.getmtime(SRC):
        os.makedirs(os.path.dirname(BIN), exist_ok=True)
        subprocess.run(["/usr/bin/swiftc", "-O", SRC, "-o", BIN], capture_output=True, timeout=300)
    return BIN


MVD = re.compile(r"\b(SPXVN[0-9A-Z]{8,}|[A-Z]{2,5}[0-9][0-9A-Z]{7,20}|[0-9]{10,16})\b")


def doc_file(path, chu=False):
    """Mã vạch/QR; chu=True: nếu không có mã vạch thì đọc chữ trong ảnh (ảnh chụp màn hình danh sách đơn sàn)."""
    try:
        r = subprocess.run([_bin(), path] + (["--chu"] if chu else []), capture_output=True, text=True, timeout=90)
    except Exception as e:
        print("mavach lỗi", e, file=sys.stderr)
        return []
    out, chu_ma = [], []
    for s in r.stdout.splitlines():
        s = s.strip()
        if s.startswith("CHU:"):
            for x in MVD.findall(s[4:].upper().replace(" ", "")):
                if x not in chu_ma:
                    chu_ma.append(x)
            continue
        if re.fullmatch(r"[A-Za-z0-9\-]{8,30}", s) and re.search(r"\d", s) and s not in out:
            out.append(s)
    return out or chu_ma


def doc(blob, ext=".jpg", chu=False):
    f = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        f.write(blob); f.close()
        return doc_file(f.name, chu)
    finally:
        os.unlink(f.name)


if __name__ == "__main__":
    print("\n".join(doc_file(sys.argv[1], "--chu" in sys.argv)) or "(không đọc được mã nào)")
