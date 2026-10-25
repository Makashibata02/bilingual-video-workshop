"""Offline unit/GUI tests; use a fixture font on CI if CJK fonts are absent."""
from pathlib import Path
import os,sys,unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'tests')]
os.environ['PYTHONDONTWRITEBYTECODE']='1'

def run():
    import layout
    if not any((Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/n).is_file() for n in ['msyh.ttc','simhei.ttf']):
        from PIL import ImageFont
        fixture_fonts=[Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts/arial.ttf',Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
        fixture_font=next((p for p in fixture_fonts if p.is_file()),None)
        if fixture_font:
            layout.font_at=lambda size:ImageFont.truetype(str(fixture_font),size)
            print('Using a fixture font for geometry tests; this does not validate CJK glyph rendering.')
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(run())
