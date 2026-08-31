import math,unittest
from planning_tool.engine import (evaluate_scenario,options,population_insights,population_summary,
 preview_scenario)

class EngineTests(unittest.TestCase):
 def setUp(self):
  self.base={"active_arm":"泰普格雷低剂量组","source_scenario":"nominal_v8_missing_nonresponder",
   "effect_multiplier":.5,"total_n":800,"control_response_rate":.7313432836,
   "active_allocation":.5,"analysis_prior":"weak_beta11","n_simulations":1000,"random_seed":123}
 def test_options(self):
  o=options();self.assertEqual(len(o["active_arms"]),2);self.assertEqual(o["simulation_sizes"],[1000,5000,20000])
  self.assertEqual(o["primary_endpoints"],["cec_ischemic_stroke_d90","mrs_ordinal_day90","mrs01_day90","mrs02_day90"])
  self.assertEqual(o["sbp_operators"],["all","lt","le","ge","gt"])
  self.assertIn("多发梗死",o["presentation_values"]);self.assertIn("慢代谢",o["cyp2c19_values"])
 def test_default_effect_multiplier_is_original_observed_effect(self):
  s={k:v for k,v in self.base.items() if k!="effect_multiplier"}
  r=evaluate_scenario(s)
  self.assertEqual(r["normalized_scenario"]["effect_multiplier"],1.0)

 def test_dynamic_scenario(self):
  r=evaluate_scenario({**self.base,"total_n":777,"active_allocation":.55})
  self.assertEqual(r["status"],"supported");self.assertEqual((r["active_n"],r["control_n"]),(427,350))
  self.assertTrue(0<=r["monte_carlo_pos"]<=1);self.assertTrue(r["not_a_prediction"])
  self.assertEqual(r["primary_endpoint"],"mrs01_day90")

 def test_all_primary_endpoints_are_runnable(self):
  for endpoint in ["cec_ischemic_stroke_d90","mrs_ordinal_day90","mrs01_day90","mrs02_day90"]:
   scenario={**self.base,"primary_endpoint":endpoint};scenario.pop("control_response_rate",None)
   r=evaluate_scenario(scenario)
   self.assertEqual(r["status"],"supported",endpoint)
   self.assertEqual(r["primary_endpoint"],endpoint)
   self.assertTrue(0<=r["monte_carlo_pos"]<=1)
   self.assertTrue(0<=r["bayesian_assurance"]<=1)
 def test_cec_endpoint_uses_lower_event_rate_as_benefit(self):
  scenario={**self.base,"primary_endpoint":"cec_ischemic_stroke_d90"};scenario.pop("control_response_rate")
  r=evaluate_scenario(scenario)
  self.assertIn("上限<0",r["success_rule"])
  self.assertTrue(math.isclose(r["assumed_benefit"],-r["assumed_risk_difference"],abs_tol=1e-12))
 def test_ordinal_endpoint_has_distribution_and_common_or(self):
  r=evaluate_scenario({**self.base,"primary_endpoint":"mrs_ordinal_day90"})
  self.assertEqual(len(r["assumed_active_distribution"]),7)
  self.assertTrue(math.isclose(sum(r["assumed_active_distribution"]),1,abs_tol=1e-12))
  self.assertGreater(r["assumed_common_or"],0)
 def test_endpoint_source_counts_are_traceable(self):
  cec=evaluate_scenario({"primary_endpoint":"cec_ischemic_stroke_d90","active_arm":"泰普格雷低剂量组","n_simulations":1000})
  self.assertEqual((cec["source_n_active"],cec["source_n_control"]),(202,201))
  self.assertEqual((cec["phase2_active_rate"]*202,cec["phase2_control_rate"]*201),(18,20))
  mrs2=evaluate_scenario({"primary_endpoint":"mrs02_day90","active_arm":"泰普格雷低剂量组","n_simulations":1000})
  self.assertEqual((mrs2["phase2_active_rate"]*202,mrs2["phase2_control_rate"]*201),(169,157))
 def test_multiplier_definition(self):
  a=evaluate_scenario({**self.base,"effect_multiplier":1.})
  b=evaluate_scenario({**self.base,"effect_multiplier":.5})
  self.assertTrue(math.isclose(b["assumed_risk_difference"],.5*a["phase2_observed_rd"],abs_tol=1e-12))
 def test_unfiltered_full_reference_is_exact(self):
  r=evaluate_scenario(self.base)
  self.assertEqual(r["monte_carlo_pos"],r["full_population_pos"])
  self.assertEqual(r["bayesian_assurance"],r["full_population_assurance"])
  self.assertEqual(r["delta_pos_vs_full"],0)
 def test_filtered_population_and_reference(self):
  f={"nihss_range":[0,3],"age_range":[55,80]}
  r=evaluate_scenario({**self.base,"population_filters":f})
  self.assertEqual(r["status"],"supported");self.assertLess(r["phase2_eligible_n"],r["phase2_source_n"])
  self.assertLess(r["phase2_source_retention"],1);self.assertGreater(r["estimated_screened_n"],r["normalized_scenario"]["total_n"])
 def test_center_is_source_sensitivity_not_screening(self):
  r=evaluate_scenario({**self.base,"population_filters":{"site_mitt_n_min":20}})
  self.assertTrue(r["source_sensitivity_active"]);self.assertEqual(r["phase2_patient_retention"],1)
  self.assertEqual(r["estimated_screened_n"],800);self.assertLess(r["phase2_source_retention"],1)
 def test_special_combination_warning(self):
  p=preview_scenario({**self.base,"effect_multiplier":1.5,"control_response_rate":.90})
  levels=[x["level"] for x in p["warnings_ui"]];titles=[x["title"] for x in p["warnings_ui"]]
  self.assertIn("strong",levels);self.assertIn("叠加外推",titles)
 def test_out_of_probability_is_explicit(self):
  p=preview_scenario({**self.base,"effect_multiplier":1.5,"control_response_rate":.95})
  self.assertEqual(p["status"],"unsupported");self.assertTrue(any("超出0%–100%" in x for x in p["errors"]))
 def test_population_insights_contract(self):
  ins=population_insights({**self.base,"population_filters":{"sex":[1]}})
  self.assertEqual(ins["source_n"],605);self.assertLess(ins["eligible_n"],605)
  self.assertIn("性别分布",ins["distributions"]);self.assertEqual(len(ins["outcome"]),2)
  self.assertIn("入组时疾病/影像类型",ins["distributions"])
  self.assertIn("既往卒中/TIA病史",ins["distributions"])
  self.assertIn("605例",ins["warning"])
  self.assertIn("终点评价",ins["warning"])
  self.assertEqual(sum(x["n"] for x in ins["arm_distribution"]),ins["eligible_n"])
 def test_continuous_sbp_sap_anchor_counts(self):
  le=population_summary({"sbp_operator":"le","sbp_threshold":140})
  gt=population_summary({"sbp_operator":"gt","sbp_threshold":140})
  self.assertEqual(le["retained_n"],323);self.assertEqual(gt["retained_n"],282)
 def test_prior_stroke_tia_proxy_has_mandatory_warning(self):
  p=preview_scenario({**self.base,"population_filters":{"prior_stroke_tia_proxy":[1]}})
  self.assertTrue(any(x["level"]=="strong" and "病史代理" in x["title"] for x in p["warnings_ui"]))
  self.assertTrue(any("终点评价为" in x["text"] and "SAR的112/103/108" in x["text"] for x in p["warnings_ui"]))
 def test_high_risk_tia_alone_is_unsupported(self):
  p=preview_scenario({**self.base,"population_filters":{"presentation_group":["高危TIA"]}})
  self.assertEqual(p["status"],"unsupported")
  self.assertTrue(any("少于20" in x for x in p["errors"]))
 def test_reproducible(self):
  self.assertEqual(evaluate_scenario(self.base),evaluate_scenario(self.base))
 def test_population_full(self):
  r=population_summary({});self.assertEqual(r["source_n"],605);self.assertEqual(r["retained_n"],605);self.assertEqual(sum(x["n"] for x in r["arm_summary"]),605)
 def test_population_baseline_filter(self):
  r=population_summary({"age_range":(65,92),"nihss_range":(0,5),"baseline_mrs":[0,1],"sex":[1,2],"indication":["轻型缺血性卒中","高危TIA"],"sbp":[0,1],"site_mitt_n_min":0})
  self.assertLessEqual(r["retained_n"],605);self.assertGreaterEqual(r["retained_n"],0)
if __name__=="__main__":unittest.main()
