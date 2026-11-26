"""Execute with python maintenance/test_rollback.py from the repository root."""
import ast
import copy
import subprocess
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


class Session(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Compatibility(unittest.TestCase):
    def test_round_trip(self):
        root = Path(__file__).resolve().parents[1]
        current = (root / 'app.py').read_text()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.py'
            path.write_text(current)
            patch = root / 'maintenance/rollback-v33.1.patch'
            subprocess.run(['git', 'apply', str(patch)], cwd=folder, check=True)
            rollback = path.read_text()
            compile(rollback, 'app.py', 'exec')
            self.assertNotIn('def _render_finances()', rollback)
            subprocess.run(['git', 'apply', '--reverse', str(patch)], cwd=folder, check=True)
            self.assertEqual(path.read_text(), current)

        database = {}
        def session(source, owner):
            state = Session()
            def request(method, path, payload=None, *args, **kwargs):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
                if method in ('GET', 'PATCH'):
                    self.assertEqual(query['owner_id'], ['eq.' + owner])
                if method == 'GET':
                    return [copy.deepcopy(database[owner])] if owner in database else []
                self.assertEqual(payload['owner_id'], owner)
                if method == 'PATCH':
                    if query['updated_at'] != ['eq.' + database[owner]['updated_at']]:
                        return []
                else:
                    self.assertEqual(method, 'POST')
                    self.assertNotIn(owner, database)
                database[owner] = copy.deepcopy(payload)
                return [database[owner]]
            names = {'load_persistent_state', 'persistent_state_payload', 'save_persistent_state'}
            tree = ast.parse(source)
            tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
            env = dict(st=SimpleNamespace(session_state=state), datetime=datetime, timezone=timezone,
                       urllib=urllib, persistence_enabled=lambda: True, _supabase_request=request,
                       persistence_config=lambda: ('', '', owner), _default_house_goal=dict,
                       _json_safe=copy.deepcopy)
            exec(compile(tree, 'app.py', 'exec'), env)
            self.assertFalse(env['save_persistent_state']())
            self.assertTrue(env['load_persistent_state']())
            return state, env['save_persistent_state']

        for owner in ('alpha', 'beta'):
            state, save = session(rollback, owner)
            state.watchlist = [owner]
            self.assertTrue(save())
            state, save = session(current, owner)
            self.assertEqual(state.watchlist, [owner])
            state.finance_months = {'month': {'closed': owner}}
            state.finance_balances = [{'account': owner}]
            state.opp_refusals = [{'ticker': owner}]
            state.opp_saved_fields['future_field'] = {'owner': owner}
            self.assertTrue(save())

        for owner in ('alpha', 'beta'):
            stale, stale_save = session(rollback, owner)
            state, save = session(rollback, owner)
            state.watchlist.append('legacy-edit')
            self.assertTrue(save())
            stale.watchlist.append('stale-edit')
            self.assertFalse(stale_save())
            state, save = session(current, owner)
            self.assertEqual(state.watchlist, [owner, 'legacy-edit'])
            self.assertEqual(state.finance_months, {'month': {'closed': owner}})
            self.assertEqual(state.finance_balances, [{'account': owner}])
            self.assertEqual(state.opp_refusals, [{'ticker': owner}])
            self.assertEqual(state.opp_saved_fields['future_field'], {'owner': owner})
            self.assertTrue(save())


if __name__ == '__main__':
    unittest.main()
