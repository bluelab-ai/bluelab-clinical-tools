import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = 3000;

app.use(express.json());

// Initialize Gemini safely to prevent crash if key is missing
let ai: GoogleGenAI | null = null;
const apiKey = process.env.GEMINI_API_KEY;

if (apiKey && apiKey !== "MY_GEMINI_API_KEY") {
  try {
    ai = new GoogleGenAI({
      apiKey,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        },
      },
    });
    console.log("Gemini client successfully initialized.");
  } catch (err) {
    console.error("Error initializing Gemini client:", err);
  }
} else {
  console.log("GEMINI_API_KEY is not defined or is placeholder. Using smart offline analytical models.");
}

/**
 * Resilient content generator helper that recovers from Gemini 503 Spikes
 * using exponential backoff and tier-2 model fallbacks.
 */
async function generateContentWithRetryAndFallback(params: {
  contents: any;
  config?: any;
}) {
  if (!ai) {
    throw new Error("Gemini client is not initialized.");
  }

  // Tier 1: gemini-3.5-flash (Standard), Tier 2: gemini-3.1-flash-lite (High availability)
  const models = ["gemini-3.5-flash", "gemini-3.1-flash-lite"];
  let lastError: any = null;

  for (const model of models) {
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        console.log(`Sending request to ${model} (attempt ${attempt}/2)...`);
        const response = await ai.models.generateContent({
          model,
          contents: params.contents,
          config: params.config,
        });
        if (response && response.text) {
          console.log(`Successfully received response from ${model}!`);
          return response;
        }
      } catch (err: any) {
        lastError = err;
        const errMsg = err.message || JSON.stringify(err);
        console.warn(`[Gemini Fallback System] Model ${model} failed on attempt ${attempt}/2: ${errMsg}`);
        
        // Wait longer on second attempt (exponentially back off: 400ms, then 800ms)
        await new Promise((resolve) => setTimeout(resolve, attempt * 400));
      }
    }
  }

  throw lastError || new Error("All model generation pathways exhausted.");
}

// ==========================================
// API Endpoint: Analyze Compliance in Real-Time
// ==========================================
app.post("/api/analyze-compliance", async (req, res) => {
  const {
    name,
    leadInvestigator,
    grantId,
    dataSources,
    primaryObjective,
    complianceRequirements,
    securityChecks,
    retentionYears,
    retentionStrategy,
  } = req.body;

  // Let's create smart local fallbacks based on compliance selections
  const fallbackSuggestions: string[] = [];
  let score = 85;
  let risk: "Low" | "Medium" | "High" = "Medium";

  if (!name) {
    fallbackSuggestions.push("Project Name is missing. Provide a descriptive title to frame the compliance scan.");
    score -= 10;
  }
  if (!leadInvestigator) {
    fallbackSuggestions.push("Lead Investigator is undefined. Multi-jurisdictional research requires appointing a designated Data Steward.");
    score -= 5;
  }
  if (complianceRequirements && complianceRequirements.length > 0) {
    risk = "High";
    if (complianceRequirements.includes("GDPR")) {
      fallbackSuggestions.push("GDPR Selected: You must ensure clear legal grounds for processing under Article 6 (e.g. Consent, Contract).");
      if (securityChecks && !securityChecks.anonymization) {
        fallbackSuggestions.push("GDPR Tip: Implement pseudonymization/anonymization immediately to comply with GDPR storage limitation & minimization principles.");
        score -= 15;
      }
    }
    if (complianceRequirements.includes("HIPAA")) {
      fallbackSuggestions.push("HIPAA Selected: Access to PHI (Protected Health Information) requires a Business Associate Agreement (BAA) and strong audit controls.");
      if (securityChecks && !securityChecks.encryptionAtRest) {
        fallbackSuggestions.push("HIPAA Warning: Federal standards strongly mandate end-to-end data encryption at rest and in transit.");
        score -= 20;
      }
      if (securityChecks && !securityChecks.auditLogging) {
        fallbackSuggestions.push("HIPAA Tech Rule: Active security auditing and event logs must be retained for at least 6 years under Security Rule §164.312(b).");
        score -= 10;
      }
    }
    if (complianceRequirements.includes("CCPA")) {
      fallbackSuggestions.push("CCPA Compliance: Ensure the right of Californians to know, delete, and opt-out of data sale can be exercised in your pipeline.");
    }
    if (complianceRequirements.includes("ISO 27001")) {
      fallbackSuggestions.push("ISO 27001 recommendation: Maintain a formal 'Statement of Applicability' and document access control records.");
      if (securityChecks && !securityChecks.rbac) {
        fallbackSuggestions.push("ISO 27001 audit defect: Implement formal Role-Based Access Control (RBAC) to limit user scopes.");
        score -= 10;
      }
    }
  } else {
    fallbackSuggestions.push("Tip: No global compliance standards (GDPR, HIPAA) were selected. Verify if your research crosses international boundaries.");
    risk = "Low";
  }

  // If secure check is ticked, boost rating
  if (securityChecks) {
    if (securityChecks.encryptionAtRest) score += 5;
    if (securityChecks.anonymization) score += 5;
    if (securityChecks.rbac) score += 5;
    if (securityChecks.auditLogging) score += 5;
    if (securityChecks.tlsInTransit) score += 5;
  }

  // Clamp score
  score = Math.max(10, Math.min(100, score));

  // If Gemini client is active, consult Gemini for deep enterprise suggestions
  if (ai) {
    try {
      const prompt = `You are an expert Data Privacy Officer and research compliance compliance consultant. Analyze the following data structure:
Project Name: ${name || "Untitled Draft"}
Lead Investigator: ${leadInvestigator || "Not specified"}
Grant ID: ${grantId || "None"}
Data Sources Selected: ${dataSources ? dataSources.join(", ") : "None"} 
Primary Objective: ${primaryObjective || "Not specified"}
Compliance Mandates: ${complianceRequirements ? complianceRequirements.join(", ") : "None"}
Security Protocols: Encryption At Rest: ${securityChecks?.encryptionAtRest}, Anonymization: ${securityChecks?.anonymization}, RBAC: ${securityChecks?.rbac}, Audit Logging: ${securityChecks?.auditLogging}, TLS in Transit: ${securityChecks?.tlsInTransit}
Retention Profile: Retained for ${retentionYears} years with strategy [${retentionStrategy}].

Provide feedback strictly as a JSON object containing the following keys:
- "complianceScore": an integer from 10 to 100
- "suggestions": an array of 3 to 5 clear, highly actionable, expert compliance/security advice items for this setup (keep each under 22 words)
- "riskLevel": either "Low", "Medium", or "High"
- "aiScanningMemo": a 20-word summary of your scan results.

Output raw JSON containing only these fields.`;

      const response = await generateContentWithRetryAndFallback({
        contents: prompt,
        config: {
          responseMimeType: "application/json",
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              complianceScore: { type: Type.INTEGER },
              suggestions: {
                type: Type.ARRAY,
                items: { type: Type.STRING },
              },
              riskLevel: { type: Type.STRING },
              aiScanningMemo: { type: Type.STRING },
            },
            required: ["complianceScore", "suggestions", "riskLevel", "aiScanningMemo"],
          },
        },
      });

      if (response && response.text) {
        const parsed = JSON.parse(response.text.trim());
        return res.json({
          complianceScore: parsed.complianceScore || score,
          suggestions: parsed.suggestions || fallbackSuggestions,
          riskLevel: parsed.riskLevel || risk,
          aiScanningMemo: parsed.aiScanningMemo || "Active AI compliance inspection successfully computed in real-time.",
        });
      }
    } catch (e) {
      console.warn("Gemini compliance analysis failed, reverting to local heuristics:", e);
    }
  }

  // Fallback response when offline or errors out
  return res.json({
    complianceScore: score,
    suggestions: fallbackSuggestions.slice(0, 5),
    riskLevel: risk,
    aiScanningMemo: "Compliance evaluation drafted locally. Add a GEMINI_API_KEY for deep AI-driven scanning.",
  });
});

// ==========================================
// API Endpoint: Generate Complete DMP Report
// ==========================================
app.post("/api/generate-plan", async (req, res) => {
  const {
    name,
    leadInvestigator,
    grantId,
    dataSources,
    primaryObjective,
    complianceRequirements,
    securityChecks,
    retentionYears,
    retentionStrategy,
  } = req.body;

  const resolvedName = name || "Research Project Alpha";
  const resolvedLead = leadInvestigator || "Dr. Jane Doe";
  const resolvedGrant = grantId || "G-249511-DM";

  if (ai) {
    try {
      const prompt = `Write a complete, professional, publication-ready Data Management Plan (DMP) compliant with NSF, NIH, and European Commission standard guidelines.
Details of Research Project:
- Project Name: ${resolvedName}
- Lead Investigator: ${resolvedLead}
- Grant Identifier: ${resolvedGrant}
- Selected Data Formats/Sources: ${dataSources ? dataSources.join(", ") : "Not selected"}
- Primary Research Objective: ${primaryObjective || "Standard scientific data curation."}
- Intended Regulatory Alignments: ${complianceRequirements && complianceRequirements.length > 0 ? complianceRequirements.join(", ") : "Internal data-privacy rules only"}
- Technical Controls Selected:
  - Encryption at Rest: ${securityChecks?.encryptionAtRest ? "Enabled" : "Disabled"}
  - Anonymization and De-identification: ${securityChecks?.anonymization ? "Enabled" : "Disabled"}
  - Role-Based Access Controls (RBAC): ${securityChecks?.rbac ? "Enabled" : "Disabled"}
  - Comprehensive Audit Logging: ${securityChecks?.auditLogging ? "Enabled" : "Disabled"}
  - Secure TLS Transmission: ${securityChecks?.tlsInTransit ? "Enabled" : "Disabled"}
- Data Life Cycle Support: Retain for ${retentionYears} year(s) then execute execution strategy: [${retentionStrategy}].

Structure your plan with these exact headings:
# Data Management Plan (DMP): ${resolvedName}

## 1. Project Overview & Scope
(Provide a publication-grade outline of the research scope, data stewards, and grant parameters.)

## 2. Data Types & Formats
(Discuss the ingest strategy for ${dataSources ? dataSources.join(", ") : "sources"}. Specify ingestion paths and standardization protocols.)

## 3. Storage, Cyber-Infrastructure, and Security
(Analyze the technical setups based on the active security items. Mention how encryption, access control, and auditing will prevent leaks.)

## 4. Policy for Access, Sharing, and Compliance
(Address how the team enforces compliance with ${complianceRequirements && complianceRequirements.length > 0 ? complianceRequirements.join("/") : "global research privacy principles"}.)

## 5. Post-Project Retention & Archiving
(Evaluate the long-term ${retentionYears}-year life cycle and specify standard operating procedures for the '${retentionStrategy}' stage.)

Keep the response formatted as rich, elegant Markdown. Focus on scientific precision and professional tone.`;

      const response = await generateContentWithRetryAndFallback({
        contents: prompt,
      });

      if (response && response.text) {
        return res.json({ markdown: response.text });
      }
    } catch (e) {
      console.error("Gemini plan generation failed:", e);
    }
  }

  // Heavy-duty fallback template
  const todayStr = new Date().toISOString().split("T")[0];
  const markdownFallback = `# Data Management Plan (DMP): ${resolvedName}

*Report generated on: ${todayStr}*
*Lead Investigator: ${resolvedLead}*
*Grant ID: ${resolvedGrant}*
*Primary Compliance Anchors: ${complianceRequirements && complianceRequirements.length > 0 ? complianceRequirements.join(", ") : "Standard Scientific Integrity Guidelines"}*

---

## 1. Project Overview & Scope
This Data Management Plan (DMP) governs the data collection, technical validation, and lifecycle management of **${resolvedName}**, led by **${resolvedLead}**. The research program is established to address the following primary objectives:
*"${primaryObjective || "The advancement and public availability of multi-dimensional scientific research raw data."}"*

The parameters are mapped to the infrastructure controls ensuring data stewardship, minimizing data leakage risks, and establishing clear accountability pathways for data custodians.

## 2. Data Types, Formats & Ingestion
The research project registers and curates data from several specialized endpoints:
${dataSources && dataSources.length > 0 ? dataSources.map((ds) => `- **${ds}**: Handled through standardized parsing APIs, standardizing schema files before staging.`).join("\n") : "- Generic Ingestion pipeline for file structures and documentation."}

All incoming files are parsed, validated, and logged inside a centralized storage bucket. 

## 3. Storage, Cyber-Infrastructure, and Security
To prevent unauthorized modification or disclosures, the architecture implements the following active technical checkpoints:
${securityChecks?.encryptionAtRest ? "- **AES-256 Bit Encryption at Rest**: Applied across databases, volumes, and cloud backup buckets." : "- **Symmetric encryption systems**: Configured across disk arrays to ensure localized containment."}
${securityChecks?.anonymization ? "- **Anonymization Engine**: Multi-column direct identifiers (names, coordinates, IDs) are programmatically scrubbed or replaced with hashed pseudonyms." : "- **Data Minimization Rules**: Standard filters exclude personal identifiers at point of ingest."}
${securityChecks?.rbac ? "- **Role-Based Access Control (RBAC)**: Least Privilege Access ensures that secondary personnel compile read-only analytics, while write permissions are locked to designated Data Stewards." : "- **Access Partitioning**: Authentication tokens are bound to active project directories."}
${securityChecks?.auditLogging ? "- **Immutable Audit Logging**: Actions performed on compliance material (read, write, export) write entries into tamper-evident logs." : "- **Transactional History**: Activity logs capture connection times and database states."}
${securityChecks?.tlsInTransit ? "- **TLS 1.3 Transmission Security**: Secure HTTPS lines mandate encrypted tunnels for remote API handshakes." : "- **Network Encapsulation**: Firewalled subnets constrain query payloads."}

## 4. Policy for Access, Sharing, and Compliance
The project complies with the explicit parameters of ${complianceRequirements && complianceRequirements.length > 0 ? complianceRequirements.join(" & ") : "standard scientific integrity frameworks"}. 
- Rights of research subjects regarding data revocation, rectification, or audit will be handled by the office of **${resolvedLead}**.
- Data exports and cross-border scientific exchanges must satisfy the technical requirements before transfer permissions are distributed.

## 5. Post-Project Retention & Archiving
Following the project closure, records will be maintained for a period of **${retentionYears} year(s)** to ensure verification of experimental findings.
At the end of this retention milestone, the data will undergo the designated **'${retentionStrategy}'** regimen:
- **Execution Actions**: Systems will coordinate automatic routines to purge disk partitions or archive metadata files in deep storage, according to official compliance guidelines.`;

  return res.json({ markdown: markdownFallback });
});

// ==========================================
// API Endpoint: Intelligent Chat Help Desk
// ==========================================
app.post("/api/chat", async (req, res) => {
  const { messages, projectContext } = req.body;
  if (!messages || messages.length === 0) {
    return res.status(400).json({ error: "Messages array is required." });
  }

  const latestMessage = messages[messages.length - 1].text;

  const currentProjectSummary = projectContext
    ? `Current Project: "${projectContext.name || "Untitled"}"
Investigator: "${projectContext.leadInvestigator || "Not specified"}"
Data Sources: "${projectContext.dataSources ? projectContext.dataSources.join(", ") : "None"}"
Objectives: "${projectContext.primaryObjective || "Not specified"}"
Compliance standard: "${projectContext.complianceRequirements ? projectContext.complianceRequirements.join(", ") : "None"}"`
    : "No active configuration set up.";

  const systemInstruction = `You are an elite, highly professional Data Privacy Officer and research compliance compliance consultant inside the DMP.Architect platform.
You guide scientific researchers on GDPR, HIPAA, CCPA, NIST, and ISO 27001 data principles.
Be direct, helpful, and technically precise. Avoid marketing fluff or self-praising fluff.
Evaluate queries in relation to this project configuration:
${currentProjectSummary}`;

  if (ai) {
    try {
      // Build standard chat format
      const chatHistory = messages.map((m: any) => ({
        role: m.sender === "user" ? "user" : "model",
        parts: [{ text: m.text }],
      }));

      // In modern SDK, you query generateContent or chat. Since we have a stream of history, let's assemble it:
      const chat = ai.chats.create({
        model: "gemini-3.5-flash",
        config: {
          systemInstruction,
        },
      });

      // Populate history except the last message
      for (let i = 0; i < chatHistory.length - 1; i++) {
        // Unfortunately SDK's chat does not expose simple setters for history sometimes,
        // but we can send all contents manually or let the SDK handle messages in system prompt.
      }

      // To make it fully reliable, we send the conversation context in contents:
      const contents = [
        ...chatHistory.slice(0, -1),
        { role: "user", parts: [{ text: latestMessage }] },
      ];

      const response = await generateContentWithRetryAndFallback({
        contents,
        config: {
          systemInstruction,
        },
      });

      if (response && response.text) {
        return res.json({ text: response.text });
      }
    } catch (e) {
      console.error("Gemini chat endpoint failed, falling back:", e);
    }
  }

  // Responsive fallback logic for chat
  let responseText = "Understood. Our local analytical model recommends implementing ";
  const lowerMsg = latestMessage.toLowerCase();

  if (lowerMsg.includes("gdpr")) {
    responseText += "informed consent banners, transparent data-processing agreements (Article 28), and documenting your Data Protection Impact Assessment (DPIA) under GDPR requirements.";
  } else if (lowerMsg.includes("hipaa")) {
    responseText += "encrypted client logs, restricted multi-tenant vaults, and signed BAAs (Business Associate Agreements) to satisfy the HIPAA Security Rule.";
  } else if (lowerMsg.includes("encrypt") || lowerMsg.includes("security")) {
    responseText += "AES-256 standard volumes, TLS 1.3 protocols, and regular key rotations combined with access control policies.";
  } else {
    responseText += `rigorous data minimization, maintaining audit logs, and defining clear access boundaries for your project "${projectContext?.name || "Project Alpha"}" in accordance with scientific privacy standards.`;
  }

  return res.json({ text: responseText });
});

// ==========================================
// Vite Middleware & Static Assets Serving
// ==========================================
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server hosting DMP.Architect running on http://localhost:${PORT}`);
  });
}

startServer();
