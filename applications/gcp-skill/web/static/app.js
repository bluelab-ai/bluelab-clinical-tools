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
        // Highlight matching button
        var scopeKey = (scenario === 'quiz') ? 'chapter' : scenario;
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
            // Determine which scopes are valid for the current URL
            var pathParts = window.location.pathname.match(/\/learn\/([^/]+)(?:\/(\d+))?/);
            var pathChapter = pathParts ? decodeURIComponent(pathParts[1]) : null;
            var pathArticle = pathParts ? pathParts[2] : null;
            var realChapters = ['导论', '第一章', '第二章', '第三章', '第四章', '第五章', '第六章'];
            var isRealChapter = pathChapter && realChapters.includes(pathChapter);
            var articleBtn = scopeBar.querySelector('[data-scope="article"]');
            var chapterBtn = scopeBar.querySelector('[data-scope="chapter"]');
            // Article scope: only on /learn/有效章节/数字
            if (articleBtn) articleBtn.disabled = !(isRealChapter && pathArticle);
            // Chapter scope: only on a page under a real chapter
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
            addAiMessage('assistant', '本条答疑需要在具体条文页面使用。请先进入学习页面，或在下方切换「本章答疑」或「GCP全法问答」。');
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
