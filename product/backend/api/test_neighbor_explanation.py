from unittest import TestCase
from .presentation import recommendation

class NeighborExplanationTests(TestCase):
    def test_phrase_only_for_nonzero_actual_historical_feature(self):
        base={'supplier_inn':'7707083893','scoring':{'score':0.015},'evidence':[]}
        phrase='Есть историческая поддержка по похожим закупкам с участием компании.'
        for value in [0, None, -1, 2, True, '0.5', float('nan')]:
            candidate={**base,'reasons':{'neighbor_lot_evidence':value}}
            self.assertNotIn(phrase,recommendation(candidate,0)['reason'])
        for value in [0.000001,0.5,1.0]:
            candidate={**base,'reasons':{'neighbor_lot_evidence':value}}
            self.assertIn(phrase,recommendation(candidate,0)['reason'])
            self.assertNotIn(phrase,recommendation(candidate,0,True)['reason'])
            self.assertEqual(recommendation(candidate,0)['score'],0.015)

    def test_registry_scope_is_user_facing_and_raw_notes_remain(self):
        notes=['Статус коллегой в этот импорт не проверялся.']
        match={'profile_id':'registry-test','registry_content_independently_verified':True,
               'identity':{'status':'official_registry_identity_evidenced','notes':notes},
               'registry_evidence':{'license_number':'123'},'freshness':{},'source_excerpt':'Лицензия'}
        candidate={'supplier_inn':'7707083893','item_evidence':[{'item_index':0,'matches':[match]}]}
        out=recommendation(candidate,0,True);scope=out['company']['sources'][0]['scope']
        self.assertIn('Статус ЕГРЮЛ и включение в МСП не проверены независимо.',scope)
        self.assertNotIn('коллегой',scope);self.assertNotIn('этот импорт',scope)
        self.assertEqual(out['rawEvidence']['item_evidence'][0]['matches'][0]['identity']['notes'],notes)
        self.assertIn('а не конкретный товар',scope)
