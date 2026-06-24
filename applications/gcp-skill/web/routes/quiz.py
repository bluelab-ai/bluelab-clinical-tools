"""Quiz route: chapter quizzes with A-E options and instant feedback."""
import sys
import json
from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from web.config import BANK_PATH, SCRIPTS_DIR, CHAPTERS, CHAPTER_ARTICLES
from web.record_manager import load_record, save_record, set_quiz_score, update_chapter_status
from web.article_parser import parse_article
from web.user_manager import load_account

# Add scripts dir to path for importing pick_questions
sys.path.insert(0, str(SCRIPTS_DIR.parent))
from scripts.pick_questions import load_json, pick_chapter

router = APIRouter()


@router.get("/{chapter}/start", response_class=HTMLResponse)
async def quiz_start(request: Request,
                     chapter: str,
                     change_only: int = 0,
                     retake: int = 0,
                     username: str = Cookie(None),
                     learner_role: str = Cookie(None)):
    """Start or resume a chapter quiz."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    # Check for in-progress quiz (resume)
    quiz_state = record.get("quiz_in_progress")
    if quiz_state and quiz_state.get("chapter") == chapter:
        # If change_only mismatch, discard old quiz and start fresh
        if bool(change_only) != bool(quiz_state.get("change_only", False)):
            del record["quiz_in_progress"]
            save_record(username, learner_role, record)
            quiz_state = None
        else:
            question_ids = quiz_state.get("question_ids", [])
            if question_ids:
                bank = load_json(BANK_PATH)
                picks = [{"id": qid} for qid in question_ids]
                current_idx = quiz_state.get("current_index", 0)
                answers = quiz_state.get("answers", {})
                if current_idx < len(picks):
                    return _render_quiz_question(request, record, username, real_name, learner_role,
                                                 chapter, picks, current_idx, answers)
                else:
                    return _quiz_results(request, record, username, learner_role, chapter, answers)

    # If chapter already passed and not explicitly retaking, show scorecard
    chapter_data = (record.get("chapters") or {}).get(chapter, {})
    if chapter_data.get("status") == "passed" and not change_only and not retake:
        return _quiz_scorecard(request, record, username, real_name, learner_role, chapter, chapter_data)

    # If retaking, clear old quiz state and chapter pass status
    if retake:
        if record.get("quiz_in_progress"):
            del record["quiz_in_progress"]
        # Reset chapter status so a new quiz can re-set it
        if chapter in (record.get("chapters") or {}):
            record["chapters"][chapter]["status"] = "active"
            record["chapters"][chapter].pop("last_quiz", None)
        save_record(username, learner_role, record)

    # New quiz: pick questions
    bank = load_json(BANK_PATH)
    picks = pick_chapter(bank, chapter, count=3,
                         change_only=bool(change_only))

    record["quiz_in_progress"] = {
        "chapter": chapter,
        "question_ids": [q["id"] for q in picks],
        "current_index": 0,
        "answers": {},
        "change_only": bool(change_only),
        "score": 0,
    }
    save_record(username, learner_role, record)

    return _render_quiz_question(request, record, username, real_name, learner_role,
                                 chapter, picks, 0, {})


def _render_quiz_question(request, record, username, real_name, learner_role,
                          chapter, picks, index, answers):
    """Render a single quiz question page."""
    if index >= len(picks):
        return _quiz_results(request, record, username, learner_role, chapter, answers)

    bank = load_json(BANK_PATH)
    q_id = picks[index]["id"]
    question = next((q for q in bank["questions"] if q["id"] == q_id), None)

    if not question:
        return HTMLResponse("Question not found", status_code=404)

    return request.app.state.templates.TemplateResponse("quiz.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "chapter": chapter,
        "question": question,
        "question_index": index + 1,
        "total_questions": len(picks),
        "is_last": index == len(picks) - 1,
        "show_feedback": False,
    })


@router.post("/{chapter}/answer", response_class=HTMLResponse)
async def quiz_answer(request: Request,
                      chapter: str,
                      question_id: str = Form(...),
                      answer: str = Form(...),
                      username: str = Cookie(None),
                      learner_role: str = Cookie(None)):
    """Process a quiz answer and show feedback."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    quiz_state = record.get("quiz_in_progress", {})
    question_ids = quiz_state.get("question_ids", [])
    current_idx = quiz_state.get("current_index", 0)
    answers = quiz_state.get("answers", {})

    bank = load_json(BANK_PATH)
    question = next((q for q in bank["questions"] if q["id"] == question_id), None)
    if not question:
        return HTMLResponse("Question not found", status_code=404)

    # Normalize true-false answers: frontend sends "对"/"错", bank has "True"/"False"
    correct_answer = question["answer"]
    normalized_answer = answer
    if question.get("type") == "true-false":
        tf_map = {"对": "True", "错": "False", "True": "True", "False": "False",
                   True: "True", False: "False"}
        normalized_answer = tf_map.get(answer, answer)
        correct_answer = tf_map.get(question["answer"], question["answer"])
    is_correct = normalized_answer == correct_answer

    # Update answers
    answers[question_id] = {
        "selected": answer,
        "correct": question["answer"],
        "is_correct": is_correct,
        "was_uncertain": answer == "E",
    }

    if is_correct:
        quiz_state["score"] = quiz_state.get("score", 0) + 1

    # Advance to next question
    quiz_state["current_index"] = current_idx + 1
    quiz_state["answers"] = answers
    record["quiz_in_progress"] = quiz_state
    save_record(username, learner_role, record)

    # If E selected, load article for review
    article_review = None
    article_num = None
    if answer == "E":
        article_num = int(question.get("article", 1))
        article_review = parse_article(article_num, learner_role)

    # Display-friendly answer labels for true-false
    display_answer = answer
    display_correct = correct_answer
    if question.get("type") == "true-false":
        tf_display = {"True": "对", "False": "错", True: "对", False: "错"}
        display_answer = tf_display.get(normalized_answer, answer)
        display_correct = tf_display.get(correct_answer, correct_answer)

    return request.app.state.templates.TemplateResponse("quiz.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "chapter": chapter,
        "question": question,
        "question_index": current_idx + 1,
        "total_questions": len(question_ids),
        "is_last": current_idx + 1 >= len(question_ids),
        "show_feedback": True,
        "selected_answer": display_answer,
        "is_correct": is_correct,
        "correct_answer": display_correct,
        "explanation": question.get("explanation", ""),
        "was_uncertain": answer == "E",
        "article_review": article_review,
        "article_num": article_num,
    })


@router.get("/{chapter}/next", response_class=HTMLResponse)
async def quiz_next(request: Request,
                    chapter: str,
                    username: str = Cookie(None),
                    learner_role: str = Cookie(None)):
    """Show next quiz question or results."""
    if not username or not learner_role:
        return RedirectResponse(url="/", status_code=303)

    record = load_record(username, learner_role)
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    quiz_state = record.get("quiz_in_progress", {})
    question_ids = quiz_state.get("question_ids", [])
    current_idx = quiz_state.get("current_index", 0)
    answers = quiz_state.get("answers", {})

    bank = load_json(BANK_PATH)
    picks = [{"id": qid} for qid in question_ids]

    if current_idx >= len(picks):
        return _quiz_results(request, record, username, learner_role, chapter, answers)

    return _render_quiz_question(request, record, username, real_name, learner_role,
                                 chapter, picks, current_idx, answers)


def _quiz_results(request, record, username, learner_role, chapter, answers):
    """Show quiz results and determine pass/fail."""
    account = load_account(username)
    real_name = account.get("real_name", username) if account else username

    score = sum(1 for a in answers.values() if a.get("is_correct"))
    total = len(answers)
    passed = score >= 2

    # Update record
    if "quiz_in_progress" in record:
        del record["quiz_in_progress"]
    score_fraction = score / total if total > 0 else 0
    set_quiz_score(record, chapter, score_fraction)
    if passed:
        update_chapter_status(record, chapter, "passed")

    # Save quiz result for later review (scorecard)
    if "chapters" not in record:
        record["chapters"] = {}
    if chapter not in record["chapters"]:
        record["chapters"][chapter] = {}
    record["chapters"][chapter]["last_quiz"] = {
        "score": score,
        "total": total,
        "passed": passed,
        "answers": answers,
    }

    # Check if B branch and all chapters done
    is_b_branch = record.get("experienced_branch") == "B"
    all_passed = all(
        c.get("status") == "passed"
        for ch, c in record.get("chapters", {}).items()
        if ch != "导论"
    ) if is_b_branch else False
    offer_upgrade = is_b_branch and all_passed

    save_record(username, learner_role, record)

    # Get next chapter (with correct first article)
    try:
        ch_idx = CHAPTERS.index(chapter)
        next_chapter = CHAPTERS[ch_idx + 1] if ch_idx + 1 < len(CHAPTERS) else None
    except ValueError:
        next_chapter = None
    next_article = None
    if next_chapter:
        art_list = CHAPTER_ARTICLES.get(next_chapter, [])
        next_article = art_list[0] if art_list else None

    # Build wrong/uncertain answer details for review
    bank = load_json(BANK_PATH)
    tf_display = {"True": "对", "False": "错", True: "对", False: "错"}
    wrong_details = []
    for q_id, ans in answers.items():
        if ans.get("is_correct") and not ans.get("was_uncertain"):
            continue  # skip correct answers
        question = next((q for q in bank["questions"] if q["id"] == q_id), None)
        if not question:
            continue
        is_tf = question.get("type") == "true-false"
        user_ans = ans.get("selected", "")
        correct_ans = ans.get("correct", "")
        if is_tf:
            user_ans = tf_display.get(user_ans, user_ans)
            correct_ans = tf_display.get(correct_ans, correct_ans)
        wrong_details.append({
            "q_id": q_id,
            "question_text": question["question"],
            "type": question.get("type", "single-choice"),
            "was_uncertain": ans.get("was_uncertain", False),
            "user_answer": user_ans,
            "correct_answer": correct_ans,
            "explanation": question.get("explanation", ""),
            "article_num": question.get("article"),
            "options": question.get("options", []),
        })

    return request.app.state.templates.TemplateResponse("quiz.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "chapter": chapter,
        "show_results": True,
        "score": score,
        "total": total,
        "passed": passed,
        "answers": answers,
        "next_chapter": next_chapter,
        "next_article": next_article,
        "wrong_details": wrong_details,
        "offer_upgrade": offer_upgrade,
        "is_b_branch": is_b_branch,
    })


def _quiz_scorecard(request, record, username, real_name, learner_role, chapter, chapter_data):
    """Show the completed quiz scorecard with option to retake."""
    last_quiz = chapter_data.get("last_quiz", {})
    saved_answers = last_quiz.get("answers", {})
    score = last_quiz.get("score", 0)
    total = last_quiz.get("total", 0)
    passed = last_quiz.get("passed", False)

    # Build wrong details from saved answers
    bank = load_json(BANK_PATH)
    tf_display = {"True": "对", "False": "错", True: "对", False: "错"}
    wrong_details = []
    for q_id, ans in saved_answers.items():
        if ans.get("is_correct") and not ans.get("was_uncertain"):
            continue
        question = next((q for q in bank["questions"] if q["id"] == q_id), None)
        if not question:
            continue
        is_tf = question.get("type") == "true-false"
        user_ans = ans.get("selected", "")
        correct_ans = ans.get("correct", "")
        if is_tf:
            user_ans = tf_display.get(user_ans, user_ans)
            correct_ans = tf_display.get(correct_ans, correct_ans)
        wrong_details.append({
            "q_id": q_id,
            "question_text": question["question"],
            "type": question.get("type", "single-choice"),
            "was_uncertain": ans.get("was_uncertain", False),
            "user_answer": user_ans,
            "correct_answer": correct_ans,
            "explanation": question.get("explanation", ""),
            "article_num": question.get("article"),
            "options": question.get("options", []),
        })

    # Get next chapter (with correct first article)
    try:
        ch_idx = CHAPTERS.index(chapter)
        next_chapter = CHAPTERS[ch_idx + 1] if ch_idx + 1 < len(CHAPTERS) else None
    except ValueError:
        next_chapter = None
    next_article = None
    if next_chapter:
        art_list = CHAPTER_ARTICLES.get(next_chapter, [])
        next_article = art_list[0] if art_list else None

    # Check if B branch and all chapters done
    is_b_branch = record.get("experienced_branch") == "B"
    all_passed = all(
        c.get("status") == "passed"
        for ch, c in record.get("chapters", {}).items()
        if ch != "导论"
    ) if is_b_branch else False
    offer_upgrade = is_b_branch and all_passed

    return request.app.state.templates.TemplateResponse("quiz.html", {
        "request": request,
        "learner_name": real_name,
        "learner_role": learner_role,
        "chapter": chapter,
        "show_scorecard": True,
        "score": score,
        "total": total,
        "passed": passed,
        "answers": saved_answers,
        "wrong_details": wrong_details,
        "next_chapter": next_chapter,
        "next_article": next_article,
        "offer_upgrade": offer_upgrade,
        "is_b_branch": is_b_branch,
    })
