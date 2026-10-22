import { Outlet, useNavigate } from "react-router-dom";
import ModuleSidebar from "@/components/ModuleSidebar";
import {
  Bell,
  User,
  Sparkles,
  LogOut,
} from "lucide-react";

interface ModuleLayoutProps {
  config: {
    name: string;
    shortName: string;
    subtitle: string;
    basePath: string;
    accentClass: string;
  };
  badges?: Record<string, { count: number; variant: string }>;
}

const ModuleLayout = ({ config, badges }: ModuleLayoutProps) => {
  const navigate = useNavigate();

  const username = localStorage.getItem("username") || "User";

  const handleLogout = () => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("app_user");
    localStorage.removeItem("username");

    navigate("/login");
  };

  return (
    <div className="min-h-screen flex bg-background">
      <ModuleSidebar config={config} badges={badges} />

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-border bg-card flex items-center justify-end px-6 shrink-0">
          <div className="flex items-center gap-3">
            
            {/* ennSight button */}
            <a
              href="http://10.4.1.204:8080/"
              target="_blank"
              rel="noopener noreferrer"
              title="ennSight"
              className="group px-3 py-1.5 rounded-lg bg-card hover:bg-muted transition-colors flex items-center"
            >
              <Sparkles className="w-5 h-5 mr-0 text-purple-700 hover:text-purple-800 transition-colors group-hover:scale-110" />
            </a>

            {/* Notifications */}
            <button className="p-2 rounded-lg hover:bg-muted transition-colors text-muted-foreground">
              <Bell className="w-4 h-4" />
            </button>

            {/* User pill */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-border bg-card cursor-pointer hover:bg-muted transition-colors">
              <User className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm font-medium text-foreground">
                {username}
              </span>
            </div>

            {/* Logout button */}
            <button
              onClick={handleLogout}
              title="Logout"
              className="p-2 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </header>

        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default ModuleLayout;