"""Named OpenAI-compatible translation profiles; Windows DPAPI protects keys."""
from __future__ import annotations
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path


def _dpapi(data: bytes, decrypt=False) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('保存密钥需要 Windows 的账户加密功能。')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    raw=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)))
    target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    if decrypt:
        fn=crypt.CryptUnprotectData
        fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    else:
        fn=crypt.CryptProtectData
        fn.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise RuntimeError('Windows 无法'+('读取' if decrypt else '加密')+'密钥，请在当前 Windows 账户下重新填写。')
    try:return ctypes.string_at(target.data,target.size)
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree
        free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
        free(target.data)


class ProfileStore:
    def __init__(self, folder):
        self.path=Path(folder)/'profiles.json'
        if self.path.exists():
            self.data=json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('schema')!=1 or not isinstance(self.data.get('profiles'),list):
                raise ValueError('翻译方案文件格式不正确，请保留文件并联系维护者。')
        else:self.data={'schema':1,'profiles':[],'model_codes':{},'next_code':10}

    def _write(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,self.path)

    def code_for(self,base,model):
        signature=hashlib.sha256(json.dumps([base.rstrip('/'),model],ensure_ascii=False).encode()).hexdigest()
        if signature not in self.data['model_codes']:
            self.data['model_codes'][signature]=self.data['next_code']
            self.data['next_code']+=1
            self._write()
        return self.data['model_codes'][signature]

    def list(self):
        return [{k:v for k,v in p.items() if k!='encrypted_key'} for p in self.data['profiles']]

    def save(self,name,base,model,key):
        from engine import _validate_api_base
        name=name.strip();base=_validate_api_base(base);model=model.strip();key=key.strip()
        if not name or not model or not key:raise ValueError('方案名称、模型名称和密钥都需要填写。')
        encrypted=base64.b64encode(_dpapi(key.encode('utf-8'))).decode('ascii')
        code=self.code_for(base,model)
        item={'name':name,'api_base':base,'model_name':model,'profile_code':code,'encrypted_key':encrypted}
        self.data['profiles']=[p for p in self.data['profiles'] if p['name']!=name]+[item]
        self._write()
        return code

    def load(self,name):
        found=next(p for p in self.data['profiles'] if p['name']==name)
        return {k:v for k,v in found.items() if k!='encrypted_key'} | {'api_key':_dpapi(base64.b64decode(found['encrypted_key']),True).decode('utf-8')}

    def delete(self,name):
        self.data['profiles']=[p for p in self.data['profiles'] if p['name']!=name]
        self._write()
