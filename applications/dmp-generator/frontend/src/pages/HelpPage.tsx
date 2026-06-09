import { HelpCircle } from "lucide-react";

interface StepProps {
  number: number;
  title: string;
  children: React.ReactNode;
}

function Step({ number, title, children }: StepProps) {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-9 h-9 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold">
          {number}
        </div>
        <div className="w-px flex-1 bg-slate-200 mt-2" />
      </div>
      <div className="pb-10 flex-1">
        <h3 className="font-bold text-slate-900 text-lg mb-3">{title}</h3>
        {children}
      </div>
    </div>
  );
}

interface FAQProps {
  q: string;
  children: React.ReactNode;
}

function FAQ({ q, children }: FAQProps) {
  return (
    <div className="mb-5">
      <p className="font-semibold text-slate-900 mb-1">{q}</p>
      <p className="text-sm text-slate-600 leading-relaxed">{children}</p>
    </div>
  );
}

export default function HelpPage() {
  return (
    <div className="min-h-screen bg-slate-50 font-sans antialiased">
      <div className="max-w-2xl mx-auto py-10 px-4">
        {/* Header */}
        <div className="mb-8">
          <img src="/logo-text.png" alt="Logo" className="h-12 mb-3" />
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">使用帮助</h1>
          <p className="mt-2 text-slate-500 text-sm">
            欢迎使用 DMP 生成平台！按照以下步骤即可快速上手，完成从方案上传到数据管理计划生成的全流程。
          </p>
        </div>

        {/* Steps Card */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8 mb-8">
          <h2 className="font-bold text-slate-900 text-xl mb-8 flex items-center gap-2">
            <HelpCircle size={22} className="text-blue-600" />
            操作步骤
          </h2>

          <Step number={1} title="注册账号">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              首次使用需要创建账号。在注册页面输入用户名（至少3个字符）和密码（至少6个字符），点击 Register 完成注册。注册成功后自动登录。
            </p>
            <img src="/help-step1-register.png" alt="注册账号" className="w-full rounded-xl border border-slate-200 shadow-sm my-3" />
          </Step>

          <Step number={2} title="登录系统">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              已有账号的用户在登录页面输入用户名和密码，点击 Login 进入系统。登录后跳转至 DM 日志信息填写页面。
            </p>
            <img src="/help-step2-login.png" alt="登录系统" className="w-full rounded-xl border border-slate-200 shadow-sm my-3" />
          </Step>

          <Step number={3} title="填写 DM 日志信息">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              在日志填写页面，完整填写各项 DM 日志信息。包含项目基本信息（版本号、日期、各方名称）、项目类型（药物/器械）、数据采集模式（EDC/PDC）、系统配置、随机系统、外部数据等。
            </p>
            <p className="text-sm text-slate-500 leading-relaxed mb-1">
              部分字段为条件显示，仅在选择特定选项后出现：
            </p>
            <ul className="list-disc list-inside text-sm text-slate-500 space-y-0.5 mb-3">
              <li>选择 EDC 系统为「其他」时，会显示供应商名称、系统名称等额外字段</li>
              <li>选择使用随机系统后，才显示随机系统相关选项</li>
              <li>涉及外部数据时，需填写外部数据类型</li>
            </ul>
            <p className="text-sm text-slate-600 leading-relaxed">
              填写完成后点击「保存日志」按钮保存。
            </p>
            <img src="/help-step3-logform.png" alt="填写 DM 日志信息" className="w-full rounded-xl border border-slate-200 shadow-sm my-3" />
          </Step>

          <Step number={4} title="上传试验方案文件">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              进入聊天页面后，在上传区域拖拽文件或点击浏览，上传试验方案文件。支持 .docx 格式，文件大小不超过 50MB。
            </p>
            <p className="text-sm text-slate-600 leading-relaxed">
              上传成功后，文件会出现在左侧 Workspace 侧边栏的 Protocols 分类下。
            </p>
            <img src="/help-step4-upload.png" alt="上传试验方案文件" className="w-full rounded-xl border border-slate-200 shadow-sm my-3" />
          </Step>

          <Step number={5} title="生成 DMP">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              Generate DMP 按钮需要同时满足两个条件才会启用（变为可点击的黑色按钮）：
            </p>
            <ul className="list-decimal list-inside text-sm text-slate-600 space-y-0.5 mb-3">
              <li>已保存 DM 日志信息（在日志填写页面完成并保存）</li>
              <li>已上传试验方案文件（.docx 格式）</li>
            </ul>
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              满足条件后，点击 Generate DMP 按钮，系统会开始 AI 驱动的 DMP 生成流程。过程中状态栏会显示当前进度。
            </p>
            <img src="/help-step5-generate.png" alt="生成 DMP" className="w-full rounded-xl border border-slate-200 shadow-sm my-3" />
          </Step>

          <Step number={6} title="与 AI 交互问答">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              在 DMP 生成过程中，AI 会通过选择题卡片或输入框向你提问，帮助你补充必要信息。选择答案或输入内容后提交即可继续。
            </p>
            <p className="text-sm text-slate-600 leading-relaxed mb-3">
              生成完成后，生成的 DMP 文件会出现在左侧侧边栏的 DMP Outputs 分类下，点击文件名即可下载。
            </p>
            <p className="text-sm text-slate-600 leading-relaxed">
              如需重新开始，可点击右上角「New Session」按钮清除当前会话上下文。
            </p>
            <img src="/help-step6-chat.png" alt="与 AI 交互问答" className="w-full rounded-xl border border-slate-200 shadow-sm my-3" />
          </Step>
        </div>

        {/* FAQ Card */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8">
          <h2 className="font-bold text-slate-900 text-xl mb-6 flex items-center gap-2">
            <HelpCircle size={22} className="text-blue-600" />
            常见问题
          </h2>

          <FAQ q="为什么 Generate DMP 按钮是灰色的？">
            需要同时具备两个条件：已保存 DM 日志信息（在日志填写页面）且已上传试验方案文件（.docx 格式）。两个条件都满足后，按钮会自动变为可点击的黑色状态。
          </FAQ>

          <FAQ q="支持哪些文件格式和大小？">
            仅支持 .docx 格式的试验方案文件，最大 50MB。请勿上传其他格式文件。
          </FAQ>

          <FAQ q="如何切换项目？">
            点击页面顶部的 Project 下拉菜单，选择已有项目或点击 "+ New project..." 创建新项目。不同项目之间的文件和数据相互隔离。
          </FAQ>

          <FAQ q="如何下载生成的 DMP 文件？">
            DMP 生成完成后，左侧 Workspace 侧边栏的 "DMP Outputs" 分类下会出现生成的 .docx 文件，点击文件名即可触发下载。
          </FAQ>
        </div>
      </div>
    </div>
  );
}
