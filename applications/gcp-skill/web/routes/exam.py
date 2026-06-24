"""Exam route: final exam with A-D only, no instant feedback, interrupt/resume."""
import sys
from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from web.config import BANK_PATH, SCRIPTS_DIR, FINAL_RULES_PATH, CHAPTERS
from web.record_manager import load_record, save_record
from web.user_manager import load_account

sys.path.insert(0, str(SCRIPTS_DIR.parent))
from scripts.pick_questions import load_json, pick_final

router = APIRouter()


@router.get("/start", response_class=HTMLResponse)
async def exam_start(request: Request,
                     retake: int = 0,
                     username: str = Cookie(None),
                     learner_role: str = Cookie(None)):
    """Start or resume final exam."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    # If exam already completed and not explicitly retaking, show scorecard
    if record.get("final_score") is not None and not record.get("final_exam_in_progress") and not retake:
        return _exam_scorecard(request, record, username, real_name, learner_role)

    # If retaking or starting fresh, clear old exam state and results
    if retake:
        if record.get("final_exam_in_progress"):
            del record["final_exam_in_progress"]
        # Clear old final results so new exam can set fresh ones
        for key in ("final_score", "final_grade", "chapter_scores"):
            record.pop(key, None)
        save_record(username, learner_role, record)

    # Check for in-progress exam (resume)
    exam_state = record.get("final_exam_in_progress")
    if exam_state and exam_state.get("question_ids"):
        current = exam_state.get("current_question", 1)
        return _render_exam_question(request, record, username, real_name, learner_role,
                                     exam_state, current)

    # New exam: pick 30 questions
    bank = load_json(BANK_PATH)
    rules = load_json(FINAL_RULES_PATH)
    picks = pick_final(bank, rules)

    exam_state = {
        "question_ids": [q["id"] for q in picks],
        "answers": {},
        "current_question": 1,
        "total": len(picks),
    }
    record["final_exam_in_progress"] = exam_state
    save_record(username, learner_role, record)

    return _render_exam_question(request, record, username, real_name, learner_role,
                                 exam_state, 1)


def _render_exam_question(request, record, username, real_name, learner_role,
                          exam_state, question_num):
    """Render a single exam question. No E option. No feedback. No AI."""
    question_ids = exam_state.get("question_ids", [])
    total = len(question_ids)

    if question_num > total:
        return _exam_results(request, record, username, learner_role)

    bank = load_json(BANK_PATH)
    q_id = question_ids[question_num - 1]
    question = next((q for q in bank["questions"] if q["id"] == q_id), None)

    if not question:
        return HTMLResponse("Question not found", status_code=404)

    return request.app.state.templates.TemplateResponse("exam.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "question": question,
        "question_num": question_num,
        "total": total,
        "show_results": False,
    })


@router.post("/answer", response_class=HTMLResponse)
async def exam_answer(request: Request,
                      question_id: str = Form(...),
                      answer: str = Form(...),
                      username: str = Cookie(None),
                      learner_role: str = Cookie(None)):
    """Record an exam answer and advance. No feedback shown."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    exam_state = record.get("final_exam_in_progress", {})
    answers = exam_state.get("answers", {})
    current = exam_state.get("current_question", 1)

    answers[question_id] = answer
    exam_state["answers"] = answers
    exam_state["current_question"] = current + 1
    record["final_exam_in_progress"] = exam_state
    save_record(username, learner_role, record)

    if current >= exam_state.get("total", 30):
        return _exam_results(request, record, username, learner_role)

    return _render_exam_question(request, record, username, real_name, learner_role,
                                 exam_state, current + 1)


def _exam_results(request, record, username, learner_role):
    """Calculate and display final exam results."""
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    exam_state = record.get("final_exam_in_progress", {})
    answers = exam_state.get("answers", {})
    question_ids = exam_state.get("question_ids", [])

    bank = load_json(BANK_PATH)

    correct = 0
    chapter_scores = {ch: {"correct": 0, "total": 0} for ch in CHAPTERS if ch != "导论"}

    for q_id, answer in answers.items():
        question = next((q for q in bank["questions"] if q["id"] == q_id), None)
        if not question:
            continue
        # Normalize true-false answers: frontend sends "对"/"错", bank has "True"/"False"
        correct_ans = question["answer"]
        user_ans = answer
        if question.get("type") == "true-false":
            tf_map = {"对": "True", "错": "False", "True": "True", "False": "False",
                       True: "True", False: "False"}
            user_ans = tf_map.get(answer, answer)
            correct_ans = tf_map.get(question["answer"], question["answer"])
        is_correct = user_ans == correct_ans
        if is_correct:
            correct += 1

        module = question.get("module", "")
        if module in chapter_scores:
            chapter_scores[module]["total"] += 1
            if is_correct:
                chapter_scores[module]["correct"] += 1

    total = len(question_ids)
    rate = round(correct / total * 100) if total > 0 else 0

    # Grade
    if rate >= 90:
        grade = "excellent"
        grade_label = "优秀"
        grade_msg = "非常出色！你对新规的理解相当扎实。"
    elif rate >= 75:
        grade = "good"
        grade_label = "良好"
        grade_msg = "不错，核心要点都掌握了。"
    elif rate >= 60:
        grade = "pass"
        grade_label = "合格"
        grade_msg = "基本掌握，建议再回顾一下薄弱章节。"
    else:
        grade = "fail"
        grade_label = "不合格"
        grade_msg = "需要加强。建议回到薄弱章节重新学习后再考一次。"

    # Calculate chapter rates
    ch_rates = {}
    for ch, scores in chapter_scores.items():
        if scores["total"] > 0:
            ch_rates[ch] = round(scores["correct"] / scores["total"] * 100)
        else:
            ch_rates[ch] = 0

    # Save results (before deleting exam state so we can save answers)
    record["last_exam_answers"] = {
        q_id: {
            "selected": ans,
            "correct": next((q["answer"] for q in bank["questions"] if q["id"] == q_id), ""),
            "type": next((q.get("type", "single-choice") for q in bank["questions"] if q["id"] == q_id), "single-choice"),
        }
        for q_id, ans in answers.items()
    }
    if "final_exam_in_progress" in record:
        del record["final_exam_in_progress"]
    record["final_score"] = rate / 100
    record["final_grade"] = grade
    record["chapter_scores"] = ch_rates
    save_record(username, learner_role, record)

    passed = rate >= 60
    weak_chapters = [ch for ch, r in ch_rates.items() if r < 60]

    is_c_branch = record.get("experienced_branch") == "C"
    offer_b_downgrade = is_c_branch and not passed

    # Build wrong details for review
    tf_display = {"True": "对", "False": "错", True: "对", False: "错"}
    wrong_details = []
    for q_id, user_answer in answers.items():
        question = next((q for q in bank["questions"] if q["id"] == q_id), None)
        if not question:
            continue
        is_tf = question.get("type") == "true-false"
        correct_ans = question["answer"]
        user_ans = user_answer
        if is_tf:
            tf_map = {"对": "True", "错": "False", "True": "True", "False": "False",
                       True: "True", False: "False"}
            user_ans = tf_map.get(user_answer, user_answer)
            correct_ans = tf_map.get(question["answer"], question["answer"])
        is_correct = user_ans == correct_ans
        if is_correct:
            continue  # only include wrong answers
        display_user = tf_display.get(user_answer, user_answer) if is_tf else user_answer
        display_correct = tf_display.get(correct_ans, correct_ans) if is_tf else correct_ans
        wrong_details.append({
            "q_id": q_id,
            "question_text": question["question"],
            "type": question.get("type", "single-choice"),
            "user_answer": display_user,
            "correct_answer": display_correct,
            "explanation": question.get("explanation", ""),
            "options": question.get("options", []),
        })

    return request.app.state.templates.TemplateResponse("exam.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "show_results": True,
        "correct": correct,
        "total": total,
        "rate": rate,
        "grade": grade_label,
        "grade_msg": grade_msg,
        "passed": passed,
        "ch_rates": ch_rates,
        "weak_chapters": weak_chapters,
        "wrong_details": wrong_details,
        "offer_b_downgrade": offer_b_downgrade,
    })


def _exam_scorecard(request, record, username, real_name, learner_role):
    """Show the completed exam scorecard with option to retake."""
    rate = round((record.get("final_score") or 0) * 100)
    grade_key = record.get("final_grade", "")
    grade_labels = {"excellent": "优秀", "good": "良好", "pass": "合格", "fail": "不合格"}
    grade_label = grade_labels.get(grade_key, grade_key)

    if rate >= 90:
        grade_msg = "非常出色！你对新规的理解相当扎实。"
    elif rate >= 75:
        grade_msg = "不错，核心要点都掌握了。"
    elif rate >= 60:
        grade_msg = "基本掌握，建议再回顾一下薄弱章节。"
    else:
        grade_msg = "需要加强。建议回到薄弱章节重新学习后再考一次。"

    passed = rate >= 60
    ch_rates = record.get("chapter_scores", {})
    weak_chapters = [ch for ch, r in ch_rates.items() if r < 60]

    is_c_branch = record.get("experienced_branch") == "C"
    offer_b_downgrade = is_c_branch and not passed

    # Build wrong details from saved exam answers
    bank = load_json(BANK_PATH)
    tf_display = {"True": "对", "False": "错", True: "对", False: "错"}
    wrong_details = []
    last_answers = record.get("last_exam_answers", {})
    for q_id, ans in last_answers.items():
        question = next((q for q in bank["questions"] if q["id"] == q_id), None)
        if not question:
            continue
        is_tf = question.get("type") == "true-false"
        correct_ans = question["answer"]
        user_ans = ans.get("selected", "")
        if is_tf:
            tf_map = {"对": "True", "错": "False", "True": "True", "False": "False",
                       True: "True", False: "False"}
            user_ans = tf_map.get(user_ans, user_ans)
            correct_ans = tf_map.get(question["answer"], question["answer"])
        is_correct = user_ans == correct_ans
        if is_correct:
            continue
        display_user = tf_display.get(ans.get("selected", ""), ans.get("selected", "")) if is_tf else ans.get("selected", "")
        display_correct = tf_display.get(correct_ans, correct_ans) if is_tf else correct_ans
        wrong_details.append({
            "q_id": q_id,
            "question_text": question["question"],
            "type": question.get("type", "single-choice"),
            "user_answer": display_user,
            "correct_answer": display_correct,
            "explanation": question.get("explanation", ""),
            "options": question.get("options", []),
        })

    return request.app.state.templates.TemplateResponse("exam.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "show_scorecard": True,
        "rate": rate,
        "grade": grade_label,
        "grade_msg": grade_msg,
        "passed": passed,
        "ch_rates": ch_rates,
        "weak_chapters": weak_chapters,
        "wrong_details": wrong_details,
        "offer_b_downgrade": offer_b_downgrade,
    })
