import unittest
from pickup_policy import classify_toast


def row(text, x, y, score=.98):
    return {'text': text, 'score': score, 'center': (x, y)}


class DropCastReceiptTest(unittest.TestCase):
    def test_despawn_countdown_beside_a_dropped_item_is_not_a_receipt(self):
        rows = [row('Metal Scraps', 300, 90), row('20', 200, 60)]
        self.assertEqual(classify_toast(rows, require_x=True).kind, 'empty')

    def test_real_receipt_still_confirms_with_x_prefix(self):
        rows = [row('Metal Scraps', 300, 90), row('X1', 420, 90)]
        receipt = classify_toast(rows, require_x=True)
        self.assertEqual((receipt.kind, receipt.text), ('reward', 'Metal Scraps X1'))


if __name__ == '__main__':
    unittest.main()
