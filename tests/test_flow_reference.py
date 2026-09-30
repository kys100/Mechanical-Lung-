import unittest
from peak_detection import standard_flow
class FlowReference(unittest.TestCase):
    def test_conversion(self):
        self.assertEqual(standard_flow(10,20,1013),10)
        self.assertAlmostEqual(standard_flow(10,25,1013),10*293.15/298.15)
        self.assertAlmostEqual(standard_flow(10,30,1013),10*293.15/303.15)
        self.assertEqual(standard_flow(-10,20,2026),-20)
        self.assertIsNone(standard_flow(10,None,None))
    def test_invalid_pairs(self):
        for t,p in [(20,None),(None,1013),(-273.15,1013),(20,0),(float('nan'),1013),(20,float('inf'))]:
            with self.assertRaises(ValueError):standard_flow(10,t,p)
