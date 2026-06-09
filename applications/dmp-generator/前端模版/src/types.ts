export interface DMPProject {
  id: string;
  name: string;
  leadInvestigator: string;
  grantId: string;
  dataSources: string[];
  customDataSourcesDesc?: string;
  primaryObjective: string;
  complianceRequirements: string[];
  securityChecks: {
    encryptionAtRest: boolean;
    anonymization: boolean;
    rbac: boolean;
    auditLogging: boolean;
    tlsInTransit: boolean;
  };
  retentionYears: number;
  retentionStrategy: 'delete' | 'archive' | 'transfer' | string;
  createdAt: string;
  updatedAt: string;
  status: 'draft' | 'analyzing' | 'completed';
  generatedPlan?: string;
  aiComplianceWarnings?: string[];
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
}
