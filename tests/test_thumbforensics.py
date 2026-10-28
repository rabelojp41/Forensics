import hashlib
import json
import plistlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from thumbforensics import cli, phash, plugins
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
        make_ios_tree(self.src / "Media")

    def tearDown(self):
        self.tmp.cleanup()

    def test_status(self):
        self.assertEqual(cli.main(["analisar", str(self.src), "-o", str(self.out)]), 0)
        self.assertEqual(ios_status(self.out), EXPECTED_IOS)
        rows = json.loads((self.out / "relatorio.json").read_text(encoding="utf-8"))
        self.assertTrue(any(r["status"] == m.NAO_DECODIFICADO for r in rows))
        orfa = next(r for r in rows if r["status"] == m.ORFA)
        self.assertEqual((self.out / orfa["exportado"]).read_bytes(), fake_jpeg())
        self.assertIn("IMG_0004", (self.out / "relatorio.html").read_text(encoding="utf-8"))
        trashed = (self.out / "tabelas/ios_photos_assets.csv").read_text(encoding="utf-8")
        self.assertIn("2024-10-07", trashed)

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
            rows = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(1 for r in rows if r["offset"] != ""), 2)


def make_ios_tree(media: Path) -> None:
    v2 = media / "PhotoData/Thumbnails/V2/DCIM/100APPLE"
    for name in ["IMG_0001.HEIC", "IMG_0002.HEIC", "IMG_0003.HEIC", "IMG_0004.HEIC"]:
        (v2 / name).mkdir(parents=True)
        (v2 / name / "5005.JPG").write_bytes(fake_jpeg())
    (media / "DCIM/100APPLE").mkdir(parents=True)
    (media / "DCIM/100APPLE/IMG_0001.HEIC").write_bytes(b"orig")
    con = sqlite3.connect(media / "PhotoData/Photos.sqlite")
    con.execute("CREATE TABLE ZASSET (ZDIRECTORY TEXT, ZFILENAME TEXT, ZDATECREATED REAL, "
                "ZTRASHEDSTATE INT, ZTRASHEDDATE REAL)")
    con.executemany("INSERT INTO ZASSET VALUES ('DCIM/100APPLE', ?, 700000000, ?, ?)",
                    [("IMG_0001.HEIC", 0, None), ("IMG_0002.HEIC", 1, 750000000), ("IMG_0003.HEIC", 0, None)])
    con.commit()
    con.close()
    (media / "PhotoData/Thumbnails/3303.ithmb").write_bytes(b"\x00" * 64)


EXPECTED_IOS = {
    "IMG_0001.HEIC": m.PRESENTE,
    "IMG_0002.HEIC": m.LIXEIRA,
    "IMG_0003.HEIC": m.SO_MINIATURA,
    "IMG_0004.HEIC": m.ORFA,
}


def ios_status(out: Path) -> dict:
    rows = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
    return {r["original"].split("/")[-1]: r["status"] for r in rows if r["original"]}


class InputFormatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip(self):
        tree = self.t / "tree"
        make_ios_tree(tree / "private/var/mobile/Media")
        archive = shutil.make_archive(str(self.t / "ext"), "zip", tree)
        out = self.t / "out"
        self.assertEqual(cli.main(["analisar", archive, "-o", str(out)]), 0)
        self.assertEqual(ios_status(out), EXPECTED_IOS)
        self.assertFalse((out / "_trabalho").exists())

    def test_tar_gz(self):
        tree = self.t / "tree"
        make_ios_tree(tree / "private/var/mobile/Media")
        archive = shutil.make_archive(str(self.t / "ext"), "gztar", tree)
        out = self.t / "out"
        self.assertEqual(cli.main(["analisar", archive, "-o", str(out)]), 0)
        self.assertEqual(ios_status(out), EXPECTED_IOS)

    def test_itunes_backup(self):
        tree = self.t / "tree"
        make_ios_tree(tree / "Media")
        backup = self.t / "backup"
        backup.mkdir()
        con = sqlite3.connect(backup / "Manifest.db")
        con.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INT, file BLOB)")
        for i, f in enumerate(p for p in tree.rglob("*") if p.is_file()):
            file_id = hashlib.sha1(str(i).encode()).hexdigest()
            (backup / file_id[:2]).mkdir(exist_ok=True)
            shutil.copy(f, backup / file_id[:2] / file_id)
            con.execute("INSERT INTO Files VALUES (?, 'CameraRollDomain', ?, 1, NULL)",
                        (file_id, f.relative_to(tree).as_posix()))
        con.commit()
        con.close()
        with open(backup / "Manifest.plist", "wb") as fh:
            plistlib.dump({"IsEncrypted": False}, fh)
        out = self.t / "out"
        self.assertEqual(cli.main(["analisar", str(backup), "-o", str(out)]), 0)
        self.assertEqual(ios_status(out), EXPECTED_IOS)
        self.assertIn("private/var/mobile/Media/PhotoData/Photos.sqlite", (out / "custodia.txt").read_text(encoding="utf-8"))

    def test_encrypted_backup_refused(self):
        backup = self.t / "backup"
        backup.mkdir()
        sqlite3.connect(backup / "Manifest.db").close()
        with open(backup / "Manifest.plist", "wb") as fh:
            plistlib.dump({"IsEncrypted": True}, fh)
        self.assertEqual(cli.main(["analisar", str(backup), "-o", str(self.t / "out")]), 2)


class PluginTest(unittest.TestCase):
    def test_external_plugin_and_error_isolation(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "src/notes").mkdir(parents=True)
            (t / "src/notes/a.txt").write_text("olá", encoding="utf-8")
            (t / "plug").mkdir()
            (t / "plug/meu.py").write_text(
                "from thumbforensics.model import Result\n"
                "ARTIFACTS = {\n"
                "  'notas': {'name': 'Notas', 'description': 'd', 'platform': 'any', 'paths': ('*/notes/*.txt',)},\n"
                "  'quebrado': {'name': 'Q', 'description': 'd', 'platform': 'any', 'paths': ('*/notes/*',)},\n"
                "}\n"
                "def notas(ctx):\n"
                "    return Result(headers=['arquivo', 'texto'],\n"
                "                  rows=[[f, ctx.seeker.read(f).decode()] for f in ctx.files])\n"
                "def quebrado(ctx):\n"
                "    raise RuntimeError('falhou de propósito')\n", encoding="utf-8")
            out = t / "out"
            self.assertEqual(cli.main(["analisar", str(t / "src"), "-o", str(out),
                                       "--plugins", str(t / "plug")]), 0)
            self.assertIn("olá", (out / "tabelas/notas.csv").read_text(encoding="utf-8-sig"))
            html = (out / "relatorio.html").read_text(encoding="utf-8")
            self.assertIn("falhou de propósito", html)
            self.assertIn("quebrado: ERRO", (out / "custodia.txt").read_text(encoding="utf-8"))

    def test_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "dup.py").write_text(
                "ARTIFACTS = {'ios_ithmb': {'name': 'x', 'description': 'd', 'platform': 'ios', 'paths': ()}}\n"
                "def ios_ithmb(ctx): pass\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                plugins.load([Path(t)])


class MediaStoreTest(unittest.TestCase):
    def test_orphan_via_external_db(self):
        with tempfile.TemporaryDirectory() as t:
            src, out = Path(t) / "ext", Path(t) / "out"
            th = src / "media/0/DCIM/.thumbnails"
            th.mkdir(parents=True)
            (th / "111.jpg").write_bytes(fake_jpeg())
            (th / "222.jpg").write_bytes(fake_jpeg(b"z" * 700))
            (th / "333.jpg").write_bytes(fake_jpeg(b"w" * 700))
            db = src / "data/data/com.android.providers.media/databases"
            db.mkdir(parents=True)
            con = sqlite3.connect(db / "external.db")
            con.execute("CREATE TABLE files (_id INTEGER, _data TEXT)")
            con.execute("CREATE TABLE thumbnails (_data TEXT, image_id INTEGER)")
            con.execute("INSERT INTO files VALUES (1, '/storage/emulated/0/DCIM/Camera/a.jpg')")
            con.executemany("INSERT INTO thumbnails VALUES (?, ?)", [
                ("/storage/emulated/0/DCIM/.thumbnails/111.jpg", 1),
                ("/storage/emulated/0/DCIM/.thumbnails/222.jpg", 2)])
            con.commit()
            con.close()
            self.assertEqual(cli.main(["analisar", str(src), "-o", str(out)]), 0)
            rows = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
            status = {Path(r["origem"]).name: r["status"] for r in rows}
            self.assertEqual(status, {"111.jpg": m.PRESENTE, "222.jpg": m.ORFA, "333.jpg": m.DESCONHECIDO})


class DeviceCheckTest(unittest.TestCase):
    def test_ios(self):
        from thumbforensics.acquire import _check_ios
        ok, msg = _check_ios(0, '[{"DeviceName": "iPhone do JP", "Identifier": "abc"}]', "")
        self.assertTrue(ok)
        self.assertIn("iPhone do JP", msg)
        self.assertFalse(_check_ios(0, "[]", "")[0])
        self.assertIn("Apple Devices", _check_ios(1, "", "erro")[1])

    def test_android(self):
        from thumbforensics.acquire import _check_android
        head = "List of devices attached\n"
        self.assertTrue(_check_android(0, head + "R58M123\tdevice")[0])
        ok, msg = _check_android(0, head + "R58M123\tunauthorized")
        self.assertFalse(ok)
        self.assertIn("aceite", msg)
        self.assertFalse(_check_android(0, head)[0])

    def test_missing_tool(self):
        from unittest import mock
        from thumbforensics import acquire
        with mock.patch.object(acquire.shutil, "which", return_value=None):
            ok, msg = acquire.check("ios")
        self.assertFalse(ok)
        self.assertIn("pip install pymobiledevice3", msg)


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
            rows = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["status"], m.PRESENTE)
            self.assertIn("IMG_renomeada.jpg", rows[0]["nota"])


if __name__ == "__main__":
    unittest.main()
