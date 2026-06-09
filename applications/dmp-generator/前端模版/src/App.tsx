import { useState, useEffect } from "react";
import { DMPProject } from "./types";
import Dashboard from "./components/Dashboard";
import WizardForm from "./components/WizardForm";
import SecurityProtocols from "./components/SecurityProtocols";
import RetentionPolicy from "./components/RetentionPolicy";
import AIAssistant from "./components/AIAssistant";
import { 
  Database, BarChart3, Lock, History, Bot, 
  Settings, HelpCircle, Bell, Search, Menu, X, PlusCircle 
} from "lucide-react";

const INITIAL_PROJECTS: DMPProject[] = [
  {
    id: "proj-alpha",
    name: "Clinical Trial Alpha - Phase II",
    leadInvestigator: "Dr. Alexander Vane",
    grantId: "NIH-R01-AI28491",
    dataSources: ["IoT Sensor Streams", "Relational SQL DBs"],
    primaryObjective: "Analyzing physiological stress responses under drug regime 12B over 90 days across 45 clinical test subjects.",
    complianceRequirements: ["HIPAA", "GDPR"],
    securityChecks: {
      encryptionAtRest: true,
      anonymization: true,
      rbac: false,
      auditLogging: true,
      tlsInTransit: true,
    },
    retentionYears: 7,
    retentionStrategy: "archive",
    createdAt: new Date(Date.now() - 36000000).toISOString(),
    updatedAt: new Date(Date.now() - 10000000).toISOString(),
    status: "completed",
    generatedPlan: `# Data Management Plan (DMP): Clinical Trial Alpha - Phase II

## 1. Project Overview & Scope
This Data Management Plan (DMP) governs the lifecycle parameters of the Clinical Trial Alpha (Phase II), directed by Lead Investigator Dr. Alexander Vane (Grant ID: NIH-R01-AI28491). This scientific initiative evaluations targeted pharmacokinetic parameters of drug compound 12B inside controlled environments.

## 2. Data Types & Ingestion Formats
The program registers telemetry from IoT Sensor Streams (continuous biometrics, pulse waveforms staged inside JSON streams) and standard electronic health records kept in Relational SQL DBs (structured patient metrics synced monthly).

## 3. Storage, Cyber-Infrastructure, and Security
Data security aligns with stringent institutional standards:
- **AES-256 Bit Encryption at Rest**: Encrypts cold records and database partitions.
- **HMS Anonymization**: All direct patient qualifiers (keys, surnames) are replaced programmatically with salted SHA3-256 hashes inside secondary data channels.
- **Audit Logging**: Logs all queries to active compliance blocks into unalterable transaction ledgers to detect access anomalies.

## 4. Policy for Access, Sharing, and Compliance
The research material falls under combined GDPR and HIPAA requirements. Access permissions are constrained to verified medical technicians and subject to Business Associate Agreements (BAAs) prior to audit reviews.

## 5. Post-Project Retention & Archiving
Following active analysis, raw records will reside under institutional lock for a duration of 7 years, then complete the preservation sequence by migrating encrypted archives to secondary cold-tape offline vaults.`
  }
];

export default function App() {
  const [projects, setProjects] = useState<DMPProject[]>([]);
  const [activeTab, setActiveTab] = useState<string>("collection"); // Matches HTML main state (Collection Plan active)
  const [activeProject, setActiveProject] = useState<DMPProject | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Load projects from localStorage or default on startup
  useEffect(() => {
    const saved = localStorage.getItem("dmp_architect_projects_v1");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        setProjects(parsed);
        if (parsed.length > 0) {
          setActiveProject(parsed[0]);
        }
      } catch (err) {
        setProjects(INITIAL_PROJECTS);
        setActiveProject(INITIAL_PROJECTS[0]);
      }
    } else {
      setProjects(INITIAL_PROJECTS);
      setActiveProject(INITIAL_PROJECTS[0]);
      localStorage.setItem("dmp_architect_projects_v1", JSON.stringify(INITIAL_PROJECTS));
    }
  }, []);

  const saveProjectsToStorage = (updatedList: DMPProject[]) => {
    setProjects(updatedList);
    localStorage.setItem("dmp_architect_projects_v1", JSON.stringify(updatedList));
  };

  // Switch or update active project configuration
  const handleActiveProjectUpdate = (updatedProj: DMPProject) => {
    setActiveProject(updatedProj);
    const updatedList = projects.map(p => p.id === updatedProj.id ? updatedProj : p);
    saveProjectsToStorage(updatedList);
  };

  const handleCreateNewProject = () => {
    const newProj: DMPProject = {
      id: `proj-${Date.now()}`,
      name: "New Research Scope Setup",
      leadInvestigator: "",
      grantId: "",
      dataSources: [],
      primaryObjective: "",
      complianceRequirements: [],
      securityChecks: {
        encryptionAtRest: false,
        anonymization: false,
        rbac: false,
        auditLogging: false,
        tlsInTransit: false
      },
      retentionYears: 5,
      retentionStrategy: "archive",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      status: "draft"
    };

    const list = [newProj, ...projects];
    saveProjectsToStorage(list);
    setActiveProject(newProj);
    setActiveTab("collection"); // Direct to the building form wizard
  };

  const handleDeleteProject = (id: string) => {
    const filtered = projects.filter(p => p.id !== id);
    saveProjectsToStorage(filtered);
    if (activeProject?.id === id) {
      setActiveProject(filtered.length > 0 ? filtered[0] : null);
    }
  };

  const handleSelectProject = (project: DMPProject) => {
    setActiveProject(project);
    setActiveTab("collection"); // Re-focus on the editor
  };

  // Safe accessor to back up empty projects gracefully
  const currentProject = activeProject || {
    id: "proj-fallback",
    name: "Draft Portfolio Setup",
    leadInvestigator: "Dr. Jane Doe",
    grantId: "",
    dataSources: [],
    primaryObjective: "",
    complianceRequirements: [],
    securityChecks: {
      encryptionAtRest: false,
      anonymization: false,
      rbac: false,
      auditLogging: false,
      tlsInTransit: false
    },
    retentionYears: 5,
    retentionStrategy: "archive",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    status: "draft" as const
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans antialiased text-slate-900 select-none">
      
      {/* Top Header Navbar */}
      <header className="bg-white fixed top-0 left-0 right-0 z-50 border-b border-slate-200/80 shadow-sm h-16">
        <div className="flex justify-between items-center w-full px-6 md:px-10 max-w-7xl mx-auto h-full">
          
          {/* Logo & Subnavs */}
          <div className="flex items-center gap-10">
            <div className="flex items-center gap-2 cursor-pointer" onClick={() => setActiveTab("dashboard")}>
              <span className="font-sans text-xl font-black tracking-tight text-slate-900">
                DMP<span className="text-blue-600">.Architect</span>
              </span>
            </div>
            
            <nav className="hidden md:flex gap-6 items-center">
              <button 
                onClick={() => setActiveTab("dashboard")} 
                className={`text-sm font-semibold transition-colors font-sans py-1 cursor-pointer ${
                  activeTab === "dashboard" ? "text-blue-600 border-b-2 border-blue-600" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                Dashboard
              </button>
              <button 
                onClick={() => {
                  setActiveTab("collection");
                }} 
                className={`text-sm font-semibold transition-colors font-sans py-1 cursor-pointer ${
                  activeTab === "collection" ? "text-blue-600 border-b-2 border-blue-600" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                Projects
              </button>
              <button 
                onClick={() => setActiveTab("ai-assistant")}
                className={`text-sm font-semibold transition-colors font-sans py-1 cursor-pointer ${
                  activeTab === "ai-assistant" ? "text-blue-600 border-b-2 border-blue-600" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                Team Agent
              </button>
            </nav>
          </div>

          {/* Right Header Controls */}
          <div className="flex items-center gap-4">
            
            {/* Search inputs */}
            <div className="relative hidden sm:block">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <input 
                type="text"
                placeholder="Search portfolios..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-50/80 border-transparent text-xs rounded-full pl-10 pr-4 py-2.5 w-56 focus:outline-none focus:ring-2 focus:ring-blue-100 focus:bg-white transition-all text-slate-700 font-sans font-medium"
              />
            </div>

            <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer relative">
              <Bell size={18} />
              <span className="absolute top-1 right-1 w-2 h-2 bg-blue-600 rounded-full"></span>
            </button>
            <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer">
              <HelpCircle size={18} />
            </button>

            {/* Profile Avatar */}
            <img 
              alt="User Profile"
              referrerPolicy="no-referrer"
              src="https://lh3.googleusercontent.com/aida-public/AB6AXuDU5hiQUBR27SsTGo4WqRr7kUVufHGsil8GPlt5tQRrv-eVEYy-fI32olBILEjgC4FuaFU9scu2H6TIxSvf9gTpAl8Jtu13sRidNX0dB7eYJEDUTo1lfJp46UqowqVjLDbj98Q-8VczjF_bepJPK8A6vLrSqPP2urjZFrQSx7gBCQ6HstiFbYKmh70XV_6_q0QJy2hhMChjtFoofTWVGqTkRVT3nLdvG7i1-NBL4pF5Jqi5Tblf3nE2JHlL9YlaIDAFfPJXmywGXxM"
              className="w-8 h-8 rounded-full border border-slate-200"
            />

            {/* Mobile Sidebar Toggle */}
            <button 
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden p-2 text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
            >
              {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>

        </div>
      </header>

      {/* Main Body Shell */}
      <div className="flex flex-1 pt-16">
        
        {/* Left Side Navigation Sidebar */}
        <aside className={`
          fixed lg:sticky top-16 h-[calc(100vh-64px)] w-64 bg-white border-r border-slate-200/80 flex flex-col p-5 gap-6 z-40 transition-transform duration-300
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
        `}>
          
          {/* Active selected project metadata panel */}
          <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-xl border border-slate-200/40">
            <div className="w-9 h-9 rounded-lg bg-blue-600 text-white flex items-center justify-center">
              <Database size={18} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-xs font-bold text-slate-800 truncate font-sans">{currentProject.name}</h3>
              <p className="text-[10px] text-slate-400 font-medium font-mono">Current Phase: Generation</p>
            </div>
          </div>

          {/* Tab Navigation links */}
          <nav className="flex-1 space-y-1">
            {[
              { id: "dashboard", label: "Data Overview", icon: BarChart3 },
              { id: "collection", label: "Collection Plan", icon: Database },
              { id: "security", label: "Security Protocols", icon: Lock },
              { id: "retention", label: "Retention Policy", icon: History },
              { id: "ai-assistant", label: "AI Assistant", icon: Bot }
            ].map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => {
                    setActiveTab(tab.id);
                    setSidebarOpen(false);
                  }}
                  className={`w-full flex items-center gap-3.5 px-4 py-3 rounded-xl transition-all font-semibold font-mono text-[11px] uppercase tracking-wider cursor-pointer ${
                    active 
                      ? "bg-blue-600 text-white shadow-sm shadow-blue-150" 
                      : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"
                  }`}
                >
                  <Icon size={16} />
                  {tab.label}
                </button>
              );
            })}
          </nav>

          {/* Primary Action Button */}
          <button 
            onClick={() => {
              handleCreateNewProject();
              setSidebarOpen(false);
            }}
            className="w-full bg-slate-900 hover:bg-slate-800 text-white py-3 px-4 rounded-xl text-xs font-semibold shadow-sm flex items-center justify-center gap-2 hover:translate-y-[-1px] active:translate-y-0 transition-all duration-200 cursor-pointer"
          >
            <PlusCircle size={15} /> New DMP Scope
          </button>

          {/* Bottom Settings Link Group */}
          <div className="border-t border-slate-150/80 pt-4 space-y-1">
            <button
              onClick={() => {
                setActiveTab("settings");
                setSidebarOpen(false);
              }}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-[10px] font-mono tracking-wider uppercase font-semibold cursor-pointer ${
                activeTab === "settings" ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:bg-slate-50"
              }`}
            >
              <Settings size={14} />
              Settings
            </button>
            <button
              onClick={() => {
                setActiveTab("support");
                setSidebarOpen(false);
              }}
              className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-[10px] font-mono tracking-wider uppercase font-semibold cursor-pointer ${
                activeTab === "support" ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:bg-slate-50"
              }`}
            >
              <HelpCircle size={14} />
              Support
            </button>
          </div>

        </aside>

        {/* Dynamic Canvas Area */}
        <main className="flex-1 p-6 md:p-10 min-h-[calc(100vh-64px)] flex justify-center overflow-x-hidden">
          <div className="w-full max-w-4xl">
            {activeTab === "dashboard" && (
              <Dashboard 
                projects={projects} 
                onSelectProject={handleSelectProject} 
                onDeleteProject={handleDeleteProject}
                onSetActiveTab={setActiveTab}
              />
            )}

            {activeTab === "collection" && (
              <WizardForm 
                activeProject={currentProject} 
                onChangeActiveProject={handleActiveProjectUpdate} 
                onSaveProject={handleActiveProjectUpdate}
                onSetActiveTab={setActiveTab}
              />
            )}

            {activeTab === "security" && (
              <SecurityProtocols 
                activeProject={currentProject} 
                onChangeActiveProject={handleActiveProjectUpdate} 
              />
            )}

            {activeTab === "retention" && (
              <RetentionPolicy 
                activeProject={currentProject} 
                onChangeActiveProject={handleActiveProjectUpdate} 
              />
            )}

            {activeTab === "ai-assistant" && (
              <AIAssistant 
                activeProject={currentProject} 
              />
            )}

            {activeTab === "settings" && (
              <div className="space-y-6 animate-fade-in py-6">
                <div>
                  <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 font-sans">System Configurations</h1>
                  <p className="text-slate-500 mt-2">Manage API access credentials, data sharing parameters, and automatic metadata publishing pipelines.</p>
                </div>
                <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm font-sans space-y-4">
                  <h3 className="font-bold text-slate-800 text-sm">Workspace Environment</h3>
                  <div className="space-y-2 text-xs text-slate-600 leading-normal">
                    <p>• **Gemini Key Status**: {process.env.GEMINI_API_KEY ? "🟢 Active & Encrypted" : "⚠️ Offline - Running static heuristics models"}</p>
                    <p>• **Database Sandbox Type**: LocalStorage persistent memory storage bucket.</p>
                    <p>• **Network Protocol**: Encrypted Express gateway bound to nginx proxy routing on Port 3000.</p>
                  </div>
                </div>
              </div>
            )}

            {activeTab === "support" && (
              <div className="space-y-6 animate-fade-in py-6">
                <div>
                  <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 font-sans">Support Desk</h1>
                  <p className="text-slate-500 mt-2">Inquire with our specialized team regarding institutional grant formats, NIH timelines, or CCPA modifications.</p>
                </div>
                <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm font-sans space-y-4 text-center py-10">
                  <HelpCircle size={40} className="text-blue-500 mx-auto animate-bounce" />
                  <h3 className="font-bold text-slate-800 text-sm">Need help writing custom schemas?</h3>
                  <p className="text-xs text-slate-500 max-w-sm mx-auto leading-relaxed">Our clinical compliance experts are available around the clock. Open a chat sidebar inside the **AI Assistant** tab to interact with our pretrained DMP-compliance model.</p>
                </div>
              </div>
            )}
          </div>
        </main>

      </div>

      {/* Global Footer */}
      <footer className="bg-white border-t border-slate-200 mt-auto shadow-sm">
        <div className="w-full max-w-7xl mx-auto py-8 px-6 md:px-10 flex flex-col md:flex-row justify-between items-center gap-4">
          <span className="font-sans text-md text-slate-900 font-black tracking-tight cursor-pointer" onClick={() => setActiveTab("dashboard")}>
            DMP<span className="text-blue-600">.Architect</span>
          </span>
          
          <div className="flex flex-wrap justify-center gap-6">
            <a className="font-mono text-[10px] uppercase tracking-wider text-slate-400 hover:text-blue-600 transition-colors" href="#">Privacy Policy</a>
            <a className="font-mono text-[10px] uppercase tracking-wider text-slate-400 hover:text-blue-600 transition-colors" href="#">Terms of Service</a>
            <a className="font-mono text-[10px] uppercase tracking-wider text-slate-400 hover:text-blue-600 transition-colors" href="#">API Documentation</a>
            <a className="font-mono text-[10px] uppercase tracking-wider text-slate-400 hover:text-blue-600 transition-colors" href="#">Security Compliance</a>
          </div>

          <p className="font-mono text-[10px] text-slate-400">© 2026 DMP.Architect. All rights reserved.</p>
        </div>
      </footer>

    </div>
  );
}
