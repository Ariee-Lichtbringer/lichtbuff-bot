import ast
import unittest
from datetime import datetime
from pathlib import Path
import pytz

class ActiveSignupTests(unittest.TestCase):
    def test_future_closed_signup_remains_refreshable(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'po_bot.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_raid_is_inactive','_active_signup_refresh_allowed'}]
        scope=dict(datetime=datetime,pytz=pytz,clean=lambda v:str(v or '').strip())
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'refresh-test','exec'),scope)
        allowed=scope['_active_signup_refresh_allowed']
        raid=dict(raidDate='2099-01-01',raidTime='21:00')
        for status in ['offen','geschlossen','closed']:
            self.assertTrue(allowed(dict(raid,status=status)))
        for status in ['archiviert','deleted','abgesagt','completed','beendet']:
            self.assertFalse(allowed(dict(raid,status=status)))
        self.assertFalse(allowed(dict(raid,status='geschlossen',raidDate='2000-01-01')))
        self.assertFalse(allowed(dict(raid,deletedAt='2026-01-01')))
        self.assertFalse(allowed(dict(raid,raidTime='invalid')))

if __name__=='__main__':unittest.main()
