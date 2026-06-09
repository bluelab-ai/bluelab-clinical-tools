import { DMPProject } from "../types";
import { ShieldCheck, ShieldAlert, CheckCircle, Info, Lock } from "lucide-react";

interface SecurityProtocolsProps {
  activeProject: DMPProject;
  onChangeActiveProject: (p: DMPProject) => void;
}

export default function SecurityProtocols({ activeProject, onChangeActiveProject }: SecurityProtocolsProps) {
  const protocolKeys: Array<{
    key: keyof DMPProject["securityChecks"];
    label: string;
    desc: string;
    gdprMapping: string;
    hipaaMapping: string;
  }> = [
    {
      key: "encryptionAtRest",
      label: "Symmetric Encryption at Rest (AES-256)",
      desc: "Implements hardware-embedded AES-256 cryptographic partitions to prevent data disclosure in the event of drive leakage.",
      gdprMapping: "GDPR Article 32(1)(a)",
      hipaaMapping: "HIPAA Rule §164.312(a)(2)(iv)"
    },
    {
      key: "anonymization",
      label: "Anonymization & Column Masking",
      desc: "Hashes high-cardinality PII parameters (names, contacts, ZIP codes) with salted key-HMAC vectors during data ingest.",
      gdprMapping: "GDPR Recital 26 / Minimization",
      hipaaMapping: "HIPAA Safe Harbor Standard"
    },
    {
      key: "rbac",
      label: "Role-Based Access Control (RBAC)",
      desc: "Limits data visibility inside the research portal based on designated user clearance grades (Least Privilege principle).",
      gdprMapping: "GDPR Access Controls",
      hipaaMapping: "HIPAA Security §164.312(a)(1)"
    },
    {
      key: "auditLogging",
      label: "Immutable Access Auditing Logs",
      desc: "Registers write/read connections into append-only cryptographic log ledgers to detect tampering or unauthorized queries.",
      gdprMapping: "GDPR Accountability Audit",
      hipaaMapping: "HIPAA Incident Audit §164.312(b)"
    },
    {
      key: "tlsInTransit",
      label: "TLS 1.3 Transport Security Layer",
      desc: "Enforces mandatory cipher suites for external API connections, neutralizing intermediate packet inspections.",
      gdprMapping: "GDPR Secure Transmission",
      hipaaMapping: "HIPAA Secure Tunnel standard"
    }
  ];

  const handleCheckboxChange = (key: keyof DMPProject["securityChecks"]) => {
    onChangeActiveProject({
      ...activeProject,
      securityChecks: {
        ...activeProject.securityChecks,
        [key]: !activeProject.securityChecks[key]
      },
      updatedAt: new Date().toISOString()
    });
  };

  const enabledCount = Object.values(activeProject.securityChecks || {}).filter(Boolean).length;
  const coveragePercent = Math.round((enabledCount / protocolKeys.length) * 100);

  return (
    <div className="space-y-8 animate-fade-in" id="security-tab">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">Security Protocols & Guardrails</h1>
        <p className="text-slate-500 mt-1">Configure active technical safeguards, encryption postures, and system audibility filters for database compliance.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left 2 Cols: Guardrails checklist checkboxes */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white border border-slate-200/70 rounded-2xl p-6 shadow-sm space-y-6">
            <h2 className="text-lg font-bold text-slate-800">Available Infrastructure Controls</h2>
            
            <div className="space-y-4">
              {protocolKeys.map((p) => {
                const checked = activeProject.securityChecks[p.key];
                return (
                  <div 
                    key={p.key}
                    onClick={() => handleCheckboxChange(p.key)}
                    className={`p-4 rounded-xl border flex gap-4 cursor-pointer transition-all ${
                      checked 
                        ? "bg-slate-50 border-blue-500 text-slate-900 shadow-sm" 
                        : "bg-white border-slate-200 text-slate-700 hover:border-slate-350"
                    }`}
                  >
                    <input 
                      type="checkbox"
                      checked={checked}
                      onChange={() => {}} // Swapped container click handles
                      className="w-5 h-5 rounded text-blue-600 focus:ring-blue-500 border-slate-300 mt-0.5"
                    />
                    <div className="space-y-1 select-none">
                      <span className="font-semibold text-slate-800 text-sm block">{p.label}</span>
                      <p className="text-xs text-slate-500 leading-relaxed">{p.desc}</p>
                      
                      <div className="flex gap-4 pt-1.5 font-mono text-[10px] text-slate-400 font-medium">
                        <span>{p.gdprMapping}</span>
                        <span>•</span>
                        <span>{p.hipaaMapping}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right 1 Col: Score Summary & Threat Index */}
        <div className="space-y-6">
          <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-md space-y-6">
            <div className="flex items-center gap-2 text-blue-400 font-mono text-xs tracking-wider uppercase font-semibold">
              <Lock size={14} /> Shield Assessment
            </div>
            
            <div className="text-center py-4 space-y-1">
              <span className="text-[11px] font-mono tracking-wider uppercase text-slate-400">Threat Defense Level</span>
              <h2 className="text-5xl font-extrabold text-blue-400 font-mono tracking-tight">{coveragePercent}%</h2>
              <p className="text-xs text-slate-300 pt-2">{enabledCount} of 5 infrastructure safeguards active</p>
            </div>

            {/* Coverage visual line */}
            <div className="w-full bg-slate-800 h-2.5 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full transition-all duration-505 ${
                  coveragePercent >= 80 ? "bg-emerald-400" : coveragePercent >= 40 ? "bg-blue-400 font-semibold" : "bg-amber-500"
                }`} 
                style={{ width: `${coveragePercent}%` }}
              ></div>
            </div>

            <div className="border-t border-slate-800 pt-4 space-y-3.5">
              <h3 className="text-xs font-semibold text-slate-400 font-mono tracking-wider uppercase">Active Coverage Matrix</h3>
              
              <div className="space-y-2 text-xs font-mono">
                <div className="flex justify-between items-center text-slate-300">
                  <span>Cryptographic Posture</span>
                  <span className={activeProject.securityChecks.encryptionAtRest ? "text-emerald-400" : "text-amber-500"}>
                    {activeProject.securityChecks.encryptionAtRest ? "🛡️ SECURED" : "❌ OPEN"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-slate-300">
                  <span>Identity Sanitization</span>
                  <span className={activeProject.securityChecks.anonymization ? "text-emerald-400" : "text-amber-500"}>
                    {activeProject.securityChecks.anonymization ? "🛡️ SECURED" : "❌ OPEN"}
                  </span>
                </div>
                <div className="flex justify-between items-center text-slate-300">
                  <span>Least-Privilege RBAC</span>
                  <span className={activeProject.securityChecks.rbac ? "text-emerald-400" : "text-amber-500"}>
                    {activeProject.securityChecks.rbac ? "🛡️ SECURED" : "❌ OPEN"}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-slate-100 p-5 rounded-2xl border border-slate-200/50 space-y-3">
            <div className="flex items-center gap-2 text-slate-700 font-bold text-sm">
              <Info size={16} className="text-blue-600" />
              Dynamic DMP Syncing
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              Updating these checks automatically alters your DMP's safety algorithm and shifts your customized compliance feedback block across the wizard and dashboard.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
