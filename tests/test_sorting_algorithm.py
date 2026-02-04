import unittest
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sorting import sorting_algorithm


class TestSortingAlgorithm(unittest.TestCase):
    def test_sorting_algorithm(self):
        # Test with a list of integers
        input_list = [5, 3, 8, 4, 2]
        expected_output = [2, 3, 4, 5, 8]
        self.assertEqual(sorting_algorithm(input_list), expected_output)

        # Test with an empty list
        input_list = []
        expected_output = []
        self.assertEqual(sorting_algorithm(input_list), expected_output)

        # Test with a list of one element
        input_list = [1]
        expected_output = [1]
        self.assertEqual(sorting_algorithm(input_list), expected_output)

        # Test with a list of strings
        input_list = ["banana", "apple", "cherry"]
        expected_output = ["apple", "banana", "cherry"]
        self.assertEqual(sorting_algorithm(input_list), expected_output)

        # Test with a list of floats
        input_list = [3.5, 1.2, 2.7, 4.1]
        expected_output = [1.2, 2.7, 3.5, 4.1]
        self.assertEqual(sorting_algorithm(input_list), expected_output)


if __name__ == "__main__":
    unittest.main()
