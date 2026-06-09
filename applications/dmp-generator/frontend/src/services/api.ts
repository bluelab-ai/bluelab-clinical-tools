import axios from "axios";

let currentProject: string =
  localStorage.getItem("currentProject") || "default";

export function setApiProject(project: string) {
  currentProject = project || "default";
  localStorage.setItem("currentProject", currentProject);
}

export function getApiProject(): string {
  return currentProject;
}

const api = axios.create({
  baseURL: "/api",
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  config.headers["ngrok-skip-browser-warning"] = "true";

  // Prepend project to all URLs except auth and top-level routes
  const topLevel = ["/auth", "/projects", "/health"];
  if (config.url && !topLevel.some((p) => config.url!.startsWith(p))) {
    config.url = `/${currentProject}${config.url}`;
  }

  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      if (!window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/register")) {
        console.log("[api] 401 received, clearing auth state");
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        window.dispatchEvent(new Event("auth:logout"));
      }
    }
    return Promise.reject(error);
  }
);

export default api;
