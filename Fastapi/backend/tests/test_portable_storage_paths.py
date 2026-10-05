"""Evidence storage paths must resolve on every platform the team uses.

The signatures file was once regenerated on Windows, which wrote
``generated\\artefacts\\...``. On macOS and Linux that names a file that does not
exist, so every artefact read as missing and RATIFY escalated clean products.
"""

import unittest

from ramify.data import seed


class TestStoragePathsArePortable(unittest.TestCase):
    def test_every_storage_path_uses_forward_slashes(self):
        for ref in seed.seed()["evidence"]:
            path = seed.evidence(ref).get("storage_path")
            if not path:
                continue
            with self.subTest(evidence=ref):
                self.assertNotIn("\\", path)

    def test_every_storage_path_names_a_shipped_artefact(self):
        for ref in seed.seed()["evidence"]:
            path = seed.evidence(ref).get("storage_path")
            if not path:
                continue
            with self.subTest(evidence=ref):
                self.assertTrue((seed.DATA_DIR / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
