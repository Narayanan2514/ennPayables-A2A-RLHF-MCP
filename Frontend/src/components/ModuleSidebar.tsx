import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, FileStack, CheckSquare, AlertTriangle, BarChart3, Settings, HelpCircle, ArrowLeft, LucideIcon } from "lucide-react";

interface ModuleConfig {
  name: string;
  shortName: string;
  subtitle: string;
  basePath: string;
  accentClass: string;
}

interface NavItem {
  label: string;
  icon: LucideIcon;
  subpath: string;
  children?: NavItem[];
}

const mainNav: NavItem[] = [
  { label: "Dashboard", icon: LayoutDashboard, subpath: "" },
  {
    label: "Collection",
    icon: FileStack,
    subpath: "/inbox",
    children: [
      { label: "Processed", icon: CheckSquare, subpath: "/processed" },
      { label: "Exceptions", icon: AlertTriangle, subpath: "/exceptions" },
    ],
  },
  { label: "Reporting", icon: BarChart3, subpath: "/reporting" },
];

const systemNav = [
  { label: "Settings", icon: Settings, subpath: "/settings" },
  { label: "Help", icon: HelpCircle, subpath: "/help" },
];

interface ModuleSidebarProps {
  config: ModuleConfig;
  badges?: Record<string, { count: number; variant: string }>;
}

const ModuleSidebar = ({ config, badges = {} }: ModuleSidebarProps) => {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <aside className="w-56 bg-sidebar text-sidebar-foreground flex flex-col shrink-0">
      <div className="p-5">
        {/* <button
          onClick={() => navigate("/ennPayables/EBS")}
          className="flex items-center gap-1.5 text-sidebar-foreground/50 hover:text-sidebar-foreground text-xs mb-4 transition-colors"
        >
          <ArrowLeft className="w-3 h-3" />
          Dashboard
        </button> */}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-sidebar-primary flex items-center justify-center">
            <span className="text-side
            bar-primary-foreground font-bold text-xs">{config.shortName}</span>
          </div>
          <div>
            <p className="font-semibold text-sm text-sidebar-foreground leading-none">{config.name}</p>
            <p className="text-[10px] text-sidebar-foreground/60">{config.subtitle}</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 space-y-1">
        <p className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 px-3 mb-2">Main</p>
        {mainNav.map(item => {
          const fullPath = config.basePath + item.subpath;
          const isActive = item.subpath === ""
            ? location.pathname === config.basePath
            : location.pathname === fullPath;

          return (
            <div key={fullPath}>
              <NavLink
                to={fullPath}
                end={item.subpath === ""}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${isActive ? "bg-sidebar-primary text-sidebar-primary-foreground" : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"}`}
              >
                <item.icon className="w-4 h-4" />
                <span>{item.label}</span>
              </NavLink>

              {/* Render children with indentation */}
              {item.children && (
                <div className="ml-3 space-y-1">
                  {item.children.map(child => {
                    const childFullPath = config.basePath + child.subpath;
                    const childIsActive = location.pathname === childFullPath;
                    return (
                      <NavLink
                        key={childFullPath}
                        to={childFullPath}
                        className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${childIsActive ? "bg-sidebar-primary text-sidebar-primary-foreground" : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"}`}
                      >
                        <child.icon className="w-4 h-4" />
                        <span>{child.label}</span>
                      </NavLink>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        <div className="pt-6">
          <p className="text-[10px] uppercase tracking-wider text-sidebar-foreground/40 px-3 mb-2">System</p>
          {systemNav.map(item => {
            const fullPath = config.basePath + item.subpath;
            const isActive = location.pathname === fullPath;
            return (
              <NavLink
                key={fullPath}
                to={fullPath}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${isActive ? "bg-sidebar-primary text-sidebar-primary-foreground" : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"}`}
              >
                <item.icon className="w-4 h-4" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </div>
      </nav>
    </aside>
  );
};

export default ModuleSidebar;
