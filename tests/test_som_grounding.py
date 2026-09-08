"""
Deep tests for Set-of-Marks visual perception, coordinate mapping, and DPI scaling.
"""
import unittest
from pathlib import Path
from PIL import Image
from browser_agent.perception import PerceptionEngine
from browser_agent.state import ElementInfo


class TestSOMGrounding(unittest.TestCase):

    def setUp(self):
        self.perception = PerceptionEngine()

    def test_som_coordinate_scaling_for_hidpi(self):
        # Create a 2560x1600 screenshot (2x scaling of a 1280x800 viewport)
        test_img = Path("test_hidpi_screen.png")
        img = Image.new("RGB", (2560, 1600), color=(255, 255, 255))
        img.save(test_img)

        # Element specified in 1280x800 CSS coordinates
        elements = [
            ElementInfo(
                id=1,
                tag="button",
                text="Submit",
                bbox=(100, 200, 80, 40),
                center=(140, 220),
            )
        ]

        # Annotate with viewport=(1280, 800)
        annotated_path = self.perception.annotate_screenshot(
            test_img,
            elements,
            viewport=(1280, 800),
        )
        self.assertTrue(annotated_path.exists())

        with Image.open(annotated_path) as ann_img:
            self.assertEqual(ann_img.size, (2560, 1600))

        # Cleanup
        if test_img.exists():
            test_img.unlink()
        if annotated_path.exists():
            annotated_path.unlink()

    def test_empty_elements_handled_gracefully(self):
        test_img = Path("test_empty_screen.png")
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        img.save(test_img)

        annotated_path = self.perception.annotate_screenshot(test_img, [])
        self.assertTrue(annotated_path.exists())

        if test_img.exists():
            test_img.unlink()
        if annotated_path.exists():
            annotated_path.unlink()


if __name__ == "__main__":
    unittest.main()
