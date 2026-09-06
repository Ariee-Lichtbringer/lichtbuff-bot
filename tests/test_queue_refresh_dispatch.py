import ast
import unittest
from pathlib import Path
class QueueRefreshDispatch(unittest.TestCase):
    def test_existing_only_refresh_is_claimed_and_dispatched(self):
        source=(Path(__file__).resolve().parents[1]/'po_bot.py').read_text()
        tree=ast.parse(source)
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PoBotV2')
        loop=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='queue_loop')
        filters=[n.value for n in ast.walk(loop) if isinstance(n,ast.Constant) and isinstance(n.value,str) and 'po_offline_notice,' in n.value]
        self.assertTrue(any('raid_announcement_refresh' in x.split(',') for x in filters))
        branch=next(n for n in ast.walk(loop) if isinstance(n,ast.If) and ast.unparse(n.test)=="queue_type == 'raid_announcement_refresh'")
        calls=[n.func.attr for n in ast.walk(branch) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertIn('refresh_existing_post',calls)
        self.assertNotIn('create_or_replace_post',calls)
        self.assertTrue(any(isinstance(n,ast.Continue) for n in branch.body))
