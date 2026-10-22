import { useState, useEffect, useRef } from "react";
import {
  Eye,
  Search,
  CheckCircle,
  AlertTriangle,
  FileText,
  Clock,
} from "lucide-react";

import StatsCard from "@/components/StatsCard";

const ITEMS_PER_PAGE = 5;

const API_URL = "http://localhost:8011/ebs/collections_ebs";
const PDF_API_URL =
  "http://localhost:8011/ebs/fetch-invoice-file-ebs";

interface Invoice {
  id: number;
  src_id: string | null;
  src: string;
  doc_type: string;
  atch_nm: string;
  archive: string;
  channel: string;
  folder_path: string;
  timestamp: string;
  from_email: string | null;
  subject: string | null;
  body: string | null;
}

interface ApiResponse {
  erp: string;
  InvoiceReceived: number;
  Processed: number;
  Exception: number;
  Avgtime: string;
  invoice_list: Invoice[];
}

const InboxPage = () => {
  const [apiData, setApiData] = useState<ApiResponse | null>(null);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);

  const [currentPage, setCurrentPage] = useState(1);

  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  const [pdfLoading, setPdfLoading] = useState(false);

  const [selectedSrcId, setSelectedSrcId] = useState<string | null>(null);

  const [searchTerm, setSearchTerm] = useState("");

  const [expandedDescriptions, setExpandedDescriptions] = useState<
    Set<number>
  >(new Set());

  const [truncatedItems, setTruncatedItems] = useState<Set<number>>(
    new Set()
  );

  const descriptionRefs = useRef<Map<number, HTMLDivElement>>(
    new Map()
  );

  useEffect(() => {
    const checkTruncation = () => {
      descriptionRefs.current.forEach((element, id) => {
        if (!expandedDescriptions.has(id)) {
          const isTruncated =
            element.scrollHeight > element.clientHeight;

          setTruncatedItems((prev) => {
            const newSet = new Set(prev);

            if (isTruncated) {
              newSet.add(id);
            } else {
              newSet.delete(id);
            }

            return newSet;
          });
        }
      });
    };

    checkTruncation();

    window.addEventListener("resize", checkTruncation);

    return () =>
      window.removeEventListener("resize", checkTruncation);
  }, [apiData, expandedDescriptions]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        if (!apiData) setLoading(true);

        const response = await fetch(API_URL, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          credentials: "omit",
          body: JSON.stringify({}),
        });

        if (!response.ok) {
          throw new Error("Failed to fetch data");
        }

        const data: ApiResponse = await response.json();

        setApiData((prev) => {
          if (!prev) return data;

          const existingIds = new Set(
            prev.invoice_list.map((inv) => inv.id)
          );

          const mergedInvoices = [
            ...data.invoice_list.filter(
              (inv) => !existingIds.has(inv.id)
            ),
            ...prev.invoice_list,
          ];

          return {
            ...data,
            invoice_list: mergedInvoices,
          };
        });

        setError(null);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Error fetching data"
        );
      } finally {
        setLoading(false);
      }
    };

    fetchData();

    const interval = setInterval(fetchData, 2000);

    return () => clearInterval(interval);
  }, []);

  const handleViewPdf = async (srcId: string | null) => {
    if (!srcId) {
      alert("Source ID not available");
      return;
    }

    setPdfLoading(true);

    try {
      const formData = new FormData();

      formData.append("src_id", srcId);

      const response = await fetch(PDF_API_URL, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error("Failed to fetch PDF");
      }

      const blob = await response.blob();

      const url = window.URL.createObjectURL(blob);

      setPdfUrl(url);
    } catch (err) {
      alert(
        err instanceof Error
          ? err.message
          : "Error loading PDF"
      );
    } finally {
      setPdfLoading(false);
    }
  };

  const invoices = apiData?.invoice_list || [];

  const filteredInvoices = invoices.filter((inv) => {
    const term = searchTerm.toLowerCase();

    return (
      (inv.src_id || "").toLowerCase().includes(term) ||
      (inv.from_email || "")
        .toLowerCase()
        .includes(term) ||
      (inv.subject || "").toLowerCase().includes(term) ||
      (inv.body || "").toLowerCase().includes(term) ||
      (inv.channel || "").toLowerCase().includes(term) ||
      (inv.atch_nm || "").toLowerCase().includes(term)
    );
  });

  const totalPages = Math.max(
    1,
    Math.ceil(filteredInvoices.length / ITEMS_PER_PAGE)
  );

  const paginatedInvoices = filteredInvoices.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  // if (loading && !apiData) {
  //   return (
  //     <div className="flex items-center justify-center h-[400px]">
  //       Loading...
  //     </div>
  //   );
  // }

  return (
    <div>
      {/* Header */}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-foreground">
            Collection
          </h2>

          {/* <p className="text-sm text-muted-foreground">
            ERP: {apiData?.erp || "EBS"}
          </p> */}
        </div>
      </div>

      {/* Error */}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          Error: {error}
        </div>
      )}

      {/* Stats */}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatsCard
          title="Invoices Received"
          value={
            apiData?.InvoiceReceived?.toString() || "0"
          }
          icon={<FileText className="w-5 h-5" />}
          variant="blue"
        />

        <StatsCard
          title="Processed"
          value={apiData?.Processed?.toString() || "0"}
          icon={<CheckCircle className="w-5 h-5" />}
          variant="green"
        />

        <StatsCard
          title="Exceptions"
          value={apiData?.Exception?.toString() || "0"}
          icon={<AlertTriangle className="w-5 h-5" />}
          variant="orange"
        />

        <StatsCard
          title="Avg Processing Time"
          value={apiData?.Avgtime || "0s"}
          icon={<Clock className="w-5 h-5" />}
          variant="blue"
        />
      </div>

      {/* Table */}

      <div className="bg-card rounded-lg border border-border shadow-sm">
        {/* Search */}

        <div className="p-4 border-b border-border flex items-center justify-end">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />

            <input
              type="text"
              placeholder="Search invoices..."
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setCurrentPage(1);
              }}
              className="pl-9 pr-4 py-2 text-sm border border-border rounded-md bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        {/* Table */}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="text-left p-4">Reference Id</th>

                <th className="text-left p-4">From</th>

                <th className="text-left p-4">Subject</th>

                <th className="text-left p-4">Description</th>

                {/* <th className="text-left p-4">Channel</th> */}

                <th className="text-left p-4">Log Time</th>

                <th className="text-left p-4">View Invoice</th>
              </tr>
            </thead>

            <tbody>
              {paginatedInvoices.map((inv, index) => (
                <tr
                  key={inv.id ?? index}
                  className="border-b hover:bg-muted/30"
                >
                  <td className="p-4">
                    {inv.src_id || "-"}
                  </td>

                  <td className="p-4">
                    {inv.from_email || "-"}
                  </td>

                  <td className="p-4">
                    {inv.subject || "-"}
                  </td>

                  <td className="p-4 max-w-[300px]">
                    <div
                      ref={(el) => {
                        if (el) {
                          descriptionRefs.current.set(
                            inv.id,
                            el
                          );
                        }
                      }}
                      className={
                        expandedDescriptions.has(inv.id)
                          ? ""
                          : "line-clamp-2"
                      }
                    >
                      {inv.body?.trim()
                        ? inv.body
                        : "No description available"}
                    </div>

                    {truncatedItems.has(inv.id) && (
                      <button
                        onClick={() => {
                          const newExpanded = new Set(
                            expandedDescriptions
                          );

                          if (newExpanded.has(inv.id)) {
                            newExpanded.delete(inv.id);
                          } else {
                            newExpanded.add(inv.id);
                          }

                          setExpandedDescriptions(
                            newExpanded
                          );
                        }}
                        className="text-red-500 text-xs hover:underline"
                      >
                        {expandedDescriptions.has(inv.id)
                          ? "Read Less"
                          : "Read More..."}
                      </button>
                    )}
                  </td>

                  {/* <td className="p-4">
                    {inv.channel}
                  </td> */}

                  {/* <td className="p-4">
                    {new Date(
                      inv.timestamp
                    ).toLocaleString()}
                  </td> */}
                  <td className="p-4 text-foreground max-w-xs truncate">
                    {new Date(`${inv.timestamp}Z`).toLocaleString("en-IN", {
                      timeZone: "Asia/Kolkata",
                    })}
                  </td>

                  <td className="p-4">
                    <Eye
                      className={`w-4 h-4 ${
                        inv.src_id
                          ? "cursor-pointer"
                          : "opacity-50 cursor-not-allowed"
                      }`}
                      onClick={() => {
                        setSelectedSrcId(inv.src_id);

                        handleViewPdf(inv.src_id);
                      }}
                    />
                  </td>
                </tr>
              ))}

              {paginatedInvoices.length === 0 && (
                <tr>
                  <td
                    colSpan={8}
                    className="text-center p-4 text-muted-foreground"
                  >
                    No invoices found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}

        <div className="p-4 flex justify-end items-center gap-2">
          <button
            className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
            disabled={currentPage === 1}
            onClick={() =>
              setCurrentPage((prev) => prev - 1)
            }
          >
            Prev
          </button>

          <span className="text-xs text-muted-foreground">
            Page {currentPage} of {totalPages}
          </span>

          <button
            className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
            disabled={currentPage === totalPages}
            onClick={() =>
              setCurrentPage((prev) => prev + 1)
            }
          >
            Next
          </button>
        </div>
      </div>

      {/* PDF Modal */}

      {pdfUrl && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setPdfUrl(null)}
        >
          <div
            className="bg-white rounded-lg shadow-lg w-full max-w-5xl h-[95vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between p-4 border-b">
              <div>
                <h2 className="font-semibold">
                  Invoice PDF
                </h2>

                {selectedSrcId && (
                  <p className="text-sm text-gray-500">
                    {selectedSrcId}
                  </p>
                )}
              </div>

              <button
                onClick={() => setPdfUrl(null)}
                className="text-xl"
              >
                ×
              </button>
            </div>

            {pdfLoading ? (
              <div className="flex-1 flex items-center justify-center">
                Loading PDF...
              </div>
            ) : (
              <iframe
                src={pdfUrl}
                className="flex-1 w-full border-none"
                title="Invoice PDF"
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default InboxPage;