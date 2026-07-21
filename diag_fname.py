#!/usr/bin/env python3
"""
FNamePool layout diagnostic for ProSoccerOnline.exe
Uses pattern scanning + heuristics from Engine_classes.hpp
"""
import struct
import pymem

# Dinamik olarak algılanacaktır. Varsayılanlar aşağıdadır:
DEFAULT_PROCESS_NAME = "ProSoccerOnline-Win64-Shipping.exe"

# Pattern from UE5 (valid for all UE5.1+ games)
GUOBJECT_SIG = bytes([
    0x48, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00,
    0x48, 0x89, 0x01, 0x45, 0x8B, 0xD1
])
GUOBJECT_MASK = bytes([1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])

def rp(pm, addr):
    try:
        return struct.unpack("<Q", pm.read_bytes(addr, 8))[0]
    except:
        return 0

def ru16(pm, addr):
    try:
        return struct.unpack("<H", pm.read_bytes(addr, 2))[0]
    except:
        return 0

def ru32(pm, addr):
    try:
        return struct.unpack("<I", pm.read_bytes(addr, 4))[0]
    except:
        return 0

def scan_guobject_array(pm):
    try:
        mod = pymem.process.module_from_name(pm.process_handle, MODULE_NAME)
        base = mod.lpBaseOfDll
        size = mod.SizeOfImage
    except Exception as e:
        print(f"[!] Modul bilgileri alinamadi: {e}")
        return 0

    pat_len = len(GUOBJECT_SIG)
    chunk_size = 0x200000

    for start in range(0, size, chunk_size):
        end = min(start + chunk_size + pat_len, size)
        try:
            data = pm.read_bytes(base + start, end - start)
        except:
            continue
        for i in range(len(data) - pat_len):
            if all(not GUOBJECT_MASK[j] or data[i+j] == GUOBJECT_SIG[j] for j in range(pat_len)):
                addr = base + start + i
                rel = struct.unpack("<i", pm.read_bytes(addr + 3, 4))[0]
                return addr + 7 + rel
    return 0

def read_name_entry(pm, entry_addr, style):
    hdr = ru16(pm, entry_addr)
    if style == "ue4":
        is_wide = hdr & 1
        length = hdr >> 1
    else:
        length = hdr & 0x3FF
        is_wide = (hdr >> 10) & 1
    if length == 0 or length > 512:
        return None
    try:
        if is_wide:
            raw = pm.read_bytes(entry_addr + 2, length * 2)
            return raw.decode("utf-16-le", errors="ignore")
        else:
            raw = pm.read_bytes(entry_addr + 2, length)
            return raw.decode("latin-1", errors="ignore")
    except:
        return None

def resolve_at(pm, fname_pool, entry_id, table_off, style):
    block_idx = entry_id >> 16
    within = (entry_id & 0xFFFF) << 1
    block_addr = rp(pm, fname_pool + table_off + block_idx * 8)
    if not block_addr:
        return None
    return read_name_entry(pm, block_addr + within, style)

def main():
    pm = None
    process_name = None
    module_name = None

    for name in ["ProSoccerOnline-Win64-Shipping.exe", "ProSoccerOnline.exe"]:
        try:
            pm = pymem.Pymem(name)
            # Modülün varlığını doğrula
            pymem.process.module_from_name(pm.process_handle, name)
            process_name = name
            module_name = name
            print(f"[+] Process baglantisi kuruldu: {name}")
            break
        except Exception:
            if pm:
                try:
                    pm.close_process()
                except:
                    pass
            continue

    if not pm:
        try:
            pm = pymem.Pymem(DEFAULT_PROCESS_NAME)
            process_name = DEFAULT_PROCESS_NAME
            module_name = DEFAULT_PROCESS_NAME
            print(f"[+] Process baglantisi kuruldu: {DEFAULT_PROCESS_NAME}")
        except Exception as e:
            print(f"[!] ProSoccerOnline calismiyor! (ProSoccerOnline-Win64-Shipping.exe veya ProSoccerOnline.exe bulunamadi)")
            return

    global MODULE_NAME
    MODULE_NAME = module_name

    guobj = scan_guobject_array(pm)
    if guobj == 0:
        print("[!] GUObjectArray bulunamadı!")
        pm.close_process()
        return

    print(f"[+] GUObjectArray = 0x{guobj:X}")

    # FNamePool'u bul - UE5 için delta aralığı
    possible_deltas = list(range(0xE0000, 0xF0000, 0x10))
    fname_pool = None

    for delta in possible_deltas:
        test_pool = guobj - delta
        try:
            test_val = ru32(pm, test_pool)
            if test_val > 0 and test_val < 0xFFFF:
                fname_pool = test_pool
                print(f"[+] FNamePool bulundu! delta = 0x{delta:X}")
                break
        except:
            continue

    if not fname_pool:
        print("[!] FNamePool otomatik bulunamadı, varsayılan kullanılıyor.")
        fname_pool = guobj - 0xE3B40

    print(f"[+] FNamePool     = 0x{fname_pool:X}")
    print(f"[+] delta         = 0x{guobj - fname_pool:X}")

    print("\n--- FNamePool ilk 0x80 byte ---")
    raw = pm.read_bytes(fname_pool, 0x80)
    for i in range(0, 0x80, 0x10):
        chunk = raw[i:i+0x10]
        print(f"  +{i:02x}: {chunk.hex()}")

    print("\n--- Block-table offset / header stili tespiti ---")
    for off in range(0, 0x80, 0x8):
        val = rp(pm, fname_pool + off)
        if not val:
            continue
        first_block = rp(pm, val)
        if first_block and (first_block & 0xFFFF000000000000) == 0 and first_block > 0x10000:
            for style in ("ue5", "ue4"):
                name = read_name_entry(pm, first_block, style)
                if name:
                    print(f"  off=+{off:02x} indirect  style={style} -> entry0='{name}'")
        for style in ("ue5", "ue4"):
            name = read_name_entry(pm, val, style)
            if name:
                print(f"  off=+{off:02x} direct    style={style} -> entry0='{name}'")

    pm.close_process()

if __name__ == "__main__":
    main()
