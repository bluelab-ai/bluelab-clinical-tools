import os
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

class AppSmokeTests(unittest.TestCase):
 def test_login_then_initial_page(self):
  app=Path(__file__).resolve().parents[1]/"app.py"
  env={"PLANNING_TOOL_USERNAME":"BlueBalloon","PLANNING_TOOL_PASSWORD":"test-only-password"}
  with patch.dict(os.environ,env,clear=False):
   at=AppTest.from_file(str(app),default_timeout=30).run()
   self.assertFalse(at.exception)
   self.assertTrue(any(x.label=="访问账号" for x in at.text_input))
   next(x for x in at.text_input if x.label=="访问账号").input("BlueBalloon")
   next(x for x in at.text_input if x.label=="访问口令").input("test-only-password")
   next(x for x in at.button if x.label=="登录").click()
   at.run()
   self.assertFalse(at.exception)
   self.assertTrue(any("探索分析" in x.value for x in at.title))
   self.assertTrue(any(x.label=="主要终点" for x in at.selectbox))

if __name__=="__main__":unittest.main()
