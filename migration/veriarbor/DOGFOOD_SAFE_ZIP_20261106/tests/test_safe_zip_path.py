import unittest
from safe_zip_path import normalize_entry


class SafeZipPathTests(unittest.TestCase):
    def test_plain_path(self):
        self.assertEqual(normalize_entry("docs/readme.txt"), "docs/readme.txt")

    def test_backslash_is_separator(self):
        self.assertEqual(normalize_entry("docs\\readme.txt"), "docs/readme.txt")

    def test_dot_leading_segment_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_entry("./readme.txt")

    def test_parent_traversal_is_rejected(self):
        for value in ("../secret", "a/../../secret", "a/../secret"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_entry(value)

    def test_absolute_paths_are_rejected(self):
        for value in ("/etc/passwd", "\\windows\\system32", "C:\\temp\\x"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_entry(value)

    def test_nul_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_entry("a\x00b")

    def test_empty_and_dot_are_rejected(self):
        for value in ("", ".", "a//b", "a/"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_entry(value)

    def test_non_string_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_entry(None)


if __name__ == "__main__":
    unittest.main()
