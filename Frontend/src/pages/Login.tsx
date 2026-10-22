import { useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, LogIn, Loader2 } from "lucide-react";
import { sha256 } from "js-sha256";

const Login = () => {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!email || !password) {
      setError("Please enter both email and password.");
      return;
    }

    setIsLoading(true);

    try {
      const response = await fetch("http://localhost:8011/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password: sha256(password) }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.message || "Invalid credentials. Please try again.");
      }

      const data = await response.json();

      // Store role and user info from API response
      if (data.role) {
        localStorage.setItem("app_user", data.erp);
      }
      if (data.token) {
        localStorage.setItem("auth_token", data.token);
      }
      if (data.name) {
        localStorage.setItem("username", data.name);
      }
      if (data.role) {
        localStorage.setItem("role", data.role);
      }

      navigate("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
      {/* Subtle background grid / glow effect matching the app's navy palette */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 60% at 50% -10%, rgba(18,37,80,0.35) 0%, transparent 70%), radial-gradient(ellipse 60% 40% at 80% 100%, rgba(18,37,80,0.2) 0%, transparent 70%)",
        }}
      />
      {/* Faint dot-grid texture */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage:
            "radial-gradient(circle, #122550 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />

      <motion.div
        initial={{ opacity: 0, y: 32 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, ease: "easeOut" }}
        className="relative z-10 w-full max-w-md mx-4"
      >
        {/* Card */}
        <div className="bg-card border border-border rounded-2xl shadow-2xl overflow-hidden">
          {/* Top accent stripe */}
          <div className="h-1.5 w-full bg-gradient-to-r from-[#122550] via-[#1e3a6e] to-[#122550]" />

          <div className="px-10 pt-10 pb-10">
            {/* Logo / Branding */}
            <motion.div
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.1 }}
              className="flex flex-col items-center mb-9"
            >
              {/* Icon badge */}
              <div className="w-14 h-14 rounded-2xl bg-[#122550] flex items-center justify-center mb-4 shadow-lg">
                <span className="text-white font-bold text-xl tracking-tight select-none">eP</span>
              </div>
              <h1 className="text-2xl font-bold text-foreground tracking-tight">ennPayables</h1>
              <p className="text-xs text-muted-foreground mt-1 uppercase tracking-widest">
                AP Invoice Automation · Oracle EBS
              </p>
            </motion.div>

            {/* Form */}
            <motion.form
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.2 }}
              onSubmit={handleLogin}
              className="space-y-5"
            >
              {/* Email */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Email
                </label>
                <input
                  type="text"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Enter your email"
                  autoComplete="email"
                  className="w-full px-4 py-2.5 rounded-lg border border-border bg-muted/40 text-foreground text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-[#122550]/40 focus:border-[#122550]/60 transition-all"
                />
              </div>

              {/* Password */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter your password"
                    autoComplete="current-password"
                    className="w-full px-4 py-2.5 pr-11 rounded-lg border border-border bg-muted/40 text-foreground text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-[#122550]/40 focus:border-[#122550]/60 transition-all"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Error message */}
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="px-4 py-2.5 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs"
                >
                  {error}
                </motion.div>
              )}

              {/* Forgot password */}
              <div className="flex justify-end">
                {/* <button
                  type="button"
                  className="text-xs text-muted-foreground hover:text-[#122550] transition-colors"
                >
                  Forgot password?
                </button> */}
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-lg bg-[#122550] text-white text-sm font-medium hover:bg-[#122550]/90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  <>
                    <LogIn className="w-4 h-4" />
                    Sign In
                  </>
                )}
              </button>
            </motion.form>
          </div>

          {/* Footer */}
          {/* <div className="px-10 pb-6 text-center">
            <p className="text-[10px] text-muted-foreground/60">
              &copy; {new Date().getFullYear()} ennVault · All rights reserved
            </p>
          </div> */}
        </div>

        {/* Module pills — decorative context */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="flex justify-center gap-3 mt-6"
        >
          {/* {["ennOrder", "ennPayables", "ennCash"].map((name) => (
            <span
              key={name}
              className="text-[10px] px-3 py-1 rounded-full border border-border bg-card/60 text-muted-foreground uppercase tracking-wider"
            >
              {name}
            </span>
          ))} */}
        </motion.div>
      </motion.div>
    </div>
  );
};

export default Login;