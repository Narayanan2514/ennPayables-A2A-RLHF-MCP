import { ReactNode } from "react";

interface StatsCardProps {
  title: string;
  value: string | number;
  icon: ReactNode;
  variant?: "blue" | "green" | "orange" | "red";
  subtitle?: string;
}

const variantClasses = {
  blue: "bg-primary/10",
  green: "bg-success/10",
  orange: "bg-warning/10",
  red: "bg-destructive/10",
};

const iconVariantClasses = {
  blue: "text-primary",
  green: "text-success",
  orange: "text-warning",
  red: "text-destructive",
};

const StatsCard = ({ title, value, icon, variant = "blue", subtitle }: StatsCardProps) => {
  return (
    <div className="bg-card rounded-lg border border-border p-5 flex items-center gap-4 shadow-sm">
      <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${variantClasses[variant]}`}>
        <span className={iconVariantClasses[variant]}>{icon}</span>
      </div>
      <div>
        <p className="text-sm text-muted-foreground">{title}</p>
        <p className="text-2xl font-bold text-foreground">{value}</p>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </div>
    </div>
  );
};

export default StatsCard;
