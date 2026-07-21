#!/usr/bin/env python3
"""
ProSoccerOnline.exe için debug aracı
Engine_classes.hpp'deki offset'leri kullanır
"""
import struct
import pymem

# Dinamik olarak algılanacaktır. Varsayılanlar aşağıdadır:
DEFAULT_PROCESS_NAME = "ProSoccerOnline-Win64-Shipping.exe"
MODULE_NAME = ""

# HPP'den alınan kesin offset'ler (Engine_classes.hpp'ye göre)
OFFSETS = {
    # UObjectBase
    "UObjectBase::ClassPrivate": 0x10,
    "UObjectBase::NamePrivate": 0x18,
    "UObjectBase::OuterPrivate": 0x20,

    # UStruct
    "UStruct::SuperStruct": 0x40,
    "UStruct::ChildProperties": 0x50,

    # FField
    "FField::Next": 0x18,
    "FField::NamePrivate": 0x20,
    "FProperty::Offset_Internal": 0x44,

    # UWorld (Engine_classes.hpp'deki UWorld yapısı)
    "UWorld::PersistentLevel": 0x30,
    "UWorld::GameState": 0x160,
    "UWorld::OwningGameInstance": 0x1D8,

    # ULevel
    "ULevel::ActorCluster": 0xE0,
    "ULevelActorContainer::Actors": 0x28,

    # AGameStateBase
    "AGameStateBase::PlayerArray": 0x02A8,

    # APlayerState
    "APlayerState::PawnPrivate": 0x0308,

    # AController
    "AController::PlayerState": 0x0298,

    # APlayerController
    "APlayerController::AcknowledgedPawn": 0x0338,
    "APlayerController::PlayerCameraManager": 0x0348,

    # AActor
    "AActor::RootComponent": 0x01A0,

    # USceneComponent
    "USceneComponent::RelativeLocation": 0x0128,

    # ACharacter
    "ACharacter::CharacterMovement": 0x0320,

    # UCharacterMovementComponent
    "UCharacterMovementComponent::MaxWalkSpeed": 0x0248,
}

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

def ru32(pm, addr):
    try:
        return struct.unpack("<I", pm.read_bytes(addr, 4))[0]
    except:
        return 0

def ru16(pm, addr):
    try:
        return struct.unpack("<H", pm.read_bytes(addr, 2))[0]
    except:
        return 0

def rvec3(pm, addr):
    try:
        return struct.unpack("<ddd", pm.read_bytes(addr, 24))
    except:
        return (0.0, 0.0, 0.0)

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

def read_array(pm, addr):
    try:
        data = rp(pm, addr)
        count = ru32(pm, addr + 8)
        cap = ru32(pm, addr + 0x10)
        return data, count, cap
    except:
        return 0, 0, 0

def actor_pos(pm, actor):
    root = rp(pm, actor + OFFSETS["AActor::RootComponent"])
    if root:
        return rvec3(pm, root + OFFSETS["USceneComponent::RelativeLocation"])
    return (0.0, 0.0, 0.0)

# ============================================================
# FNAME RESOLVER (esp.py'den entegre edildi)
# ============================================================
class FNameResolver:
    BLOCK_TABLE_OFFSETS = (0x8, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40)

    def __init__(self, pm, fname_pool):
        self.pm = pm
        self.fname_pool = fname_pool
        self.block_table_off = 0x10
        self.header_style = "ue5"
        self._detect_layout()

    def _read_entry(self, entry_id, table_off, style):
        block_idx = entry_id >> 16
        within = (entry_id & 0xFFFF) << 1
        block_addr = rp(self.pm, self.fname_pool + table_off + block_idx * 8)
        if not block_addr:
            return None
        hdr = ru16(self.pm, block_addr + within)
        length = (hdr >> 6) & 0x3FF if style == "custom" else (hdr & 0x3FF if style == "ue5" else hdr >> 1)
        is_wide = hdr & 1 if style in ("custom", "ue4") else (hdr >> 10) & 1
        if length == 0 or length > 512:
            return None
        try:
            raw = self.pm.read_bytes(block_addr + within + 2, length * (2 if is_wide else 1))
            return raw.decode("utf-16-le" if is_wide else "latin-1", errors="ignore")
        except:
            return None

    def _detect_layout(self):
        for off in self.BLOCK_TABLE_OFFSETS:
            for style in ("custom", "ue5", "ue4"):
                try:
                    if self._read_entry(0, off, style) == "None":
                        self.block_table_off, self.header_style = off, style
                        print(f"[+] FName layout tespit edildi: table_off=0x{off:X}, style={style}")
                        return
                except:
                    pass

    def resolve(self, entry_id):
        try:
            name = self._read_entry(entry_id, self.block_table_off, self.header_style)
            if name:
                return name
        except:
            pass
        return None

class UObjectArray:
    def __init__(self, pm, guobject_array, fname_pool):
        self.pm = pm
        self.guobject_array = guobject_array
        self.fnames = FNameResolver(pm, fname_pool)

    def _obj_name(self, obj):
        try:
            name_idx = ru32(self.pm, obj + OFFSETS["UObjectBase::NamePrivate"])
            return self.fnames.resolve(name_idx) or f"obj_{obj:X}"
        except:
            return "?"

    def iter_objects(self):
        objects_ptr = rp(self.pm, self.guobject_array + 0x10)
        if not objects_ptr:
            return
        for chunk_idx in range(64):
            chunk = rp(self.pm, objects_ptr + chunk_idx * 8)
            if not chunk:
                break
            for within in range(0x10000):
                obj = rp(self.pm, chunk + within * 0x18)
                if obj:
                    yield obj

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
    if not guobj:
        print("[!] GUObjectArray bulunamadı!")
        pm.close_process()
        return

    # FNamePool bul (esp.py'den entegre edildi)
    fname_pool = None
    for delta in range(0xE0000, 0xF0000, 0x10):
        test_pool = guobj - delta
        try:
            if ru32(pm, test_pool) < 0xFFFF:
                fname_pool = test_pool
                print(f"[+] FNamePool bulundu! delta=0x{delta:X}")
                break
        except:
            continue

    if not fname_pool:
        fname_pool = guobj - 0xE3B40
        print(f"[-] FNamePool varsayilan secildi: 0x{fname_pool:X}")

    objects = UObjectArray(pm, guobj, fname_pool)

    # GameEngine'i bul
    game_engine = None
    for obj in objects.iter_objects():
        name = objects._obj_name(obj)
        if "GameEngine" in name:
            game_engine = obj
            print(f"[+] GameEngine: 0x{obj:X}")
            break

    if not game_engine:
        print("[!] GameEngine bulunamadı!")
        pm.close_process()
        return

    # World'ü bul (UEngine::GameViewport -> UGameViewportClient::World)
    viewport = rp(pm, game_engine + 0x30)  # UEngine::GameViewport
    world = rp(pm, viewport + 0x58) if viewport else 0

    if not world:
        print("[!] World bulunamadı!")
        pm.close_process()
        return

    print(f"[+] World: 0x{world:X}")

    # GameState
    game_state = rp(pm, world + OFFSETS["UWorld::GameState"])
    print(f"[+] GameState: 0x{game_state:X}")

    # PlayerArray
    pa_data, pa_count, _ = read_array(pm, game_state + OFFSETS["AGameStateBase::PlayerArray"])
    print(f"[+] Toplam Oyuncu: {pa_count}")

    print("\n--- Oyuncular ---")
    for i in range(pa_count):
        ps = rp(pm, pa_data + i * 8)
        if not ps:
            continue
        pawn = rp(pm, ps + OFFSETS["APlayerState::PawnPrivate"])
        pos = actor_pos(pm, pawn) if pawn else (0,0,0)
        print(f"[{i}] PS=0x{ps:X} Pawn=0x{pawn:X} pos=({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")

    print("\n--- Level'daki Character'lar ---")
    level = rp(pm, world + OFFSETS["UWorld::PersistentLevel"])
    if level:
        container = rp(pm, level + OFFSETS["ULevel::ActorCluster"])
        if container:
            actors_data, actors_count, _ = read_array(pm, container + OFFSETS["ULevelActorContainer::Actors"])
            print(f"[+] Toplam Actor: {actors_count}")

            for i in range(actors_count):
                actor = rp(pm, actors_data + i * 8)
                if not actor:
                    continue
                cls = rp(pm, actor + OFFSETS["UObjectBase::ClassPrivate"])
                if not cls:
                    continue
                cls_name = objects._obj_name(cls)
                if cls_name and ("Character" in cls_name or "Player" in cls_name or "Pawn" in cls_name):
                    pos = actor_pos(pm, actor)
                    print(f"[{i}] 0x{actor:X} [{cls_name}] pos=({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")

    pm.close_process()

if __name__ == "__main__":
    main()
