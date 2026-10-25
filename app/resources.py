"""Local hardware inventory and conservative per-process compute budgets.

No identifiers, paths, accounts or hardware serial numbers are collected.
Thread budgets and low priority leave headroom; they are not CPU percent caps.
"""
from __future__ import annotations
import ctypes
import functools
import json
import os
import subprocess
import uuid

GIB = 1024**3


def memory_status():
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (key, ctypes.c_ulonglong) for key in
            ('total', 'available', 'page_total', 'page_available', 'virtual', 'virtual_available', 'extended')]
    if os.name != 'nt':
        return {'total': 0, 'available': 0}
    value = Memory(); value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return {'total': 0, 'available': 0}
    return {'total': int(value.total), 'available': int(value.available)}


def _gpu_inventory():
    """DXGI distinguishes real dedicated video memory from shared system RAM."""
    if os.name != 'nt': return []
    class Description(ctypes.Structure):
        _fields_ = [('name', ctypes.c_wchar*128), ('vendor', ctypes.c_uint),
                    ('device', ctypes.c_uint), ('subsystem', ctypes.c_uint), ('revision', ctypes.c_uint),
                    ('dedicated', ctypes.c_size_t), ('dedicated_system', ctypes.c_size_t),
                    ('shared', ctypes.c_size_t), ('luid_low', ctypes.c_uint),
                    ('luid_high', ctypes.c_int), ('flags', ctypes.c_uint)]
    def method(ptr, index, *args):
        table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *args)(table[index])
    factory = ctypes.c_void_p()
    guid = (ctypes.c_byte*16).from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    result = ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(guid), ctypes.byref(factory))
    if result < 0: return []
    adapters = []
    try:
        for index in range(16):
            adapter = ctypes.c_void_p()
            if method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(factory, index, ctypes.byref(adapter)) < 0: break
            try:
                desc = Description()
                if method(adapter, 10, ctypes.POINTER(Description))(adapter, ctypes.byref(desc)) >= 0 and not desc.flags & 2:
                    adapters.append({'name': desc.name, 'vendor': int(desc.vendor),
                                     'dedicated_vram': int(desc.dedicated), 'shared_ram_limit': int(desc.shared),
                                     'memory_source': 'DXGI', 'encoding_selected': False})
            finally: method(adapter, 2)(adapter)
    finally: method(factory, 2)(factory)
    unique={}
    for adapter in adapters:
        unique.setdefault((adapter['name'],adapter['vendor'],adapter['dedicated_vram'],adapter['shared_ram_limit']),adapter)
    return list(unique.values())


@functools.lru_cache(maxsize=1)
def detect_hardware():
    logical = max(1, os.cpu_count() or 2)
    result = {'cpu_name': '处理器', 'logical_cores': logical, 'physical_cores': 0,
              'gpus': [], 'memory': memory_status(), 'detection': 'partial'}
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                result['cpu_name'] = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError: pass
        try:
            response = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                'Get-CimInstance Win32_Processor | Select-Object NumberOfCores | ConvertTo-Json -Compress'],
                capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
            rows = json.loads(response.stdout)
            result['physical_cores'] = sum(int(x['NumberOfCores']) for x in (rows if isinstance(rows, list) else [rows]))
        except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired): pass
        try: result['gpus'] = _gpu_inventory()
        except (OSError, ValueError, AttributeError): pass
    result['detection'] = 'complete' if result['physical_cores'] and result['memory']['total'] and result['gpus'] else 'partial'
    return result


def balanced_plan(hardware, available=None):
    logical = max(1, int(hardware.get('logical_cores') or 2))
    physical = max(1, int(hardware.get('physical_cores') or max(1, logical//2)))
    memory = hardware.get('memory', {})
    total = max(0, int(memory.get('total') or 0))
    available = max(0, int(memory.get('available') or 0)) if available is None else max(0, int(available))
    reserve = min(8*GIB, max(1*GIB, total//4)) if total else 1*GIB
    budget = max(0, min(int(total*.5), available-reserve)) if total and available else 0
    encode = max(1, min(12, physical//2, max(1, logical-2)))
    if total and total < 8*GIB: encode = min(encode, 2)
    return {'mode': 'balanced', 'asr_threads': max(1, min(4, encode)), 'encode_threads': encode,
            'decode_threads': min(2, encode), 'filter_threads': min(2, encode),
            'memory_reserve_bytes': reserve, 'memory_budget_bytes': budget,
            'priority': 'below_normal', 'asr_device': 'cpu', 'compute_type': 'int8',
            'gpu_policy': '检测并显示；当前已验证后端使用 CPU，保留原编码画质',
            'limits': '线程与优先级预算不等于固定占用百分比；共享显存不是独立显存。'}


def describe(hardware, plan):
    memory = hardware.get('memory', {})
    ram = f"{memory.get('total',0)/GIB:.1f} GB" if memory.get('total') else '未知'
    gpu = '；'.join(f"{g['name']}（独立显存 {g['dedicated_vram']/GIB:.2f} GB，共享上限 {g['shared_ram_limit']/GIB:.1f} GB）" for g in hardware.get('gpus', [])) or '未能读取，采用保守预算'
    return (f"{hardware.get('cpu_name')} · {hardware.get('physical_cores') or '?'} 核 / {hardware.get('logical_cores')} 线程 · 内存 {ram}\n"
            f"{gpu}\n均衡：识别 {plan['asr_threads']} 线程，压制 {plan['encode_threads']} 线程，低优先级；"
            f"预留约 {plan['memory_reserve_bytes']/GIB:.1f} GB 内存。GPU 仅检测，当前后端使用 CPU。")
