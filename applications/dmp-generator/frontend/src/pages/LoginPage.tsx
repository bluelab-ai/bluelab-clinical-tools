import { useState, useEffect, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogIn } from "lucide-react";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    const msg = sessionStorage.getItem("auth_expired");
    if (msg) {
      setInfo(msg);
      sessionStorage.removeItem("auth_expired");
    }
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api.post("/auth/login", { username, password });
      login(res.data);
      navigate("/log-form");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Login failed");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center font-sans antialiased">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8 mx-4">
        <div className="mb-8 text-center">
          <img src="/logo.png" alt="Logo" className="h-16 mx-auto mb-4" />
          <div className="flex items-center gap-3 justify-center">
            <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center">
              <LogIn size={20} />
            </div>
            <div className="text-left">
              <h1 className="text-xl font-bold text-slate-900">DMP Platform</h1>
              <p className="text-xs text-slate-500">Sign in to your account</p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Username</label>
            <input
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              placeholder="Enter your username"
            />
          </div>
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Password</label>
            <input
              type="password"
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              placeholder="Enter your password"
            />
          </div>
          {info && <p className="text-amber-600 text-xs font-medium bg-amber-50 px-3 py-2 rounded-lg">{info}</p>}
          {error && <p className="text-red-500 text-xs font-medium bg-red-50 px-3 py-2 rounded-lg">{error}</p>}
          <button
            type="submit"
            className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer"
          >
            Login
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          No account? <Link to="/register" className="text-blue-600 hover:text-blue-700 font-semibold">Register</Link>
        </p>
      </div>
    </div>
  );
}
