import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from thumbforensics import cli, phash
from thumbforensics import model as m
from thumbforensics.carve import carve_jpegs


def fake_jpeg(payload: bytes = b"x" * 600) -> bytes:
    # SOI, APP0 mínimo, SOS, dados, EOI
    app0 = b"\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 9
    sos = b"\xff\xda\x00\x08" + b"\x01\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + app0 + sos + payload + b"\xff\xd9"


class CarveTest(unittest.TestCase):
    def test_carves_concatenated(self):
        a, b = fake_jpeg(b"a" * 700), fake_jpeg(b"b" * 900)
        blob = b"\x00" * 10 + a + b"lixo" + b
        found = list(carve_jpegs(blob))
        self.assertEqual([x[1] for x in found], [a, b])
        self.assertEqual(found[0][0], 10)

    def test_ignores_truncated(self):
        self.assertEqual(list(carve_jpegs(fake_jpeg()[:-2])), [])


class IOSTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.src, self.out = t / "ext", t / "out"
        media = self.src / "Media"
        v2 = media / "PhotoData/Thumbnails/V2/DCIM/100APPLE"
        for name in ["IMG_0001.HEIC", "IMG_0002.HEIC", "IMG_0003.HEIC", "IMG_0004.HEIC"]:
            (v2 / name).mkdir(parents=True)
            (v2 / name / "5005.JPG").write_bytes(fake_jpeg())
        (media / "DCIM/100APPLE").mkdir(parents=True)
        (media / "DCIM/100APPLE/IMG_0001.HEIC").write_bytes(b"orig")
        con = sqlite3.connect(media / "PhotoData/Photos.sqlite")
        con.execute("CREATE TABLE ZASSET (ZDIRECTORY TEXT, ZFILENAME TEXT, ZTRASHEDSTATE INT)")
        con.executemany("INSERT INTO ZASSET VALUES ('DCIM/100APPLE', ?, ?)",
                        [("IMG_0001.HEIC", 0), ("IMG_0002.HEIC", 1), ("IMG_0003.HEIC", 0)])
        con.commit()
        con.close()
        (media / "PhotoData/Thumbnails/3303.ithmb").write_bytes(b"\x00" * 64)

    def tearDown(self):
        self.tmp.cleanup()

    def test_status(self):
        self.assertEqual(cli.main(["analisar", str(self.src), "-o", str(self.out)]), 0)
        rows = json.loads((self.out / "relatorio.json").read_text())
        status = {r["original"].split("/")[-1]: r["status"] for r in rows if r["original"]}
        self.assertEqual(status, {
            "IMG_0001.HEIC": m.PRESENTE,
            "IMG_0002.HEIC": m.LIXEIRA,
            "IMG_0003.HEIC": m.SO_MINIATURA,
            "IMG_0004.HEIC": m.ORFA,
        })
        self.assertTrue(any(r["status"] == m.NAO_DECODIFICADO for r in rows))
        orfa = next(r for r in rows if r["status"] == m.ORFA)
        self.assertEqual((self.out / orfa["exportado"]).read_bytes(), fake_jpeg())
        self.assertIn("IMG_0004", (self.out / "relatorio.html").read_text())

    def test_refuses_output_inside_source(self):
        self.assertEqual(cli.main(["analisar", str(self.src), "-o", str(self.src / "x")]), 2)


class AndroidTest(unittest.TestCase):
    def test_thumbnails_and_thumbdata(self):
        with tempfile.TemporaryDirectory() as t:
            src, out = Path(t) / "ext", Path(t) / "out"
            th = src / "DCIM/.thumbnails"
            th.mkdir(parents=True)
            (th / "1234.jpg").write_bytes(fake_jpeg())
            (th / ".thumbdata3-1967290299").write_bytes(fake_jpeg(b"1" * 800) + b"\x00" * 50 + fake_jpeg(b"2" * 800))
            self.assertEqual(cli.main(["analisar", str(src), "-o", str(out)]), 0)
            rows = json.loads((out / "relatorio.json").read_text())
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(1 for r in rows if r["offset"] != ""), 2)


@unittest.skipUnless(phash.available(), "Pillow não instalado")
class PhashTest(unittest.TestCase):
    def test_match_renamed_original(self):
        import io
        from PIL import Image
        with tempfile.TemporaryDirectory() as t:
            src, out = Path(t) / "ext", Path(t) / "out"
            img = Image.new("RGB", (400, 300))
            for x in range(400):
                for y in range(0, 300, 10):
                    img.putpixel((x, y), (x % 256, 255 - x % 256, 90))
            (src / "DCIM/Camera").mkdir(parents=True)
            img.save(src / "DCIM/Camera/IMG_renomeada.jpg")
            th = src / "DCIM/.thumbnails"
            th.mkdir()
            buf = io.BytesIO()
            img.resize((96, 72)).save(buf, "JPEG")
            (th / "99.jpg").write_bytes(buf.getvalue())
            self.assertEqual(cli.main(["analisar", str(src), "-o", str(out), "--phash"]), 0)
            rows = json.loads((out / "relatorio.json").read_text())
            self.assertEqual(rows[0]["status"], m.PRESENTE)
            self.assertIn("IMG_renomeada.jpg", rows[0]["nota"])


if __name__ == "__main__":
    unittest.main()
