from pathlib import Path
import importlib.util
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/migration/pwb_final_closure_matrix.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pwb_final_closure_matrix", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FinalClosureMatrixTest(unittest.TestCase):
    def test_matrix_covers_every_python_module_once(self):
        module = load_module()
        matrix = module.build_matrix(ROOT)
        sources = [row["python_source"] for row in matrix["rows"]]
        product_dir = module.python_product_dir(ROOT)
        prefix = "paleo_workbench/"
        expected = sorted(
            prefix + path.relative_to(product_dir).as_posix()
            for path in product_dir.rglob("*.py")
            if "__pycache__" not in path.parts
        )
        self.assertEqual(sources, expected)
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(matrix["summary"]["python_runtime_required"], 0)
        self.assertEqual(matrix["summary"]["python_modules_packaged"], 0)

    def test_classifications_are_closed_and_wiring_is_not_invented(self):
        module = load_module()
        matrix = module.build_matrix(ROOT)
        allowed = set(module.CLASSIFICATIONS)
        self.assertLessEqual(
            {row["final_classification"] for row in matrix["rows"]}, allowed
        )
        for row in matrix["rows"]:
            if row["final_classification"] == "NATIVE_PRODUCT":
                self.assertTrue(row["native_target_exists"])
                self.assertTrue(row["product_wired"])
                self.assertTrue(row["runtime_reachable"])
            if row["final_classification"] == "NATIVE_LIBRARY_NOT_WIRED":
                self.assertTrue(row["native_target_exists"])
                self.assertFalse(row["product_wired"])
                self.assertFalse(row["runtime_reachable"])
            self.assertFalse(row["native_target_built"])
            self.assertFalse(row["product_tested"])

    def test_root_features_are_declared_before_resolution(self):
        root_cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        features_cmake = (ROOT / "cmake/PwbFeatures.cmake").read_text(
            encoding="utf-8"
        )
        root_options = set(re.findall(r"option\((PWB_[A-Z0-9_]+)", root_cmake))
        declarations = set(
            re.findall(
                r"pwb_declare_feature\((PWB_[A-Z0-9_]+)", features_cmake
            )
        )
        report_only_match = re.search(
            r"set\(PWB_FEATURE_REPORT_ONLY(.*?)\)", features_cmake, re.DOTALL
        )
        self.assertIsNotNone(report_only_match)
        report_only = set(
            re.findall(r'"(PWB_[A-Z0-9_]+)"', report_only_match.group(1))
        )
        self.assertEqual(root_options - declarations - report_only, set())

        native_product = re.search(
            r"pwb_declare_feature\(PWB_BUILD_NATIVE_PRODUCT(.*?)"
            r"\n\n# Switches owned",
            features_cmake,
            re.DOTALL,
        )
        self.assertIsNotNone(native_product)
        for required in (
            "PWB_BUILD_PLATFORM",
            "PWB_BUILD_CONV_27",
            "PWB_BUILD_CONV_29",
            "PWB_BUILD_PROVIDERS",
            "PWB_BUILD_CLOSURE_SCIENCE",
        ):
            self.assertIn(required, native_product.group(1))

        product_cmake = (ROOT / "cmake/PwbNativeProduct.cmake").read_text(
            encoding="utf-8"
        )
        self.assertIn("PWB_NATIVE_PRODUCT_LINK_CLOSURE", product_cmake)
        self.assertIn("does not link ${_target}", product_cmake)
        self.assertIn("A feature switch alone is not", product_cmake)
        self.assertIn("accepted as product wiring.", product_cmake)

    def test_native_install_excludes_python_sources(self):
        install_cmake = (ROOT / "cmake/PwbInstall.cmake").read_text(
            encoding="utf-8"
        )
        self.assertIn('PATTERN "*.py" EXCLUDE', install_cmake)
        self.assertIn('PATTERN "*.pyc" EXCLUDE', install_cmake)
        self.assertIn('PATTERN "__pycache__" EXCLUDE', install_cmake)


if __name__ == "__main__":
    unittest.main()
