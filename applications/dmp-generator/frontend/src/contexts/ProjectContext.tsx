import { createContext, useState, useMemo, ReactNode, useCallback } from "react";
import { setApiProject, getApiProject } from "../services/api";

interface ProjectContextType {
  project: string;
  setProject: (name: string) => void;
}

export const ProjectContext = createContext<ProjectContextType>({
  project: "default",
  setProject: () => {},
});

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [project, setProjectState] = useState(getApiProject);

  const setProject = useCallback((name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setApiProject(trimmed);
    setProjectState(trimmed);
  }, []);

  const value = useMemo(() => ({ project, setProject }), [project, setProject]);

  return (
    <ProjectContext.Provider value={value}>
      {children}
    </ProjectContext.Provider>
  );
}
