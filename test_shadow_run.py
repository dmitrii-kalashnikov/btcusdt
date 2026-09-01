import unittest
import pandas as pd
import shadow_sources as s
import shadow_model as m
import shadow_score as q
class ShadowTests(unittest.TestCase):
    def test_contract(self): self.assertEqual(len(s.MACRO_FEATURES),39); self.assertEqual(len(set(s.MACRO_FEATURES)),39)
    def test_probability_bounds(self):
        for x in (-2,-.1,0,.1,2): self.assertTrue(0<=m.p_up(x,.5)<=1)
    def test_no_auto_promotion(self):
        z=pd.DataFrame(columns=['scope','horizon_days','model','n','directional_accuracy','mae_log_return','rmse_log_return','brier_up']); r=q.promotion(z,'INSUFFICIENT_DATA'); self.assertEqual(r['status'],'INSUFFICIENT_DATA'); self.assertFalse(r['auto_promoted'])
if __name__=='__main__': unittest.main()
