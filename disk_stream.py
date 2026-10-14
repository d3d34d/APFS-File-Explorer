"""
disk_stream.py - Windows Physical Disk & Partition Stream Provider
Provides robust 64-bit sector-aligned reading for raw physical drives,
partitions (\\\\.\\HarddiskNPartitionM), and disk image files (.dmg, .raw, .img).
"""

import os
import io
import struct
import ctypes
from ctypes import wintypes
import subprocess
import json
from typing import List, Dict, Optional, Any

try:
    import win32file
    import win32con
except ImportError:
    win32file = None
    win32con = None


def is_admin() -> bool:
    """Check if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


kernel32 = ctypes.windll.kernel32
kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID
]
kernel32.DeviceIoControl.restype = wintypes.BOOL

kernel32.SetFilePointerEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int64,
    ctypes.POINTER(ctypes.c_int64),
    wintypes.DWORD
]
kernel32.SetFilePointerEx.restype = wintypes.BOOL


def get_drive_size(handle_val: int) -> int:
    """Get the size in bytes of a Windows physical drive or partition using DeviceIoControl."""
    # IOCTL_DISK_GET_LENGTH_INFO = 0x0007405c
    buf = ctypes.create_string_buffer(8)
    bytes_returned = wintypes.DWORD()
    ok = kernel32.DeviceIoControl(
        wintypes.HANDLE(int(handle_val)),
        0x0007405c,
        None, 0,
        buf, ctypes.sizeof(buf),
        ctypes.byref(bytes_returned),
        None
    )
    if ok:
        return struct.unpack("<Q", buf.raw)[0]
    return 0


class WindowsDiskStream(io.RawIOBase):
    """
    A robust 64-bit sector-aligned, seekable file-like reader for Windows physical disks,
    partitions (\\\\.\\HarddiskNPartitionM), and disk images.
    """
    def __init__(self, device_path: str, sector_size: int = 4096):
        self.device_path = device_path
        self.sector_size = sector_size
        self._pos = 0
        self._device_pos = -1
        self._is_device = device_path.startswith("\\\\.\\") or device_path.startswith("\\\\?\\")
        
        if self._is_device:
            if not win32file:
                raise RuntimeError("pywin32 (win32file) is required to open physical drives on Windows.")
            
            self.handle = win32file.CreateFile(
                device_path,
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None,
                win32con.OPEN_EXISTING,
                0,
                None
            )
            # Retrieve size using IOCTL
            self._size = get_drive_size(int(self.handle))
        else:
            self._file = open(device_path, "rb")
            self._file.seek(0, io.SEEK_END)
            self._size = self._file.tell()
            self._file.seek(0)

    @property
    def size(self) -> int:
        return self._size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self._size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")
        return self._pos

    def readinto(self, b) -> int:
        length = len(b)
        if length == 0:
            return 0

        if not self._is_device:
            self._file.seek(self._pos)
            data = self._file.read(length)
            n = len(data)
            b[:n] = data
            self._pos += n
            return n

        # Check bounds
        if self._size > 0 and self._pos >= self._size:
            return 0

        if self._size > 0 and self._pos + length > self._size:
            length = self._size - self._pos

        # Calculate 4096-byte sector alignment
        start_sector = self._pos // self.sector_size
        offset_in_sector = self._pos % self.sector_size
        end_byte = self._pos + length
        end_sector = (end_byte + self.sector_size - 1) // self.sector_size
        sectors_to_read = end_sector - start_sector
        bytes_to_read = sectors_to_read * self.sector_size

        aligned_offset = start_sector * self.sector_size
        
        # 64-bit seek via SetFilePointerEx only when needed
        if aligned_offset != self._device_pos:
            new_pos = ctypes.c_int64()
            ok = kernel32.SetFilePointerEx(
                wintypes.HANDLE(int(self.handle)),
                ctypes.c_int64(aligned_offset),
                ctypes.byref(new_pos),
                0  # FILE_BEGIN
            )
            if not ok:
                return 0
            self._device_pos = aligned_offset

        try:
            hr, data = win32file.ReadFile(self.handle, bytes_to_read)
            self._device_pos += len(data)
        except Exception:
            return 0

        chunk = data[offset_in_sector : offset_in_sector + length]
        n = len(chunk)
        b[:n] = chunk
        self._pos += n
        return n

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            if self._size > 0:
                size = max(0, self._size - self._pos)
            else:
                size = 1024 * 1024
        if size == 0:
            return b""

        # Fast path for aligned physical disk reads: bypass intermediate bytearray allocations
        if self._is_device and (self._pos % self.sector_size == 0) and (size % self.sector_size == 0):
            if self._size > 0 and self._pos >= self._size:
                return b""
            if self._size > 0 and self._pos + size > self._size:
                size = self._size - self._pos
                size = size - (size % self.sector_size)
                if size <= 0:
                    buf = bytearray(self._size - self._pos)
                    n = self.readinto(buf)
                    return bytes(buf[:n])

            if self._pos != self._device_pos:
                new_pos = ctypes.c_int64()
                ok = kernel32.SetFilePointerEx(
                    wintypes.HANDLE(int(self.handle)),
                    ctypes.c_int64(self._pos),
                    ctypes.byref(new_pos),
                    0
                )
                if not ok:
                    return b""
                self._device_pos = self._pos

            try:
                hr, data = win32file.ReadFile(self.handle, size)
                self._device_pos += len(data)
                self._pos += len(data)
                return data
            except Exception:
                return b""

        buf = bytearray(size)
        n = self.readinto(buf)
        return bytes(buf[:n])

    def close(self):
        if self._is_device and hasattr(self, 'handle'):
            try:
                win32file.CloseHandle(self.handle)
            except Exception:
                pass
        elif hasattr(self, '_file'):
            try:
                self._file.close()
            except Exception:
                pass
        super().close()


IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_DISK_GET_DRIVE_LAYOUT_EX = 0x00070050
IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0
APFS_GPT_GUID_BYTES = bytes.fromhex("ef57347c0000aa11aa1100306543ecac")


class STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [
        ("PropertyId", wintypes.DWORD),
        ("QueryType", wintypes.DWORD),
        ("AdditionalParameters", wintypes.BYTE * 1)
    ]


def list_physical_drives_win32() -> List[Dict[str, Any]]:
    """
    Ultra-fast native Win32 drive & partition enumeration via kernel32 DeviceIoControl.
    Executes in under 1 millisecond without launching external processes.
    """
    kernel32 = ctypes.windll.kernel32
    drives = []
    ret = wintypes.DWORD()

    for i in range(16):
        path = f"\\\\.\\PHYSICALDRIVE{i}"
        # Open with 0 access (query only) to avoid permission blocks
        h = kernel32.CreateFileW(path, 0, 1 | 2, None, 3, 0, None)
        if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
            continue

        model = f"Physical Drive {i}"
        query = STORAGE_PROPERTY_QUERY(0, 0)
        desc_buf = ctypes.create_string_buffer(1024)
        if kernel32.DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query), desc_buf, 1024, ctypes.byref(ret), None):
            vendor_off = struct.unpack("<I", desc_buf.raw[12:16])[0]
            prod_off = struct.unpack("<I", desc_buf.raw[16:20])[0]
            vendor = desc_buf.raw[vendor_off:].split(b"\x00")[0].decode("ascii", errors="ignore").strip() if (0 < vendor_off < 1024) else ""
            prod = desc_buf.raw[prod_off:].split(b"\x00")[0].decode("ascii", errors="ignore").strip() if (0 < prod_off < 1024) else ""
            full_model = (vendor + " " + prod).strip()
            if full_model:
                model = full_model

        geom_buf = ctypes.create_string_buffer(64)
        size_bytes = 0
        if kernel32.DeviceIoControl(h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, None, 0, geom_buf, 64, ctypes.byref(ret), None):
            size_bytes = struct.unpack("<q", geom_buf.raw[24:32])[0]

        partitions = []
        has_apfs = False
        layout_buf = ctypes.create_string_buffer(8192)
        if kernel32.DeviceIoControl(h, IOCTL_DISK_GET_DRIVE_LAYOUT_EX, None, 0, layout_buf, 8192, ctypes.byref(ret), None):
            style, count = struct.unpack("<II", layout_buf.raw[:8])
            offset = 48
            for _ in range(count):
                p_buf = layout_buf.raw[offset : offset + 144]
                if len(p_buf) < 144:
                    break
                p_start, p_len, p_num = struct.unpack("<qqI", p_buf[8:28])
                if p_len > 0:
                    p_type_guid = p_buf[32:48]
                    is_p_apfs = (p_type_guid == APFS_GPT_GUID_BYTES)
                    if is_p_apfs:
                        has_apfs = True
                    partitions.append({
                        "PartitionNumber": p_num,
                        "StartOffset": p_start,
                        "Size": p_len,
                        "IsAPFS": is_p_apfs,
                        "DevicePath": f"\\\\.\\Harddisk{i}Partition{p_num}"
                    })
                offset += 144

        kernel32.CloseHandle(h)
        drives.append({
            "DeviceID": path,
            "Index": i,
            "Model": model,
            "Size": size_bytes,
            "HasAPFS": has_apfs,
            "Partitions": partitions
        })

    return drives


def list_physical_drives() -> List[Dict[str, Any]]:
    """Enumerate physical disk drives instantly using Win32 API with PowerShell fallback."""
    try:
        fast_drives = list_physical_drives_win32()
        if fast_drives:
            return fast_drives
    except Exception as e:
        print(f"Fast Win32 drive enum failed: {e}")

    ps_cmd = """
    $ErrorActionPreference = 'SilentlyContinue'
    $drives = Get-CimInstance Win32_DiskDrive
    $result = @()
    foreach ($d in $drives) {
        $diskNum = $d.Index
        $parts = Get-Partition -DiskNumber $diskNum
        $partList = @()
        foreach ($p in $parts) {
            $isApfs = ($p.GptType -eq '{7c3457ef-0000-11aa-aa11-00306543ecac}')
            $partDev = "\\\\.\\Harddisk$diskNum`Partition$($p.PartitionNumber)"
            $partList += @{
                PartitionNumber = $p.PartitionNumber
                DriveLetter = $p.DriveLetter
                Size = $p.Size
                Type = $p.Type
                GptType = $p.GptType
                IsAPFS = $isApfs
                DevicePath = $partDev
            }
        }
        $result += @{
            DeviceID = $d.DeviceID
            Index = $d.Index
            Model = $d.Model
            Size = $d.Size
            MediaType = $d.MediaType
            Partitions = $partList
            HasAPFS = ($partList | Where-Object { $_.IsAPFS -eq $true }).Count -gt 0
        }
    }
    $result | ConvertTo-Json -Depth 4
    """
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            if isinstance(data, dict):
                return [data]
            elif isinstance(data, list):
                return data
    except Exception as e:
        print(f"Failed to query physical drives via PS: {e}")
    return []
