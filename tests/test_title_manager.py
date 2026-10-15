import unittest
from title_manager import desired_titles, slot_titles


def row(text,x,y):
    return {'text':text,'center':(x,y)}


class TitleManagerTest(unittest.TestCase):
    def test_partial_ocr_name_and_empty_slot(self):
        rows=[row('LegendaryF',1331,1145),row('Fisherman',1476,1144),
              row('Salvager',1659,1145),row('One',1405,1180),
              row('Two',1659,1181),row('Three',1954,1181)]
        result=slot_titles(rows)
        self.assertEqual(result['One'][0],'Legendary Fisherman')
        self.assertEqual(result['Two'][0],'Salvager')
        self.assertIsNone(result['Three'][0])

    def test_best_titles_only_from_owned(self):
        self.assertEqual(desired_titles({'Angler','Salvager','Deep Water Angler'}),
                         ('Salvager','Deep Water Angler','Angler'))


if __name__=='__main__':unittest.main()


class CurrentTitleScreen(unittest.TestCase):
    def test_fishing_category_label_variants_and_luck_titles_lead(self):
        import re
        import title_manager
        pattern=r'Fishing\s*[\(\[]?\s*\d*\s*[\)\]]?'
        for text in ('Fishing (6)','Fishing(6)','Fishing [6]','Fishing'):
            self.assertTrue(re.fullmatch(pattern,text,re.I),text)
        self.assertFalse(re.fullmatch(pattern,'Fishing Permit',re.I))
        self.assertEqual(title_manager.desired_titles(set(title_manager.PRIORITY)),('Salvager','Legendary Fisherman','Leviathan Hunter'))
        luck=1.
        for name in title_manager.desired_titles(set(title_manager.PRIORITY)):luck*=title_manager.TITLE_BUFFS[name].get('fishing_luck',1)
        self.assertAlmostEqual(luck,1.08*1.07*1.05)


class TitleCatalog(unittest.TestCase):
    def test_buffs_are_read_from_the_detail_panel(self):
        from title_manager import parse_buffs
        rows=[{'text':'Legendary Fisherman','center':(2100,366)},{'text':'Buffs','center':(2060,640)},
              {'text':'1.07x (Fishing Luck','center':(2190,680)},{'text':'Factor)','center':(2120,718)},
              {'text':'1.05x (Bite Speed','center':(2180,760)},{'text':'Factor)','center':(2120,798)},
              {'text':'1.06x (Breath Duration','center':(2200,900)},{'text':'Factor)','center':(2120,938)}]
        self.assertEqual(parse_buffs(rows),{'fishing_luck':1.07,'bite_speed':1.05})

    def test_priority_picks_luck_or_bite_titles(self):
        from title_manager import desired_titles,PRIORITY
        owned=set(PRIORITY)
        self.assertEqual(desired_titles(owned,'luck'),('Salvager','Legendary Fisherman','Leviathan Hunter'))
        self.assertEqual(desired_titles(owned,'bite'),('Legendary Fisherman','Deep Water Angler','Angler'))
        new={**{n:{} for n in owned},'Salvager':{'fishing_luck':1.08},'Sea Sage':{'fishing_luck':1.2}}
        self.assertEqual(desired_titles(owned|{'Sea Sage'},'luck',new)[0],'Sea Sage')


class NewTitles(unittest.TestCase):
    def test_unknown_title_is_listed_kept_and_not_merged_into_a_known_one(self):
        from title_manager import listed_titles,canonical_title,category_count
        rows=[row('Angler',800,400),row('Deep Water Angler',1100,400),row('Leviathan H',1450,400),
              row('Legendary Fisherman',800,520),row('Salvager',1100,520),row('Master Angler',1450,520),
              row('One',1405,700),row('Buffs',2100,640)]
        names=[canonical_title(n) for n in listed_titles(rows)]
        self.assertEqual(names,['Angler','Deep Water Angler','Leviathan Hunter','Legendary Fisherman','Salvager','Master Angler'])
        self.assertEqual(category_count('Fishing (6)'),6)
        self.assertIsNone(category_count('Fishing'))

    def test_new_title_is_matched_in_a_slot_and_ranked(self):
        import title_manager
        names=title_manager.PRIORITY+('Master Angler',)
        rows=[row('Master Angler',1405,1145),row('One',1405,1180),
              row('Salvager',1659,1145),row('Two',1659,1181),
              row('Angler',1954,1145),row('Three',1954,1181)]
        slots=title_manager.slot_titles(rows,names)
        self.assertEqual([slots[s][0] for s in ('One','Two','Three')],['Master Angler','Salvager','Angler'])
        table=title_manager.known_buffs({'Master Angler':{'buffs':{'fishing_luck':1.1}}})
        best=title_manager.desired_titles(set(names),'luck',table)
        self.assertEqual(best,('Master Angler','Salvager','Legendary Fisherman'))
