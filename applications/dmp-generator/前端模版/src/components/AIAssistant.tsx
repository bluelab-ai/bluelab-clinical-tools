import { useState } from "react";
import { DMPProject, ChatMessage } from "../types";
import { Bot, User, Send, Sparkles, MessageSquareDot, ShieldAlert, FileSearch } from "lucide-react";

interface AIAssistantProps {
  activeProject: DMPProject;
}

export default function AIAssistant({ activeProject }: AIAssistantProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "init-message-1",
      sender: "assistant",
      text: `Hello! I'm your DMP compliance advisor, synchronized with your active portfolio: **"${activeProject.name || "Untitled Draft"}"**.

How can I help you strengthen your data architecture, manage GDPR/HIPAA mandates, or refine your post-project preservation steps today?`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);

  const [inputVal, setInputVal] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSendMessage = async (textToSend: string) => {
    if (!textToSend.trim()) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: "user",
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputVal("");
    setIsLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [...messages, userMsg],
          projectContext: activeProject
        }),
      });

      if (response.ok) {
        const data = await response.json();
        const aiMsg: ChatMessage = {
          id: `ai-${Date.now()}`,
          sender: "assistant",
          text: data.text,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        setMessages((prev) => [...prev, aiMsg]);
      }
    } catch (e) {
      console.error(e);
      // fallback in case of connection drop
      const errorMsg: ChatMessage = {
        id: `ai-err-${Date.now()}`,
        sender: "assistant",
        text: "I encountered a workspace connection timeout. I recommend implementing AES-256 standard volumes, access boundaries, and validating consent structures.",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const quickActionPrompts = [
    {
      label: "Evaluate GDPR Article 32 compliance",
      text: "How does our selected security controls line up with GDPR Article 32 data security expectations?"
    },
    {
      label: "HIPAA Safe Harbor vs Expert Determination",
      text: "Can you explain the differences between HIPAA's Safe Harbor and Expert Determination de-identification methods?"
    },
    {
      label: "Formulate Data Minimization Strategy",
      text: "Provide an actionable, 3-step data minimization policy that we can include inside our active plan."
    },
    {
      label: "Draft NIST Data Destruction SOP",
      text: "Draft standard operating procedures for the physical and cryptographic shredding of research drives according to NIST guidelines."
    }
  ];

  return (
    <div className="space-y-8 animate-fade-in" id="ai-assistant-tab">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Compliance Advisory & AI Assistant</h1>
        <p className="text-slate-500 mt-1">Engage with a specialized compliance model loaded with your active data specifications, schemas, and research goals.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        
        {/* Left Col: Prompt shortcuts & synced context */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-white border border-slate-200/70 p-5 rounded-2xl shadow-sm space-y-5">
            <h3 className="font-bold text-slate-800 text-xs font-mono tracking-wider uppercase flex items-center gap-1.5 border-b border-slate-100 pb-3">
              <FileSearch size={14} className="text-slate-500" /> Synced Context
            </h3>
            
            <div className="space-y-3">
              <div className="text-xs">
                <span className="text-slate-400 font-mono block">PROJECT NAME</span>
                <span className="font-semibold text-slate-800 break-words">{activeProject.name || "None Specified"}</span>
              </div>
              <div className="text-xs">
                <span className="text-slate-400 font-mono block">INVESTIGATOR</span>
                <span className="font-semibold text-slate-800">{activeProject.leadInvestigator || "None Specified"}</span>
              </div>
              <div className="text-xs">
                <span className="text-slate-400 font-mono block">MANDATES</span>
                <span className="text-blue-600 font-semibold font-mono">
                  {activeProject.complianceRequirements.length > 0 
                    ? activeProject.complianceRequirements.join(", ") 
                    : "Standard Integrity"}
                </span>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <h3 className="font-bold text-slate-800 text-xs font-mono tracking-wider uppercase">Shortcuts</h3>
            <div className="space-y-2">
              {quickActionPrompts.map((p, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSendMessage(p.text)}
                  className="w-full text-left p-3 bg-white hover:bg-slate-50 border border-slate-200 hover:border-slate-300 rounded-xl text-xs text-slate-700 leading-snug cursor-pointer block hover:translate-x-1 transition-all duration-150"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right Cols: Main Interactive Chat Feed */}
        <div className="lg:col-span-3 bg-white border border-slate-200/80 rounded-2xl shadow-sm flex flex-col overflow-hidden h-[580px]">
          {/* Feed Header */}
          <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center">
                <Bot size={16} />
              </div>
              <div>
                <h4 className="font-bold text-sm text-slate-800">DMP Architect Agent</h4>
                <p className="text-[10px] text-slate-400 font-mono">POWERED BY GEMINI 3.5 FLASH</p>
              </div>
            </div>

            <div className="flex items-center gap-1 bg-emerald-50 text-emerald-800 border-emerald-100 border text-[10px] px-2 py-0.5 rounded-full font-semibold">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
              Live Synced
            </div>
          </div>

          {/* Messages Container */}
          <div className="flex-1 p-6 space-y-4 overflow-y-auto bg-slate-50/40 select-text">
            {messages.map((m) => {
              const isAi = m.sender === "assistant";
              return (
                <div 
                  key={m.id}
                  className={`flex gap-3 max-w-[85%] ${isAi ? "mr-auto" : "ml-auto flex-row-reverse"}`}
                >
                  {/* Icon */}
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                    isAi ? "bg-blue-100 text-blue-700" : "bg-slate-900 text-white"
                  }`}>
                    {isAi ? <Bot size={15} /> : <User size={15} />}
                  </div>

                  {/* Bubble body */}
                  <div className="space-y-1">
                    <div className={`p-4 rounded-2xl text-xs leading-relaxed whitespace-pre-wrap ${
                      isAi 
                        ? "bg-white border border-slate-200 text-slate-800 rounded-tl-none" 
                        : "bg-slate-900 text-white rounded-tr-none"
                    }`}>
                      {m.text}
                    </div>
                    <span className={`block text-[10px] font-mono text-slate-400 ${!isAi && "text-right"}`}>
                      {m.timestamp}
                    </span>
                  </div>
                </div>
              );
            })}

            {isLoading && (
              <div className="flex gap-3 mr-auto items-center animate-pulse">
                <div className="w-8 h-8 rounded-full bg-blue-50 text-blue-400 flex items-center justify-center shrink-0">
                  <Bot size={15} className="animate-spin" />
                </div>
                <span className="text-xs font-mono text-slate-400 tracking-wider">AI typing responses...</span>
              </div>
            )}
          </div>

          {/* Input controls form */}
          <form 
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage(inputVal);
            }}
            className="p-4 border-t border-slate-200 bg-white flex gap-2"
          >
            <input 
              type="text"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              disabled={isLoading}
              placeholder="Ask a compliance question about your data schema..."
              className="flex-1 bg-slate-50 border border-slate-150 focus:border-blue-500 focus:bg-white rounded-xl px-4 py-3 text-xs outline-none focus:ring-2 focus:ring-blue-100 text-slate-800 disabled:opacity-50 transition-all font-sans"
            />
            <button 
              type="submit"
              disabled={isLoading || !inputVal.trim()}
              className="w-11 h-11 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white rounded-xl flex items-center justify-center transition-all cursor-pointer active:scale-95"
            >
              <Send size={15} />
            </button>
          </form>
        </div>

      </div>
    </div>
  );
}
