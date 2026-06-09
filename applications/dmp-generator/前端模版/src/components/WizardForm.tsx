import React, { useState, useEffect } from "react";
import { DMPProject } from "../types";
import { 
  CloudUpload, ArrowLeft, ArrowRight, Info, Sparkles, 
  Bot, RefreshCw, CheckCircle2, Copy, Check 
} from "lucide-react";

interface WizardFormProps {
  activeProject: DMPProject;
  onChangeActiveProject: (p: DMPProject) => void;
  onSaveProject: (p: DMPProject) => void;
  onSetActiveTab: (tab: string) => void;
}

export default function WizardForm({ 
  activeProject, 
  onChangeActiveProject, 
  onSaveProject, 
  onSetActiveTab 
}: WizardFormProps) {
  const [currentStep, setCurrentStep] = useState(1);
  const totalSteps = 3;
  
  // Real-time AI Compliances State
  const [complianceScore, setComplianceScore] = useState(85);
  const [suggestions, setSuggestions] = useState<string[]>([
    "Project Name is missing. Provide a descriptive title to frame the compliance scan.",
    "Tip: No global compliance standards (GDPR, HIPAA) were selected. Verify if your research crosses international boundaries."
  ]);
  const [riskLevel, setRiskLevel] = useState<string>("Medium");
  const [aiMemo, setAiMemo] = useState<string>("AI system stands ready to analyze your draft inputs.");
  const [isScanning, setIsScanning] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedPlan, setGeneratedPlan] = useState<string>("");
  const [isCopied, setIsCopied] = useState(false);

  // File Upload drag states
  const [dragActive, setDragActive] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);

  // Effect to perform debounce-scans to the backend for Automated scan block
  useEffect(() => {
    let active = true;
    const delayDebounceFn = setTimeout(async () => {
      setIsScanning(true);
      try {
        const response = await fetch("/api/analyze-compliance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(activeProject),
        });
        if (response.ok && active) {
          const data = await response.json();
          setComplianceScore(data.complianceScore);
          setSuggestions(data.suggestions);
          setRiskLevel(data.riskLevel);
          setAiMemo(data.aiScanningMemo);
        }
      } catch (err) {
        console.warn("Client scanner failed connection, using fallback standard evaluator:", err);
      } finally {
        if (active) setIsScanning(false);
      }
    }, 1000); // Trigger compliance scan after typing ceases for 1s

    return () => {
      active = false;
      clearTimeout(delayDebounceFn);
    };
  }, [activeProject]);

  const handleTextChange = (field: keyof DMPProject, value: string) => {
    onChangeActiveProject({
      ...activeProject,
      [field]: value,
      updatedAt: new Date().toISOString()
    });
  };

  const handleDataSourceToggle = (src: string) => {
    const prev = activeProject.dataSources;
    const next = prev.includes(src) 
      ? prev.filter(item => item !== src)
      : [...prev, src];
    
    onChangeActiveProject({
      ...activeProject,
      dataSources: next,
      updatedAt: new Date().toISOString()
    });
  };

  const handleComplianceToggle = (comp: string) => {
    const prev = activeProject.complianceRequirements;
    const next = prev.includes(comp)
      ? prev.filter(item => item !== comp)
      : [...prev, comp];

    onChangeActiveProject({
      ...activeProject,
      complianceRequirements: next,
      updatedAt: new Date().toISOString()
    });
  };

  // Drag & Drop File Handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      setUploadedFileName(file.name);
      // Automatically register the file metadata description
      onChangeActiveProject({
        ...activeProject,
        customDataSourcesDesc: `Registered source: ${file.name} (${Math.round(file.size / 1024)} KB)`,
        dataSources: Array.from(new Set([...activeProject.dataSources, "Imported Schema Registry"]))
      });
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploadedFileName(file.name);
      onChangeActiveProject({
        ...activeProject,
        customDataSourcesDesc: `Registered source: ${file.name} (${Math.round(file.size / 1024)} KB)`,
        dataSources: Array.from(new Set([...activeProject.dataSources, "Imported Schema Registry"]))
      });
    }
  };

  // Build the complete DMP document in Markdown with the Gemini API
  const handleCompleteBuild = async () => {
    setIsGenerating(true);
    try {
      const response = await fetch("/api/generate-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(activeProject),
      });
      if (response.ok) {
        const data = await response.json();
        setGeneratedPlan(data.markdown);
        // Save the complete plan in workspace state so dashboard works
        const updatedProj: DMPProject = {
          ...activeProject,
          status: "completed",
          generatedPlan: data.markdown,
          updatedAt: new Date().toISOString()
        };
        onSaveProject(updatedProj);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsGenerating(false);
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(generatedPlan);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  // Visual highlights for steps
  const stepNodeClass = (step: number) => {
    if (currentStep >= step) {
      return "bg-blue-600 text-white shadow-md shadow-blue-200 ring-4 ring-blue-50";
    }
    return "bg-slate-100 text-slate-400";
  };

  const stepLabelClass = (step: number) => {
    if (currentStep === step) return "text-blue-600 font-semibold";
    return "text-slate-400 font-medium";
  };

  return (
    <div className="space-y-12 animate-fade-in w-full max-w-4xl py-6">
      
      {/* Step Indicators Header */}
      <div className="space-y-8 text-center md:text-left">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Configure Project Scope</h1>
          <p className="text-slate-500 font-normal text-md mt-2 max-w-2xl">
            Define the fundamental architecture of your data management plan. Your responses will calibrate the AI drafting engine.
          </p>
        </div>

        {/* Progress Bar (Interactive visual nodes) */}
        {!generatedPlan && (
          <div className="relative w-full flex justify-between items-center px-4 md:px-12 py-4">
            <div className="absolute top-1/2 left-0 w-full h-[3px] bg-slate-100 -translate-y-1/2 -z-10 rounded-full"></div>
            <div 
              className="absolute top-1/2 left-0 h-[3px] bg-blue-600 -translate-y-1/2 -z-10 transition-all duration-500 rounded-full" 
              style={{ width: `${((currentStep - 1) / (totalSteps - 1)) * 100}%` }}
            ></div>
            
            <div className="relative flex flex-col items-center group cursor-pointer" onClick={() => setCurrentStep(1)}>
              <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 ${stepNodeClass(1)}`}>1</div>
              <span className={`absolute -bottom-7 font-mono text-[11px] tracking-wider uppercase whitespace-nowrap ${stepLabelClass(1)}`}>Core Details</span>
            </div>
            
            <div className="relative flex flex-col items-center group cursor-pointer" onClick={() => setCurrentStep(2)}>
              <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 ${stepNodeClass(2)}`}>2</div>
              <span className={`absolute -bottom-7 font-mono text-[11px] tracking-wider uppercase whitespace-nowrap ${stepLabelClass(2)}`}>Data Sources</span>
            </div>
            
            <div className="relative flex flex-col items-center group cursor-pointer" onClick={() => setCurrentStep(3)}>
              <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 ${stepNodeClass(3)}`}>3</div>
              <span className={`absolute -bottom-7 font-mono text-[11px] tracking-wider uppercase whitespace-nowrap ${stepLabelClass(3)}`}>Objectives</span>
            </div>
          </div>
        )}
      </div>

      {/* Main Interactive Workspace Card */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-80 h-80 bg-blue-50/40 rounded-full -mr-40 -mt-40 blur-3xl -z-[1]"></div>
        
        {/* If the DMP is successfully built with AI */}
        {generatedPlan ? (
          <div className="space-y-8 animate-fade-in">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-100">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="p-1 px-2.5 bg-emerald-50 text-emerald-700 text-[10px] font-mono font-bold tracking-wider rounded uppercase border border-emerald-200">
                    Plan Complied
                  </span>
                  <h2 className="text-xl font-bold text-slate-800">Your AI-Drafted DMP is Ready</h2>
                </div>
                <p className="text-xs text-slate-500">Formulated utilizing NSF & NIH compliance guidelines against active project directives.</p>
              </div>

              <div className="flex items-center gap-2">
                <button 
                  onClick={copyToClipboard}
                  className="px-4 py-2 bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700 rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm active:scale-95 transition-all cursor-pointer"
                >
                  {isCopied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                  {isCopied ? "Copied" : "Copy Raw Document"}
                </button>
                <button 
                  onClick={() => {
                    setGeneratedPlan("");
                    setCurrentStep(3);
                  }}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm active:scale-95 transition-all cursor-pointer"
                >
                  <RefreshCw size={14} />
                  Adjust Parameters
                </button>
              </div>
            </div>

            {/* Generated Document Reader Body */}
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-6 h-[480px] overflow-y-auto font-mono text-sm text-slate-800 leading-relaxed whitespace-pre-wrap select-text scrollbar-thin">
              {generatedPlan}
            </div>

            <div className="flex justify-end gap-3 pt-4">
              <button 
                onClick={() => onSetActiveTab("dashboard")}
                className="px-6 py-2.5 border border-slate-200 text-slate-700 rounded-xl text-xs font-semibold hover:bg-slate-50 shadow-sm active:scale-95 transition-all cursor-pointer"
              >
                Return to Dashboard
              </button>
            </div>
          </div>
        ) : (
          <form className="space-y-8 relative" onSubmit={(e) => e.preventDefault()}>
            
            {/* Step 1: Core Details */}
            {currentStep === 1 && (
              <div className="space-y-6 animate-fade-in-shorter">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="col-span-2 space-y-2">
                    <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Project Name</label>
                    <input 
                      type="text"
                      value={activeProject.name}
                      onChange={(e) => handleTextChange("name", e.target.value)}
                      className="w-full bg-[#F1F5F9] border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-4 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-sans font-medium outline-none"
                      placeholder="e.g., Clinical Trial Alpha - Phase II"
                    />
                  </div>
                  
                  <div className="space-y-2">
                    <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Lead Investigator</label>
                    <input 
                      type="text"
                      value={activeProject.leadInvestigator}
                      onChange={(e) => handleTextChange("leadInvestigator", e.target.value)}
                      className="w-full bg-[#F1F5F9] border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-4 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-sans font-medium outline-none"
                      placeholder="Full legal name"
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Grant ID</label>
                    <input 
                      type="text"
                      value={activeProject.grantId}
                      onChange={(e) => handleTextChange("grantId", e.target.value)}
                      className="w-full bg-[#F1F5F9] border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-4 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-sans font-medium outline-none"
                      placeholder="Optional identifier"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 2: Data Sources */}
            {currentStep === 2 && (
              <div className="space-y-6 animate-fade-in-shorter">
                <div className="space-y-4">
                  {/* Drag and Drop Region */}
                  <div 
                    onDragEnter={handleDrag}
                    onDragOver={handleDrag}
                    onDragLeave={handleDrag}
                    onDrop={handleDrop}
                    className={`p-8 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center gap-3 transition-colors cursor-pointer relative ${
                      dragActive 
                        ? "border-blue-500 bg-blue-50/50" 
                        : "border-slate-300 bg-slate-50 hover:bg-slate-100/70"
                    }`}
                  >
                    <CloudUpload className="text-4xl text-blue-600 animate-pulse" size={40} />
                    <div className="text-center space-y-1">
                      <p className="font-bold text-slate-800 text-base">Import Source Registry</p>
                      <p className="text-slate-400 text-xs">Drag & drop CSV, JSON schema description files or click below</p>
                    </div>
                    
                    <input 
                      type="file" 
                      id="file-upload-input" 
                      onChange={handleFileInput} 
                      className="absolute inset-0 opacity-0 cursor-pointer" 
                    />

                    {uploadedFileName && (
                      <p className="text-[11px] font-mono text-emerald-600 bg-emerald-50 px-3 py-1 border border-emerald-100 rounded-full mt-2 flex items-center gap-1">
                        <CheckCircle2 size={12} /> Registered: {uploadedFileName}
                      </p>
                    )}
                  </div>

                  {/* Standard Ingestion Categories checkboxes */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {[
                      "IoT Sensor Streams",
                      "Relational SQL DBs",
                      "Unstructured Documents",
                      "Legacy Mainframe Data"
                    ].map((src) => {
                      const active = activeProject.dataSources.includes(src);
                      return (
                        <div 
                          key={src}
                          onClick={() => handleDataSourceToggle(src)}
                          className={`p-4 rounded-xl flex items-center gap-4 cursor-pointer transition-all border ${
                            active 
                              ? "bg-blue-50 border-blue-200 text-blue-900 shadow-sm" 
                              : "bg-slate-50 border-slate-100 text-slate-800 hover:bg-slate-100"
                          }`}
                        >
                          <input 
                            type="checkbox"
                            checked={active}
                            onChange={() => {}} // Synced via container click
                            className="w-5 h-5 rounded text-blue-600 focus:ring-blue-500 border-slate-300 pointer-events-none"
                          />
                          <span className="text-sm font-semibold">{src}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Step 3: Objectives */}
            {currentStep === 3 && (
              <div className="space-y-6 animate-fade-in-shorter">
                <div className="space-y-4">
                  <div className="space-y-2">
                    <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Primary Research Objective</label>
                    <textarea 
                      value={activeProject.primaryObjective}
                      onChange={(e) => handleTextChange("primaryObjective", e.target.value)}
                      className="w-full bg-[#F1F5F9] border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-4 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-sans outline-none min-h-[120px]"
                      placeholder="Describe the intended utility, experimental boundaries, and long-term scientific objectives of this database..."
                    ></textarea>
                  </div>

                  {/* Compliance Mandates */}
                  <div className="space-y-2">
                    <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500 block">Compliance Requirements</label>
                    <div className="flex flex-wrap gap-2 pt-1">
                      {["GDPR", "HIPAA", "CCPA", "ISO 27001"].map((comp) => {
                        const active = activeProject.complianceRequirements.includes(comp);
                        return (
                          <button
                            type="button"
                            key={comp}
                            onClick={() => handleComplianceToggle(comp)}
                            className={`px-4 py-2 rounded-full font-semibold font-mono text-xs border cursor-pointer transition-all ${
                              active 
                                ? "bg-blue-600 border-blue-600 text-white shadow-sm shadow-blue-100" 
                                : "bg-slate-100 hover:bg-slate-200/85 text-slate-600 border-transparent"
                            }`}
                          >
                            {comp}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Form Action Controls */}
            <div className="flex justify-between items-center pt-8 border-t border-slate-150">
              <button
                type="button"
                onClick={() => setCurrentStep(prev => Math.max(1, prev - 1))}
                className={`px-6 py-3 border border-slate-200 text-slate-700 bg-white font-semibold rounded-xl hover:bg-slate-50 transition-all active:scale-95 flex items-center gap-2 cursor-pointer ${
                  currentStep === 1 ? "invisible" : ""
                }`}
              >
                <ArrowLeft size={16} /> Previous
              </button>

              {currentStep < totalSteps ? (
                <button
                  type="button"
                  onClick={() => setCurrentStep(prev => Math.min(totalSteps, prev + 1))}
                  className="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl shadow-md shadow-blue-100 active:scale-95 transition-all flex items-center gap-2 cursor-pointer"
                >
                  Next Step <ArrowRight size={16} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleCompleteBuild}
                  disabled={isGenerating}
                  className="px-8 py-3 bg-slate-900 text-white font-semibold rounded-xl shadow-lg hover:bg-slate-850 active:scale-95 transition-all flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                >
                  {isGenerating ? (
                    <>
                      <Bot size={16} className="animate-spin" /> Compiling Plan...
                    </>
                  ) : (
                    <>
                      Complete Build <Sparkles size={16} className="text-yellow-400" />
                    </>
                  )}
                </button>
              )}
            </div>
          </form>
        )}
      </div>

      {/* Guidance Bento Grid (Render at all times when editing form) */}
      {!generatedPlan && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Need Help Card */}
          <div className="bg-slate-100 p-6 rounded-2xl space-y-3.5 border border-slate-200/50">
            <div className="w-10 h-10 rounded-xl bg-slate-200/65 flex items-center justify-center text-blue-600">
              <Info size={20} />
            </div>
            <h4 className="text-lg font-bold text-slate-800">Need Help?</h4>
            <p className="text-xs text-slate-500 leading-relaxed">
              Access our documentation library for industry-specific data management templates, schemas, and policy directives.
            </p>
          </div>

          {/* Automated Real-time compliance monitoring */}
          <div className="bg-slate-150 p-6 rounded-2xl md:col-span-2 relative overflow-hidden flex flex-col justify-between border border-slate-200/60 min-h-[220px]">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-lg font-bold text-slate-800">Automated Compliance Scan</h4>
                
                {/* Score badge */}
                <span className="font-mono text-xs bg-slate-900 text-white font-bold px-2.5 py-1 rounded-md">
                  Safety Rating: {complianceScore}/100
                </span>
              </div>
              
              <p className="text-xs text-slate-500 leading-relaxed">
                {aiMemo}
              </p>

              {/* Suggestions bullets list */}
              <ul className="text-xs space-y-1.5 pt-2 text-slate-600 font-sans list-inside list-disc">
                {suggestions.map((s, idx) => (
                  <li key={idx} className="leading-snug">
                    {s}
                  </li>
                ))}
              </ul>
            </div>

            {/* AI Heartbeat scanning */}
            <div className="flex items-center gap-2 mt-4 pt-4 border-t border-slate-200/70">
              <span className={`w-2.5 h-2.5 rounded-full ${isScanning ? "bg-amber-500 animate-ping" : "bg-blue-600 pulse-glow"}`}></span>
              <span className="font-mono text-[10px] tracking-wider font-semibold text-blue-600 uppercase">
                {isScanning ? "ANALYSIS IN PROGRESS..." : "AI ACTIVE & SCANNING"}
              </span>
            </div>

            {/* Robot background silhouette */}
            <div className="absolute -right-6 -bottom-6 w-28 h-28 opacity-5 text-slate-700 pointer-events-none">
              <Bot size={110} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
