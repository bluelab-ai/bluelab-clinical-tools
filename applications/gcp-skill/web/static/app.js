/**
 * GCP 2026 Training — Frontend interactivity.
 * Handles: AI chat panel open/close/send, quiz option clicks.
 */

// ---- AI Chat Panel ----

// Open panel from floating button (no auto-scope — user picks)
function openFloatAi() {
    openAiPanel(null);
}

// Open panel (scenario optional — if null, show scope selector)
function openAiPanel(scenario, id, extraIds) {
    const panel = document.getElementById('ai-panel');
    const title = document.getElementById('ai-panel-title');
    const hint = document.getElementById('ai-scope-hint');
    const messages = document.getElementById('ai-messages');
    const input = document.getElementById('ai-input');
    const sendBtn = document.getElementById('ai-send');
    const scopeBar = document.getElementById('ai-scope-bar');

    if (!panel) return;

    panel.classList.remove('hidden');
    messages.innerHTML = '';
    input.value = '';

    // Reset all scope buttons
    if (scopeBar) scopeBar.querySelectorAll('.scope-btn').forEach(b => b.classList.remove('active'));

    if (scenario) {
        // Inline button: pre-select scope, hide scope bar
        panel.dataset.scenario = scenario;
        panel.dataset.id = id || '';
        panel.dataset.extraIds = extraIds ? JSON.stringify(extraIds) : '';
        if (scopeBar) scopeBar.style.display = 'none';
        input.disabled = false;
        input.placeholder = '输入你的问题…';
        sendBtn.disabled = false;
        // Highlight matching scope button
        var scopeKey = (scenario === 'quiz') ? 'full' : scenario;
        var btn = scopeBar ? scopeBar.querySelector('[data-scope="' + scopeKey + '"]') : null;
        if (btn) btn.classList.add('active');
        // Title & hint
        if (scenario === 'article') {
            title.textContent = '🤖 AI 助教（本条答疑）';
            hint.textContent = 'AI 仅基于当前条文回答。';
        } else if (scenario === 'chapter') {
            title.textContent = '📚 AI 助教（本章答疑）';
            hint.textContent = 'AI 可引用本章条文综合回答。';
        } else if (scenario === 'quiz') {
            title.textContent = '🤖 AI 助教（题目讲解）';
            hint.textContent = 'AI 会在预写解析基础上深入讲解。';
        }
        hint.style.display = 'block';
    } else {
        // Floating button: show scope bar, disable input until scope picked.
        // Disable scopes that don't apply to the current page.
        panel.dataset.scenario = '';
        panel.dataset.id = '';
        panel.dataset.extraIds = '';
        if (scopeBar) {
            scopeBar.style.display = 'flex';
            var pathParts = window.location.pathname.match(/\/learn\/([^/]+)(?:\/(\d+))?/);
            var pathChapter = pathParts ? decodeURIComponent(pathParts[1]) : null;
            var pathArticle = pathParts ? pathParts[2] : null;
            var realChapters = ['导论', '第一章', '第二章', '第三章', '第四章', '第五章', '第六章'];
            var isRealChapter = pathChapter && realChapters.includes(pathChapter);
            var articleBtn = scopeBar.querySelector('[data-scope="article"]');
            var chapterBtn = scopeBar.querySelector('[data-scope="chapter"]');
            // Article scope: only on /learn/有效章节/数字
            if (articleBtn) articleBtn.disabled = !(isRealChapter && pathArticle);
            // Chapter scope: only on a page under a real chapter (disabled on diff pages)
            if (chapterBtn) chapterBtn.disabled = !isRealChapter;
            // Full scope: always enabled
        }
        title.textContent = '🤖 AI 助教';
        input.disabled = true;
        input.placeholder = '请先选择问答范围…';
        sendBtn.disabled = true;
        hint.style.display = 'none';
    }

    input.focus();
    addAiMessage('assistant', '有什么我可以帮你的？');
}

function selectScope(scope) {
    var panel = document.getElementById('ai-panel');
    var input = document.getElementById('ai-input');
    var sendBtn = document.getElementById('ai-send');
    var title = document.getElementById('ai-panel-title');
    var hint = document.getElementById('ai-scope-hint');
    var scopeBar = document.getElementById('ai-scope-bar');

    if (!panel) return;

    // Ignore clicks on disabled scope buttons
    var btn = scopeBar.querySelector('[data-scope="' + scope + '"]');
    if (btn && btn.disabled) return;

    // Highlight button
    scopeBar.querySelectorAll('.scope-btn').forEach(function(b){ b.classList.remove('active'); });
    if (btn) btn.classList.add('active');

    // Store scope
    panel.dataset.scenario = scope;
    // For article scope, auto-detect article_num from URL
    if (scope === 'article') {
        var match = window.location.pathname.match(/\/learn\/[^/]+\/(\d+)/);
        panel.dataset.id = match ? match[1] : '';
    } else {
        panel.dataset.id = '';
    }

    // Enable input
    input.disabled = false;
    input.placeholder = '输入你的问题…';
    sendBtn.disabled = false;
    input.focus();

    // Update title & hint
    if (scope === 'article') {
        title.textContent = '🤖 AI 助教（本条答疑）';
        hint.textContent = 'AI 仅基于当前条文回答。超范围问题会提示"与这一段无关"。';
        hint.style.color = '';
    } else if (scope === 'chapter') {
        title.textContent = '📚 AI 助教（本章答疑）';
        hint.textContent = 'AI 可引用本章条文综合回答。';
        hint.style.color = '';
    } else if (scope === 'full') {
        title.textContent = '📖 AI 助教（GCP全法问答）';
        hint.textContent = 'AI 可引用全部54条GCP 2026法规回答。';
        hint.style.color = '';
    }
    hint.style.display = 'block';
}

function closeAiPanel() {
    const panel = document.getElementById('ai-panel');
    if (panel) panel.classList.add('hidden');
}

async function sendAiMessage() {
    const input = document.getElementById('ai-input');
    const question = input.value.trim();
    if (!question) return;

    const panel = document.getElementById('ai-panel');
    const scenario = panel.dataset.scenario;
    const id = panel.dataset.id;

    if (!scenario) {
        addAiMessage('assistant', '请先在上方选择一个问答范围。');
        return;
    }

    addAiMessage('user', question);
    input.value = '';
    input.disabled = true;
    document.getElementById('ai-send').disabled = true;

    // Determine endpoint and body
    let endpoint, body;
    if (scenario === 'article') {
        if (!id || isNaN(parseInt(id))) {
            addAiMessage('assistant', '本条答疑需要在具体条文页面使用。请先进入学习页面，或切换「GCP全法问答」。');
            input.disabled = false;
            document.getElementById('ai-send').disabled = false;
            return;
        }
        endpoint = '/ask/article';
        body = { article_num: parseInt(id), question: question };
    } else if (scenario === 'chapter') {
        endpoint = '/ask/chapter';
        body = { chapter: getCurrentChapter(), question: question };
        if (panel.dataset.extraIds) {
            body.articles = JSON.parse(panel.dataset.extraIds);
        }
    } else if (scenario === 'quiz') {
        endpoint = '/ask/quiz';
        body = { question_id: id, question: question };
    } else if (scenario === 'full') {
        endpoint = '/ask/full';
        body = { question: question };
    } else {
        addAiMessage('assistant', '无法确定问题类型。');
        input.disabled = false;
        document.getElementById('ai-send').disabled = false;
        return;
    }

    // Show thinking dots
    const msgs = document.getElementById('ai-messages');
    const thinkingEl = document.createElement('div');
    thinkingEl.className = 'ai-typing';
    thinkingEl.id = 'ai-thinking';
    for (let i = 0; i < 3; i++) {
        const dot = document.createElement('span');
        thinkingEl.appendChild(dot);
    }
    msgs.appendChild(thinkingEl);
    msgs.scrollTop = msgs.scrollHeight;

    try {
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        const th = document.getElementById('ai-thinking');
        if (th) th.remove();
        addAiMessage('assistant', data.reply || '抱歉，没有收到回复。');
    } catch (err) {
        const th = document.getElementById('ai-thinking');
        if (th) th.remove();
        addAiMessage('assistant', '网络错误，请稍后重试。');
    } finally {
        input.disabled = false;
        document.getElementById('ai-send').disabled = false;
        input.focus();
    }
}

function addAiMessage(role, text) {
    const messages = document.getElementById('ai-messages');
    if (!messages) return;
    const div = document.createElement('div');
    div.className = 'ai-message ai-' + role;
    if (role === 'assistant') {
        div.innerHTML = text;
    } else {
        div.textContent = text;
    }
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function getCurrentChapter() {
    const match = window.location.pathname.match(/\/learn\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}

// ---- Feedback Modal ----

function openFeedbackModal() {
    document.getElementById('feedback-modal').style.display = 'block';
    document.getElementById('feedback-error').style.display = 'none';
    document.getElementById('feedback-success').style.display = 'none';
    document.getElementById('feedback-form-fields').style.display = 'block';
    document.getElementById('feedback-title').value = '';
    document.getElementById('feedback-content').value = '';
    document.getElementById('feedback-contact').value = '';
    setTimeout(function() { document.getElementById('feedback-title').focus(); }, 100);
}

function closeFeedbackModal() {
    document.getElementById('feedback-modal').style.display = 'none';
}

async function submitFeedback() {
    var title = document.getElementById('feedback-title').value.trim();
    var content = document.getElementById('feedback-content').value.trim();
    var contact = document.getElementById('feedback-contact').value.trim();

    if (!title || !content) {
        var err = document.getElementById('feedback-error');
        err.textContent = '请填写标题和内容';
        err.style.display = 'block';
        return;
    }

    var btn = document.getElementById('feedback-submit-btn');
    btn.textContent = '提交中…';
    btn.disabled = true;
    document.getElementById('feedback-error').style.display = 'none';

    try {
        var resp = await fetch('/feedback/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                content: content,
                contact: contact,
                page: window.location.href,
            }),
        });
        if (resp.ok) {
            document.getElementById('feedback-form-fields').style.display = 'none';
            var ok = document.getElementById('feedback-success');
            ok.innerHTML = '✅ 感谢反馈！<br>我们会尽快处理。';
            ok.style.display = 'block';
            setTimeout(closeFeedbackModal, 2000);
        } else {
            var data = await resp.json();
            document.getElementById('feedback-error').textContent = data.detail || '提交失败';
            document.getElementById('feedback-error').style.display = 'block';
        }
    } catch {
        document.getElementById('feedback-error').textContent = '网络错误，请重试';
        document.getElementById('feedback-error').style.display = 'block';
    } finally {
        btn.textContent = '提交反馈';
        btn.disabled = false;
    }
}

// ---- Admin Panel ----

function openAdminModal() {
    document.getElementById('admin-modal').style.display = 'block';
    document.getElementById('admin-step-password').style.display = 'block';
    document.getElementById('admin-step-unlocked').style.display = 'none';
    document.getElementById('admin-error').style.display = 'none';
    document.getElementById('admin-password-input').value = '';
    document.getElementById('admin-modal-icon').textContent = '🔒';
    document.getElementById('admin-modal-title').textContent = '管理员验证';
    document.getElementById('admin-modal-sub').textContent = '请输入管理员密码以继续';
    setTimeout(function() { document.getElementById('admin-password-input').focus(); }, 100);
}

function closeAdminModal() {
    document.getElementById('admin-modal').style.display = 'none';
}

async function verifyAdmin() {
    var pw = document.getElementById('admin-password-input').value;
    if (!pw) return;
    var btn = document.getElementById('admin-verify-btn');
    btn.textContent = '验证中…';
    btn.disabled = true;
    try {
        var resp = await fetch('/admin/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pw }),
        });
        if (resp.ok) {
            document.getElementById('admin-step-password').style.display = 'none';
            document.getElementById('admin-step-unlocked').style.display = 'block';
            document.getElementById('admin-modal-icon').textContent = '📂';
            document.getElementById('admin-modal-title').textContent = '后台管理';
            document.getElementById('admin-modal-sub').textContent = '管理后端数据';
            fetchUserCount();
        } else {
            var data = await resp.json();
            var err = document.getElementById('admin-error');
            err.textContent = data.detail || '密码错误';
            err.style.display = 'block';
        }
    } catch {
        document.getElementById('admin-error').textContent = '网络错误，请重试';
        document.getElementById('admin-error').style.display = 'block';
    } finally {
        btn.textContent = '验证';
        btn.disabled = false;
    }
}

async function fetchUserCount() {
    try {
        var resp = await fetch('/admin/users/count');
        var data = await resp.json();
        var el = document.getElementById('admin-user-count');
        el.innerHTML = '<span style="font-size:16px;">👥</span> 当前系统已注册 <b>' + data.count + '</b> 位用户';
        el.style.display = 'block';
    } catch {}
}

async function clearArchive() {
    var btn = document.getElementById('admin-clear-btn');
    btn.textContent = '清空中…';
    btn.disabled = true;
    try {
        await fetch('/admin/archive/clear', { method: 'POST' });
        btn.textContent = '✅ 已清空';
    } catch {
        document.getElementById('admin-action-error').textContent = '清空失败，请重试';
        document.getElementById('admin-action-error').style.display = 'block';
        btn.textContent = '🗑 清空记录';
    }
    btn.disabled = false;
}

function downloadArchive() {
    var a = document.createElement('a');
    a.href = '/admin/archive/download';
    a.download = 'gcp_training_data.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// ---- Event Listeners ----

document.addEventListener('DOMContentLoaded', () => {
    // AI panel close button
    const closeBtn = document.getElementById('ai-panel-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeAiPanel);
    }

    // AI send button
    const sendBtn = document.getElementById('ai-send');
    if (sendBtn) {
        sendBtn.addEventListener('click', sendAiMessage);
    }

    // AI input: send on Enter
    const aiInput = document.getElementById('ai-input');
    if (aiInput) {
        aiInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') sendAiMessage();
        });
    }

    // Admin modal: close on Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeAdminModal();
            closeFeedbackModal();
        }
    });

    // Quiz form: prevent double submission using a hidden field,
    // NOT by disabling buttons (disabled button values are not sent!)
    document.querySelectorAll('.quiz-form, .exam-form').forEach(form => {
        let submitted = false;
        form.addEventListener('submit', (e) => {
            if (submitted) {
                e.preventDefault();
                return;
            }
            submitted = true;
            // Fade buttons to show submission without disabling them
            const buttons = form.querySelectorAll('button[type="submit"]');
            buttons.forEach(btn => { btn.style.opacity = '0.6'; });
        });
    });
});
