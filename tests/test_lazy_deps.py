"""Registration must survive missing optional image dependencies.

    python3 -m unittest discover -s tests -v

Hermes's capability probe imports klieg_tools (which imports the taste module) before any
tool runs. numpy and Pillow are optional: a missing one must not abort registration.
"""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class LazyImageDeps(unittest.TestCase):
    def test_taste_module_imports_without_numpy_or_pillow(self):
        """Simulate the deps being absent at import time."""
        import klieg_taste as T
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def blocked(name, *args, **kw):
            if name == "numpy" or name.startswith("PIL"):
                raise ImportError(f"blocked {name}")
            return real_import(name, *args, **kw)

        # Re-import the module fresh with numpy/PIL blocked.
        sys.modules.pop("klieg_taste", None)
        try:
            with mock.patch("builtins.__import__", side_effect=blocked):
                import klieg_taste as fresh
            self.assertTrue(hasattr(fresh, "register") or hasattr(fresh, "features"))
        finally:
            sys.modules.pop("klieg_taste", None)
            import klieg_taste  # noqa: F401 - restore for other tests

    def test_deps_helper_is_lazy(self):
        """The module-level namespace has no np/Image until a verb needs them."""
        import klieg_taste as T
        self.assertFalse(hasattr(T, "np"))
        self.assertFalse(hasattr(T, "Image"))
        self.assertTrue(callable(T._deps))


if __name__ == "__main__":
    unittest.main()
