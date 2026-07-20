import { useState, useEffect, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogIn, ShieldCheck } from "lucide-react";
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
      navigate("/home");
    } catch (err: any) {
      setError(err.response?.data?.detail || "登录失败，请重试");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center font-sans antialiased">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8 mx-4">
        {/* Logo & Title */}
        <div className="mb-8 text-center">
          <img src="/logo.png" alt="Logo" className="h-16 mx-auto mb-4" />
          <div className="flex items-center gap-3 justify-center">
            <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center">
              <ShieldCheck size={20} />
            </div>
            <div className="text-left">
              <h1 className="text-xl font-bold text-slate-900">TFL QC Platform</h1>
              <p className="text-xs text-slate-500">临床试验 TFL 质控平台</p>
            </div>
          </div>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">
              用户名
            </label>
            <input
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              placeholder="请输入用户名"
            />
          </div>
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">
              密码
            </label>
            <input
              type="password"
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-blue-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-blue-100 transition-all font-medium outline-none"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              placeholder="请输入密码"
            />
          </div>
          {info && (
            <p className="text-amber-600 text-xs font-medium bg-amber-50 px-3 py-2 rounded-lg">{info}</p>
          )}
          {error && (
            <p className="text-red-500 text-xs font-medium bg-red-50 px-3 py-2 rounded-lg">{error}</p>
          )}
          <button
            type="submit"
            className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer flex items-center justify-center gap-2"
          >
            <LogIn size={18} />
            登录
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          还没有账号？{" "}
          <Link to="/register" className="text-blue-600 hover:text-blue-700 font-semibold">
            注册
          </Link>
        </p>
      </div>
    </div>
  );
}
