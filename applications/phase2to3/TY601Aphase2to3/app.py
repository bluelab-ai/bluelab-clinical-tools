from __future__ import annotations
import base64,hashlib,hmac,html,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
APP_ROOT=Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
from planning_tool.engine import (CONTROL_ARM,DATA_VERSION,ENGINE_VERSION,assets,comparison_frame,
 default_control_rate,dose_tooltip,endpoint_metadata,evaluate_scenario,normalize_population_filters,options,
 phase2_evidence,population_insights,preview_scenario,scenario_hash)
from feedback_mail import queue_feedback_email

ROOT=APP_ROOT
CONFIG_PATH=ROOT/"project_config.json";CONTRACT_PATH=ROOT/"data/phase3_dynamic_parameter_contract.json"
LOGO_PATH=ROOT/"assets/blueballoon_logo.png";RUNTIME=ROOT/"runtime"
ALL_REFERENCE="__full_population__"
PAGES=["探索分析","二期人群洞察","情景比较与管理","使用说明","更新日志","问题反馈"]
SOURCE_LABELS={"nominal_v8_missing_nonresponder":"缺失按未应答（默认规划）",
 "available_case":"仅分析有D90评分者",
 "strict_d85_d95_missing_nonresponder":"严格D85–D95窗口，窗外/缺失按未应答",
 "locf_like_through_d95":"D95前末次观测结转（LOCF型），仍缺失按未应答"}
SOURCE_HELP=("D90 mRS类终点提供四种记录/缺失敏感性方法：默认方法把死亡和缺失记为最差结局（在二分类中为未应答）；"
 "“仅分析有D90评分者”会排除没有评分者，可能受选择偏倚影响；严格窗口方法只接受D85–D95评分；"
 "LOCF型方法使用D95前最近一次mRS。Phase II SAP对mRS未规定多重插补，因此当前不把多重插补列为mRS方法。")
ENDPOINT_LABELS={x:endpoint_metadata(x)["label"] for x in options()["primary_endpoints"]}
ENDPOINT_HELP=("四项是互斥的主要终点规划情景，不代表同时设置共同主要终点或自动判断次要终点。"
 "CEC缺血性卒中为Phase II正式主要终点；完整有序mRS为SAP预设shift分析；mRS≤1与mRS≤2为探索性二分类规划。")
FIXED_ANALYSIS_PRIOR="weak_beta11"
DOSE_LABELS={"泰普格雷低剂量组":"低剂量方案","泰普格雷高剂量组":"高剂量方案"}
FEATURE_LABELS={"age":"年龄范围","sex":"性别","baseline_mrs":"发病前mRS","sbp":"基线SBP",
 "presentation_group":"入组时疾病/影像类型","history_hypertension":"高血压病史",
 "history_diabetes":"糖尿病史","history_dyslipidemia":"血脂异常病史",
 "cyp2c19_group":"CYP2C19代谢分型","prior_stroke_tia_proxy":"既往卒中/TIA病史"}
SBP_OPERATOR_LABELS={"all":"不限","lt":"小于","le":"小于等于","ge":"大于等于","gt":"大于"}
FEATURE_CONTRACT=["Scenario exploration","Phase II population insights","Scenario comparison and management",
 "Methods, assumptions, and limitations","Changelog","Feedback","Save scenario","Anchor scenario","Download scenario report"]

st.set_page_config(page_title="泰普格雷 Phase III规划探索",layout="wide",initial_sidebar_state="auto")
st.markdown("""
<style>
:root{--ink:#182230;--muted:#667085;--line:#d0d5dd;--accent:#0f766e;--navy:#073b4c;--canvas:#f4f7f8}
.stApp{background:var(--canvas);color:var(--ink)}
.stApp::before{content:"";position:fixed;inset:0 0 0 auto;width:28vw;pointer-events:none;background:rgba(7,59,76,.025);border-left:1px solid rgba(15,118,110,.05);clip-path:polygon(38% 0,100% 0,100% 100%,0 100%)}
[data-testid="stHeader"]{background:rgba(244,247,248,.96)}[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stAppDeployButton"],[data-testid="stMainMenu"]{display:none}
[data-testid="stSidebar"]{background:#fbfdfe;border-right:1px solid var(--line);width:226px!important;min-width:226px!important;max-width:226px!important}
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding-top:.45rem}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{padding-left:.72rem;padding-right:.72rem}
[data-testid="stSidebar"] [data-testid="stImage"]{margin:0 auto 2px}
[data-testid="stSidebar"] [data-testid="stImage"] img{max-height:94px;object-fit:contain}
.block-container{position:relative;z-index:1;max-width:1240px;padding-top:4.25rem;padding-bottom:3rem}
.sidebar-product{color:#182230;font-size:1rem;font-weight:700;margin:2px 0 3px}
.sidebar-section{color:#98a2b3;font-size:.67rem;font-weight:700;margin:5px 0 3px;padding-left:2px}
[data-testid="stSidebar"] .stButton button{justify-content:flex-start;gap:.35rem;min-height:36px;border-radius:6px;padding:4px 8px;font-weight:600;transition:.16s}
[data-testid="stSidebar"] .stButton button[kind="tertiary"]{color:#475467}
[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover{background:#f2f6f7;color:#12394a;border-color:transparent}
[data-testid="stSidebar"] .stButton button[kind="primary"]{background:#e7f3f2;color:#0b5d57;border-color:#c4dfdc;box-shadow:none}
.sidebar-status{border-top:1px solid #e4e7ec;margin-top:18px;padding-top:15px;color:#667085;font-size:.74rem;line-height:1.6}
.status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#159a78;margin-right:7px;box-shadow:0 0 0 3px rgba(21,154,120,.10)}
h1{font-size:2rem!important;letter-spacing:0!important}.eyebrow{color:#0f766e;font-weight:700;font-size:.82rem;margin-bottom:.2rem}
.boundary{color:var(--muted);font-size:.9rem;border-left:3px solid #98a2b3;padding-left:.75rem}
.reference-banner{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:1rem 0 1.35rem;padding:11px 14px;border:1px solid #c9dedc;border-left:4px solid var(--accent);border-radius:6px;background:#f8fcfc;color:#344054}
.reference-banner strong{color:#0b5d57}.reference-banner span{color:#667085;font-size:.8rem;text-align:right}
.result-strip{border-top:1px solid var(--line);padding-top:1rem;margin-top:1.3rem}
div[data-testid="stMetric"]{background:#fff;border:1px solid #e4e7ec;border-radius:6px;padding:13px;min-height:104px;transition:transform .18s,box-shadow .18s,border-color .18s}
div[data-testid="stMetric"]:hover{transform:translateY(-3px);border-color:#75aaa5;box-shadow:0 8px 20px rgba(15,118,110,.11)}
.support-status{background:#fff;border:1px solid #e4e7ec;border-left:4px solid #0f766e;border-radius:6px;padding:12px 14px;min-height:104px}
.support-status b,.support-status strong,.support-status span{display:block}.support-status b{color:#344054;font-size:.83rem;margin-bottom:7px}.support-status strong{font-size:1.02rem}.support-status span{color:#667085;font-size:.76rem;margin-top:6px}
.warning-card{position:relative;border:1px solid;border-radius:6px;padding:12px 46px 12px 14px;margin:.45rem 0;transition:transform .18s,box-shadow .18s}
.warning-card:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(16,24,40,.10)}
.warning-card.ordinary{background:#eff8ff;border-color:#b2ddff;color:#1849a9}.warning-card.caution{background:#fffaeb;border-color:#fedf89;color:#93370d}.warning-card.strong{background:#fff4ed;border-color:#f7b27a;color:#9c2a10}.warning-card.block{background:#fef3f2;border-color:#fda29b;color:#912018}
.warning-title{display:flex;align-items:center;gap:8px;font-weight:750;margin-bottom:4px}.warning-level{font-size:.70rem;border:1px solid currentColor;border-radius:4px;padding:1px 5px}.warning-text{font-size:.88rem;line-height:1.55;color:#344054}
.warning-help{position:absolute;right:14px;top:12px;width:22px;height:22px;display:flex;align-items:center;justify-content:center;border:1px solid currentColor;border-radius:50%;font-size:.76rem;font-weight:800;cursor:help}
.warning-tooltip{position:absolute;z-index:20;right:0;top:29px;width:250px;padding:9px 10px;border-radius:5px;background:#101828;color:#fff;font-size:.75rem;line-height:1.45;font-weight:400;opacity:0;visibility:hidden;transform:translateY(-4px);transition:.16s;pointer-events:none}
.warning-help:hover .warning-tooltip,.warning-help:focus .warning-tooltip{opacity:1;visibility:visible;transform:translateY(0)}
.manual-step{border-left:4px solid #0f766e;padding:.25rem 0 .25rem 1rem;margin:.8rem 0 1.2rem}
.local-note{border:1px solid #c9dedc;border-left:4px solid #0f766e;border-radius:6px;background:#f8fcfc;padding:12px 14px;margin:1rem 0 1.25rem;color:#344054;font-size:.86rem}
.change-feed{position:relative;margin:1.35rem 0 .5rem 12px;padding-left:30px}.change-feed::before{content:"";position:absolute;left:6px;top:10px;bottom:16px;width:2px;background:#c9dedc}
.change-post{position:relative;margin:0 0 18px;padding:16px 18px;background:#fff;border:1px solid #e4e7ec;border-radius:6px}.change-post::before{content:"";position:absolute;left:-30px;top:20px;width:12px;height:12px;border-radius:50%;background:#0f766e;border:3px solid #f4f7f8}
.change-meta{display:flex;gap:8px;color:#667085;font-size:.76rem}.change-badge{border:1px solid #b9d8d5;border-radius:4px;padding:2px 6px;color:#0b5d57;background:#eff8f7;font-weight:700}
.st-key-tapgrel_login_panel{max-width:460px;margin:6vh auto 0;padding:30px 34px 25px;box-sizing:border-box;background:rgba(255,255,255,.98);border:1px solid #d0d5dd;border-top:4px solid #0f766e;border-radius:8px;box-shadow:0 18px 44px rgba(15,59,76,.09)}
.login-brand{text-align:center;margin-bottom:22px}.login-brand img{display:block;width:176px;max-width:68%;height:auto;max-height:156px;object-fit:contain;margin:0 auto 17px}.login-kicker{color:#0f766e;font-size:.75rem;font-weight:700;margin-bottom:7px}.login-brand h1{color:#182230;font-size:1.72rem!important;line-height:1.25;margin:0 0 7px;letter-spacing:0!important}.login-brand p{color:#667085;font-size:.88rem;margin:0}
.st-key-tapgrel_login_panel [data-testid="stForm"]{border:0;padding:0}.st-key-tapgrel_login_panel [data-testid="stTextInput"] input{min-height:46px;border-radius:6px}.st-key-tapgrel_login_panel [data-testid="stFormSubmitButton"] button{min-height:46px;font-weight:700;background:#0f766e!important;border-color:#0f766e!important;color:#fff!important}.st-key-tapgrel_login_panel [data-testid="stFormSubmitButton"] button:hover{background:#0b5d57!important;border-color:#0b5d57!important}
.login-boundary{border-left:3px solid #0f766e;background:#f4fbfa;color:#475467;padding:10px 12px;margin:17px 0 0;font-size:.78rem;line-height:1.55}.login-boundary strong{display:block;color:#0b5d57;margin-bottom:2px}.login-footer{margin-top:13px;color:#98a2b3;font-size:.72rem;line-height:1.5;text-align:center}
@media(max-width:760px){[data-testid="stToolbar"]{display:flex!important}[data-testid="stAppDeployButton"],[data-testid="stMainMenu"]{display:none!important}.stApp::before{display:none}.block-container{padding-top:4.5rem}.reference-banner{align-items:flex-start;flex-direction:column}.reference-banner span{text-align:left}.st-key-tapgrel_login_panel{margin:1.25rem auto 0;padding:25px 22px 22px}.login-brand img{width:152px}}
</style>
""",unsafe_allow_html=True)

@st.cache_data
def load_json(path:str)->dict[str,Any]:return json.loads(Path(path).read_text())
def pct(x):return "—" if x is None or pd.isna(x) else f"{100*float(x):.1f}%"
def pp(x):return "—" if x is None or pd.isna(x) else f"{100*float(x):+.1f}"
def sid(item,index=0):return str(item.get("scenario_id") or f"scenario-{index}")
def dose_name(x):return DOSE_LABELS.get(x,x)

def init_state():
 defaults={"active_page":"探索分析","saved_scenarios":[],"current_scenario":None,"current_result":None,
  "current_meta":None,"anchor_id":None,"comparison_selected_ids":[],
  "comparison_known_ids":[],"comparison_previous_snapshot":[],"population_applied":None,
  "population_previous":None,"feedback_source_page":"探索分析","_last_page":None}
 for k,v in defaults.items():st.session_state.setdefault(k,v)

def logo_html():
 if not LOGO_PATH.exists():return ""
 data=base64.b64encode(LOGO_PATH.read_bytes()).decode()
 return f'<img src="data:image/png;base64,{data}" alt="Blue Ballon BlueLab">'

def _positive_int_env(name,default,minimum,maximum):
 try:value=int(os.getenv(name,str(default)))
 except ValueError:return default
 return max(minimum,min(maximum,value))

def portal_ticket_is_valid(token,expected_tool):
 secret=os.getenv("PORTAL_TICKET_SECRET","").strip()
 if not token or not secret:return False,""
 try:
  body,encoded_signature=token.split(".",1)
  received_signature=base64.urlsafe_b64decode(encoded_signature+"="*(-len(encoded_signature)%4))
  expected_signature=hmac.new(secret.encode(),body.encode("ascii"),hashlib.sha256).digest()
  if not hmac.compare_digest(received_signature,expected_signature):return False,""
  payload=json.loads(base64.urlsafe_b64decode(body+"="*(-len(body)%4)).decode())
  now=int(time.time());issued_at=int(payload.get("iat",0));expires_at=int(payload.get("exp",0))
  client_id=str(payload.get("clientId","")).strip()
  valid=(payload.get("tool")==expected_tool and bool(client_id) and issued_at<=now+30
   and expires_at>=now and 0<expires_at-issued_at<=180)
  return valid,client_id if valid else ""
 except (ValueError,TypeError,json.JSONDecodeError):return False,""

def accept_portal_ticket(now):
 raw_ticket=st.query_params.get("portal_ticket","")
 if isinstance(raw_ticket,list):raw_ticket=raw_ticket[0] if raw_ticket else ""
 valid,client_id=portal_ticket_is_valid(str(raw_ticket),"tapgrel")
 if not valid:return
 st.session_state.authenticated=True;st.session_state.authenticated_at=now
 st.session_state.access_failed_attempts=0;st.session_state.access_locked_until=0
 st.session_state.portal_client_id=client_id
 try:del st.query_params["portal_ticket"]
 except KeyError:pass
 st.rerun()

def clear_access():
 for key in ("authenticated","authenticated_at","access_failed_attempts","access_locked_until"):
  st.session_state.pop(key,None)

def require_access(cfg):
 enabled=bool(cfg.get("website",{}).get("enable_login",False) or os.getenv("PLANNING_TOOL_PASSWORD",""))
 if not enabled:return
 expected_user=os.getenv("PLANNING_TOOL_USERNAME","BlueBalloon").strip();expected_pass=os.getenv("PLANNING_TOOL_PASSWORD","")
 if not expected_pass:
  st.error("访问控制已启用，但服务器未配置PLANNING_TOOL_PASSWORD。");st.stop()
 session_minutes=_positive_int_env("PLANNING_TOOL_SESSION_MINUTES",480,15,1440)
 max_failures=_positive_int_env("PLANNING_TOOL_MAX_FAILURES",5,3,10)
 lock_seconds=_positive_int_env("PLANNING_TOOL_LOCK_SECONDS",60,15,900)
 now=time.time();granted_at=float(st.session_state.get("authenticated_at") or 0)
 accept_portal_ticket(now)
 if st.session_state.get("authenticated") and now-granted_at<session_minutes*60:return
 if st.session_state.get("authenticated"):
  clear_access();st.session_state["access_notice"]="会话已结束，请重新登录。"
 remaining=max(0,int(float(st.session_state.get("access_locked_until") or 0)-now))
 with st.container(border=False,key="tapgrel_login_panel"):
  st.markdown(f'<div class="login-brand">{logo_html()}<div class="login-kicker">受保护访问 · 甲方试用环境</div><h1>泰普格雷 Phase III规划探索</h1><p>临床开发决策支持工具</p></div>',unsafe_allow_html=True)
  notice=str(st.session_state.pop("access_notice","") or "")
  if notice:st.info(notice)
  if remaining:st.warning(f"为保护试用账号，请在约{remaining}秒后重试。")
  else:
   with st.form("login",clear_on_submit=False,border=False):
    u=st.text_input("访问账号",autocomplete="username",placeholder="请输入访问账号")
    p=st.text_input("访问口令",type="password",autocomplete="current-password",placeholder="请输入访问口令")
    go=st.form_submit_button("登录",type="primary",use_container_width=True)
   if go:
    if hmac.compare_digest(u.strip(),expected_user) and hmac.compare_digest(p,expected_pass):
     st.session_state.authenticated=True;st.session_state.authenticated_at=now
     st.session_state.access_failed_attempts=0;st.session_state.access_locked_until=0;st.rerun()
    failures=int(st.session_state.get("access_failed_attempts") or 0)+1;st.session_state.access_failed_attempts=failures
    if failures>=max_failures:
     st.session_state.access_locked_until=now+lock_seconds;st.error("尝试次数过多，请稍后再试。")
    else:st.error("账号或访问口令不正确。")
  st.markdown('<div class="login-boundary"><strong>使用边界</strong>本工具仅供授权用户进行探索性规划，不代表三期成功承诺。请勿转发访问凭据或包含受试者信息的截图。</div>'
   f'<div class="login-footer">开发试用版 · 会话最长保留约{session_minutes}分钟<br>访问异常请联系项目团队</div>',unsafe_allow_html=True)
 st.stop()

def header(title,subtitle):
 st.markdown('<div class="eyebrow">TY601A-P2-01 · 探索性规划</div>',unsafe_allow_html=True)
 st.title(title);st.caption(subtitle)
 st.markdown('<div class="boundary">探索性规划，不代表Phase III成功概率或成功承诺。</div>',unsafe_allow_html=True)

def render_warning(item):
 levels={"ordinary":("规划提示","一般说明，不阻止运行。"),"caution":("谨慎解释","存在数据支持或假设负担。"),
  "strong":("强警示","外推、稀疏或叠加假设较强。"),"block":("无法运行","当前组合不满足计算支持条件。")}
 level=item.get("level","ordinary");label,meaning=levels.get(level,levels["ordinary"])
 st.markdown(f'<div class="warning-card {level}" role="status"><div class="warning-title"><span class="warning-level">{label}</span>{html.escape(str(item.get("title","提示")))}</div><div class="warning-text">{html.escape(str(item.get("text","")))}</div><span class="warning-help" tabindex="0">?<span class="warning-tooltip">{meaning}</span></span></div>',unsafe_allow_html=True)

def anchor_item():
 target=st.session_state.get("anchor_id")
 for i,item in enumerate(st.session_state.saved_scenarios):
  if sid(item,i)==target:return item
 if target:st.session_state.anchor_id=None
 return None

def set_anchor(value):
 st.session_state.anchor_id=None if value in (None,ALL_REFERENCE) else value

def anchor_selector(key,label="比较基准"):
 saved=st.session_state.saved_scenarios;labels={sid(x,i):x["name"] for i,x in enumerate(saved)}
 choices=[ALL_REFERENCE,*labels];desired=st.session_state.get("anchor_id") or ALL_REFERENCE
 if desired not in choices:desired=ALL_REFERENCE;set_anchor(None)
 selected=st.selectbox(label,choices,index=choices.index(desired),
  format_func=lambda x:"全人群（默认）" if x==ALL_REFERENCE else f"已保存情景：{labels[x]}",
  key=key,help="比较基准只改变结果卡片、动画与报告中的参照，不改变模拟计算。")
 set_anchor(selected)
 if len(choices)==1:st.caption("保存至少一个情景后，可将其设为固定比较基准,之后每次的结果会自动与比较基准进行对比。")
 return selected

def reference_for(result):
 item=anchor_item()
 if item and item["result"].get("primary_endpoint","mrs01_day90")==result.get("primary_endpoint","mrs01_day90"):return item["result"],item["name"],"anchor"
 incompatible=bool(item)
 return {"monte_carlo_pos":result.get("full_population_pos"),"bayesian_assurance":result.get("full_population_assurance"),
  "full_population_pos":result.get("full_population_pos"),"delta_pos_vs_full":0,
  "phase2_source_retention":1,"estimated_screened_n":result["normalized_scenario"]["total_n"],
  "phase2_eligible_n":result.get("phase2_source_n")}, "同设计全人群（固定基准终点不同）" if incompatible else "同设计全人群","full"

def reference_banner():
 item=anchor_item()
 if item:
  st.markdown(f'<div class="reference-banner"><div><strong>当前比较基准：{html.escape(item["name"])}</strong><br>后续结果统一与该已保存情景比较。</div><span>仅改变显示参照，不改变模拟计算</span></div>',unsafe_allow_html=True)
 else:
  st.markdown('<div class="reference-banner"><div><strong>当前参照：同设计全人群</strong><br>保持当前设计参数、移除基线筛选条件后的参照。</div><span>比较不依赖运行顺序</span></div>',unsafe_allow_html=True)

def metric_delta(current,reference,key,count=False,inverse=False):
 a=current.get(key);b=reference.get(key)
 if a is None or b is None:return None,"off"
 diff=float(a)-float(b)
 if count:
  text=f"{diff:+,.0f}人";color="inverse" if inverse else "normal"
 else:
  text=("+<0.1" if 0<diff*100<.05 else ("−<0.1" if -.05<diff*100<0 else f"{diff*100:+.1f}"))
  color="normal"
 if abs(diff)<1e-12:color="off"
 return text,color

def _result_animation_html(current,reference,label):
 rows=[("探索性成功频率","monte_carlo_pos","#0f766e"),("Bayesian assurance","bayesian_assurance","#d97706"),("同设计全人群参照","full_population_pos","#3b82f6")]
 bars=[]
 for title,key,color in rows:
  end=current.get(key);start=reference.get(key)
  if end is None:bars.append(f'<div class="row"><span>{title}</span><strong>不可估计</strong></div>');continue
  start=end if start is None else start
  bars.append(f'<div class="row"><div class="meta"><span>{title}</span><strong class="counter" data-a="{start*100:.6f}" data-b="{end*100:.6f}">{start:.1%}</strong></div><div class="track"><i data-b="{end*100:.6f}" style="width:{start*100:.3f}%;background:{color}"></i></div></div>')
 cards=[("Phase II来源保留",current.get("phase2_source_retention"),"pct"),("预计筛查人数",current.get("estimated_screened_n"),"int"),("当前来源人数",current.get("phase2_eligible_n"),"int")]
 minis=[]
 for title,value,kind in cards:
  end=0 if value is None else float(value)*(100 if kind=="pct" else 1)
  minis.append(f'<div class="mini"><span>{title}</span><strong class="counter" data-a="0" data-b="{end:.6f}" data-kind="{kind}">0</strong></div>')
 return f"""<!doctype html><html><meta charset=utf-8><style>*{{box-sizing:border-box}}body{{margin:0;font-family:Microsoft YaHei,Arial;color:#182230;background:#fff}}.row{{margin:0 0 17px}}.meta{{display:flex;justify-content:space-between}}.meta span{{color:#475467;font-size:14px;font-weight:600}}.meta strong{{font-size:22px}}.track{{height:12px;background:#eef2f4;border-radius:3px;margin-top:7px}}.track i{{display:block;height:12px;border-radius:3px;transition:width 650ms cubic-bezier(.22,1,.36,1)}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:20px}}.mini{{padding:12px;border:1px solid #e4e7ec;border-radius:6px;background:#fbfcfd}}.mini span{{display:block;color:#667085;font-size:12px}}.mini strong{{font-size:20px}}@media(max-width:560px){{.grid{{grid-template-columns:1fr}}}}@media(prefers-reduced-motion:reduce){{.track i{{transition:none}}}}</style><body>{''.join(bars)}<p style="font-size:12px;color:#667085">变化参照：{html.escape(label)}；概率差异单位为百分点。</p><div class="grid">{''.join(minis)}</div><script>const d=window.matchMedia('(prefers-reduced-motion:reduce)').matches?0:650;function f(v,k){{return k==='int'?Math.round(v).toLocaleString('zh-CN'):v.toFixed(1)+'%'}};requestAnimationFrame(()=>{{document.querySelectorAll('.track i').forEach(x=>x.style.width=x.dataset.b+'%');const s=performance.now();function t(n){{const p=d?Math.min(1,(n-s)/d):1,e=1-Math.pow(1-p,3);document.querySelectorAll('.counter').forEach(x=>{{const a=+x.dataset.a,b=+x.dataset.b;x.textContent=f(a+(b-a)*e,x.dataset.kind||'pct')}});if(p<1)requestAnimationFrame(t)}}requestAnimationFrame(t)}})</script></body></html>"""

@st.dialog("结果变化速览",width="large")
def result_dialog(current,reference,label,meta):
 if meta.get("cache_hit"):st.caption("相同参数结果已从缓存读取。")
 components.html(_result_animation_html(current,reference,label),height=410,scrolling=False)
 st.caption("动画只呈现结果变化，不改变计算或下载内容。")

def _comparison_animation_html(items,previous,motion):
 current={x["id"]:x for x in items};old={x["id"]:x for x in previous};order=[*old]
 order.extend(x for x in current if x not in old);groups=[];duration=650 if motion else 0
 for identity in order:
  now=current.get(identity);before=old.get(identity);name=html.escape((now or before)["name"])
  idx=list(current).index(identity) if identity in current else 0;count=max(len(current),1)
  pos=0 if now is None else now["pos"];ass=0 if now is None else now["assurance"]
  a0=0 if before is None else before["pos"];b0=0 if before is None else before["assurance"]
  deleted=" deleted" if now is None else ""
  groups.append(f'<div class="g{deleted}" style="left:{idx/count*100}%;width:{100/count}%"><div class="bars"><div><b class="v" data-a="{a0}" data-b="{pos}">{a0:.1f}%</b><i data-b="{pos}" style="height:{a0}%;background:#0f766e"></i></div><div><b class="v" data-a="{b0}" data-b="{ass}">{b0:.1f}%</b><i data-b="{ass}" style="height:{b0}%;background:#d97706"></i></div></div><span>{name}</span></div>')
 return f"""<!doctype html><html><meta charset=utf-8><style>*{{box-sizing:border-box}}body{{margin:0;font-family:Microsoft YaHei,Arial;color:#182230}}.legend{{height:30px;font-size:12px;color:#475467}}.legend i{{display:inline-block;width:10px;height:10px;margin:0 6px 0 14px}}.plot{{height:300px;position:relative;border-bottom:1px solid #d0d5dd;background:repeating-linear-gradient(to top,#fff 0,#fff 59px,#eaecf0 60px)}}.g{{position:absolute;bottom:-38px;height:338px;text-align:center;opacity:1;transition:left {duration}ms,width {duration}ms,opacity {duration}ms}}.bars{{height:300px;display:flex;align-items:flex-end;justify-content:center;gap:8%;padding:20px 15% 0}}.bars div{{height:100%;flex:1;display:flex;align-items:flex-end;position:relative}}.bars i{{width:100%;display:block;transition:height {duration}ms cubic-bezier(.22,1,.36,1)}}.bars b{{position:absolute;left:50%;transform:translate(-50%,-5px);font-size:10px;bottom:0;transition:bottom {duration}ms}}.g>span{{font-size:11px;color:#475467;white-space:nowrap}}@media(prefers-reduced-motion:reduce){{*{{transition:none!important}}}}</style><body><div class="legend"><i style="background:#0f766e"></i>成功频率<i style="background:#d97706"></i>Bayesian assurance</div><div class="plot">{''.join(groups)}</div><script>const d={duration};requestAnimationFrame(()=>requestAnimationFrame(()=>{{document.querySelectorAll('.bars i').forEach(x=>x.style.height=x.dataset.b+'%');document.querySelectorAll('.bars b').forEach(x=>x.style.bottom=x.dataset.b+'%');document.querySelectorAll('.g.deleted').forEach(x=>{{x.style.opacity='0';x.style.width='0';setTimeout(()=>x.remove(),d+30)}});const s=performance.now();function t(n){{const p=d?Math.min(1,(n-s)/d):1,e=1-Math.pow(1-p,3);document.querySelectorAll('.v').forEach(x=>x.textContent=(+x.dataset.a+(+x.dataset.b-+x.dataset.a)*e).toFixed(1)+'%');if(p<1)requestAnimationFrame(t)}}requestAnimationFrame(t)}}))</script></body></html>"""

def explorer_defaults():
 d=assets()["population"];o=options()
 defaults={"exp_endpoint":"mrs01_day90","exp_arm":o["active_arms"][0],"exp_total_n":800,"exp_source":o["source_scenarios"][0],
  "exp_effect":100,"exp_use_p2_control":True,"exp_custom_control":float(default_control_rate(o["active_arms"][0],o["source_scenarios"][0])),
  "exp_nihss":(int(d.baseline_nihss.min()),int(d.baseline_nihss.max())),"exp_features":[],
  "exp_age":(int(d.age.min()),int(d.age.max())),"exp_sex":o["sex_values"],"exp_mrs":o["baseline_mrs_values"],
  "exp_sbp_operator":"all","exp_sbp_threshold":140,"exp_presentation":o["presentation_values"],
  "exp_hypertension":o["history_values"],"exp_diabetes":o["history_values"],
  "exp_dyslipidemia":o["history_values"],"exp_cyp2c19":o["cyp2c19_values"],
  "exp_prior_proxy":o["prior_stroke_tia_proxy_values"],"exp_alloc":50,
  "exp_sims":5000,"exp_seed":20260810,"exp_site_min":0}
 for k,v in defaults.items():st.session_state.setdefault(k,v)

def sync_endpoint_defaults():
 endpoint=st.session_state.get("exp_endpoint","mrs01_day90");o=options()
 source="cec_adjudicated_d1_d90" if endpoint=="cec_ischemic_stroke_d90" else st.session_state.get("exp_source",o["source_scenarios"][0])
 rate=default_control_rate(st.session_state.get("exp_arm",o["active_arms"][0]),source,endpoint)
 st.session_state.exp_use_p2_control=True
 if rate is not None:st.session_state.exp_custom_control=float(rate)

def filters_from_state(prefix):
 d=assets()["population"];o=options();features=st.session_state.get(f"{prefix}_features",[])
 return normalize_population_filters({
  "nihss_range":st.session_state.get(f"{prefix}_nihss",(int(d.baseline_nihss.min()),int(d.baseline_nihss.max()))),
  "age_range":st.session_state.get(f"{prefix}_age",(int(d.age.min()),int(d.age.max()))) if "age" in features else [int(d.age.min()),int(d.age.max())],
  "sex":st.session_state.get(f"{prefix}_sex",o["sex_values"]) if "sex" in features else o["sex_values"],
  "baseline_mrs":st.session_state.get(f"{prefix}_mrs",o["baseline_mrs_values"]) if "baseline_mrs" in features else o["baseline_mrs_values"],
  "indication":o["indication_values"],
  "sbp_operator":st.session_state.get(f"{prefix}_sbp_operator","all") if "sbp" in features else "all",
  "sbp_threshold":st.session_state.get(f"{prefix}_sbp_threshold",140),
  "presentation_group":st.session_state.get(f"{prefix}_presentation",o["presentation_values"]) if "presentation_group" in features else o["presentation_values"],
  "history_hypertension":st.session_state.get(f"{prefix}_hypertension",o["history_values"]) if "history_hypertension" in features else o["history_values"],
  "history_diabetes":st.session_state.get(f"{prefix}_diabetes",o["history_values"]) if "history_diabetes" in features else o["history_values"],
  "history_dyslipidemia":st.session_state.get(f"{prefix}_dyslipidemia",o["history_values"]) if "history_dyslipidemia" in features else o["history_values"],
  "cyp2c19_group":st.session_state.get(f"{prefix}_cyp2c19",o["cyp2c19_values"]) if "cyp2c19_group" in features else o["cyp2c19_values"],
  "prior_stroke_tia_proxy":st.session_state.get(f"{prefix}_prior_proxy",o["prior_stroke_tia_proxy_values"]) if "prior_stroke_tia_proxy" in features else o["prior_stroke_tia_proxy_values"],
  "site_mitt_n_min":st.session_state.get(f"{prefix}_site_min",0),
 })

def render_population_controls(prefix):
 d=assets()["population"];o=options()
 st.slider("基线NIHSS范围",int(d.baseline_nihss.min()),int(d.baseline_nihss.max()),
  key=f"{prefix}_nihss",help="仅使用随机前基线NIHSS；左右边界均纳入。")
 selected=st.multiselect("其他随机前候选条件（最多2项）",list(FEATURE_LABELS),format_func=lambda x:FEATURE_LABELS[x],
  max_selections=2,key=f"{prefix}_features",help="只允许Phase II可追溯的随机前变量；最多叠加2项，以控制稀疏和多重选择风险。")
 if "age" in selected:st.slider("年龄范围",int(d.age.min()),int(d.age.max()),key=f"{prefix}_age")
 if "sex" in selected:st.multiselect("性别",o["sex_values"],format_func=lambda x:{1:"男",2:"女"}[x],key=f"{prefix}_sex")
 if "baseline_mrs" in selected:
  st.multiselect("发病前mRS",o["baseline_mrs_values"],key=f"{prefix}_mrs",
   help="Phase II中仅观察到0、1、2分（550、47、8例）；方案排除了发病前mRS>2者。mRS=2样本很少。")
 if "sbp" in selected:
  a,b=st.columns([1,1.2])
  a.selectbox("基线SBP比较方式",o["sbp_operators"],format_func=lambda x:SBP_OPERATOR_LABELS[x],key=f"{prefix}_sbp_operator",
   help="基线SBP取首次用药前最后一次有效收缩压。SAP 6.3.3的预设分层界值为140 mmHg。")
  if st.session_state.get(f"{prefix}_sbp_operator","all")!="all":
   b.number_input("SBP阈值（mmHg）",int(d.baseline_sbp.min()),int(d.baseline_sbp.max()),step=1,key=f"{prefix}_sbp_threshold")
 if "presentation_group" in selected:
  st.multiselect("入组时疾病/影像类型",o["presentation_values"],key=f"{prefix}_presentation",
   help="来自SAR可核对分层；高危TIA仅8例，单独选择时数据不足以支持核心模拟。")
 if "history_hypertension" in selected:st.multiselect("高血压病史",o["history_values"],format_func=lambda x:"有" if x else "无",key=f"{prefix}_hypertension")
 if "history_diabetes" in selected:st.multiselect("糖尿病史",o["history_values"],format_func=lambda x:"有" if x else "无",key=f"{prefix}_diabetes")
 if "history_dyslipidemia" in selected:st.multiselect("血脂异常病史",o["history_values"],format_func=lambda x:"有" if x else "无",key=f"{prefix}_dyslipidemia")
 if "cyp2c19_group" in selected:
  st.multiselect("CYP2C19代谢分型",o["cyp2c19_values"],key=f"{prefix}_cyp2c19",
   help="来自SAR/检测数据；快代谢及部分治疗臂分层样本较少，仅作高级探索。")
 if "prior_stroke_tia_proxy" in selected:
  st.multiselect("既往卒中/TIA病史",o["prior_stroke_tia_proxy_values"],format_func=lambda x:"有" if x else "无",key=f"{prefix}_prior_proxy",
   help="甲方SAR将既往卒中和TIA合并为一个亚组。当前患者级选择由MH关键词临时派生：低剂量/高剂量/对照为111/102/108例，SAR为112/103/108例；选择后会显示强警示。")

def load_scenario_widgets(s):
 explorer_defaults();f=normalize_population_filters(s.get("population_filters"));d=assets()["population"];o=options()
 st.session_state.exp_endpoint=s.get("primary_endpoint","mrs01_day90")
 st.session_state.exp_arm=s["active_arm"];st.session_state.exp_total_n=s["total_n"]
 st.session_state.exp_source=s["source_scenario"] if s["source_scenario"] in o["source_scenarios"] else o["source_scenarios"][0]
 st.session_state.exp_effect=int(round(s["effect_multiplier"]*100));default=default_control_rate(s["active_arm"],s["source_scenario"],st.session_state.exp_endpoint)
 st.session_state.exp_use_p2_control=default is None or abs((s.get("control_response_rate") or default)-default)<1e-10
 if default is not None:st.session_state.exp_custom_control=s.get("control_response_rate") or default
 st.session_state.exp_alloc=int(round(s["active_allocation"]*100))
 st.session_state.exp_sims=s["n_simulations"];st.session_state.exp_seed=s["random_seed"];st.session_state.exp_site_min=f["site_mitt_n_min"]
 st.session_state.exp_nihss=tuple(f["nihss_range"]);features=[]
 if f["age_range"]!=[int(d.age.min()),int(d.age.max())]:features.append("age")
 if f["sex"]!=o["sex_values"]:features.append("sex")
 if f["baseline_mrs"]!=o["baseline_mrs_values"]:features.append("baseline_mrs")
 if f["sbp_operator"]!="all":features.append("sbp")
 if f["presentation_group"]!=o["presentation_values"]:features.append("presentation_group")
 if f["history_hypertension"]!=o["history_values"]:features.append("history_hypertension")
 if f["history_diabetes"]!=o["history_values"]:features.append("history_diabetes")
 if f["history_dyslipidemia"]!=o["history_values"]:features.append("history_dyslipidemia")
 if f["cyp2c19_group"]!=o["cyp2c19_values"]:features.append("cyp2c19_group")
 if f["prior_stroke_tia_proxy"]!=o["prior_stroke_tia_proxy_values"]:features.append("prior_stroke_tia_proxy")
 st.session_state.exp_features=features[:2];st.session_state.exp_age=tuple(f["age_range"]);st.session_state.exp_sex=f["sex"]
 st.session_state.exp_mrs=f["baseline_mrs"];st.session_state.exp_sbp_operator=f["sbp_operator"];st.session_state.exp_sbp_threshold=f["sbp_threshold"]
 st.session_state.exp_presentation=f["presentation_group"];st.session_state.exp_hypertension=f["history_hypertension"]
 st.session_state.exp_diabetes=f["history_diabetes"];st.session_state.exp_dyslipidemia=f["history_dyslipidemia"]
 st.session_state.exp_cyp2c19=f["cyp2c19_group"];st.session_state.exp_prior_proxy=f["prior_stroke_tia_proxy"]

def apply_saved_scenario_choice():
 chosen=st.session_state.get("exp_saved_choice",ALL_REFERENCE)
 if chosen==ALL_REFERENCE:
  for key in [x for x in st.session_state if x.startswith("exp_") and x!="exp_saved_choice"]:del st.session_state[key]
  explorer_defaults();st.toast("已应用“全人群（默认）”参数；不会自动运行模拟。")
  return
 for i,item in enumerate(st.session_state.saved_scenarios):
  if sid(item,i)==chosen:
   load_scenario_widgets(item["scenario"]);st.toast(f'已应用“{item["name"]}”参数；不会自动运行模拟。');return

def build_explorer_scenario():
 endpoint=st.session_state.exp_endpoint;arm=st.session_state.exp_arm
 source="cec_adjudicated_d1_d90" if endpoint=="cec_ischemic_stroke_d90" else st.session_state.exp_source
 default=default_control_rate(arm,source,endpoint)
 control=None if default is None else (default if st.session_state.exp_use_p2_control else float(st.session_state.exp_custom_control))
 return {"primary_endpoint":endpoint,"active_arm":arm,"control_arm":CONTROL_ARM,"source_scenario":source,"total_n":int(st.session_state.exp_total_n),
  "effect_multiplier":st.session_state.exp_effect/100,"control_response_rate":control,
  "active_allocation":st.session_state.exp_alloc/100,"analysis_prior":FIXED_ANALYSIS_PRIOR,
  "n_simulations":int(st.session_state.exp_sims),"random_seed":int(st.session_state.exp_seed),
  "population_filters":filters_from_state("exp")}

def scenario_report_html(s,r,anchor):
 rows=[]
 for k,v in {**s,**{k:v for k,v in r.items() if not isinstance(v,(list,dict))}}.items():
  rows.append(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>")
 warnings="".join(f"<li>{html.escape(x.get('title',''))}：{html.escape(x.get('text',''))}</li>" for x in r.get("warnings_ui",[]))
 anchor_text="全人群" if not anchor else anchor["name"]
 return f"""<!doctype html><html lang=zh-CN><meta charset=utf-8><title>泰普格雷探索报告</title><style>body{{font-family:Arial;max-width:980px;margin:32px auto;color:#182230}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border:1px solid #d0d5dd;text-align:left}}.warn{{border-left:4px solid #0f766e;background:#f8fcfc;padding:12px}}</style><h1>泰普格雷Phase III探索性规划报告</h1><div class=warn><b>不是Phase III成功率预测。</b><p>主要终点：{html.escape(r.get("endpoint_label","D90 mRS≤1"))}；比较基准：{html.escape(anchor_text)}；引擎：{ENGINE_VERSION}；数据：{DATA_VERSION}</p></div><h2>预警</h2><ul>{warnings}</ul><h2>情景与结果</h2><table>{''.join(rows)}</table><h2>方法</h2><p>{html.escape(r.get("success_rule",""))}。Bayesian assurance对Phase II来源参数不确定性积分。筛选条件仅含随机前基线变量；描述性亚组差异不证明效应修饰。</p></html>"""

def result_chart(r):
 labels=["当前情景成功频率","同设计全人群参照","Bayesian assurance"];vals=[r["monte_carlo_pos"],r["full_population_pos"],r["bayesian_assurance"]]
 fig=go.Figure(go.Bar(x=[x*100 for x in vals],y=labels,orientation="h",marker_color=["#0f766e","#3b82f6","#d97706"],
  text=[f"{x:.1%}" for x in vals],textposition="outside",hovertemplate="%{y}：%{x:.1f}%<extra></extra>"))
 fig.update_layout(height=270,margin=dict(l=20,r=65,t=20,b=40),xaxis=dict(title="概率（%）",range=[0,100],gridcolor="#e4e7ec"),
  yaxis=dict(autorange="reversed"),plot_bgcolor="white",paper_bgcolor="white",showlegend=False,
  transition=dict(duration=650 if st.session_state.result_motion_enabled else 0))
 return fig

def render_results(s,r,meta):
 if r.get("status")!="supported":
  st.error(r.get("reason","当前组合无法计算。"));return
 ref,label,_=reference_for(r);st.subheader("核心结果")
 st.caption(f'{r.get("endpoint_label","D90 mRS≤1")}｜{r.get("endpoint_evidence_tag","")}｜成功规则：{r.get("success_rule","")}')
 if meta and meta.get("cache_hit"):st.success("已从缓存读取相同参数结果。")
 st.caption(f"箭头与变化量相对{label}；概率差异单位：百分点。")
 d1=metric_delta(r,ref,"monte_carlo_pos");d2=metric_delta(r,ref,"bayesian_assurance");d3=metric_delta(r,ref,"full_population_pos");d4=metric_delta(r,ref,"delta_pos_vs_full")
 cols=st.columns(4)
 cols[0].metric("探索性成功频率",pct(r["monte_carlo_pos"]),d1[0],delta_color=d1[1],help="重复模拟达到当前成功规则的比例。")
 cols[1].metric("Bayesian assurance",pct(r["bayesian_assurance"]),d2[0],delta_color=d2[1],help="对来源参数不确定性积分后的规划概率。")
 cols[2].metric("同设计全人群参照",pct(r["full_population_pos"]),d3[0],delta_color=d3[1],help="相同设计参数、移除基线筛选后的参照。")
 cols[3].metric("相对全人群差异",f'{r["delta_pos_vs_full"]*100:+.1f}个百分点',d4[0],delta_color=d4[1])
 e1=metric_delta(r,ref,"phase2_source_retention");e2=metric_delta(r,ref,"estimated_screened_n",count=True,inverse=True);e3=metric_delta(r,ref,"phase2_eligible_n",count=True)
 cols=st.columns([1,1,1,1.2])
 cols[0].metric("Phase II来源保留",pct(r["phase2_source_retention"]),e1[0],delta_color=e1[1])
 cols[1].metric("预计筛查人数",r["estimated_screened_n"] or "—",e2[0],delta_color=e2[1],help="仅按患者基线条件估算；来源中心敏感性不计入。")
 cols[2].metric("当前来源人数",r["phase2_eligible_n"],e3[0],delta_color=e3[1])
 status="可进入候选讨论" if r["evidence_support"]=="supported" else "仅作探索性假设"
 cols[3].markdown(f'<div class="support-status"><b>数据支持状态</b><strong>{status}</strong><span>当前比较组终点评价：{r["source_n_active"]}/{r["source_n_control"]}例；仍须结合区间与预警解释。</span></div>',unsafe_allow_html=True)
 left,right=st.columns([1.45,1])
 with left:st.plotly_chart(result_chart(r),use_container_width=True,config={"displayModeBar":False})
 with right:
  st.markdown("#### 当前解读")
  if r.get("endpoint_kind")=="ordinal":summary=f'假设共同优势比 OR={r["assumed_common_or"]:.2f}（>1偏向较好mRS）'
  else:
   direction="事件绝对减少" if r.get("endpoint_direction")=="lower" else "应答绝对增加"
   summary=f'{direction}{r["assumed_benefit"]*100:+.1f}个百分点；原始RD={r["assumed_risk_difference"]*100:+.1f}个百分点'
  st.write(f'{summary}；MC SE={pct(r["monte_carlo_standard_error"])}。请与来源支持、筛查负担及假设强度一起解释。')
  for item in r.get("warnings_ui",[])[:4]:render_warning(item)
 st.markdown("---");a,b=st.columns([2,1],vertical_alignment="bottom")
 name=a.text_input("情景名称",value=f"情景{len(st.session_state.saved_scenarios)+1}",max_chars=32,key=f'name_{r["scenario_hash"]}')
 if b.button("保存情景",type="primary",use_container_width=True):
  if any(x["result"]["scenario_hash"]==r["scenario_hash"] for x in st.session_state.saved_scenarios):st.info("相同参数情景已保存。")
  elif len(st.session_state.saved_scenarios)>=12:st.warning("最多保存12个情景，请先管理已有情景。")
  else:
   st.session_state.saved_scenarios.append({"scenario_id":f'{r["scenario_hash"]}-{time.time_ns()}',"name":name.strip() or f"情景{len(st.session_state.saved_scenarios)+1}","scenario":copy_json(s),"result":copy_json(r)})
   st.success("情景已保存；可直接应用、设为比较基准或进入比较管理。")
 anchor=anchor_item();payload={"scenario":s,"result":r,"anchor":None if not anchor else {"name":anchor["name"],"result":anchor["result"]},
  "engine_version":ENGINE_VERSION,"data_version":DATA_VERSION,"planning_stage":True,"not_a_prediction":True}
 st.markdown("#### 下载当前情景")
 c1,c2,c3=st.columns(3)
 c1.download_button("下载中文HTML报告",scenario_report_html(s,r,anchor),f'tapgrel_{r["scenario_hash"]}.html',"text/html",use_container_width=True)
 c2.download_button("下载CSV结果",pd.DataFrame([{**s,**{k:v for k,v in r.items() if not isinstance(v,(list,dict))}}]).to_csv(index=False),f'tapgrel_{r["scenario_hash"]}.csv',"text/csv",use_container_width=True)
 c3.download_button("下载JSON",json.dumps(payload,ensure_ascii=False,indent=2),f'tapgrel_{r["scenario_hash"]}.json',"application/json",use_container_width=True)
 st.caption("下载直接复用当前结果，不会重新运行模拟；不包含患者级记录。")

def copy_json(x):return json.loads(json.dumps(x,ensure_ascii=False))

def exploration_page():
 explorer_defaults();header("探索分析","设置候选设计与随机前人群条件，运行探索情景。")
 saved=st.session_state.saved_scenarios
 ids=[ALL_REFERENCE]+[sid(x,i) for i,x in enumerate(saved)];labels={sid(x,i):x["name"] for i,x in enumerate(saved)}
 if st.session_state.get("exp_saved_choice") not in ids:st.session_state.exp_saved_choice=ALL_REFERENCE
 st.selectbox("情景参数",ids,format_func=lambda x:"全人群（默认）" if x==ALL_REFERENCE else labels[x],
  key="exp_saved_choice",on_change=apply_saved_scenario_choice,
  help="选择后直接应用参数，但不会自动运行模拟；“全人群（默认）”恢复初始设计和不筛选人群。")
 anchor_selector("explore_anchor");reference_banner()
 st.subheader("设计参数")
 left,right=st.columns(2,gap="large")
 o=options()
 with left:
  st.selectbox("主要终点",o["primary_endpoints"],format_func=lambda x:ENDPOINT_LABELS[x],key="exp_endpoint",help=ENDPOINT_HELP,on_change=sync_endpoint_defaults)
  meta=endpoint_metadata(st.session_state.exp_endpoint)
  st.caption(f'{meta["evidence_tag"]}｜{meta["description"]}')
  st.selectbox("候选剂量",o["active_arms"],format_func=dose_name,key="exp_arm",help=dose_tooltip())
  st.number_input("目标随机样本量N",200,5000,step=2,key="exp_total_n",help="Phase III计划随机总人数；高级设置可调整两组分配。")
  if st.session_state.exp_endpoint=="cec_ischemic_stroke_d90":st.text_input("事件判定口径",value="D1–D90 CEC裁定缺血性卒中",disabled=True)
  else:st.selectbox("D90评分缺失处理/敏感性方法",o["source_scenarios"],format_func=lambda x:SOURCE_LABELS[x],key="exp_source",help=SOURCE_HELP)
  effect_unit="共同优势比的log效应" if meta["kind"]=="ordinal" else "Phase II观察有利差值"
  st.slider("相对Phase II原始效应系数",50,150,step=5,key="exp_effect",format="%d%%",help=f"100%=当前剂量、证据口径及来源人群的{effect_unit}；超过100%为乐观外推。")
 with right:
  st.markdown("##### 随机前候选人群")
  render_population_controls("exp")
  st.caption("筛选后的Phase II观察差异仅用于探索性发现；不证明治疗效应实际存在差异。")
 with st.expander("高级设置"):
  a,b,c=st.columns(3)
  with a:
   st.slider("试验组分配比例",30,70,step=5,key="exp_alloc",help="总N中分配至泰普格雷的比例。")
   st.number_input("Phase II来源中心mITT人数下限",0,int(assets()["population"].site_mitt_n.max()),key="exp_site_min",help="仅作来源中心敏感性，不是患者入组条件。")
  with b:
   st.selectbox("模拟次数",o["simulation_sizes"],format_func=lambda x:{1000:"1,000（快速）",5000:"5,000（稳定）",20000:"20,000（复核）"}[x],key="exp_sims")
  with c:
   st.number_input("随机种子",1,2147483647,key="exp_seed")
   rule="比例优势共同OR双侧95%区间下限>1" if meta["kind"]=="ordinal" else ("RD双侧95%区间上限<0" if meta["direction"]=="lower" else "RD双侧95%区间下限>0")
   st.text_input("探索性成功规则",value=rule,disabled=True,key=f"success_rule_{st.session_state.exp_endpoint}")
  if meta["kind"]=="binary":
   st.markdown("##### 规划对照率")
   st.checkbox("自动使用Phase II全人群氯吡格雷组观察值",key="exp_use_p2_control",help="对照率是二分类结局模拟的必要输入；默认值来自所选终点下Phase II氯吡格雷组观察结果。")
   source="cec_adjudicated_d1_d90" if st.session_state.exp_endpoint=="cec_ischemic_stroke_d90" else st.session_state.exp_source
   low,high=(.01,.50) if st.session_state.exp_endpoint=="cec_ischemic_stroke_d90" else (.20,.95)
   label="缺血性卒中发生率" if meta["direction"]=="lower" else f'{meta["short_label"]}应答率'
   if not st.session_state.exp_use_p2_control:
    st.number_input(f"自定义未来对照组{label}",low,high,step=.005,format="%.3f",key="exp_custom_control",help="仅作规划假设；未来应结合Phase III方案、同期标准治疗和可比外部证据确认。")
   else:
    p0=default_control_rate(st.session_state.exp_arm,source,st.session_state.exp_endpoint)
    st.number_input("当前自动对照率",low,high,value=float(p0),step=.005,format="%.3f",disabled=True,key=f'default_p0_{st.session_state.exp_endpoint}_{st.session_state.exp_arm}_{source}')
  else:
   st.markdown("##### 规划对照分布")
   evidence=phase2_evidence(st.session_state.exp_arm,st.session_state.exp_source,None,st.session_state.exp_endpoint)
   dist=evidence["control_distribution"];den=sum(dist)
   st.dataframe(pd.DataFrame({"mRS等级":list(range(7)),"Phase II对照组例数":dist,"规划比例":[x/den for x in dist]}).style.format({"规划比例":"{:.1%}"}),hide_index=True,use_container_width=True)
   st.caption("第一版固定使用所选D90缺失口径下的Phase II全人群对照组0–6分布；效应系数作用于log共同优势比。")
 draft=build_explorer_scenario();preview=preview_scenario(draft)
 if preview.get("warnings_ui"):
  st.markdown("#### 参数提示")
  for item in preview["warnings_ui"][:5]:render_warning(item)
 if preview["status"]!="supported":
  st.markdown("#### 当前组合的计算可用性")
  for reason in preview.get("errors",[]):render_warning({"level":"block","title":"核心结果不可计算","text":reason})
 run=st.button("运行模拟",type="primary",disabled=preview["status"]!="supported",use_container_width=True)
 if run:
  progress=st.progress(12,text="核对参数与来源支持");started=time.perf_counter();progress.progress(45,text="运行频率学Monte Carlo")
  before=st.session_state.current_result;result=evaluate_scenario(draft);progress.progress(78,text="计算Bayesian assurance与全人群参照")
  elapsed=time.perf_counter()-started;progress.progress(100,text="情景计算完成")
  meta={"elapsed_seconds":elapsed,"cache_hit":bool(before and before.get("scenario_hash")==result.get("scenario_hash"))}
  st.session_state.current_scenario=result.get("normalized_scenario",draft);st.session_state.current_result=result;st.session_state.current_meta=meta
  if result.get("status")=="supported":
   if st.session_state.result_motion_enabled:
    ref,label,_=reference_for(result);result_dialog(result,ref,label,meta)
   else:st.toast("模拟完成，结果已更新。")
 current=st.session_state.current_result
 if current:
  current_hash=current.get("scenario_hash");draft_hash=scenario_hash(preview["normalized_scenario"]) if preview.get("normalized_scenario") else None
  if draft_hash and current_hash!=draft_hash:st.info("参数已调整；下方仍显示上一次已运行结果。点击“运行模拟”后更新。")
  st.markdown('<div class="result-strip"></div>',unsafe_allow_html=True)
  render_results(st.session_state.current_scenario,current,st.session_state.current_meta)
 else:st.info("设置参数后点击“运行模拟”。调整控件不会自动计算。")

def manual_population_scenario():
 d=assets()["population"];o=options()
 for k,v in {"pop_endpoint":"mrs01_day90","pop_arm":o["active_arms"][0],"pop_source":o["source_scenarios"][0],"pop_nihss":(int(d.baseline_nihss.min()),int(d.baseline_nihss.max())),
  "pop_features":[],"pop_age":(int(d.age.min()),int(d.age.max())),"pop_sex":o["sex_values"],"pop_mrs":o["baseline_mrs_values"],
  "pop_sbp_operator":"all","pop_sbp_threshold":140,"pop_presentation":o["presentation_values"],
  "pop_hypertension":o["history_values"],"pop_diabetes":o["history_values"],"pop_dyslipidemia":o["history_values"],
  "pop_cyp2c19":o["cyp2c19_values"],"pop_prior_proxy":o["prior_stroke_tia_proxy_values"],"pop_site_min":0}.items():st.session_state.setdefault(k,v)
 a,b=st.columns(2)
 a.selectbox("主要终点",o["primary_endpoints"],format_func=lambda x:ENDPOINT_LABELS[x],key="pop_endpoint",help=ENDPOINT_HELP)
 b.selectbox("候选剂量",o["active_arms"],format_func=dose_name,key="pop_arm",help=dose_tooltip())
 if st.session_state.pop_endpoint!="cec_ischemic_stroke_d90":st.selectbox("D90评分缺失处理/敏感性方法",o["source_scenarios"],format_func=lambda x:SOURCE_LABELS[x],key="pop_source",help=SOURCE_HELP)
 else:st.info("事件判定口径固定为D1–D90 CEC裁定缺血性卒中。")
 render_population_controls("pop")
 st.number_input("Phase II来源中心mITT人数下限（敏感性）",0,int(d.site_mitt_n.max()),key="pop_site_min")
 source="cec_adjudicated_d1_d90" if st.session_state.pop_endpoint=="cec_ischemic_stroke_d90" else st.session_state.pop_source
 return {"primary_endpoint":st.session_state.pop_endpoint,"active_arm":st.session_state.pop_arm,"source_scenario":source,"population_filters":filters_from_state("pop")}

def population_change_html(cur,prev):
 metrics=[("当前来源人数","eligible_n","int"),("来源保留比例","source_retention","pct"),("患者条件人数","patient_eligible_n","int")]
 cards=[]
 for title,key,kind in metrics:
  a=float(prev.get(key,0))*(100 if kind=="pct" else 1);b=float(cur.get(key,0))*(100 if kind=="pct" else 1)
  cards.append(f'<div><span>{title}</span><strong class="c" data-a="{a}" data-b="{b}" data-k="{kind}">{a:.1f}</strong></div>')
 return f"""<!doctype html><html><meta charset=utf-8><style>body{{font-family:Microsoft YaHei,Arial;margin:0;color:#182230}}.g{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.g div{{padding:14px;border:1px solid #e4e7ec;border-radius:6px}}span{{display:block;color:#667085;font-size:12px}}strong{{font-size:22px}}.flow{{margin-top:20px}}.flow i{{display:block;height:12px;background:#0f766e;margin:8px 0;transition:width 650ms}}</style><body><div class=g>{''.join(cards)}</div><div class=flow>{''.join(f'<span>{html.escape(x["stage"])}：{x["n"]}例</span><i data-w="{x["n"]/max(cur["source_n"],1)*100:.3f}" style="width:0"></i>' for x in cur["flow"])}</div><script>requestAnimationFrame(()=>{{document.querySelectorAll('i').forEach(x=>x.style.width=x.dataset.w+'%');const s=performance.now();function t(n){{const p=Math.min(1,(n-s)/650),e=1-Math.pow(1-p,3);document.querySelectorAll('.c').forEach(x=>{{let v=+x.dataset.a+(+x.dataset.b-+x.dataset.a)*e;x.textContent=x.dataset.k==='pct'?v.toFixed(1)+'%':Math.round(v).toLocaleString('zh-CN')}});if(p<1)requestAnimationFrame(t)}}requestAnimationFrame(t)}})</script></body></html>"""

@st.dialog("人群变化速览",width="large")
def population_dialog(cur,prev):
 components.html(population_change_html(cur,prev),height=430,scrolling=False)
 st.caption("变化相对上一已应用筛选；人数增加表示来源支持增加，不代表疗效提高。")

@st.dialog("放大查看",width="large")
def chart_dialog(title,fig,key):
 st.markdown(f"### {title}");large=go.Figure(fig);large.update_layout(height=700,transition=dict(duration=0))
 st.plotly_chart(large,use_container_width=True,key=f"{key}_large")

def render_chart(fig,title,key):
 st.markdown(f"### {title}");fig.update_layout(transition=dict(duration=650 if st.session_state.result_motion_enabled else 0),uirevision=key)
 st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False},key=f"{key}_chart")
 _,b=st.columns([10,1])
 if b.button("放大",icon=":material/fullscreen:",key=f"{key}_expand",use_container_width=True):chart_dialog(title,fig,key)

def distribution_figure(rows,mode,show_zero):
 rows=[x for x in rows if show_zero or x["full_n"] or x["eligible_n"]]
 labels=[x["level"] for x in rows];full=[x["full_pct"]*100 for x in rows];current=[x["eligible_pct"]*100 for x in rows]
 custom=[[x["full_n"],x["full_denominator"],x["eligible_n"],x["eligible_denominator"],(x["eligible_pct"]-x["full_pct"])*100] for x in rows]
 full_text=[f'{x["full_n"]}/{x["full_denominator"]} · {x["full_pct"]:.1%}' for x in rows]
 current_text=[f'{x["eligible_n"]}/{x["eligible_denominator"]} · {x["eligible_pct"]:.1%}' for x in rows]
 fig=go.Figure()
 if mode=="完整分布":
  fig.add_bar(name="Phase II全人群",x=full,y=labels,orientation="h",marker_color="#cbd5e1",customdata=custom,
   text=full_text,textposition="outside",cliponaxis=False,textfont=dict(size=11,color="#475467"),
   hovertemplate="<b>%{y}</b><br>全人群：%{customdata[0]}/%{customdata[1]}（%{x:.1f}%）<extra></extra>")
  fig.add_bar(name="当前条件人群",x=current,y=labels,orientation="h",marker_color="#0f766e",customdata=custom,
   text=current_text,textposition="outside",cliponaxis=False,textfont=dict(size=11,color="#344054"),
   hovertemplate="<b>%{y}</b><br>当前：%{customdata[2]}/%{customdata[3]}（%{x:.1f}%）<br>差异：%{customdata[4]:+.1f}个百分点<extra></extra>")
  fig.update_layout(barmode="group",xaxis_title="人群内占比（%）")
  axis_max=max(full+current,default=0);fig.update_xaxes(range=[0,max(10,axis_max+max(12,axis_max*.28))])
 else:
  diff=[b-a for a,b in zip(full,current)];diff_text=[f"{x:+.1f}个百分点" for x in diff]
  fig.add_bar(x=diff,y=labels,orientation="h",marker_color=["#0f766e" if x>0 else "#64748b" for x in diff],customdata=custom,
   text=diff_text,textposition="outside",cliponaxis=False,textfont=dict(size=11,color="#344054"),
   hovertemplate="<b>%{y}</b><br>全人群：%{customdata[0]}/%{customdata[1]}<br>当前：%{customdata[2]}/%{customdata[3]}<br>差异：%{x:+.1f}个百分点<extra></extra>")
  fig.add_vline(x=0,line_color="#98a2b3");fig.update_layout(xaxis_title="当前条件人群 − Phase II全人群（百分点）",showlegend=False)
  limit=max(5,max((abs(x) for x in diff),default=0)*1.45);fig.update_xaxes(range=[-limit,limit])
 fig.update_layout(height=max(390,len(rows)*56+175),margin=dict(l=55,r=135,t=92,b=55),
  yaxis=dict(autorange="reversed",automargin=True),plot_bgcolor="white",paper_bgcolor="white",
  legend=dict(orientation="h",yanchor="bottom",y=1.08,xanchor="left",x=0))
 return fig

def population_page():
 header("二期人群洞察","按手动参数、当前探索结果或已保存情景查看Phase II来源人群分布与数值。")
 sources=["手动选择参数"]
 if st.session_state.current_scenario:sources.append("读取当前探索参数")
 if st.session_state.saved_scenarios:sources.append("读取已保存情景")
 source=st.radio("参数来源",sources,horizontal=True,help="本页只做Phase II聚合汇总，不重新运行Monte Carlo或Bayesian模拟。")
 if source=="手动选择参数":scenario=manual_population_scenario()
 elif source=="读取当前探索参数":
  scenario=copy_json(st.session_state.current_scenario);st.info("已读取当前探索分析最近一次运行的参数。")
 else:
  saved=st.session_state.saved_scenarios;idx=st.selectbox("选择已保存情景",range(len(saved)),format_func=lambda i:saved[i]["name"])
  scenario=copy_json(saved[idx]["scenario"]);st.info(f'已读取“{saved[idx]["name"]}”。')
 signature=json.dumps(scenario,sort_keys=True,ensure_ascii=False)
 dirty=st.session_state.get("population_signature")!=signature
 if dirty and st.session_state.population_applied:st.info("参数已改变；下方仍显示上一已应用筛选。")
 if st.button("应用筛选",type="primary",disabled=not dirty,use_container_width=True):
  cur=population_insights(scenario);prev=st.session_state.population_applied
  st.session_state.population_previous=prev;st.session_state.population_applied=cur;st.session_state.population_signature=signature
  if prev and st.session_state.result_motion_enabled:population_dialog(cur,prev)
  else:st.toast("二期人群汇总已更新。")
 if st.session_state.population_applied is None:
  st.session_state.population_applied=population_insights(scenario);st.session_state.population_signature=signature
 ins=st.session_state.population_applied;prev=st.session_state.population_previous
 st.markdown("### 当前人群概览")
 if prev:st.caption("箭头相对上一已应用筛选；人数变化不代表疗效方向。")
 cols=st.columns(4)
 cols[0].metric("Phase II mITT来源",ins["source_n"])
 cols[1].metric("患者条件人数",ins["patient_eligible_n"])
 cols[2].metric("当前来源人数",ins["eligible_n"])
 cols[3].metric("来源保留比例",pct(ins["source_retention"]))
 arm_map={x["arm"]:x for x in ins["arm_distribution"]};active=ins["scenario"]["active_arm"]
 a,b=st.columns(2);a.metric(f"所选剂量组（{dose_name(active)}）",arm_map.get(active,{}).get("n",0));b.metric(CONTROL_ARM,arm_map.get(CONTROL_ARM,{}).get("n",0))
 if ins["support_status"]=="数据支持相对充分":st.success(f'数据支持状态：{ins["support_status"]}，可进入候选讨论')
 else:st.warning(f'数据支持状态：{ins["support_status"]}')
 st.warning(ins["warning"])
 flow=ins["flow"];fig=go.Figure(go.Bar(x=[x["n"] for x in flow],y=[x["stage"] for x in flow],orientation="h",marker_color=["#98a2b3","#3b82f6","#0f766e","#d97706"][:len(flow)],text=[x["n"] for x in flow],textposition="outside",hovertemplate="%{y}：%{x}例<extra></extra>"))
 fig.update_layout(height=360,margin=dict(l=50,r=70,t=40,b=40),yaxis=dict(autorange="reversed"),plot_bgcolor="white",paper_bgcolor="white")
 render_chart(fig,"人群筛选流程","pop_flow")
 arms=ins["arm_distribution"];fig=go.Figure(go.Bar(x=[dose_name(x["arm"]) if x["arm"]!=CONTROL_ARM else x["arm"] for x in arms],y=[x["n"] for x in arms],marker_color=["#3b82f6","#0f766e","#d97706"],text=[x["n"] for x in arms],textposition="outside",customdata=[[x["available_n"],x["missing_n"]] for x in arms],hovertemplate="%{x}：%{y}例<br>终点可用：%{customdata[0]}<br>缺失：%{customdata[1]}<extra></extra>"))
 fig.update_layout(height=350,yaxis_title="人数",plot_bgcolor="white",paper_bgcolor="white")
 render_chart(fig,"当前条件人群的原随机组构成","pop_arms")
 a,b=st.columns([1.5,1])
 mode=a.segmented_control("页面比较模式",["完整分布","相对全人群变化"],default="完整分布")
 zero=sum(1 for rows in ins["distributions"].values() for x in rows if x["full_n"]==0 and x["eligible_n"]==0)
 show_zero=b.toggle(f"显示零占比分层（{zero}）",value=False,disabled=zero==0)
 for i,(title,rows) in enumerate(ins["distributions"].items()):render_chart(distribution_figure(rows,mode,show_zero),title,f"dist_{i}_{mode}_{int(show_zero)}")
 current=ins["outcome"];full=ins["full_outcome"];fig=go.Figure();meta=ins["endpoint"]
 if meta["kind"]=="binary":
  for name,rows,color in [("Phase II全人群",full,"#cbd5e1"),("当前条件人群",current,"#0f766e")]:
   fig.add_bar(name=name,x=[dose_name(x["arm"]) if x["arm"]!=CONTROL_ARM else x["arm"] for x in rows],y=[None if x["response_rate"] is None else x["response_rate"]*100 for x in rows],marker_color=color,
    customdata=[[x["n"],x["available_n"],x["missing_n"],x["responders"]] for x in rows],hovertemplate="<b>%{x}</b><br>来源n=%{customdata[0]}<br>可用n=%{customdata[1]}<br>缺失n=%{customdata[2]}<br>事件/应答=%{customdata[3]}<br>比例=%{y:.1f}%<extra></extra>")
  fig.update_layout(barmode="group",height=410,yaxis=dict(title=f'{meta["short_label"]}比例（%）',range=[0,100]),plot_bgcolor="white",paper_bgcolor="white",legend=dict(orientation="h",y=1.05))
 else:
  colors=["#d9f0ed","#b8ddd8","#7fc4ba","#40a699","#0f766e","#475467","#182230"]
  for level,color in enumerate(colors):
   values=[];custom=[]
   for x in current:
    den=max(x["available_n"],1);values.append(x.get("distribution",[0]*7)[level]/den*100);custom.append([x.get("distribution",[0]*7)[level],x["available_n"]])
   fig.add_bar(name=f"mRS {level}",x=[dose_name(x["arm"]) if x["arm"]!=CONTROL_ARM else x["arm"] for x in current],y=values,marker_color=color,customdata=custom,hovertemplate=f"mRS {level}：%{{customdata[0]}}/%{{customdata[1]}}（%{{y:.1f}}%）<extra></extra>")
  fig.update_layout(barmode="stack",height=430,yaxis=dict(title="D90 mRS等级构成（%）",range=[0,100]),plot_bgcolor="white",paper_bgcolor="white",legend=dict(orientation="h",y=1.12))
 render_chart(fig,f'{meta["label"]}结局概况',"pop_outcome")
 frames=[]
 for title,rows in ins["distributions"].items():
  for x in rows:frames.append({"分布":title,**x})
 st.download_button("下载二期人群聚合数值CSV",pd.DataFrame(frames).to_csv(index=False),"tapgrel_phase2_population_insights.csv","text/csv")
 st.caption("所有图表和下载均为去标识化聚合值；不包含患者明细。")

@st.dialog("确认删除情景")
def delete_dialog(identity):
 saved=st.session_state.saved_scenarios;target=next((x for i,x in enumerate(saved) if sid(x,i)==identity),None)
 if not target:st.info("情景已不存在。");return
 st.warning(f'将永久删除“{target["name"]}”。此操作与比较勾选无关。')
 if st.session_state.anchor_id==identity:st.error("该情景是当前比较基准；删除后将恢复为全人群。")
 a,b=st.columns(2)
 if a.button("取消",use_container_width=True):st.rerun()
 if b.button("确认删除",type="primary",use_container_width=True):
  st.session_state.saved_scenarios=[x for i,x in enumerate(saved) if sid(x,i)!=identity]
  st.session_state.comparison_selected_ids=[x for x in st.session_state.comparison_selected_ids if x!=identity]
  if st.session_state.anchor_id==identity:set_anchor(None)
  st.toast("情景已删除。");st.rerun()

def comparison_report_html(items,anchor):
 rows=""
 for item in items:
  r=item["result"];rows+=f'<tr><td>{html.escape(item["name"])}</td><td>{html.escape(r.get("endpoint_label","D90 mRS≤1"))}</td><td>{html.escape(dose_name(item["scenario"]["active_arm"]))}</td><td>{item["scenario"]["total_n"]}</td><td>{item["scenario"]["effect_multiplier"]:.0%}</td><td>{pct(r.get("monte_carlo_pos"))}</td><td>{pct(r.get("bayesian_assurance"))}</td><td>{pct(r.get("phase2_source_retention"))}</td></tr>'
 return f"""<!doctype html><html lang=zh-CN><meta charset=utf-8><style>body{{font-family:Arial;max-width:980px;margin:32px auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d0d5dd;padding:8px}}</style><h1>泰普格雷情景比较报告</h1><p><b>探索性规划，不是Phase III成功率预测。</b></p><p>比较基准：{html.escape(anchor["name"] if anchor else "全人群")}；引擎：{ENGINE_VERSION}</p><table><tr><th>情景</th><th>主要终点</th><th>剂量</th><th>N</th><th>效应系数</th><th>成功频率</th><th>Assurance</th><th>来源保留</th></tr>{rows}</table></html>"""

def comparison_page():
 header("情景比较与管理","比较选择、比较基准和永久删除分别管理；取消比较选择不会删除情景。")
 saved=st.session_state.saved_scenarios
 if not saved:st.info("尚未保存情景。请先在探索分析运行并保存。");return
 entries=[(sid(x,i),x) for i,x in enumerate(saved)];ids=[x for x,_ in entries];labels={x:y["name"] for x,y in entries}
 anchor_selector("comparison_anchor","比较基准")
 if anchor_item():st.success(f'当前比较基准：“{anchor_item()["name"]}”。')
 else:st.info("当前比较基准：全人群。")
 known=st.session_state.comparison_known_ids;selected=[x for x in st.session_state.comparison_selected_ids if x in ids]
 selected.extend(x for x in ids if x not in known and x not in selected)
 if not known:selected=list(ids)
 st.session_state.comparison_selected_ids=selected;st.session_state.comparison_known_ids=list(ids)
 selected=st.multiselect("选择参与比较的情景",ids,format_func=lambda x:labels[x],key="comparison_selected_ids",
  help="取消勾选只表示不参与本次比较，不会删除情景。永久删除必须在下方管理区单独确认。")
 st.info(f"已选择{len(selected)}/{len(ids)}个情景参与比较。未选情景仍完整保存在管理列表中。")
 chosen=[item for identity,item in entries if identity in set(selected)]
 if chosen:
  endpoints={x["result"].get("primary_endpoint","mrs01_day90") for x in chosen}
  if len(endpoints)>1:st.warning("当前比较包含不同主要终点；成功频率使用各自成功规则，只适合并列查看设计情景，不应解释为同一estimand下的优劣排序。")
  frame=comparison_frame(chosen)
  st.dataframe(frame.style.format({"效应系数":"{:.0%}","对照发生/应答率":"{:.1%}","试验组分配":"{:.0%}","来源保留":"{:.1%}","探索性成功频率":"{:.1%}","全人群参照":"{:.1%}","Bayesian assurance":"{:.1%}","假设RD":"{:+.1%}","假设共同OR":"{:.2f}"},na_rep="—"),use_container_width=True,hide_index=True)
 else:st.warning("当前没有情景参与比较；下方管理列表仍保留全部情景。")
 snap=[{"id":identity,"name":item["name"],"pos":float(item["result"].get("monte_carlo_pos") or 0)*100,"assurance":float(item["result"].get("bayesian_assurance") or 0)*100} for identity,item in entries if identity in set(selected)]
 components.html(_comparison_animation_html(snap,st.session_state.comparison_previous_snapshot,st.session_state.result_motion_enabled),height=380,scrolling=False)
 st.session_state.comparison_previous_snapshot=snap
 st.caption("勾选变化只更新比较表和动画；不会删除、改名或重新运行任何情景。")
 if chosen:
  anchor=anchor_item();a,b=st.columns(2)
  a.download_button("下载比较HTML报告",comparison_report_html(chosen,anchor),"tapgrel_scenario_comparison.html","text/html",use_container_width=True)
  b.download_button("下载比较CSV",comparison_frame(chosen).to_csv(index=False),"tapgrel_scenario_comparison.csv","text/csv",use_container_width=True)
 st.markdown("#### 管理已保存情景")
 for identity,item in entries:
  name,rename,anchor_col,delete=st.columns([2.8,1,1.2,1],vertical_alignment="bottom")
  new=name.text_input("情景名称",value=item["name"],key=f"rename_value_{identity}",label_visibility="collapsed")
  if rename.button("重命名",key=f"rename_{identity}",use_container_width=True):
   if new.strip():item["name"]=new.strip();st.rerun()
  is_anchor=st.session_state.anchor_id==identity
  if anchor_col.button("当前基准" if is_anchor else "设为基准",key=f"anchor_{identity}",disabled=is_anchor,use_container_width=True):
   set_anchor(identity);st.rerun()
  if delete.button("删除",key=f"delete_{identity}",use_container_width=True):delete_dialog(identity)
 st.caption("只有点击每行“删除”并在确认对话框再次确认，情景才会被永久删除。")

def manual_page():
 header("使用说明","说明参数、比较基准、人群洞察、情景管理和方法边界。")
 st.markdown("""### 三步完成一次探索
<div class="manual-step"><b>1. 选择参数</b><br>选择剂量、样本量、D90口径、效应系数、对照率及随机前候选人群。</div>
<div class="manual-step"><b>2. 查看预警并运行</b><br>特殊组合会在运行前分级提示；无法支持的组合不会生成伪精确概率。</div>
<div class="manual-step"><b>3. 保存、比较和下载</b><br>保存情景后可直接应用参数、设为比较基准，并下载当前或比较报告。</div>""",unsafe_allow_html=True)
 st.subheader("常见问题")
 qa=[
 ("100%效应系数是什么意思？","等于当前剂量、D90证据口径和所选Phase II来源人群的观察风险差；不是已证实真实效应；高于100%代表认为三期结果比二期乐观。"),
 ("比较基准会改变模拟吗？","不会。它只改变卡片箭头、动画和报告中的参照。"),
 ("取消比较选择会删除情景吗？","不会。取消勾选只使情景退出本次比较；永久删除必须在管理区二次确认。"),
 ("二期人群洞察会重新运行模型吗？","不会。该页只计算去标识化Phase II mITT聚合分布和描述性结局。"),
 ("为什么只使用mITT？","Phase II SAP将mITT规定为主要有效性分析人群；PPS仅作支持性分析且会按治疗后信息排除患者，因此本工具固定使用mITT作为疗效来源。"),
 ("为什么中心人数不能作为入组条件？","它描述Phase II来源中心结构，不是患者随机前临床特征，因此只作来源敏感性且不计入筛查人数。"),
 ("下载报告会重新模拟吗？","不会。下载复用已完成结果，保留完整参数、版本、比较基准、预警和规划边界。")]
 for q,a in qa:
  with st.expander(q):st.write(a)
 with st.expander("方法、假设与限制",expanded=True):
  st.markdown("""- 可切换的四个主要终点情景：D1–D90 CEC裁定缺血性卒中、D90完整有序mRS、D90 mRS≤1及D90 mRS≤2；每次只选择一个，不自动构成共同主要或次要终点层级。
- CEC缺血性卒中使用二项累积发生率规划；mRS≤1/≤2使用二项Monte Carlo；完整有序mRS使用比例优势共同OR近似Monte Carlo。不同终点的成功频率不可直接当作同一estimand横向排序。
- Phase II SAP正式mRS分析为shift；mRS二分类证据属于探索性规划。完整有序mRS仍需在正式SAP中核查比例优势假设、协变量调整和缺失/ICE策略。
- 分析人群固定为Phase II mITT；不提供PPS或安全性分析集切换。
- D90缺失/记录设置均为规划敏感性方法；LOCF型已单列，Phase II SAP未规定对mRS进行多重插补。
- 频率学结果：二项Monte Carlo，RD双侧95% Newcombe/Wilson区间下限>0。
- Bayesian assurance：积分Phase II来源参数不确定性；二分类终点使用弱信息Beta(1,1)，有序mRS使用弱信息正态先验近似，均不向普通用户开放先验切换。
- 人群筛选只使用随机前基线变量；筛选后观察差异不证明治疗效应修饰。
- 高血压、糖尿病、血脂异常及入组时疾病/影像类型已与SAR人数核对；CYP2C19仅作高级稀疏探索。
- “既往卒中/TIA病史”在SAR中为合并亚组；当前患者级选择由MH关键词临时派生，选择后显示强警示，待官方派生规则或最终旗标核对。
- 正式Phase III方案、SAP、剂量/多臂结构、分析人群、缺失/ICE、alpha和多重性仍待锁定。""")
 st.caption("打开本页不会运行模型或生成虚拟患者。")

def changelog_page():
 header("更新日志","正式发布后的功能、数据与方法变化将在此记录。")
 entries=load_json(str(RUNTIME/"changelog.json")) if (RUNTIME/"changelog.json").exists() else []
 if not entries:
  st.info("暂无发布后更新记录。")
  st.caption("本页不会运行模型或修改已保存情景。")
  return
 posts=[]
 for e in entries:
  highlights="".join(f"<li>{html.escape(str(x))}</li>" for x in e.get("highlights",[]))
  posts.append(f'<article class="change-post"><div class="change-meta"><span class="change-badge">功能更新</span><span>{html.escape(e.get("date",""))}</span></div><h3>{html.escape(e.get("title","更新"))}</h3><p>{html.escape(e.get("body",""))}</p><ul>{highlights}</ul></article>')
 st.markdown(f'<div class="change-feed">{"".join(posts)}</div>',unsafe_allow_html=True)

def safe_upload(name,data):
 ext=Path(name).suffix.lower();return hashlib.sha256(data).hexdigest()[:16]+(ext if ext in {".png",".jpg",".jpeg",".webp"} else "")

def feedback_page():
 header("问题反馈","提交使用问题、截图或建议并获得追踪编号。")
 st.markdown('<div class="local-note"><strong>反馈提交</strong><br>提交后将保存记录，并通知项目负责人。</div>',unsafe_allow_html=True)
 left,right=st.columns([2.1,1],gap="large")
 with left:
  with st.form("feedback",clear_on_submit=True):
   a,b,c=st.columns(3);category=a.selectbox("问题类型",["功能异常","界面或排版","计算结果疑问","功能建议","其他"]);impact=b.selectbox("影响程度",["一般建议","影响部分使用","无法继续使用"]);source=c.selectbox("问题发生页面",PAGES)
   title=st.text_input("问题标题",max_chars=80);description=st.text_area("问题描述",height=150,max_chars=4000)
   steps=st.text_area("复现步骤（可选）",height=90,max_chars=2000);contact=st.text_input("联系邮箱（可选）")
   upload=st.file_uploader("上传截图（可选，≤5MB）",type=["png","jpg","jpeg","webp"])
   attach=st.checkbox("关联当前情景级参数与汇总结果",value=bool(st.session_state.current_result),disabled=not st.session_state.current_result)
   privacy=st.checkbox("我确认文字和截图不包含任何患者可识别信息。")
   submit=st.form_submit_button("提交反馈",type="primary",use_container_width=True)
  if submit:
   if not privacy:st.error("请先确认不包含患者隐私。")
   elif not title.strip() or not description.strip():st.error("请填写标题和问题描述。")
   elif upload and len(upload.getvalue())>5*1024*1024:st.error("截图超过5MB。")
   else:
    now=datetime.now(timezone.utc).isoformat();fid="FB-"+hashlib.sha256(f"{now}|{title}".encode()).hexdigest()[:10].upper();attachment=None
    attachment_path=None
    if upload:
     data=upload.getvalue();attachment=safe_upload(upload.name,data);dest=RUNTIME/"feedback/uploads";dest.mkdir(parents=True,exist_ok=True);attachment_path=dest/attachment;attachment_path.write_bytes(data)
    record={"feedback_id":fid,"submitted_at_utc":now,"category":category,"impact":impact,"source_page":source,"title":title.strip(),"description":description.strip(),"steps":steps.strip(),"contact":contact.strip(),"attachment":attachment,
     "scenario":None if not attach else {"scenario":st.session_state.current_scenario,"result":st.session_state.current_result}}
    target=RUNTIME/"feedback/feedback.jsonl";target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("a",encoding="utf-8") as f:f.write(json.dumps(record,ensure_ascii=False)+"\n")
    try:queue_feedback_email(record,attachment_path)
    except Exception:st.warning(f"反馈已保存：{fid}。邮件通知正在恢复，请保留该编号。")
    else:st.success(f"反馈已提交：{fid}")
 with right:
  st.markdown("### 提交建议");st.markdown("- 标明问题页面和影响程度。\n- 写清复现顺序。\n- 保留截图。\n- 可提供当前情景参数。")
  st.warning("请勿提交患者级数据、受试者编号或其他可识别信息。")

def sidebar():
 workspace=[("探索分析",":material/tune:"),("二期人群洞察",":material/groups:"),("情景比较与管理",":material/compare_arrows:"),("使用说明",":material/menu_book:")]
 collab=[("更新日志",":material/history:"),("问题反馈",":material/bug_report:")]
 with st.sidebar:
  if LOGO_PATH.exists():st.image(str(LOGO_PATH),width=168)
  st.markdown('<div class="sidebar-product">泰普格雷 Phase III规划探索</div><div class="sidebar-section">工作区</div>',unsafe_allow_html=True)
  for label,icon in workspace:
   if st.button(label,icon=icon,type="primary" if st.session_state.active_page==label else "tertiary",use_container_width=True,key=f"nav_{label}"):
    st.session_state.active_page=label;st.rerun()
  st.markdown('<div class="sidebar-section" style="margin-top:10px">协作</div>',unsafe_allow_html=True)
  for label,icon in collab:
   if st.button(label,icon=icon,type="primary" if st.session_state.active_page==label else "tertiary",use_container_width=True,key=f"nav_{label}"):
    st.session_state.active_page=label;st.rerun()
  st.markdown('<div class="sidebar-section" style="margin-top:16px">显示设置</div>',unsafe_allow_html=True)
  st.toggle("结果动画",value=True,key="result_motion_enabled",help="只控制结果、人群和比较变化动画，不改变计算。")
  st.markdown('<div class="sidebar-status"><div><span class="status-dot"></span>试用环境运行中</div><div>探索性 / 规划阶段</div></div>',unsafe_allow_html=True)
  if st.button("退出登录",icon=":material/logout:",use_container_width=True,key="logout"):
   clear_access();st.rerun()

def main():
 cfg=load_json(str(CONFIG_PATH));init_state();require_access(cfg);sidebar();page=st.session_state.active_page
 if page=="探索分析":exploration_page()
 elif page=="二期人群洞察":population_page()
 elif page=="情景比较与管理":comparison_page()
 elif page=="使用说明":manual_page()
 elif page=="更新日志":changelog_page()
 else:feedback_page()

if __name__=="__main__":main()
