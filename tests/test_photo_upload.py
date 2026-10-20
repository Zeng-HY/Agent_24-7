import io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import pillow_heif
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_control import Bridge,ControlError
pillow_heif.register_heif_opener()

class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.bridge=Bridge();self.bridge.data_root=Path(self.temp.name)
        self.find=patch('codex_control.chats.find',return_value={'id':'test'});self.find.start()
    def tearDown(self):self.find.stop();self.temp.cleanup()
    def encode(self,fmt,**options):
        b=io.BytesIO();Image.new('RGB',(32,24),'red').save(b,format=fmt,**options);return b.getvalue()
    def uploaded(self,raw):
        meta=self.bridge.upload('test','camera-photo.jpg',raw)
        with Image.open(self.bridge.data_root/meta['id']/'image.png') as image:return meta,image.copy()
    def test_mpo_jpeg_uses_primary_photo(self):
        raw=self.encode('MPO',save_all=True,append_images=[Image.new('RGB',(8,8),'blue')])
        with Image.open(io.BytesIO(raw)) as source:self.assertEqual(source.format,'MPO');self.assertEqual(source.n_frames,2)
        meta,image=self.uploaded(raw);self.assertEqual(image.size,(32,24));self.assertGreater(image.getpixel((0,0))[0],240)
        stored=json.loads((self.bridge.data_root/meta['id']/'meta.json').read_text(encoding='utf-8'));self.assertEqual(stored['source_format'],'MPO')
    def test_heif_collection_respects_selected_primary(self):
        raw=self.encode('HEIF',save_all=True,append_images=[Image.new('RGB',(8,10),'blue')],primary_index=1)
        with Image.open(io.BytesIO(raw)) as source:self.assertEqual(source.n_frames,2);self.assertEqual(source.size,(8,10))
        _,image=self.uploaded(raw);self.assertEqual(image.size,(8,10));self.assertGreater(image.getpixel((0,0))[2],240)
    def test_supported_single_photos_and_rotation(self):
        for fmt in ('JPEG','PNG','WEBP','HEIF'):
            with self.subTest(fmt=fmt):self.assertEqual(self.uploaded(self.encode(fmt))[1].size,(32,24))
        exif=Image.Exif();exif[274]=6
        self.assertEqual(self.uploaded(self.encode('JPEG',exif=exif))[1].size,(24,32))
    def test_distinct_errors_and_animation_guard(self):
        with self.assertRaisesRegex(ControlError,'BMP'):self.uploaded(self.encode('BMP'))
        raw=self.encode('PNG',save_all=True,append_images=[Image.new('RGB',(32,24),'blue')],duration=100)
        with self.assertRaisesRegex(ControlError,'动画'):self.uploaded(raw)
        with self.assertRaisesRegex(ControlError,'无法读取图片'):self.uploaded(b'not an image')
        class Oversize:
            format='JPEG';width=10000;height=6000
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('PIL.Image.open',return_value=Oversize()):
            with self.assertRaisesRegex(ControlError,'10000×6000.*5000 万像素'):self.uploaded(b'fixture')

if __name__=='__main__':unittest.main()
