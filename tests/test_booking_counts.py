import tempfile
import unittest
from pathlib import Path
from sqlite_fixture import TestDatabase

class CountTests(unittest.TestCase):
    def test_edits_5_to_8_to_11_and_new_confirmation_remain_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=TestDatabase(str(Path(tmp)/'bot.sqlite'))
            with db._connect() as c:
                c.execute("INSERT INTO users(id,telegram_id) VALUES(1,42)")
                c.execute("INSERT INTO events(id,title,event_date,event_time,location) VALUES(51,'Test','2099-10-25','19:00','Test')")
                c.execute("INSERT INTO registrations(id,event_id,user_id,team_name,team_size,captain_name,phone) VALUES(1,51,1,'Test',5,'Test','synthetic')")
            db.save_confirmation(1,5,'5 человек')
            for size in (8,11):
                db.update_team_size(1,size)
                self.assertEqual(db.get_registration_by_id(1)['team_size'],size)
                self.assertEqual(db.get_confirmation(1)['confirmed_count'],size)
            db.save_confirmation(1,9,'Нас 9')
            self.assertEqual(db.get_registration_by_id(1)['team_size'],9)
            db.save_confirmation(1,0,'declined')
            db.update_team_size(1,11)
            self.assertEqual(db.get_confirmation(1)['player_names'],'declined')
            with self.assertRaises(ValueError):db.update_team_size(1,0)
