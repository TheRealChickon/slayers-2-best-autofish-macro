"""Budget limits, transaction ambiguity and CLI dispatch without game input."""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch
import numpy as np
import bait_buy as bait
import fishing_cli


class BaitPurchase(unittest.TestCase):
    def test_quote_requires_exact_quantity_and_price_with_real_ocr_spacing(self):
        self.assertTrue(bait.quote_matches('99piece(s)then.Thatwillbe$891forthelot.Deal?',99))
        self.assertTrue(bait.quote_matches('46 piece(s) then. That will be <414 for the lot.',46))
        for text in ('99 pieces then. That will be $91 for the lot.',
                     '9 pieces then. That will be $891 for the lot.',
                     '99 pieces then. That will be $8910 for the lot.'):
            self.assertFalse(bait.quote_matches(text,99))

    def test_gold_recognition_requires_agreement_and_confidence(self):
        d=Mock(); frame=np.zeros((1440,2560,3),np.uint8)
        frame[1040:1060,1570:1690]=(0,255,255)
        d.ocr.side_effect=[([['491,612',.99]],None),([['491612',.99]],None)]
        self.assertEqual(bait.currency(d,frame),491612)
        d.ocr.side_effect=[([['491,612',.99]],None),([['491,812',.99]],None)]
        with patch.object(bait.cv2,'imwrite'),self.assertRaises(ValueError):bait.currency(d,frame)
        d.ocr.side_effect=[([['491,612',.6]],None),([['491612',.99]],None)]
        with patch.object(bait.cv2,'imwrite'),self.assertRaises(ValueError):bait.currency(d,frame)

    def test_button_matching_tolerates_spacing_but_refuses_duplicates(self):
        self.assertEqual(bait.find([{'text':'Buy more','center':(1,2)}],'Buy more'),(1,2))
        self.assertEqual(bait.find([{'text':'Letmelookagain','center':(1,2)}],'Let me look again'),(1,2))
        self.assertIsNone(bait.find([{'text':'Deal','center':(1,2)},{'text':'Deal','center':(3,4)}],'Deal'))

    def test_resume_verifies_pending_debit_and_plans_only_remaining_quantity(self):
        previous={'quantity':198,'bought':0,'spent':0,'gold_remaining':5000,'gold_start':5000,
            'started':1,'stage':'stopped','pending':True,'gold_before':5000,
            'pending_quantity':99,'pending_price':891}
        d=Mock(); frame=np.zeros((1440,2560,3),np.uint8)
        with patch.object(bait,'read',side_effect=lambda name:previous if name=='bait-buy-status.json' else {}),\
                patch.object(bait,'Buyer',return_value=d),patch.object(bait,'words',return_value=[]),\
                patch.object(bait,'ready_shop',return_value=(frame,[])),\
                patch.object(bait,'read_gold',return_value=4109),patch.object(bait,'write'),\
                patch.object(bait.cv2,'imwrite'),patch.object(bait,'purchase') as purchase,\
                contextlib.redirect_stdout(io.StringIO()):
            bait.buy(resume=True)
        self.assertEqual(purchase.call_args.args[1],[99])
        self.assertEqual(purchase.call_args.args[2]['bought'],99)
        self.assertEqual(purchase.call_args.args[2]['spent'],891)

    def test_new_remaining_budget_is_applied_after_pending_reconciliation(self):
        previous={'quantity':22222,'bought':3564,'spent':32076,'gold_remaining':469337,
            'gold_start':501413,'started':1,'stage':'stopped','pending':True,
            'gold_before':469337,'pending_quantity':99,'pending_price':891}
        d=Mock(); frame=np.zeros((1440,2560,3),np.uint8)
        with patch.object(bait,'read',return_value=previous),patch.object(bait,'Buyer',return_value=d),\
                patch.object(bait,'words',return_value=[]),patch.object(bait,'ready_shop',return_value=(frame,[])),\
                patch.object(bait,'read_gold',return_value=468446),patch.object(bait,'write'),\
                patch.object(bait.cv2,'imwrite'),patch.object(bait,'purchase') as purchase,\
                contextlib.redirect_stdout(io.StringIO()):
            bait.buy(budget=169000,resume=True)
        batches,result=purchase.call_args.args[1:3]
        self.assertEqual(sum(batches)*9,168993)
        self.assertEqual(result['bought'],3663)
        self.assertEqual(result['quantity'],22440)
        self.assertEqual(result['gold_remaining']-sum(batches)*9,299453)

    def test_failed_buy_never_starts_full_farmer(self):
        import control_actions
        with patch.object(bait,'buy',side_effect=ValueError('unverified debit')),\
                patch.object(control_actions,'restart_full') as restart:
            self.assertEqual(fishing_cli.main(['bait','buy','--budget','169k','--then-full','--overnight']),1)
        restart.assert_not_called()

    def test_completed_buy_releases_driver_before_starting_full(self):
        import control_actions
        with patch.object(bait,'buy',return_value={'stage':'complete'}) as buy,\
                patch.object(control_actions,'restart_full',return_value='started') as restart,\
                contextlib.redirect_stdout(io.StringIO()):
            fishing_cli.main(['bait','buy','--quantity','99','--then-full','--overnight'])
        buy.assert_called_once_with(99,None,check=False)
        restart.assert_called_once_with(overnight=True)

    def test_full_restart_command_is_explicit_and_dispatches_through_controls(self):
        import control_actions
        with patch.object(control_actions,'restart_full',return_value='started') as restart,\
                contextlib.redirect_stdout(io.StringIO()):
            fishing_cli.main(['full','--restart','--overnight'])
        restart.assert_called_once_with(overnight=True)

    def test_restart_does_not_interrupt_an_active_buyer(self):
        import control_actions
        with patch.object(control_actions,'guard',contextlib.nullcontext),\
                patch.object(control_actions,'refuse_peer_controller'),\
                patch.object(control_actions,'alive',side_effect=lambda name:name=='bait-driver-pid.json'),\
                patch.object(control_actions,'pause') as pause,patch.object(control_actions,'resume') as resume:
            with self.assertRaises(RuntimeError):control_actions.restart_full(overnight=True)
        pause.assert_not_called();resume.assert_not_called()

    def test_terminal_menu_exposes_amount_buy_and_full_restart(self):
        import terminal_app
        import app_config
        import control_actions
        app=terminal_app.Terminal.__new__(terminal_app.Terminal)
        app.config={**app_config.DEFAULTS,'bait_buy_amount':169000,'bait_buy_then_full':True}
        app.data={};app.reference_position=False;app.page=3;app.scroll=0
        app.selection=app.settings_keys.index('Buy bait now')
        with patch.object(terminal_app,'read',return_value={}):
            rendered='\n'.join(terminal_app.ANSI.sub('',r) for r in app.body(100))
        for label in ('Purchase amount','169,000','Gold budget','Buy bait now','Reset + start Full farmer'):
            self.assertIn(label,rendered)
        app.job=lambda fn:fn()
        with patch.object(bait,'launch',return_value='launched') as launch:
            app.activate()
            launch.assert_called_once_with(then_full=True,budget=169000)
        app.page=0;app.selection=len(app.run_modes)+3
        with patch.object(control_actions,'restart_full',return_value='started') as restart:
            app.activate()
        restart.assert_called_once_with()

    def test_budget_never_rounds_up_and_quantity_is_exact(self):
        batches=bait.plan(budget=200000)
        self.assertEqual(sum(batches),22222)
        self.assertEqual(sum(batches)*9,199998)
        self.assertEqual(batches[-1],46)
        self.assertEqual(sum(bait.plan(quantity=1000)),1000)
        self.assertEqual(bait.amount('200k'),200000)
        for kwargs in ({},{'budget':8},{'quantity':0},{'budget':9,'quantity':1}):
            with self.assertRaises(ValueError): bait.plan(**kwargs)

    def test_ambiguous_or_changed_debit_stops_after_one_deal(self):
        d=Mock(); frame=np.zeros((1440,2560,3),np.uint8)
        rows=[{'text':'Buy more','center':(1700,1200)}]
        result={'gold_remaining':5000,'bought':0,'spent':0}
        saved=[]
        with patch.object(bait,'choose',return_value=(1700,1200)), \
                patch.object(bait,'wait_rows',return_value=(frame,rows)), \
                patch.object(bait,'currency',return_value=4000):
            with self.assertRaisesRegex(ValueError,'uncertain'):
                bait.purchase(d,[99,99],result,lambda value:saved.append(dict(value)))
        self.assertTrue(saved[0]['pending'])
        self.assertEqual(d.click.call_count,2) # Deal once and Buy more once.
        self.assertEqual(result['bought'],0)

    def test_confirmed_debit_accounts_only_exact_quantity(self):
        d=Mock(); frame=np.zeros((1440,2560,3),np.uint8)
        result={'gold_remaining':5000,'bought':0,'spent':0}
        with patch.object(bait,'choose',return_value=(1700,1200)), \
                patch.object(bait,'wait_rows',return_value=(frame,[{'text':'Buy more','center':(1700,1200)}])), \
                patch.object(bait,'currency',side_effect=[4109,3695]):
            bait.purchase(d,[99,46],result,Mock())
        self.assertEqual(result['bought'],145)
        self.assertEqual(result['spent'],1305)
        self.assertFalse(result['pending'])

    def test_cli_budget_and_quantity_dispatch(self):
        with patch.object(bait,'buy',return_value={'stage':'complete'}) as buy,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fishing_cli.main(['bait','buy','--budget','200k']),0)
            buy.assert_called_once_with(None,200000,check=False)
        with self.assertRaises(SystemExit):
            fishing_cli.parser().parse_args(['bait','buy','--budget','100','--quantity','10'])

    def test_pending_transaction_blocks_input_initialization(self):
        with patch.object(bait,'read',return_value={'pending':True}),patch.object(bait,'Buyer') as driver:
            with self.assertRaisesRegex(ValueError,'unresolved'): bait.buy(budget=100)
            driver.assert_not_called()

    def test_dialogue_speed_click_never_targets_deal(self):
        d=Mock()
        rows=[{'text':'Baitmonger Nori','center':(1200,1100)}]
        with patch.object(bait,'words',return_value=rows),patch.object(bait.time,'monotonic',side_effect=[0,1,8]),patch.object(bait.cv2,'imwrite'):
            with self.assertRaises(ValueError):bait.wait_rows(d,lambda r:False,advance=True)
        d.tap.assert_called_once_with(1280,1240)


if __name__=='__main__':unittest.main()
