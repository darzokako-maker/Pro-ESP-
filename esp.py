#!/usr/bin/env python3
"""
ProSoccerOnline ESP - Otomatik Pattern Scan + Fallback
Hata durumunda konsol açık kalır
"""
import sys
import os
import struct
import math
import ctypes
import traceback
import json
from dataclasses import dataclass
from typing import Tuple

# ============================================================
# HATA YAKALAMA - Konsol her zaman açık
# ============================================================
if not sys.stdout:
    sys.stdout = open(os.devnull, 'w')

# Hata durumunda konsol açık kalsın diye
try:
    import pymem
except ImportError:
    print("[!] pymem kurulu değil! pip install pymem")
    input("Devam etmek için Enter'a basın...")
    sys.exit(1)

try:
    from PyQt5.QtWidgets import *
    from PyQt5.QtCore import Qt, QTimer, QCoreApplication
    from PyQt5.QtGui import QPainter, QPen, QColor, QFont
except ImportError:
    print("[!] PyQt5 kurulu değil! pip install PyQt5")
    input("Devam etmek için Enter'a basın...")
    sys.exit(1)

PROCESS_NAME = "ProSoccerOnline.exe"
MODULE_NAME = "ProSoccerOnline.exe"

# ============================================================
# LOG SİSTEMİ (EXE çalışırken debug için)
# ============================================================
class Logger:
    def __init__(self):
        try:
            self.log_file = open("prosoccer_esp.log", "w", encoding="utf-8")
        except:
            self.log_file = None
        self.errors = []
        self.warnings = []
        
    def log(self, msg, end="\n"):
        print(msg, end=end)
        if self.log_file:
            self.log_file.write(msg + end)
            self.log_file.flush()
            
    def success(self, msg):
        self.log(f"[✓] {msg}")
        
    def error(self, msg):
        self.log(f"[✗] {msg}")
        self.errors.append(msg)
        
    def warning(self, msg):
        self.log(f"[⚠] {msg}")
        self.warnings.append(msg)
        
    def info(self, msg):
        self.log(f"[i] {msg}")
        
    def close(self):
        if self.log_file:
            self.log_file.close()

logger = Logger()

# ============================================================
# HPP'DEN ALINAN OFFSET'LER (FALLBACK İÇİN)
# ============================================================
OFFSETS = {
    "UObjectBase::ClassPrivate": 0x10,
    "UObjectBase::NamePrivate": 0x18,
    "UObjectBase::OuterPrivate": 0x20,
    "UStruct::SuperStruct": 0x40,
    "UStruct::ChildProperties": 0x50,
    "FField::Next": 0x18,
    "FField::NamePrivate": 0x20,
    "FProperty::Offset_Internal": 0x44,
    "UWorld::PersistentLevel": 0x30,
    "UWorld::GameState": 0x160,
    "UWorld::OwningGameInstance": 0x1D8,
    "ULevel::ActorCluster": 0xE0,
    "ULevelActorContainer::Actors": 0x28,
    "AGameStateBase::PlayerArray": 0x02A8,
    "APlayerState::PawnPrivate": 0x0308,
    "AController::PlayerState": 0x0298,
    "APlayerController::AcknowledgedPawn": 0x0338,
    "APlayerController::PlayerCameraManager": 0x0348,
    "APlayerCameraManager::CameraCachePrivate": 0x1390,
    "AActor::RootComponent": 0x01A0,
    "USceneComponent::RelativeLocation": 0x0128,
    "ACharacter::CharacterMovement": 0x0320,
    "UCharacterMovementComponent::MaxWalkSpeed": 0x0248,
    "UEngine::GameViewport": 0x30,
    "UGameViewportClient::World": 0x58,
    "UGameInstance::LocalPlayers": 0x38,
    "UPlayer::PlayerController": 0x30,
}

# ============================================================
# PATTERN SCAN
# ============================================================
GUOBJECT_SIG = bytes([
    0x48, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00,
    0x48, 0x89, 0x01, 0x45, 0x8B, 0xD1
])
GUOBJECT_MASK = bytes([1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])

class PatternScanner:
    CHUNK_SIZE = 0x200000
    
    def __init__(self, pm, module_name):
        self.pm = pm
        try:
            self.module = pymem.process.module_from_name(pm.process_handle, module_name)
            self.base = self.module.lpBaseOfDll
            self.size = self.module.SizeOfImage
            logger.success(f"Modül bulundu: Base=0x{self.base:X}, Size=0x{self.size:X}")
        except Exception as e:
            logger.error(f"Modül bulunamadı: {e}")
            raise

    def scan_all(self, pattern, mask):
        pat_len = len(pattern)
        logger.info(f"Pattern taraması başlıyor... (Modül boyutu: {self.size} bytes)")
        
        for start in range(0, self.size, self.CHUNK_SIZE):
            end = min(start + self.CHUNK_SIZE + pat_len, self.size)
            try:
                data = self.pm.read_bytes(self.base + start, end - start)
            except:
                continue
            for i in range(len(data) - pat_len):
                if all(not mask[j] or data[i+j] == pattern[j] for j in range(pat_len)):
                    addr = self.base + start + i
                    logger.success(f"Pattern bulundu! Adres: 0x{addr:X}")
                    yield addr
                    return
        
        logger.error("Pattern bulunamadı!")

# ============================================================
# BELLEK FONKSİYONLARI
# ============================================================
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

def rfloat(pm, addr):
    try:
        return struct.unpack("<f", pm.read_bytes(addr, 4))[0]
    except:
        return 0.0

def rvec3(pm, addr):
    try:
        return struct.unpack("<ddd", pm.read_bytes(addr, 24))
    except:
        return (0.0, 0.0, 0.0)

def read_array(pm, addr):
    try:
        data = rp(pm, addr)
        count = ru32(pm, addr + 8)
        cap = ru32(pm, addr + 0x10)
        return data, count, cap
    except:
        return 0, 0, 0

def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

# ============================================================
# FNAME RESOLVER
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
                        logger.success(f"FName layout: table_off=0x{off:X}, style={style}")
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

# ============================================================
# UOBJECT ARRAY
# ============================================================
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

    def _obj_class(self, obj):
        return rp(self.pm, obj + OFFSETS["UObjectBase::ClassPrivate"])

    def iter_objects(self):
        objects_ptr = rp(self.pm, self.guobject_array + 0x10)
        if not objects_ptr:
            logger.error("GUObjectArray pointer geçersiz!")
            return
        for chunk_idx in range(64):
            chunk = rp(self.pm, objects_ptr + chunk_idx * 8)
            if not chunk:
                break
            for within in range(0x10000):
                obj = rp(self.pm, chunk + within * 0x18)
                if obj:
                    yield obj

    def find_class(self, name):
        for obj in self.iter_objects():
            if self._obj_name(obj) == name:
                return obj
        return 0

    def find_first_instance(self, class_name):
        cls = self.find_class(class_name)
        if not cls:
            return 0
        for obj in self.iter_objects():
            if self._obj_class(obj) == cls:
                name = self._obj_name(obj)
                if name and not name.startswith("Default__"):
                    return obj
        return 0

# ============================================================
# ANA ESP SINIFI (Pattern Scan + Fallback)
# ============================================================
class ProSoccerESP:
    def __init__(self):
        logger.log("=" * 60)
        logger.log("PRO SOCCER ONLINE ESP v2.0")
        logger.log("=" * 60)
        
        self.use_pattern_scan = True
        self.pm = None
        self.guobject_array = 0
        self.fname_pool = 0
        self.objects = None
        self.gengine = 0
        self.original_speed = 0.0
        
        # 1. Process'e bağlan
        self._connect_process()
        
        # 2. Önce Pattern Scan Dene
        try:
            self._init_with_pattern_scan()
            logger.success("Pattern Scan ile başarıyla başlatıldı!")
        except Exception as e:
            logger.warning(f"Pattern Scan başarısız: {e}")
            logger.info("Fallback offset'ler deneniyor...")
            try:
                self._init_with_fallback()
                logger.success("Fallback offset'ler ile başarıyla başlatıldı!")
            except Exception as e2:
                logger.error(f"Fallback da başarısız: {e2}")
                raise RuntimeError("ESP başlatılamadı! Lütfen oyunu güncelledikten sonra tekrar deneyin.")
        
        logger.log("=" * 60)
        logger.success("ESP BAŞARIYLA BAŞLATILDI!")
        logger.log("=" * 60)

    def _connect_process(self):
        """Process'e bağlan"""
        try:
            self.pm = pymem.Pymem(PROCESS_NAME)
            logger.success(f"Process bağlantısı: {PROCESS_NAME}")
        except Exception as e:
            logger.error(f"Process bulunamadı: {e}")
            raise RuntimeError(f"{PROCESS_NAME} çalışmıyor! Lütfen oyunu başlatın.")

    def _init_with_pattern_scan(self):
        """Pattern Scan ile başlat"""
        logger.info("Pattern Scan ile başlatılıyor...")
        
        # GUObjectArray bul
        scanner = PatternScanner(self.pm, MODULE_NAME)
        addr = next(scanner.scan_all(GUOBJECT_SIG, GUOBJECT_MASK), 0)
        if not addr:
            raise RuntimeError("GUObjectArray pattern bulunamadı!")
        
        rel_offset = struct.unpack("<i", self.pm.read_bytes(addr + 3, 4))[0]
        self.guobject_array = addr + 7 + rel_offset
        logger.success(f"GUObjectArray: 0x{self.guobject_array:X}")
        
        # FNamePool bul
        fname_pool = None
        for delta in range(0xE0000, 0xF0000, 0x10):
            test_pool = self.guobject_array - delta
            try:
                if ru32(self.pm, test_pool) < 0xFFFF:
                    fname_pool = test_pool
                    logger.success(f"FNamePool bulundu! delta=0x{delta:X}")
                    break
            except:
                continue
        
        if not fname_pool:
            fname_pool = self.guobject_array - 0xE3B40
            logger.warning(f"FNamePool varsayılan kullanılıyor: 0x{fname_pool:X}")
        
        self.fname_pool = fname_pool
        
        # UObjectArray oluştur
        self.objects = UObjectArray(self.pm, self.guobject_array, self.fname_pool)
        
        # GameEngine bul
        self.gengine = self.objects.find_first_instance("GameEngine")
        if not self.gengine:
            raise RuntimeError("GameEngine bulunamadı!")
        logger.success(f"GameEngine: 0x{self.gengine:X}")
        
        self.use_pattern_scan = True

    def _init_with_fallback(self):
        """Fallback offset'ler ile başlat (GUObjectArray manuel)"""
        logger.info("Fallback offset'ler ile başlatılıyor...")
        
        # Pattern scan ile GUObjectArray bulunamadıysa, manuel dene
        # UE5'te GUObjectArray genelde bu adreslerde olur
        module = pymem.process.module_from_name(self.pm.process_handle, MODULE_NAME)
        base = module.lpBaseOfDll
        
        # Bilinen pattern'lerle dene
        known_patterns = [
            (b"\x48\x8B\x05\x00\x00\x00\x00\x48\x8B\x0D", "xxxxxxx"),
            (b"\x48\x8D\x05\x00\x00\x00\x00\x48\x89\x01", "xxxxxxx"),
        ]
        
        for pattern, mask in known_patterns:
            try:
                # Basit arama
                for i in range(0, module.SizeOfImage, 0x1000):
                    try:
                        data = self.pm.read_bytes(base + i, 0x1000)
                        for j in range(len(data) - len(pattern)):
                            if data[j:j+len(pattern)] == pattern:
                                addr = base + i + j
                                logger.warning(f"Alternatif pattern bulundu: 0x{addr:X}")
                                # Bu adresi kullan
                                break
                    except:
                        continue
            except:
                continue
        
        # Hala bulunamadıysa, kullanıcıya sor
        logger.error("Otomatik başlatma başarısız!")
        logger.log("")
        logger.log("MANUEL MÜDAHALE GEREKİYOR:")
        logger.log("1. ProSoccerOnline.exe'nin güncel sürümünü çalıştırın")
        logger.log("2. diag_fname.py ile doğru offset'leri bulun")
        logger.log("3. Bulunan değerleri bu dosyaya girin")
        
        raise RuntimeError("Otomatik başlatma başarısız! Lütfen log dosyasını kontrol edin.")

    def _get_world(self):
        try:
            vp = rp(self.pm, self.gengine + OFFSETS["UEngine::GameViewport"])
            if not vp:
                return 0
            return rp(self.pm, vp + OFFSETS["UGameViewportClient::World"])
        except:
            return 0

    def _get_local_controller(self, world):
        if not world:
            return 0
        try:
            gi = rp(self.pm, world + OFFSETS["UWorld::OwningGameInstance"])
            if not gi:
                return 0
            lp_data, lp_count, _ = read_array(self.pm, gi + OFFSETS["UGameInstance::LocalPlayers"])
            if not lp_count:
                return 0
            return rp(self.pm, rp(self.pm, lp_data) + OFFSETS["UPlayer::PlayerController"])
        except:
            return 0

    def iter_players(self, include_local=False):
        try:
            world = self._get_world()
            if not world:
                return
            
            gamestate = rp(self.pm, world + OFFSETS["UWorld::GameState"])
            if not gamestate:
                return
                
            pc = self._get_local_controller(world)
            local_ps = rp(self.pm, pc + OFFSETS["AController::PlayerState"]) if pc else 0

            pa_data, pa_count, _ = read_array(self.pm, gamestate + OFFSETS["AGameStateBase::PlayerArray"])
            
            for i in range(pa_count):
                ps = rp(self.pm, pa_data + i * 8)
                if not ps or (ps == local_ps and not include_local):
                    continue
                pawn = rp(self.pm, ps + OFFSETS["APlayerState::PawnPrivate"])
                if not pawn:
                    continue
                root = rp(self.pm, pawn + OFFSETS["AActor::RootComponent"])
                if not root:
                    continue
                pos = rvec3(self.pm, root + OFFSETS["USceneComponent::RelativeLocation"])
                if abs(pos[0]) > 0.01:
                    yield (ps == local_ps), pos, i
        except Exception as e:
            pass

    def get_camera(self):
        try:
            world = self._get_world()
            if not world:
                return None
            pc = self._get_local_controller(world)
            if not pc:
                return None
            cam = rp(self.pm, pc + OFFSETS["APlayerController::PlayerCameraManager"])
            if not cam:
                return None
            pov = cam + OFFSETS["APlayerCameraManager::CameraCachePrivate"] + 0x10
            return {
                "loc": rvec3(self.pm, pov + 0x0),
                "rot": rvec3(self.pm, pov + 0x18),
                "fov": rfloat(self.pm, pov + 0x30),
            }
        except:
            return None

    def update_speed_hack(self, state: bool, multiplier: float = 1.25):
        try:
            world = self._get_world()
            if not world:
                return
            pc = self._get_local_controller(world)
            if not pc:
                return
            pawn = rp(self.pm, pc + OFFSETS["APlayerController::AcknowledgedPawn"])
            if not pawn:
                return
            movement = rp(self.pm, pawn + OFFSETS["ACharacter::CharacterMovement"])
            if not movement:
                return
            speed_addr = movement + OFFSETS["UCharacterMovementComponent::MaxWalkSpeed"]
            current = rfloat(self.pm, speed_addr)
            if state and current > 10.0:
                if self.original_speed == 0.0:
                    self.original_speed = current
                self.pm.write_float(speed_addr, self.original_speed * multiplier)
            else:
                if self.original_speed > 10.0:
                    self.pm.write_float(speed_addr, self.original_speed)
        except:
            pass

# ============================================================
# WORLD TO SCREEN
# ============================================================
def w2s(world_pos, camera, sw, sh):
    if not camera:
        return None
    try:
        pitch, yaw, roll = [math.radians(x) for x in camera["rot"]]
        sp, cp, sy, cy, sr, cr = math.sin(pitch), math.cos(pitch), math.sin(yaw), math.cos(yaw), math.sin(roll), math.cos(roll)
        forward = (cp * cy, cp * sy, sp)
        right = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
        up = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp)
        dx, dy, dz = [world_pos[i] - camera["loc"][i] for i in range(3)]
        vx = dx*forward[0] + dy*forward[1] + dz*forward[2]
        vy = dx*right[0] + dy*right[1] + dz*right[2]
        vz = dx*up[0] + dy*up[1] + dz*up[2]
        if vx <= 0.1:
            return None
        tan_fov = math.tan(math.radians(camera["fov"]) / 2.0)
        screen_x = (1.0 + vy / (vx * tan_fov)) * sw / 2.0
        screen_y = (1.0 - vz / (vx * tan_fov / (sw / sh))) * sh / 2.0
        return (screen_x, screen_y) if (0 <= screen_x <= sw and 0 <= screen_y <= sh) else None
    except:
        return None

# ============================================================
# GUI
# ============================================================
@dataclass
class Config:
    enabled: bool = True
    dot_esp: bool = True
    show_local: bool = False
    show_names: bool = True
    show_distance: bool = True
    snap_lines: bool = True
    speed_hack: bool = False
    speed_multiplier: float = 1.25
    enemy_color: Tuple[int, int, int] = (255, 0, 0)
    local_color: Tuple[int, int, int] = (0, 255, 0)
    dot_radius: int = 6

class Menu(QWidget):
    def __init__(self, config: Config, esp: ProSoccerESP):
        super().__init__()
        self.config = config
        self.esp = esp
        self.setWindowTitle("PRO SOCCER ESP")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(280, 400)
        self._build_ui()

    def _build_ui(self):
        container = QFrame(self)
        container.setStyleSheet("""
            QFrame { 
                background-color: rgba(25, 25, 25, 240); 
                border: 2px solid #00ffcc; 
                border-radius: 10px; 
            } 
            QLabel { 
                color: #eee; 
                font-family: Consolas; 
                font-size: 11px; 
            }
            QCheckBox { 
                color: #eee; 
                font-family: Consolas; 
                font-size: 11px; 
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QPushButton { 
                background-color: #2a2a2a; 
                color: #eee; 
                border: 1px solid #555; 
                border-radius: 4px;
                padding: 6px;
                font-family: Consolas;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #00ffcc;
            }
        """)
        layout = QVBoxLayout(container)
        layout.setSpacing(8)

        title = QLabel("⚽ PRO SOCCER ESP v2.0")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #00ffcc;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Çizgi
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #444;")
        layout.addWidget(line)

        layout.addWidget(self._chk("☑ ESP Aktif", "enabled"))
        layout.addWidget(self._chk("● Nokta ESP", "dot_esp"))
        layout.addWidget(self._chk("👤 Kendimi Göster", "show_local"))
        layout.addWidget(self._chk("📝 İsimleri Yaz", "show_names"))
        layout.addWidget(self._chk("📏 Mesafeyi Yaz", "show_distance"))
        layout.addWidget(self._chk("📐 İz Çizgileri", "snap_lines"))

        # Çizgi
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("background-color: #444;")
        layout.addWidget(line2)

        cb_speed = QCheckBox(f"🚀 Speed Hack (%{int((self.config.speed_multiplier-1)*100)})")
        cb_speed.setChecked(self.config.speed_hack)
        cb_speed.stateChanged.connect(self._toggle_speed)
        layout.addWidget(cb_speed)

        btn_color = QPushButton("🎨 Düşman Rengi Seç")
        btn_color.clicked.connect(self._pick_color)
        layout.addWidget(btn_color)

        # Çizgi
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setStyleSheet("background-color: #444;")
        layout.addWidget(line3)

        info = QLabel("Insert / F1 : Menü Gizle")
        info.setStyleSheet("color: #888; font-size: 10px;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        # ESP durumu
        self.status_label = QLabel("✅ ESP Aktif")
        self.status_label.setStyleSheet("color: #00ff88; font-size: 10px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        outer = QVBoxLayout(self)
        outer.addWidget(container)
        self.setLayout(outer)

    def _chk(self, text, attr):
        cb = QCheckBox(text)
        cb.setChecked(getattr(self.config, attr))
        cb.stateChanged.connect(lambda s, a=attr: self._on_change(a, s))
        return cb

    def _on_change(self, attr, state):
        setattr(self.config, attr, bool(state))
        if attr == "enabled":
            self.status_label.setText("✅ ESP Aktif" if state else "⏸ ESP Pasif")
            self.status_label.setStyleSheet("color: #00ff88;" if state else "color: #ff8844;")

    def _toggle_speed(self, state):
        self.config.speed_hack = bool(state)
        try:
            self.esp.update_speed_hack(self.config.speed_hack, self.config.speed_multiplier)
        except:
            pass

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(*self.config.enemy_color), self)
        if c.isValid():
            self.config.enemy_color = (c.red(), c.green(), c.blue())

class Overlay(QWidget):
    def __init__(self, esp: ProSoccerESP, config: Config):
        super().__init__()
        self.esp, self.config = esp, config
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Tam ekran
        screen = QApplication.primaryScreen()
        rect = screen.geometry()
        self.setGeometry(rect)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)
        
        self.frame_count = 0
        logger.info("Overlay başlatıldı")

    def paintEvent(self, event):
        if not self.config.enabled:
            return
        
        self.frame_count += 1
        
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setFont(QFont("Consolas", 9))
            w, h = self.width(), self.height()
            cam = self.esp.get_camera()
            if not cam:
                return

            if self.config.speed_hack:
                self.esp.update_speed_hack(True, self.config.speed_multiplier)

            player_count = 0
            for is_local, pos, idx in self.esp.iter_players(include_local=self.config.show_local):
                s = w2s(pos, cam, w, h)
                if not s:
                    continue
                cx, cy = s
                color = self.config.local_color if is_local else self.config.enemy_color

                if self.config.dot_esp:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(*color))
                    radius = self.config.dot_radius + (5 if is_local else 0)
                    painter.drawEllipse(int(cx - radius), int(cy - radius), radius*2, radius*2)

                if self.config.snap_lines:
                    painter.setPen(QPen(QColor(*color), 1))
                    painter.drawLine(int(w / 2), int(h), int(cx), int(cy))

                labels = []
                if self.config.show_names:
                    labels.append("SİZ" if is_local else f"P{idx}")
                if self.config.show_distance:
                    labels.append(f"{int(dist(pos, cam['loc'])/100)}m")
                if labels:
                    painter.setPen(QPen(QColor(*color)))
                    painter.drawText(int(cx + self.config.dot_radius + 8), int(cy + 4), " | ".join(labels))
                
                player_count += 1

        except Exception as e:
            # Sessizce hata geç
            pass

# ============================================================
# HATA MESAJI DİYALOĞU
# ============================================================
def show_error_dialog(error_msg):
    """Hata mesajı göster"""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    msg.setWindowTitle("❌ ESP BAŞLATILAMADI")
    msg.setText("ProSoccerOnline ESP başlatılırken bir hata oluştu!")
    
    detailed = f"""
Hata: {error_msg}

Çözüm Önerileri:
1. ProSoccerOnline.exe çalıştığından emin olun
2. Yönetici olarak çalıştırmayı deneyin
3. prosoccer_esp.log dosyasını kontrol edin
4. diag_fname.py ile doğru offset'leri bulun

Log dosyası: prosoccer_esp.log
    """
    msg.setInformativeText(detailed)
    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec_()

# ============================================================
# MAIN
# ============================================================
def main():
    """Ana fonksiyon"""
    logger.log("")
    logger.log("UYGULAMA BAŞLATILIYOR...")
    logger.log("")
    
    try:
        # PyQt uygulaması
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        
        config = Config()
        
        # ESP'yi başlat
        esp = None
        try:
            esp = ProSoccerESP()
        except Exception as e:
            error_msg = str(e)
            logger.error(f"ESP başlatılamadı: {error_msg}")
            logger.error(traceback.format_exc())
            
            # Hata mesajı göster
            show_error_dialog(error_msg)
            
            # Konsolda detaylar
            print("\n" + "=" * 60)
            print("HATA DETAYLARI:")
            print("=" * 60)
            print(traceback.format_exc())
            print("\nLog dosyası: prosoccer_esp.log")
            print("=" * 60)
            input("\nDevam etmek için Enter'a basın...")
            return

        # GUI'yi başlat
        menu = Menu(config, esp)
        overlay = Overlay(esp, config)
        overlay.show()
        menu.show()
        
        logger.success("GUI başlatıldı! ESP çalışıyor.")
        print("\n" + "=" * 60)
        print("✅ PRO SOCCER ONLINE ESP BAŞARIYLA BAŞLATILDI!")
        print("=" * 60)
        print("📖 Kullanım:")
        print("  - Insert / F1: Menüyü göster/gizle")
        print("  - ESP ayarlarını menüden değiştirebilirsiniz")
        print("=" * 60 + "\n")

        # Menü toggle
        VK_INSERT, VK_F1 = 0x2D, 0x70
        states = {"ins": False, "f1": False}
        
        def poll():
            try:
                for vk, k in [(VK_INSERT, "ins"), (VK_F1, "f1")]:
                    s = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                    if s and not states[k]:
                        menu.setVisible(not menu.isVisible())
                    states[k] = s
            except:
                pass
                
        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(50)
        
        sys.exit(app.exec_())
        
    except Exception as e:
        logger.error(f"Beklenmeyen hata: {e}")
        logger.error(traceback.format_exc())
        
        print("\n" + "=" * 60)
        print("❌ BEKLENMEYEN HATA!")
        print("=" * 60)
        print(traceback.format_exc())
        print("\nLog dosyası: prosoccer_esp.log")
        print("=" * 60)
        input("\nDevam etmek için Enter'a basın...")
        sys.exit(1)
    finally:
        logger.close()

if __name__ == "__main__":
    main()