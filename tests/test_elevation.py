import unittest


class ElevationTests(unittest.TestCase):
    def test_elevation_module_loads(self) -> None:
        # Basic test to ensure elevation module imports without errors
        from scribe import elevation
        self.assertTrue(callable(elevation.is_elevated))
        self.assertTrue(callable(elevation.relaunch_elevated))


if __name__ == "__main__":
    unittest.main()