import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { UserPlus } from "lucide-react";
import api from "../services/api";
import { useAuth } from "../hooks/useAuth";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api.post("/auth/register", { username, password });
      login(res.data);
      navigate("/log-form");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Registration failed");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center font-sans antialiased">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8 mx-4">
        <div className="mb-8 text-center">
          <img src="/logo.png" alt="Logo" className="h-16 mx-auto mb-4" />
          <div className="flex items-center gap-3 justify-center">
            <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center">
              <UserPlus size={20} />
            </div>
            <div className="text-left">
              <h1 className="text-xl font-bold text-slate-900">Create Account</h1>
              <p className="text-xs text-slate-500">Register for DMP Platform</p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Username (min 3 chars)</label>
            <input
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              placeholder="Choose a username"
            />
          </div>
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">Password (min 6 chars)</label>
            <input
              type="password"
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              placeholder="Choose a password"
            />
          </div>
          {error && <p className="text-red-500 text-xs font-medium bg-red-50 px-3 py-2 rounded-lg">{error}</p>}
          <button
            type="submit"
            className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer"
          >
            Register
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          Already have an account? <Link to="/login" className="text-blue-600 hover:text-blue-700 font-semibold">Login</Link>
        </p>
      </div>
    </div>
  );
}
