import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell, Legend } from "recharts";
import * as XLSX from "xlsx";

const volumeData = [
  { name: "Week 1", value: 200 },
  { name: "Week 2", value: 250 },
  { name: "Week 3", value: 280 },
  { name: "Week 4", value: 320 },
];

const matchRateData = [
  { name: "Mon", rate: 90 },
  { name: "Tue", rate: 93 },
  { name: "Wed", rate: 87 },
  { name: "Thu", rate: 95 },
  { name: "Fri", rate: 92 },
  { name: "Sat", rate: 89 },
  { name: "Sun", rate: 94 },
];

const exceptionDist = [
  { name: "Extraction", value: 20, color: "hsl(0, 72%, 51%)" },
  { name: "Validation", value: 35, color: "hsl(38, 92%, 50%)" },
  { name: "Matching", value: 25, color: "hsl(221, 83%, 40%)" },
  { name: "AP Posting", value: 20, color: "hsl(262, 83%, 58%)" },
];

const processingTime = [
  { name: "Mon", duration: 200 },
  { name: "Tue", duration: 160 },
  { name: "Wed", duration: 120 },
  { name: "Thu", duration: 90 },
  { name: "Fri", duration: 70 },
  { name: "Sat", duration: 50 },
  { name: "Sun", duration: 40 },
];

interface InvoiceRow {
  invoiceNumber: string;
  supplierName: string;
  invoiceAmount: string;
  invoiceDate: string;
  poNumber: string;
  currency: string;
  remainingAmount: string;
  status: string;
  supplierSiteName: string;
  holdReason: string;
}

const API_URL = "http://localhost:8011/ebs/reporting_list_ebs";
const ITEMS_PER_PAGE = 5;

const formatDate = (value: string) => {
  if (!value) return "-";
  const normalized = value.split("T")[0];
  if (!normalized) return value;
  const [year, month, day] = normalized.split("-");
  if (!year || !month || !day) return value;
  return `${month}/${day}/${year}`;
};

const formatAmount = (value: string) => {
  if (!value) return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return value;
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric);
};

const ReportingPage = () => {
  const [rows, setRows] = useState<InvoiceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const fetchRows = async () => {
      try {
        setLoading(true);
        setError(null);

        const formData = new FormData();
        const role = localStorage.getItem("role") || "";
        formData.append("role", role);

        const response = await fetch(API_URL, {
          method: "POST",
          headers: {
            Accept: "application/json",
          },
          credentials: "omit",
          body: formData,
        });

        if (!response.ok) {
          throw new Error("Unable to load reporting data");
        }

        const payload = await response.json();
        const items = payload?.data?.OutputParameters?.X_INVOICE_TBL?.X_INVOICE_TBL_ITEM ?? [];

        const normalizedRows = (Array.isArray(items) ? items : []).map((item: Record<string, unknown>,index:number) => ({
          invoiceNumber: String(item.INVOICE_NUMBER ?? ""),
          supplierName: String(item.SUPPLIER_NAME ?? ""),
          invoiceAmount: String(item.INVOICE_AMOUNT ?? ""),
          invoiceDate: String(item.INVOICE_DATE ?? ""),
          poNumber: String(item.PO_NUMBER ?? ""),
          currency: String(item.CURRENCY_CODE ?? ""),
          remainingAmount: String(item.AMOUNT_REMAINING ?? ""),
          // status: Math.random() < 0.5 ? "Paid" : "Not Paid",
          status: index > 5 ? "Paid" : "Not Paid",
          supplierSiteName: String(item.SUPPLIER_SITE_NAME ?? ""),
          holdReason: String(item.HOLD_REASON ?? ""),
        }));

        setRows(normalizedRows);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unexpected error");
        setRows([]);
      } finally {
        setLoading(false);
      }
    };

    void fetchRows();
  }, []);

  useEffect(() => {
    setCurrentPage(1);
  }, [search]);

  const filteredRows = useMemo(() => {
    const searchValue = search.trim().toLowerCase();

    if (!searchValue) {
      return rows;
    }

    return rows.filter((row) => {
      const searchableValues = [
        row.invoiceNumber,
        row.supplierName,
        row.invoiceAmount,
        row.invoiceDate,
        row.poNumber,
        row.currency,
        row.remainingAmount,
        row.status,
        row.supplierSiteName,
        row.holdReason,
      ];

      return searchableValues.some((value) => value.toLowerCase().includes(searchValue));
    });
  }, [rows, search]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / ITEMS_PER_PAGE));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const startIndex = (safeCurrentPage - 1) * ITEMS_PER_PAGE;
  const pagedRows = filteredRows.slice(startIndex, startIndex + ITEMS_PER_PAGE);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const handleExportReport = () => {
    if (filteredRows.length === 0) {
      return;
    }

    const exportData = filteredRows.map((row) => ({
      "Invoice Number": row.invoiceNumber || "",
      "Supplier Name": row.supplierName || "",
      "Invoice Amount": row.invoiceAmount
        ? Number(row.invoiceAmount)
        : "",
      "Invoice Date": formatDate(row.invoiceDate),
      "PO Number": row.poNumber || "",
      "Currency": row.currency || "",
      "Remaining Amount": row.remainingAmount
        ? Number(row.remainingAmount)
        : "",
      "Status": row.status || "",
      "Supplier Site Name": row.supplierSiteName || "",
      "Hold Reason": row.holdReason || "",
    }));

    // Create worksheet
    const worksheet = XLSX.utils.json_to_sheet(exportData);

    // Create workbook
    const workbook = XLSX.utils.book_new();

    // Add worksheet to workbook
    XLSX.utils.book_append_sheet(workbook, worksheet, "Invoices");

    // Generate Excel file
    XLSX.writeFile(workbook, "Invoice_Report.xlsx");
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-foreground">Reporting</h2>
          <p className="text-sm text-muted-foreground">Invoice processing analytics and performance</p>
        </div>
        <div className="flex gap-2">
          <select className="text-sm border border-border rounded-md px-3 py-2 bg-background text-foreground">
            <option>Last 30 days</option>
            <option>Last 7 days</option>
            <option>Last 90 days</option>
          </select>
          <button className="px-4 py-2 text-xs font-medium border border-border rounded-lg text-foreground hover:bg-muted transition-colors" onClick={handleExportReport}>
            Export Report
          </button>
        </div>
      </div>

      <div className="bg-card rounded-lg border border-border p-5 shadow-sm mb-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Invoice Listing</h3>
            <p className="text-xs text-muted-foreground">Searchable invoice records with paginated results</p>
          </div>
          <div className="relative w-full md:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search invoice, supplier, PO..."
              className="pl-9"
            />
          </div>
        </div>

        {loading ? (
          <div className="py-8 text-center text-sm text-muted-foreground">Loading invoices...</div>
        ) : error ? (
          <div className="py-8 text-center text-sm text-destructive">{error}</div>
        ) : filteredRows.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">No invoices found.</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-3 font-medium">Invoice number</th>
                    <th className="px-3 py-3 font-medium">Supplier name</th>
                    <th className="px-3 py-3 font-medium">Invoice amount</th>
                    <th className="px-3 py-3 font-medium">Inv date</th>
                    <th className="px-3 py-3 font-medium">PO number</th>
                    <th className="px-3 py-3 font-medium">Currency</th>
                    <th className="px-3 py-3 font-medium">Remaining amount</th>
                    <th className="px-3 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedRows.map((row) => (
                    <tr key={`${row.invoiceNumber}-${row.poNumber}-${row.invoiceDate}`} className="border-b border-border/60 text-foreground hover:bg-muted/40">
                      <td className="px-3 py-3 font-medium">{row.invoiceNumber || "-"}</td>
                      <td className="px-3 py-3">{row.supplierName || "-"}</td>
                      <td className="px-3 py-3">{formatAmount(row.invoiceAmount)}</td>
                      <td className="px-3 py-3">{formatDate(row.invoiceDate)}</td>
                      <td className="px-3 py-3">{row.poNumber || "-"}</td>
                      <td className="px-3 py-3">{row.currency || "-"}</td>
                      <td className="px-3 py-3">{formatAmount(row.remainingAmount)}</td>
                      <td className="px-3 py-3">
                        <span
                          className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
                            row.status === "Paid"
                              ? "bg-green-100 text-green-800"
                              : "bg-yellow-100 text-yellow-800"
                          }`}
                        >
                          {row.status || "-"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
              <span>
                Showing {startIndex + 1}-{Math.min(startIndex + ITEMS_PER_PAGE, filteredRows.length)} of {filteredRows.length}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  disabled={safeCurrentPage === 1}
                  className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <span>Page {safeCurrentPage} of {totalPages}</span>
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                  disabled={safeCurrentPage === totalPages}
                  className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-1">Processing Volume</h3>
          <p className="text-xs text-muted-foreground mb-4">Weekly invoice counts</p>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={volumeData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 13%, 91%)" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <Tooltip />
              <Area type="monotone" dataKey="value" stroke="hsl(221, 83%, 40%)" fill="hsl(221, 83%, 40%)" fillOpacity={0.1} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-1">Success Rate Trend</h3>
          <p className="text-xs text-muted-foreground mb-4">Daily match success rate</p>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={matchRateData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 13%, 91%)" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <YAxis domain={[80, 100]} tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <Tooltip />
              <Area type="monotone" dataKey="rate" stroke="hsl(142, 71%, 45%)" fill="hsl(142, 71%, 45%)" fillOpacity={0.1} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-1">Exception Distribution</h3>
          <p className="text-xs text-muted-foreground mb-4">By failure stage</p>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={exceptionDist} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value">
                {exceptionDist.map((entry, i) => <Cell key={i} fill={entry.color} />)}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-card rounded-lg border border-border p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-1">Processing Time</h3>
          <p className="text-xs text-muted-foreground mb-4">Average processing duration (sec)</p>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={processingTime}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 13%, 91%)" />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <YAxis tick={{ fontSize: 12, fill: "hsl(220, 9%, 46%)" }} />
              <Tooltip />
              <Bar dataKey="duration" fill="hsl(221, 83%, 40%)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};

export default ReportingPage;
