import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
from types import SimpleNamespace

import ph8057_qualify as q

class TestAhdiAvoidance(unittest.TestCase):
    def test_random64k_does_not_write_sector_zero(self):
        targets = [SimpleNamespace(size=500_107_862_016) for _ in range(2)]
        ranges = q.rand64k_regions(targets)
        self.assertEqual(ranges, [(512*q.MIB, 256*q.MIB)]*2)
        self.assertTrue(all(offset > 0 and offset + size <= q.GIB
                            for offset, size in ranges))

    def test_random64k_rejects_too_small_disk(self):
        with self.assertRaises(q.Abort):
            q.rand64k_regions([SimpleNamespace(size=512*q.MIB)])

if __name__ == '__main__':
    unittest.main()
