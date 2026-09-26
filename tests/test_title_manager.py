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
