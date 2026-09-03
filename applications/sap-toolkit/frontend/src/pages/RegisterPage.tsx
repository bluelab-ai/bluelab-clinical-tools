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
      navigate("/home");
    } catch (err: any) {
      setError(err.response?.data?.detail || "注册失败，请重试");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-sm border border-slate-200/70 p-8 mx-4">
        <div className="mb-8 text-center">
          <div className="flex items-center gap-3 justify-center">
            <div className="w-12 h-12 rounded-xl bg-emerald-600 text-white flex items-center justify-center">
              <UserPlus size={24} />
            </div>
            <div className="text-left">
              <h1 className="text-xl font-bold text-slate-900">注册账号</h1>
              <p className="text-xs text-slate-500">创建新的 SAP Toolkit 账号</p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">用户名</label>
            <input
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-emerald-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-100 transition-all font-medium outline-none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              placeholder="至少3个字符"
            />
          </div>
          <div>
            <label className="font-mono text-xs tracking-wider uppercase font-semibold text-slate-500">密码</label>
            <input
              type="password"
              className="w-full mt-1.5 bg-slate-50 border-transparent focus:border-emerald-500 focus:bg-white rounded-xl p-3.5 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-100 transition-all font-medium outline-none"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              placeholder="至少6个字符"
            />
          </div>
          {error && <p className="text-red-500 text-xs font-medium bg-red-50 px-3 py-2 rounded-lg">{error}</p>}
          <button
            type="submit"
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-xl shadow-sm active:scale-[0.98] transition-all cursor-pointer"
          >
            注册
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          已有账号？{" "}
          <Link to="/login" className="text-emerald-600 hover:text-emerald-700 font-semibold">登录</Link>
        </p>
      </div>
    </div>
  );
}
