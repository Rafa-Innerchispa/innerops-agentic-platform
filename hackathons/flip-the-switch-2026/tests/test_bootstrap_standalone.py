import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bootstrap_standalone", ROOT / "scripts/bootstrap_standalone.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class StandaloneExportTests(unittest.TestCase):
    def test_exports_clean_project_with_equal_checksums(self):
        with TemporaryDirectory() as folder:
            dst = Path(folder) / "clean_export"
            manifest = module.export_kit(ROOT, dst)
            self.assertIn("README.md", manifest)
            self.assertIn("scripts/preflight.py", manifest)
            self.assertEqual((dst / "README.md").read_bytes(), (ROOT / "README.md").read_bytes())
            self.assertGreaterEqual(len(manifest), 21)

    def test_refuses_overwrite(self):
        with TemporaryDirectory() as folder:
            dst = Path(folder) / "exists"
            dst.mkdir()
            with self.assertRaises(FileExistsError):
                module.export_kit(ROOT, dst)

    def test_refuses_export_into_self(self):
        with self.assertRaises(ValueError):
            module.export_kit(ROOT, ROOT / "nested_export")

    def test_missing_source_is_rejected(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                module.build_manifest(Path(folder))

    def test_source_symlink_is_rejected(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source"
            source.mkdir()
            for rel in module.REQUIRED:
                dst = source / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text("synthetic", encoding="utf-8")
            (source / "shortcut").symlink_to(source / "README.md")
            with self.assertRaises(ValueError):
                module.build_manifest(source)


if __name__ == "__main__":
    unittest.main()
