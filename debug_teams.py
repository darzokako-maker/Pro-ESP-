#!/usr/bin/env python3
"""
ProSoccerOnline.exe için debug aracı
Engine_classes.hpp'deki offset'leri kullanır
"""
import struct
import pymem

PROCESS_NAME = "ProSoccerOnline.exe"
MODULE_NAME = "ProSoccerOnline.exe"

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
    mod = pymem.process.module_from_name(pm.process_handle, MODULE_NAME)
    base = mod.lpBaseOfDll
    size = mod.SizeOfImage
    data = pm.read_bytes(base, size)
    pat_len = len(GUOBJECT_SIG)
    for i in range(size - pat_len):
        matched = True
        for j in range(pat_len):
            if GUOBJECT_MASK[j] and data[i + j] != GUOBJECT_SIG[j]:
                matched = False
                break
        if matched:
            addr = base + i
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

class UObjectArray:
    def __init__(self, pm, guobject_array):
        self.pm = pm
        self.guobject_array = guobject_array

    def _obj_name(self, obj):
        try:
            name_idx = ru32(self.pm, obj + OFFSETS["UObjectBase::NamePrivate"])
            return f"obj_{obj:X}_idx{name_idx}"
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
    try:
        pm = pymem.Pymem(PROCESS_NAME)
    except:
        print(f"[!] {PROCESS_NAME} bulunamadı!")
        return

    guobj = scan_guobject_array(pm)
    if not guobj:
        print("[!] GUObjectArray bulunamadı!")
        pm.close_process()
        return

    objects = UObjectArray(pm, guobj)

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
