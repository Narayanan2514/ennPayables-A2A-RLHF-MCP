import { useState, useEffect } from "react";
import { FileSearch, CheckCircle, AlertTriangle, X } from "lucide-react";
import StatsCard from "@/components/StatsCard";
import { Search, Clock, FileText } from "lucide-react";

const API_URL = "http://localhost:8011/ebs/processed_ebs";

interface LineItem {
  id: number;
  total: number;
  remark: string;
  automation_flag: number;
  order_number: string;
  item_name: string;
  item_desc: string;
  item_number: string;
}

interface ProcessedInvoice {
  id: number;
  src_id: string;
  company: string;
  supplier_number: string;
  invoice_number: string;
  supplier_name: string;
  invoice_date: string;
  gl_date: string;
  business_unit: string;
  batch_number: string;
  created_at: string;
  line_items: LineItem[];
}

interface ApiResponse {
  InvoiceReceived: number;
  Processed: number;
  Exception: number;
  Avgtime: string;
  invoice_list: ProcessedInvoice[];
}

const ITEMS_PER_PAGE = 5;

const ProcessedPage = () => {
  const [apiData, setApiData] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedInvoice, setSelectedInvoice] = useState<ProcessedInvoice | null>(null);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const fetchData = async () => {
      try {
        if (!apiData) setLoading(true);

        const response = await fetch(API_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
          },
          credentials: "omit",
          body: JSON.stringify({}),
        });

        if (!response.ok) throw new Error("Failed to fetch data");
        const data: ApiResponse = await response.json();

        setApiData(prev => {
          if (!prev) return data;
          const existingIds = new Set(prev.invoice_list.map(inv => inv.id));
          const mergedInvoices = [
            ...prev.invoice_list,
            ...data.invoice_list.filter(inv => !existingIds.has(inv.id)),
          ];
          return {
            ...data,
            invoice_list: mergedInvoices,
          };
        });

        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error fetching data");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  const invoices = apiData?.invoice_list || [];

  const filteredInvoices = invoices.filter((inv) =>
    inv.src_id.toLowerCase().includes(search.toLowerCase()) ||
    inv.invoice_number.toLowerCase().includes(search.toLowerCase()) ||
    inv.supplier_name.toLowerCase().includes(search.toLowerCase())
  );

  const totalPages = Math.ceil(filteredInvoices.length / ITEMS_PER_PAGE);

  const paginatedInvoices = filteredInvoices.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-foreground">Processed</h2>
          <p className="text-sm text-muted-foreground">Successfully matched and posted to Accounts Payable</p>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          Error: {error}
        </div>
      )}

      {/* KPI cards removed as requested */}

      <div className="bg-card rounded-lg border border-border shadow-sm overflow-x-auto mt-0">
        <div className="flex justify-end py-4 mr-6 ">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search invoices..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setCurrentPage(1);
              }}
              className="pl-9 pr-4 py-2 text-sm border border-border rounded-md bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50 h-1">
              <th className="text-left p-4 font-medium text-muted-foreground">Reference Id</th>
              <th className="text-left p-4 font-medium text-muted-foreground">Invoice Number</th>
              <th className="text-left p-4 font-medium text-muted-foreground">Supplier Name</th>
              <th className="text-left p-4 font-medium text-muted-foreground">LogTime</th>
              <th className="text-left p-4 font-medium text-muted-foreground">View Details</th>
            </tr>
          </thead>

          <tbody>
            {loading && !apiData ? (
              <tr>
                <td colSpan={5} className="p-4 text-center text-muted-foreground">
                  Loading invoices...
                </td>
              </tr>
            ) : paginatedInvoices.length === 0 ? (
              <tr>
                <td colSpan={5} className="p-4 text-center text-muted-foreground">
                  No invoices found
                </td>
              </tr>
            ) : (
              paginatedInvoices.map((inv) => (
                <tr key={inv.id} className="border-b border-border hover:bg-muted/30 transition-colors">
                  <td className="p-4 font-medium text-foreground">{inv.src_id}</td>
                  <td className="p-4 text-foreground">{inv.invoice_number}</td>
                  <td className="p-4 text-foreground">{inv.supplier_name}</td>
                  {/* <td className="p-4 text-muted-foreground">{new Date(inv.invoice_date).toLocaleString()}</td> */}
                  <td className="p-4 text-muted-foreground">
                    {new Date(`${inv.invoice_date}Z`).toLocaleString("en-IN", {
                      timeZone: "Asia/Kolkata",
                    })}
                  </td>
                  <td className="p-4">
                    <FileSearch className="w-5 h-5 text-primary cursor-pointer hover:text-primary/80" onClick={() => setSelectedInvoice(inv)} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination - RIGHT */}
        <div className="p-4 flex justify-end items-center gap-2">
          <button
            className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
            disabled={currentPage === 1}
            onClick={() => setCurrentPage(prev => prev - 1)}
          >
            Prev
          </button>

          <span className="text-xs text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>

          <button
            className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
            disabled={currentPage === totalPages}
            onClick={() => setCurrentPage(prev => prev + 1)}
          >
            Next
          </button>
        </div>
      </div>

      {selectedInvoice && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 overflow-y-auto" onClick={() => setSelectedInvoice(null)}>
          <div className="bg-white rounded-lg shadow-lg w-full max-w-3xl my-8 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-foreground">Invoice Details</h2>
              <button
                onClick={() => setSelectedInvoice(null)}
                className="text-gray-500 hover:text-gray-700 text-2xl leading-none"
              >
                <X size={24} />
              </button>
            </div>

            {/* Invoice Header Info */}
            <div className="grid grid-cols-2 gap-4 mb-6 pb-6 border-b border-border">
              <div className="space-y-3">
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Company</p>
                  <p className="text-sm font-medium text-foreground">{selectedInvoice.supplier_name}</p>
                </div>
                {/* <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Supplier Number</p>
                  <p className="text-sm font-medium text-foreground">{selectedInvoice.supplier_number}</p>
                </div> */}
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Invoice Number</p>
                  <p className="text-sm font-medium text-foreground">{selectedInvoice.invoice_number}</p>
                </div>
              </div>
              <div className="space-y-3">
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Invoice Date</p>
                  <p className="text-sm font-medium text-foreground">{new Date(selectedInvoice.invoice_date).toLocaleDateString()}</p>
                </div>
                {/* <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">GL Date</p>
                  <p className="text-sm font-medium text-foreground">{new Date(selectedInvoice.gl_date).toLocaleDateString()}</p>
                </div> */}
                {/* <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Source ID</p>
                  <p className="text-sm font-medium text-foreground">{selectedInvoice.src_id}</p>
                </div> */}
              </div>
            </div>

            {/* Line Items Table */}
            <div>
              <h3 className="text-lg font-semibold text-foreground mb-4">Line Items</h3>
              <div className="overflow-x-auto border border-border rounded-lg">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-muted/50 border-b border-border">
                      {/* <th className="text-left p-3 font-medium text-muted-foreground">Item ID</th> */}
                      <th className="text-left p-3 font-medium text-muted-foreground">Gross Amount</th>
                      {/* <th className="text-left p-3 font-medium text-muted-foreground">Remark</th> */}
                      {/* <th className="text-left p-3 font-medium text-muted-foreground">Order Number</th> */}
                      <th className="text-left p-3 font-medium text-muted-foreground">Item Name</th>
                      <th className="text-left p-3 font-medium text-muted-foreground">Item Description</th>
                      {/* <th className="text-left p-3 font-medium text-muted-foreground">Item Number</th> */}
                    </tr>
                  </thead>
                  <tbody>
                    {selectedInvoice.line_items.map((item) => (
                      <tr key={item.id} className="border-b border-border hover:bg-muted/20">
                        {/* <td className="p-3 font-medium text-foreground">{item.id}</td> */}
                        <td className="p-3 text-foreground">${item.total.toFixed(2)}</td>
                        {/* <td className="p-3 text-foreground">{item.remark}</td> */}
                        {/* <td className="p-3 text-foreground">{item.order_number}</td> */}
                        <td className="p-3 text-foreground">{item.item_name}</td>
                        <td className="p-3 text-foreground">{item.item_desc}</td>
                        {/* <td className="p-3 text-foreground">{item.item_number}</td> */}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProcessedPage;