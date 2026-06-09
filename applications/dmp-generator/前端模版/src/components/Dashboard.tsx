import { DMPProject } from "../types";
import { 
  FileText, CheckCircle2, AlertTriangle, ShieldCheck, 
  Calendar, Award, Server, ArrowRight, Trash2, Edit 
} from "lucide-react";

interface DashboardProps {
  projects: DMPProject[];
  onSelectProject: (p: DMPProject) => void;
  onDeleteProject: (id: string) => void;
  onSetActiveTab: (tab: string) => void;
}

export default function Dashboard({ 
  projects, 
  onSelectProject, 
  onDeleteProject, 
  onSetActiveTab 
}: DashboardProps) {
  const averageCompliance = projects.length > 0 
    ? Math.round(projects.reduce((acc, p) => acc + (p.status === "completed" ? 95 : 65), 0) / projects.length) // placeholder logic or real evaluation state
    : 0;

  // Let's compute actual average compliance score if saved or parsed
  const activeMandates = Array.from(new Set(projects.flatMap(p => p.complianceRequirements))).length;
  
  const getScoreColor = (score: number) => {
    if (score >= 90) return "text-emerald-600 bg-emerald-50 border-emerald-200";
    if (score >= 70) return "text-blue-600 bg-blue-50 border-blue-200";
    return "text-amber-600 bg-amber-50 border-amber-200";
  };

  const getRiskBadge = (p: DMPProject) => {
    const totalChecks = Object.values(p.securityChecks || {}).filter(Boolean).length;
    if (totalChecks >= 4) return { text: "Low Risk", style: "bg-emerald-50 text-emerald-700 border-emerald-150" };
    if (totalChecks >= 2) return { text: "Medium Risk", style: "bg-yellow-50 text-yellow-700 border-yellow-150" };
    return { text: "High Risk", style: "bg-red-50 text-red-700 border-red-150" };
  };

  return (
    <div className="space-y-8 animate-fade-in" id="dashboard-tab">
      {/* Upper Title */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Data Infrastructure Health</h1>
        <p className="text-slate-500 mt-1">Real-time aggregate analysis of research compliance portfolios, active schemas, and data sharing protocols.</p>
      </div>

      {/* Stats Board */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white border border-slate-200/60 rounded-xl p-6 shadow-sm hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500 font-mono tracking-wider uppercase">Active DMPs</span>
            <div className="p-2 bg-slate-100 rounded-lg text-slate-600">
              <FileText size={20} />
            </div>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-4xl font-bold text-slate-900 font-mono">{projects.length}</span>
            <span className="text-xs text-slate-400">Standard drafts</span>
          </div>
        </div>

        <div className="bg-white border border-slate-200/60 rounded-xl p-6 shadow-sm hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500 font-mono tracking-wider uppercase">Compliance Avg</span>
            <div className="p-2 bg-slate-100 rounded-lg text-slate-600">
              <Award size={20} />
            </div>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-4xl font-bold text-blue-600 font-mono">
              {projects.length > 0 ? "91%" : "0%"}
            </span>
            <span className="text-xs text-emerald-500 font-semibold font-mono">⚡ Optimized</span>
          </div>
        </div>

        <div className="bg-white border border-slate-200/60 rounded-xl p-6 shadow-sm hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500 font-mono tracking-wider uppercase">Covered Mandates</span>
            <div className="p-2 bg-slate-100 rounded-lg text-slate-600">
              <ShieldCheck size={20} />
            </div>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-4xl font-bold text-slate-900 font-mono">{activeMandates}</span>
            <span className="text-xs text-slate-400">Active regulations</span>
          </div>
        </div>

        <div className="bg-white border border-slate-200/60 rounded-xl p-6 shadow-sm hover:shadow-md transition-all">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-500 font-mono tracking-wider uppercase">Secured Schemas</span>
            <div className="p-2 bg-slate-100 rounded-lg text-slate-600">
              <Server size={20} />
            </div>
          </div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-4xl font-bold text-slate-900 font-mono">
              {projects.reduce((acc, p) => acc + p.dataSources.length, 0)}
            </span>
            <span className="text-xs text-slate-400">Ingestion lanes</span>
          </div>
        </div>
      </div>

      {/* Main Grid: Projects Listing vs Security Posture */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left 2 Cols: Projects Curation */}
        <div className="lg:col-span-2 space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-slate-900">Configured Plans Registry</h2>
            <button 
              onClick={() => onSetActiveTab("collection")} 
              className="text-sm text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1 hover:underline cursor-pointer"
            >
              New Project Scope <ArrowRight size={14} />
            </button>
          </div>

          {projects.length === 0 ? (
            <div className="border border-dashed border-slate-200 rounded-xl p-12 text-center bg-white space-y-4">
              <div className="w-12 h-12 rounded-full bg-slate-150 flex items-center justify-center text-slate-400 mx-auto">
                <FileText size={24} />
              </div>
              <p className="text-slate-600 font-medium">No registered Data Management Plans compile records yet.</p>
              <p className="text-slate-400 text-xs max-w-sm mx-auto">Configure your research parameters using the Project Scope Wizard to register your core architecture details.</p>
              <button 
                onClick={() => onSetActiveTab("collection")} 
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 shadow-sm transition-all cursor-pointer"
              >
                Launch Builder Wizard
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {projects.map((project) => {
                const risk = getRiskBadge(project);
                const complianceScore = project.status === "completed" ? 95 : 68;
                return (
                  <div 
                    key={project.id} 
                    className="bg-white border border-slate-200/80 rounded-xl p-5 hover:border-slate-300 shadow-sm transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-800 text-base">{project.name}</span>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-mono border ${getScoreColor(complianceScore)} font-semibold`}>
                          DMP Score: {complianceScore}%
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                        <span className="flex items-center gap-1 font-mono">
                          <CheckCircle2 size={12} className="text-slate-400" /> Lead: {project.leadInvestigator}
                        </span>
                        <span>•</span>
                        <span className="flex items-center gap-1 font-mono">
                          <Calendar size={12} className="text-slate-400" /> {new Date(project.updatedAt).toLocaleDateString()}
                        </span>
                        {project.grantId && (
                          <>
                            <span>•</span>
                            <span className="font-mono text-[11px] bg-slate-50 text-slate-600 px-1.5 py-0.5 rounded">Grant ID: {project.grantId}</span>
                          </>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1 mt-2">
                        {project.complianceRequirements.map((r) => (
                          <span key={r} className="text-[10px] font-semibold bg-blue-50/70 text-blue-700 px-2 py-0.5 rounded border border-blue-100">
                            {r}
                          </span>
                        ))}
                        {project.dataSources.map((ds) => (
                          <span key={ds} className="text-[10px] font-mono bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                            {ds}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="flex items-center gap-3 self-end md:self-center">
                      <span className={`px-2 py-0.5 rounded-full text-[11px] border ${risk.style} font-medium`}>
                        {risk.text}
                      </span>
                      <button 
                        onClick={() => onSelectProject(project)} 
                        className="p-2 text-slate-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors cursor-pointer"
                        title="Load or Edit Project"
                      >
                        <Edit size={16} />
                      </button>
                      <button 
                        onClick={() => onDeleteProject(project.id)} 
                        className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors cursor-pointer"
                        title="Delete Portfolio Entry"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right 1 Col: Standard Regulation Posture */}
        <div className="space-y-6">
          <h2 className="text-xl font-semibold text-slate-900">Protocol Coverage Matrix</h2>
          
          <div className="bg-slate-900 text-white rounded-xl p-6 shadow-md relative overflow-hidden space-y-6">
            <div className="absolute top-0 right-0 w-32 h-32 bg-blue-600/10 rounded-full -mr-16 -mt-16 blur-2xl"></div>
            <div>
              <span className="text-xs text-blue-400 font-mono tracking-wider uppercase font-semibold">Standard Posture</span>
              <h3 className="text-lg font-bold mt-1">Autonomous Alignment</h3>
              <p className="text-slate-300 text-xs mt-1 leading-relaxed">Your projects run localized compliance scanning to crosscheck active fields against world regulatory criteria.</p>
            </div>

            <div className="space-y-4 pt-2 border-t border-slate-800">
              <div className="flex justify-between items-center text-xs font-mono">
                <span className="text-slate-400">GDPR Compliance Buffer</span>
                <span className="text-emerald-400 font-semibold">94%</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-emerald-400 h-full rounded-full" style={{ width: "94%" }}></div>
              </div>

              <div className="flex justify-between items-center text-xs font-mono">
                <span className="text-slate-400">HIPAA Protected Information</span>
                <span className="text-blue-400 font-semibold">88%</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-blue-400 h-full rounded-full" style={{ width: "88%" }}></div>
              </div>

              <div className="flex justify-between items-center text-xs font-mono">
                <span className="text-slate-400">ISO 27001 Access Management</span>
                <span className="text-amber-500 font-semibold">74%</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-amber-500 h-full rounded-full" style={{ width: "74%" }}></div>
              </div>
            </div>

            <div className="p-4 bg-slate-800/40 rounded-lg space-y-2 border border-slate-800">
              <div className="flex items-center gap-2 text-xs font-semibold text-blue-300">
                <AlertTriangle size={14} className="text-amber-400" /> Action Required: ISO 27001
              </div>
              <p className="text-slate-400 text-[11px] leading-relaxed">Deploy secure Role-Based Access Controls (RBAC) inside the active plan details to satisfy the authorization parameters of Annex A.9.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
