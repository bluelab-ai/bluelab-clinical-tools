import React from "react";
import { DMPProject } from "../types";
import { Hourglass, Lock, RefreshCw, CalendarRange, Info } from "lucide-react";

interface RetentionPolicyProps {
  activeProject: DMPProject;
  onChangeActiveProject: (p: DMPProject) => void;
}

export default function RetentionPolicy({ activeProject, onChangeActiveProject }: RetentionPolicyProps) {
  const handleStrategyChange = (strat: string) => {
    onChangeActiveProject({
      ...activeProject,
      retentionStrategy: strat,
      updatedAt: new Date().toISOString()
    });
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChangeActiveProject({
      ...activeProject,
      retentionYears: parseInt(e.target.value, 10),
      updatedAt: new Date().toISOString()
    });
  };

  // Determine stage description text based on years and strategies
  const getPreservationSop = () => {
    switch (activeProject.retentionStrategy) {
      case "delete":
        return "At the End of term, automated software shredders clean filesystem blocks using NIST 800-88 single-pass overwrite algorithms.";
      case "archive":
        return "Data is compressed into GZIP TAR volumes, encrypted under AES-256 keys, and cold-stored in deep multi-regional Glacier vaults.";
      default:
        return "Ownership and file indexes transfer to an accredited academic core library or historical registry system.";
    }
  };

  return (
    <div className="space-y-8 animate-fade-in" id="retention-tab">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Retention & Archive Policies</h1>
        <p className="text-slate-500 mt-1">Steward the lifecycle of collected parameters, and define post-project data disposal, archiving timelines, and purge protocols.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left 2 Cols: Interactive selections */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white border border-slate-200/70 rounded-2xl p-6 shadow-sm space-y-8">
            
            {/* Range Slider Section */}
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <h3 className="font-bold text-slate-800 text-sm font-mono tracking-wider uppercase">Retention Span</h3>
                <span className="font-mono text-sm bg-blue-50 text-blue-700 font-bold px-3 py-1 rounded border border-blue-200">
                  {activeProject.retentionYears === 30 ? "Indefinite Scale" : `${activeProject.retentionYears} Years`}
                </span>
              </div>
              
              <input 
                type="range"
                min="1"
                max="30"
                value={activeProject.retentionYears}
                onChange={handleSliderChange}
                className="w-full h-2 bg-slate-100 rounded-lg appearance-none cursor-pointer accent-blue-600 focus:outline-none"
              />
              <div className="flex justify-between text-[11px] font-mono text-slate-400">
                <span>1 Year</span>
                <span>5 Years (Standard)</span>
                <span>10 Years</span>
                <span>30 Years (Indefinite)</span>
              </div>
            </div>

            {/* Preservation Regimen radio selectors */}
            <div className="space-y-4">
              <h3 className="font-bold text-slate-800 text-sm font-mono tracking-wider uppercase">Preservation Regimen</h3>
              
              <div className="grid grid-cols-1 gap-4">
                {[
                  {
                    id: "delete",
                    title: "Automatic Purge & File Shred (GDPR Purge)",
                    desc: "Deletes partitions at retention term to comply with GDPR Storage Limitation principles."
                  },
                  {
                    id: "archive",
                    title: "Encrypted Deep Glacier Cold-Storage",
                    desc: "Saves encrypted archives in deep offline tape directories for verification audits."
                  },
                  {
                    id: "transfer",
                    title: "Asset Transfer to Institutional Core Library",
                    desc: "Transfers primary research ownership directly to our public database archive."
                  }
                ].map((s) => {
                  const active = activeProject.retentionStrategy === s.id;
                  return (
                    <div
                      key={s.id}
                      onClick={() => handleStrategyChange(s.id)}
                      className={`p-4 rounded-xl border flex gap-4 cursor-pointer transition-all ${
                        active 
                          ? "bg-slate-50 border-blue-500 text-slate-900 shadow-sm" 
                          : "bg-white border-slate-200 text-slate-700 hover:border-slate-350"
                      }`}
                    >
                      <input 
                        type="radio"
                        checked={active}
                        onChange={() => {}} // Synced on parent click
                        className="w-4 h-4 text-blue-600 focus:ring-blue-500 border-slate-300 mt-1 cursor-pointer"
                      />
                      <div className="space-y-1 select-none">
                        <span className="font-semibold text-slate-800 text-sm block">{s.title}</span>
                        <p className="text-xs text-slate-500 leading-relaxed">{s.desc}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

          </div>
        </div>

        {/* Right 1 Col: Life cycle timeline visual progression */}
        <div className="space-y-6">
          <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-md space-y-6">
            <div className="flex items-center gap-2 text-blue-400 font-mono text-xs tracking-wider uppercase font-semibold">
              <CalendarRange size={14} /> Lifecycle Timeline
            </div>

            {/* Simulated chronological progress indicators */}
            <div className="space-y-6 relative pl-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-[2px] before:bg-slate-800 font-sans">
              
              <div className="relative">
                <span className="absolute -left-[22px] top-1 w-3.5 h-3.5 bg-blue-500 border-2 border-slate-900 rounded-full"></span>
                <span className="text-[10px] font-mono text-slate-400">STAGE 1: INGESTION</span>
                <h4 className="text-sm font-bold mt-0.5">Parameter Registration</h4>
                <p className="text-slate-400 text-xs py-0.5 leading-relaxed">Incoming research registries are indexed and verified against parameters.</p>
              </div>

              <div className="relative">
                <span className="absolute -left-[22px] top-1 w-3.5 h-3.5 bg-blue-500 border-2 border-slate-900 rounded-full"></span>
                <span className="text-[10px] font-mono text-slate-400">STAGE 2: RETENTION</span>
                <h4 className="text-sm font-bold mt-0.5">{activeProject.retentionYears}-Year Storage Window</h4>
                <p className="text-slate-400 text-xs py-0.5 leading-relaxed">Secure data servers maintain read access controls during the configured preservation term.</p>
              </div>

              <div className="relative font-semibold text-blue-300">
                <span className="absolute -left-[22px] top-1 w-3.5 h-3.5 bg-amber-400 border-2 border-slate-900 rounded-full"></span>
                <span className="text-[10px] font-mono text-amber-400">STAGE 3: DISPOSAL REGIMEN</span>
                <h4 className="text-sm font-bold mt-0.5 uppercase">{activeProject.retentionStrategy === "delete" ? "Disposal Purge" : activeProject.retentionStrategy === "archive" ? "Glacier Archiving" : "University Integration"}</h4>
                <p className="text-slate-300 text-xs font-normal py-0.5 leading-relaxed">{getPreservationSop()}</p>
              </div>

            </div>
          </div>

          <div className="bg-slate-100 p-5 rounded-2xl border border-slate-200/50 space-y-3">
            <div className="flex items-center gap-2 text-slate-700 font-bold text-sm">
              <Hourglass size={16} className="text-blue-600 animate-spin" style={{ animationDuration: "10s" }} />
              Active System Stewardship
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              DMP.Architect automatically embeds this timeline roadmap within Section 5 of your generated plan documents, detailing precise preservation SOPs for grant evaluators.
            </p>
          </div>
        </div>

      </div>
    </div>
  );
}
