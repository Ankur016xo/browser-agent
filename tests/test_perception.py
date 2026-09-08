"""
Tests for the PerceptionEngine, element extraction, and Set-of-Marks visual annotation.
"""
import unittest
from pathlib import Path
from PIL import Image
from browser_agent.perception import PerceptionEngine
from browser_agent.state import ElementInfo


class TestPerception(unittest.TestCase):

    def setUp(self):
        self.perception = PerceptionEngine()

    def test_format_elements_for_prompt(self):
        elements = [
            ElementInfo(
                id=1,
                tag="button",
                text="Search",
                element_type="submit",
                role="button",
                bbox=(10, 20, 100, 40),
                center=(60, 40),
            ),
            ElementInfo(
                id=2,
                tag="input",
                text="",
                element_type="text",
                attributes={"placeholder": "Enter search query..."},
                bbox=(120, 20, 200, 40),
                center=(220, 40),
            ),
        ]
        formatted = self.perception.format_elements_for_prompt(elements)
        self.assertIn("[1] button", formatted)
        self.assertIn("text='Search'", formatted)
        self.assertIn("[2] input", formatted)
        self.assertIn("placeholder='Enter search query...'", formatted)

    def test_annotate_screenshot(self):
        # Create a dummy image
        test_img_path = Path("test_dummy_screen.png")
        img = Image.new("RGB", (800, 600), color=(240, 240, 240))
        img.save(test_img_path)

        elements = [
            ElementInfo(
                id=1,
                tag="button",
                text="Click Me",
                bbox=(50, 50, 100, 40),
                center=(100, 70),
            ),
            ElementInfo(
                id=2,
                tag="a",
                text="Visit link",
                bbox=(200, 100, 150, 30),
                center=(275, 115),
            ),
        ]

        annotated_path = self.perception.annotate_screenshot(test_img_path, elements)
        self.assertTrue(annotated_path.exists())

        # Verify image was created and can be opened
        with Image.open(annotated_path) as annotated_img:
            self.assertEqual(annotated_img.size, (800, 600))

        # Cleanup
        if test_img_path.exists():
            test_img_path.unlink()
        if annotated_path.exists():
            annotated_path.unlink()


if __name__ == "__main__":
    unittest.main()
