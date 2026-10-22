
// import StatsCard from "@/components/StatsCard";
// import { FileText, CheckCircle, AlertTriangle, DollarSign } from "lucide-react";
// import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
// import React, { useEffect, useState } from "react";

// const API_URL = "http://localhost:8011/ennpayables/dashboard";

// const InvoiceDashboard = () => {
//   const [kpi, setKpi] = useState({ received_30: 0, processed_30: 0, failed_30: 0 });
//   const [chartData, setChartData] = useState([]);
//   const [recentActivity, setRecentActivity] = useState([]);
//   const [loading, setLoading] = useState(true);
//   const [lastUpdated, setLastUpdated] = useState(new Date());

//   useEffect(() => {
//     const fetchData = async () => {
//       try {
//         const res = await fetch(API_URL, { method: "POST" });
//         const data = await res.json();
//         setKpi(data.kpi || { received_30: 0, processed_30: 0, failed_30: 0 });
//         // Prepare chart data for recharts
//         if (data.process_chart) {
//           const x = data.process_chart.x || [];
//           const received = data.process_chart.received || [];
//           const processed = data.process_chart.processed || [];
//           const failed = data.process_chart.failed || [];
//           const chartArr = x.map((name, i) => ({
//             name,
//             received: received[i] || 0,
//             processed: processed[i] || 0,
//             failed: failed[i] || 0,
//           }));
//           setChartData(chartArr);
//         }
//         // Prepare recent activity
//         if (data.recent_act) {
//           setRecentActivity(data.recent_act);
//         }
//         setLastUpdated(new Date());
//       } catch (e) {
//         // fallback to empty
//         setKpi({ received_30: 0, processed_30: 0, failed_30: 0 });
//         setChartData([]);
//         setRecentActivity([]);
//       } finally {
//         setLoading(false);
//       }
//     };
    
//     fetchData();
//     const interval = setInterval(fetchData, 5000);
//     return () => clearInterval(interval);
//   }, []);

//   // Map activity to icon and color
//   const getActivityIcon = (title) => {
//     if (title === "New Invoice Received") return { icon: FileText, color: "text-primary" };
//     if (title === "Invoice Failed") return { icon: AlertTriangle, color: "text-destructive" };
//     if (title === "Invoice Posted") return { icon: CheckCircle, color: "text-success" };
//     return { icon: FileText, color: "text-muted-foreground" };
//   };

//   return (
//     <div>
//       <div className="flex items-center justify-between mb-6">
//         <div>
//           <h2 className="text-xl font-bold text-foreground">Dashboard</h2>
//           <p className="text-sm text-muted-foreground">Real-time overview of invoice processing automation</p>
//         </div>
//         <p className="text-xs text-muted-foreground">Last updated: {lastUpdated.toLocaleTimeString()}</p>
//       </div>

//       <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
//         <StatsCard title="Invoices Received" value={loading ? "-" : kpi.received_30} icon={<FileText className="w-5 h-5" />} variant="blue" subtitle="Last 30 days" />
//         <StatsCard title="Processed" value={loading ? "-" : kpi.processed_30} icon={<CheckCircle className="w-5 h-5" />} variant="green" subtitle="Last 30 days" />
//         <StatsCard title="Exceptions" value={loading ? "-" : kpi.failed_30} icon={<AlertTriangle className="w-5 h-5" />} variant="orange" subtitle="Last 30 days" />
//         <StatsCard title="AP Amount Due" value="$4.2M" icon={<DollarSign className="w-5 h-5" />} variant="blue" subtitle=" " />
//       </div>

//       <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
//         <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
//           <div className="flex items-center justify-between mb-4">
//             <h3 className="text-sm font-semibold text-foreground">Processing Volume</h3>
//             <span className="text-xs text-muted-foreground">Last 7 days</span>
//           </div>
//           <ResponsiveContainer width="100%" height={220}>
//             <LineChart data={chartData}>
//               <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 13%, 91%)" />
//               <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
//               <YAxis tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
//               <Tooltip />
//               <Legend />
//               <Line type="monotone" dataKey="received" stroke="hsl(221, 83%, 40%)" strokeWidth={2} dot={false} name="Received" />
//               <Line type="monotone" dataKey="processed" stroke="hsl(142, 71%, 45%)" strokeWidth={2} dot={false} name="Processed" />
//               <Line type="monotone" dataKey="failed" stroke="hsl(0, 72%, 51%)" strokeWidth={2} dot={false} name="Failed" />
//             </LineChart>
//           </ResponsiveContainer>
//         </div>

//         <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
//           <div className="flex items-center justify-between mb-4">
//             <h3 className="text-sm font-semibold text-foreground">Recent Activity</h3>
//           </div>
//           <div className="space-y-3">
//             {recentActivity.map((item, i) => {
//               const { icon: Icon, color } = getActivityIcon(item.title);
//               return (
//                 <div key={i} className="flex items-start gap-3">
//                   <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${color}`} />
//                   <div className="flex-1 min-w-0">
//                     <p className="text-sm font-medium text-foreground">{item.title}</p>
//                     <p className="text-xs text-muted-foreground truncate">{item.subtitle}</p>
//                   </div>
//                   <span className="text-[10px] text-muted-foreground whitespace-nowrap">{item.time}</span>
//                 </div>
//               );
//             })}
//           </div>
//         </div>
//       </div>
//     </div>
//   );
// };

// export default InvoiceDashboard;



import StatsCard from "@/components/StatsCard";
import { FileText, CheckCircle, AlertTriangle, DollarSign, Clock, Mail } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import React, { useEffect, useState } from "react";

const API_URL = "http://localhost:8011/ebs/dashboard_ebs";

const InvoiceDashboard = () => {
  const [kpi, setKpi] = useState({ received_30: 0, processed_30: 0, failed_30: 0 });
  const [chartData, setChartData] = useState([]);
  const [recentActivity, setRecentActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(API_URL, { method: "POST" });
        const data = await res.json();
        setKpi(data.kpi || { received_30: 0, processed_30: 0, failed_30: 0 });
        // Prepare chart data for recharts
        if (data.process_chart) {
          const x = data.process_chart.x || [];
          const received = data.process_chart.received || [];
          const processed = data.process_chart.processed || [];
          const failed = data.process_chart.failed || [];
          const chartArr = x.map((name, i) => ({
            name,
            received: received[i] || 0,
            processed: processed[i] || 0,
            failed: failed[i] || 0,
          }));
          setChartData(chartArr);
        }
        // Prepare recent activity
        if (data.recent_act) {
          setRecentActivity(data.recent_act);
        }
        setLastUpdated(new Date());
      } catch (e) {
        // fallback to empty
        setKpi({ received_30: 0, processed_30: 0, failed_30: 0 });
        setChartData([]);
        setRecentActivity([]);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  // Map activity to icon and color
  const getActivityIcon = (title) => {
    if (title === "New Invoice Received") return { icon: FileText, color: "text-primary" };
    if (title === "Invoice Failed") return { icon: AlertTriangle, color: "text-destructive" };
    if (title === "Invoice Posted") return { icon: CheckCircle, color: "text-success" };
    if (title === "Admin Approved") return { icon: CheckCircle, color: "text-success" };

    if (title === "Duplicate Invoice Archived") return { icon: CheckCircle, color: "text-success" };
    if (title === "Email Notified") return { icon: Mail, color: "text-primary" };

    if (title === "Invoice OnHold") return { icon: Clock, color: "text-yellow-500" };
    return { icon: FileText, color: "text-muted-foreground" };
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-foreground">Dashboard</h2>
          <p className="text-sm text-muted-foreground">Real-time overview of invoice processing automation</p>
        </div>
        <p className="text-xs text-muted-foreground">Last updated: {lastUpdated.toLocaleTimeString()}</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatsCard title="Invoices Received" value={loading ? "-" : kpi.received_30} icon={<FileText className="w-5 h-5" />} variant="blue" subtitle="Last 30 days" />
        <StatsCard title="Processed" value={loading ? "-" : kpi.processed_30} icon={<CheckCircle className="w-5 h-5" />} variant="green" subtitle="Last 30 days" />
        <StatsCard title="Exceptions" value={loading ? "-" : kpi.failed_30} icon={<AlertTriangle className="w-5 h-5" />} variant="orange" subtitle="Last 30 days" />
        <StatsCard title="AP Amount Due" value="$117k" icon={<DollarSign className="w-5 h-5" />} variant="blue" subtitle=" " />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-foreground">Processing Volume</h3>
            <span className="text-xs text-muted-foreground">Last 7 days</span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 13%, 91%)" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="received" stroke="hsl(221, 83%, 40%)" strokeWidth={2} dot={false} name="Received" />
              <Line type="monotone" dataKey="processed" stroke="hsl(142, 71%, 45%)" strokeWidth={2} dot={false} name="Processed" />
              <Line type="monotone" dataKey="failed" stroke="hsl(0, 72%, 51%)" strokeWidth={2} dot={false} name="Failed" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-foreground">Recent Activity</h3>
          </div>
          <div className="space-y-3">
            {recentActivity.map((item, i) => {
              const { icon: Icon, color } = getActivityIcon(item.title);
              return (
                <div key={i} className="flex items-start gap-3">
                  <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${color}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <p className="text-xs text-muted-foreground truncate">{item.subtitle}</p>
                  </div>
                  <span className="text-[10px] text-muted-foreground whitespace-nowrap">{item.time}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default InvoiceDashboard;
