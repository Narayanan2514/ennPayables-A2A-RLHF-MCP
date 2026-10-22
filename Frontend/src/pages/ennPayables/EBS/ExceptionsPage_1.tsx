import { Search, Pencil } from "lucide-react";
import StatsCard from "@/components/StatsCard";
import { AlertTriangle, Clock, User, Zap } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { useToast } from "@/hooks/use-toast";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import Tooltip from "@mui/material/Tooltip";
import Box from "@mui/material/Box";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import hotToast from "react-hot-toast";

// Types for exception details API
interface ExceptionDocLink {
  path: string;
  status_code: number;
  filename: string;
  media_type: string;
}

interface ExceptionLineItem {
  id: number;
  line_number: string;
  total: number;
  remark: string;
  automation_flag: string | number;
  item_desc: string;
  order_company: string;
  order_type: string;
  item_name: string;
}

interface ExceptionHeader {
  id: number;
  src_id: string;
  supplier_name: string;
  customer_po_number: string;
  invoice_number: string;
  invoice_date: string;
  gl_date: string;
  business_unit: string;
  batch_number: string;
  created_at: string;
  line_items: ExceptionLineItem[];
}

interface ExceptionDetailsResponse {
  doc_link: ExceptionDocLink;
  header_line_items: ExceptionHeader[];
  error_desc: string[];
  action_button?: string;
  modified_list?: string[];
}

const API_URL = "http://localhost:8011/ebs/exceptions_ebs";

interface Exception {
  id: number;
  entity_id: string;
  status: string;
  stage: number;
  description: string;
  log_time: string;
  from_email: string | null;
  invoice_number: string | null;
  is_hold?: number;
}

interface ApiResponse {
  exception_cnt: number;
  open_exception_cnt: number;
  manual_review: number;
  avg_time: string;
  invoice_list: Exception[];
  my_approval: Exception[];
}

interface ReviewedRecord {
  entity_id: string;
  invoice_number: string;
  from_email: string;
  description: string;
  action_taken: string;
  log_time?: string;
}

const stageTitles = {
  1: "Collection",
  2: "Preprocessing",
  3: "AI Extraction",
  4: "JDE",
};

const ITEMS_PER_PAGE = 5;

// Helper function to convert dd-mm-yyyy to mm/dd/yyyy format
const formatDateToMMDDYYYY = (dateString: string): string => {
  if (!dateString) return "";
  // Try to parse if it's in dd-mm-yyyy format
  const parts = dateString.split('-');
  if (parts.length === 3 && parts[0].length === 2 && parts[1].length === 2 && parts[2].length === 4) {
    // Assuming dd-mm-yyyy format, convert to mm/dd/yyyy
    return `${parts[1]}/${parts[0]}/${parts[2]}`;
  }
  return dateString;
};

// Helper function to convert mm/dd/yyyy back to dd-mm-yyyy format
const formatDateToDDMMYYYY = (dateString: string): string => {
  if (!dateString) return "";
  const parts = dateString.split('/');
  if (parts.length === 3 && parts[0].length === 2 && parts[1].length === 2 && parts[2].length === 4) {
    // Assuming mm/dd/yyyy format, convert to dd-mm-yyyy
    return `${parts[1]}-${parts[0]}-${parts[2]}`;
  }
  return dateString;
};

// Helper function to format date input as MM/DD/YYYY on the fly
const formatDateInput = (input: string): string => {
  // Remove all non-numeric characters
  const cleaned = input.replace(/\D/g, '');

  // Limit to 8 characters (MMDDYYYY)
  if (cleaned.length === 0) return '';
  if (cleaned.length <= 2) return cleaned;
  if (cleaned.length <= 4) return `${cleaned.slice(0, 2)}/${cleaned.slice(2)}`;
  return `${cleaned.slice(0, 2)}/${cleaned.slice(2, 4)}/${cleaned.slice(4, 8)}`;
};

const ExceptionsPage = () => {
  const { toast } = useToast();
  const [apiData, setApiData] = useState<ApiResponse | null>(null);
  const [exceptions, setExceptions] = useState<Exception[]>([]);
  const [myApprovals, setMyApprovals] = useState<Exception[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  // Pagination for reviewed tab
  const [reviewedPage, setReviewedPage] = useState(1);
  const [approvalPage, setApprovalPage] = useState(1);
  const [selectedExceptionId, setSelectedExceptionId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [tableTab, setTableTab] = useState<"open" | "reviewed" | "approvals">("approvals");
  const isAdmin = localStorage.getItem("role") === "Admin";
  const isUser = localStorage.getItem("role") === "User";
  const [isEditing, setIsEditing] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [changedFields, setChangedFields] = useState<Record<string, string>>({});
  const originalDetailsRef = useRef<ExceptionDetailsResponse | null>(null);
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [exceptionDetails, setExceptionDetails] = useState<ExceptionDetailsResponse | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [modalView, setModalView] = useState<"exception" | "email">("exception");
  const [emailData, setEmailData] = useState({ to: "", subject: "", body: "" });
  const [attachmentRemoved, setAttachmentRemoved] = useState(false);
  const [isSendingEmail, setIsSendingEmail] = useState(false);
  const [reviewedData, setReviewedData] = useState<ReviewedRecord[]>([]);
  const [reviewedLoading, setReviewedLoading] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [showApprovalConfirm, setShowApprovalConfirm] = useState(false);
  const [expandedDescriptions, setExpandedDescriptions] = useState<Set<number>>(new Set());
  const [expandedReviewedDescriptions, setExpandedReviewedDescriptions] = useState<Set<string>>(new Set());
  const [truncatedOpenItems, setTruncatedOpenItems] = useState<Set<number>>(new Set());
  const [truncatedReviewedItems, setTruncatedReviewedItems] = useState<Set<string>>(new Set());
  const openDescriptionRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const reviewedDescriptionRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [invfilenm, setInvFilenm] = useState("");

  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false);
  const [isArchiving, setIsArchiving] = useState(false);
  const [isSubmittingRequest, setIsSubmittingRequest] = useState(false);

  useEffect(() => {
    const checkOpenTruncation = () => {
      openDescriptionRefs.current.forEach((element, id) => {
        // Only check truncation if not expanded
        if (!expandedDescriptions.has(id)) {
          const isTruncated = element.scrollHeight > element.clientHeight;
          setTruncatedOpenItems(prev => {
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
    checkOpenTruncation();
    window.addEventListener('resize', checkOpenTruncation);
    return () => window.removeEventListener('resize', checkOpenTruncation);
  }, [exceptions, expandedDescriptions]);

  useEffect(() => {
    const checkReviewedTruncation = () => {
      reviewedDescriptionRefs.current.forEach((element, entityId) => {
        // Only check truncation if not expanded
        if (!expandedReviewedDescriptions.has(entityId)) {
          const isTruncated = element.scrollHeight > element.clientHeight;
          setTruncatedReviewedItems(prev => {
            const newSet = new Set(prev);
            if (isTruncated) {
              newSet.add(entityId);
            } else {
              newSet.delete(entityId);
            }
            return newSet;
          });
        }
      });
    };
    checkReviewedTruncation();
    window.addEventListener('resize', checkReviewedTruncation);
    return () => window.removeEventListener('resize', checkReviewedTruncation);
  }, [reviewedData, expandedReviewedDescriptions]);

  const fetchData = async () => {
    try {
      if (!apiData) setLoading(true);
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
        throw new Error("Failed to fetch data");
      }

      const data: ApiResponse = await response.json();

      setApiData(data);

      // Replace with fresh API data
      setExceptions(data.invoice_list || []);
      setMyApprovals(data.my_approval || []);

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

  useEffect(() => {
    fetchData();

    const interval = setInterval(fetchData, 20000);

    return () => clearInterval(interval);

  }, []);

  // Fetch reviewed data
  // Fetch reviewed data only when switching to reviewed tab
  useEffect(() => {
    const fetchReviewedData = async () => {
      try {
        setReviewedLoading(true);
        const response = await fetch("http://localhost:8011/ebs/reviewed_ebs", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
          },
          credentials: "omit",
          body: JSON.stringify({}),
        });

        if (!response.ok) throw new Error("Failed to fetch reviewed data");
        const data = await response.json();
        // Transform the response object into an array
        const reviewedArray: ReviewedRecord[] = Object.values(data).map((item: any) => ({
          entity_id: item.entity_id,
          invoice_number: item.invoice_number,
          from_email: item.from_email,
          description: item.description,
          action_taken: item.action_taken,
          log_time: item.log_time || new Date().toISOString(),
        }));
        setReviewedData(reviewedArray);
      } catch (err) {
        console.error('Error fetching reviewed data:', err);
      } finally {
        setReviewedLoading(false);
      }
    };


    if (tableTab === "reviewed") {
      fetchReviewedData();
    }
    // No interval, only fetch on tab switch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableTab]);

  useEffect(() => {
    console.log("invfilenm updated:", invfilenm);
  }, [invfilenm]);
  const filteredExceptions = exceptions.filter((exc) =>
    exc.entity_id.toLowerCase().includes(search.toLowerCase()) ||
    (exc.invoice_number && exc.invoice_number.toLowerCase().includes(search.toLowerCase())) ||
    (exc.from_email && exc.from_email.toLowerCase().includes(search.toLowerCase())) ||
    exc.description.toLowerCase().includes(search.toLowerCase()) ||
    exc.log_time.toLowerCase().includes(search.toLowerCase()) ||
    String(exc.stage).includes(search)
  );

  const filteredApprovals = myApprovals.filter((exc) =>
    exc.entity_id.toLowerCase().includes(search.toLowerCase()) ||
    (exc.invoice_number &&
      exc.invoice_number.toLowerCase().includes(search.toLowerCase())) ||
    (exc.from_email &&
      exc.from_email.toLowerCase().includes(search.toLowerCase())) ||
    exc.description.toLowerCase().includes(search.toLowerCase()) ||
    exc.log_time.toLowerCase().includes(search.toLowerCase()) ||
    String(exc.stage).includes(search)
  );

  const totalPages = Math.ceil(filteredExceptions.length / ITEMS_PER_PAGE);
  const reviewedTotalPages = Math.ceil(reviewedData.length / ITEMS_PER_PAGE);
  const approvalTotalPages = Math.ceil(
    filteredApprovals.length / ITEMS_PER_PAGE
  );
  const paginatedExceptions = filteredExceptions.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );
  const paginatedReviewed = reviewedData.slice(
    (reviewedPage - 1) * ITEMS_PER_PAGE,
    reviewedPage * ITEMS_PER_PAGE
  );

  const paginatedApprovals = filteredApprovals.slice(
    (approvalPage - 1) * ITEMS_PER_PAGE,
    approvalPage * ITEMS_PER_PAGE
  );

  const selectedException =
    exceptions.find(exc => exc.id === selectedExceptionId) ||
    myApprovals.find(exc => exc.id === selectedExceptionId);

  // Fetch exception details for modal
  const handleOpenModal = async (exceptionId: number) => {
    console.log('handleOpenModal called with exceptionId:', exceptionId);
    setSelectedExceptionId(exceptionId);
    setExceptionDetails(null);
    setDetailsError(null);
    setDetailsLoading(true);
    const exc =
      exceptions.find(e => e.id === exceptionId) ||
      myApprovals.find(e => e.id === exceptionId);
    console.log('Found exception:', exc);
    setFormData({
      entity_id: exc?.entity_id || "",
      invoice_number: exc?.invoice_number || "",
      description: exc?.description || "",
    });
    // Initialize email data with from_email
    setEmailData({
      to: exc?.from_email || "",
      subject: "",
      body: "",
    });
    setAttachmentRemoved(false);
    setIsEditing(false);
    setIsDirty(false);
    setChangedFields({});
    originalDetailsRef.current = null;
    setModalView("exception");
    setModalOpen(true);
    if (!exc) {
      console.warn('No exception found for id:', exceptionId);
      return;
    }
    try {
      console.log('Fetching details for src_id:', exc.entity_id);
      const formData = new FormData();
      formData.append('src_id', exc.entity_id);
      const resp = await fetch("http://localhost:8011/ebs/except_hlink_ebs", {
        method: "POST",
        body: formData,
      });
      if (!resp.ok) throw new Error("Failed to fetch exception details");
      const data: ExceptionDetailsResponse = await resp.json();
      setExceptionDetails(data);
      setInvFilenm(`${data.header_line_items[0].invoice_number}.pdf`)
      originalDetailsRef.current = JSON.parse(JSON.stringify(data));
      console.log('Fetched exception details:', data);

      // Fetch PDF after successfully getting details
      await handleFetchPdf(exc.entity_id);
    } catch (err) {
      setDetailsError(err instanceof Error ? err.message : "Error fetching details");
      console.error('Error fetching exception details:', err);
    } finally {
      setDetailsLoading(false);
    }
  };

  const handleCloseModal = () => {
    setModalOpen(false);
    setSelectedExceptionId(null);
    setFormData({});
    setExceptionDetails(null);
    setDetailsError(null);
    setDetailsLoading(false);
    setPdfUrl(null);
    setModalView("exception");
    setEmailData({ to: "", subject: "", body: "" });
    setIsSendingEmail(false);
  };

  // Fetch PDF as blob and create object URL
  const handleFetchPdf = async (srcId: string) => {
    setPdfLoading(true);
    try {
      const formData = new FormData();
      formData.append('src_id', srcId);

      const resp = await fetch("http://localhost:8011/ebs/fetch-invoice-file-ebs", {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) throw new Error("Failed to fetch PDF");

      const blob = await resp.blob();
      const url = window.URL.createObjectURL(blob);
      setPdfUrl(url);

      console.log("Invfilenm inside pdf function ", invfilenm);
      // To create attachment selectedException
      // const fileName = `${exceptionDetails?.header_line_items[0]?.invoice_number || "Invoice_Document"}.pdf`;

      const file = new File([blob], invfilenm, {
        type: "application/pdf",
      });

      setAttachmentFile(file);
      //End 
    } catch (err) {
      console.error('Error fetching PDF:', err);
      setDetailsError(err instanceof Error ? err.message : "Error loading PDF");
    } finally {
      setPdfLoading(false);
    }
  };

  // Handle approve action
  const handleApprove = async () => {
    setShowApprovalConfirm(true);
  };

  const handleArchiveException = async () => {
    try {
      setIsArchiving(true);

      const exc =
        exceptions.find(e => e.id === selectedExceptionId) ||
        myApprovals.find(e => e.id === selectedExceptionId);

      if (!exc) throw new Error("Exception not found");

      const formData = new FormData();
      formData.append("src_id", exc.entity_id);

      const response = await fetch(
        "http://localhost:8011/ebs/archive_exception_ebs",
        {
          method: "POST",
          body: formData,
        }
      );

      const data = await response.json();

      if (response.ok && data.status === "success") {

        hotToast.success(
          data.message || "Exception archived successfully"
        );

        setShowArchiveConfirm(false);

        handleCloseModal();

        fetchData();

      } else {
        hotToast.error(
          data.message || "Archive failed"
        );
      }

    } catch (error) {
      console.error("Archive Error:", error);

      hotToast.error("Failed to archive exception");

    } finally {
      setIsArchiving(false);
    }
  };

  // Confirm approval and proceed with API call
  const handleConfirmApprove = async () => {
    if (!selectedExceptionId) return;

    setIsApproving(true);
    setShowApprovalConfirm(false);
    try {
      const exc =
        exceptions.find(e => e.id === selectedExceptionId) ||
        myApprovals.find(e => e.id === selectedExceptionId);
      if (!exc) throw new Error('Exception not found');

      const formData = new FormData();
      formData.append('src_id', exc.entity_id);

      const response = await fetch("http://localhost:8011/ebs/reprocess_ebs", {
        method: "POST",
        body: formData,
      });

      if (response.ok) {
        // toast({
        //   title: "Approval Successful",
        //   description: "Invoice has been approved",
        // });
        hotToast.success("Invoice has been approved.");
        setIsApproving(false);
        handleCloseModal();
        // Refresh data immediately after approval
        await fetchData();
      } else {
        // toast({
        //   title: "Approval Failed",
        //   description: "Please try again",
        //   variant: "destructive",
        // });
        hotToast.error("Approval Failed: Please try again.");
      }
    } catch (err) {
      console.error("Error approving:", err);
      // toast({
      //   title: "Error",
      //   description: "An error occurred during approval",
      //   variant: "destructive",
      // });
      hotToast.error("An error occurred during approval.");
    } finally {
      setIsApproving(false);
    }
  };

  // Handle reprocess action
  const handleReprocess = async () => {
    if (!exceptionDetails || !selectedExceptionId) return;

    setIsReprocessing(true);
    try {
      const exc =
        exceptions.find(e => e.id === selectedExceptionId) ||
        myApprovals.find(e => e.id === selectedExceptionId);
      if (!exc) throw new Error('Exception not found');

      const formData = new FormData();
      formData.append('src_id', exc.entity_id);
      formData.append('invoice_number', exceptionDetails.header_line_items[0].invoice_number);
      formData.append('invoice_date', exceptionDetails.header_line_items[0].invoice_date);
      formData.append('customer_po_number', exceptionDetails.header_line_items[0].customer_po_number);

      // Serialize line items
      const lineItems = exceptionDetails.header_line_items[0].line_items.map((item, idx) => ({
        line_number: idx + 1,
        item_name: item.item_name,
        total: item.total,
        item_desc: item.item_desc || ""
      }));
      formData.append('line_items', JSON.stringify(lineItems));

      const response = await fetch("http://localhost:8011/ebs/reprocess_ebs", {
        method: "POST",
        body: formData,
      });

      if (response.ok) {
        // toast({
        //   title: "Reprocess Successful",
        //   description: "Invoice has been reprocessed",
        // });
        hotToast.success("Invoice has been reprocessed.");
        setIsReprocessing(false);
        handleCloseModal();
      } else {
        // toast({
        //   title: "Reprocess Failed",
        //   description: "Please try again",
        //   variant: "destructive",
        // });
        hotToast.error("Reprocess Failed: Please try again.");
      }
    } catch (err) {
      console.error("Error reprocessing:", err);
      // toast({
      //   title: "Error",
      //   description: "An error occurred during reprocess",
      //   variant: "destructive",
      // });
      hotToast.error("An error occurred during reprocess.");
    } finally {
      setIsReprocessing(false);
    }
  };

  // Handle request approval — sends changed fields as a flat dict in form data
  const handleRequestApproval = async () => {
    if (!exceptionDetails || !selectedExceptionId) return;
    const exc =
      exceptions.find(e => e.id === selectedExceptionId) ||
      myApprovals.find(e => e.id === selectedExceptionId);
    if (!exc) return;

    setIsSubmittingRequest(true);
    try {
      const formData = new FormData();
      formData.append("src_id", exc.entity_id);
      formData.append("field_list", JSON.stringify(changedFields));

      const response = await fetch("http://localhost:8011/ebs/request_approval_ebs", {
        method: "POST",
        body: formData,
      });

      if (response.ok) {
        hotToast.success("Approval request has been submitted.");
        setIsEditing(false);
        setIsDirty(false);
        setChangedFields({});
        handleCloseModal();
      } else {
        // toast({ title: "Request Failed", description: "Please try again.", variant: "destructive" });
        hotToast.error("Request Failed: Please try again.");
      }
    } catch (err) {
      console.error("Error requesting approval:", err);
      // toast({ title: "Error", description: "An error occurred while requesting approval.", variant: "destructive" });
      hotToast.error("An error occurred while requesting approval.");
    } finally {
      setIsSubmittingRequest(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-foreground">Exceptions</h2>
          <p className="text-sm text-muted-foreground">Review and resolve invoice processing failures</p>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          Error: {error}
        </div>
      )}

      {/* KPIs removed as requested */}

      <div className="bg-card rounded-lg border border-border shadow-sm mt-0">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between py-4 px-4 gap-2">
          {/* Tabs for Open/Reviewed */}
          {/* Switch-style tabs */}
          <div className="flex items-center mb-2 md:mb-0">
            <div className="flex bg-[#f5f6fa] rounded-xl p-1 border border-transparent">
              <button
                className={`px-4 py-1.5 text-sm font-medium rounded-xl transition-colors duration-150 focus:outline-none ${tableTab === "open"
                  ? "bg-white text-foreground font-semibold shadow-sm"
                  : "bg-transparent text-muted-foreground font-normal"
                  }`}
                style={{ minWidth: 70 }}
                onClick={() => {
                  setTableTab("open");
                  // Keep page number same as in reviewed tab
                  setCurrentPage(reviewedPage);
                }}
              >
                Open
              </button>
              <button
                className={`px-4 py-1.5 text-sm font-medium rounded-xl transition-colors duration-150 focus:outline-none ${tableTab === "reviewed"
                  ? "bg-white text-foreground font-semibold shadow-sm"
                  : "bg-transparent text-muted-foreground font-normal"
                  }`}
                style={{ minWidth: 70 }}
                onClick={() => {
                  setTableTab("reviewed");
                  // Keep page number same as in open tab
                  setReviewedPage(currentPage);
                }}
              >
                Reviewed
              </button>
              {isAdmin && (
                <button
                  className={`px-4 py-1.5 text-sm font-medium rounded-xl transition-colors duration-150 focus:outline-none flex items-center gap-2 ${tableTab === "approvals"
                    ? "bg-white text-foreground font-semibold shadow-sm"
                    : "bg-transparent text-muted-foreground font-normal"
                    }`}
                  style={{ minWidth: 100 }}
                  onClick={() => setTableTab("approvals")}
                >
                  My Approvals
                  {myApprovals.length > 0 && (
                    <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-red-600 text-white text-xs font-bold">
                      {myApprovals.length}
                    </span>
                  )}
                </button>
              )}
            </div>
          </div>
          {/* Search bar */}
          <div className="relative w-full md:w-72 ml-auto">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search exceptions..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setCurrentPage(1);
              }}
              className="pl-9 pr-4 py-2 text-sm border border-border rounded-md bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring w-full"
            />
          </div>
        </div>

        {/* Table content based on tab */}
        {tableTab === "open" ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left p-4 font-medium text-muted-foreground">Reference Id</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Inv No</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">From</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Error Description</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Stage</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Log Time</th>
                  </tr>
                </thead>

                <tbody>
                  {loading && !apiData ? (
                    <tr>
                      <td colSpan={6} className="p-4 text-center text-muted-foreground">
                        Loading exceptions...
                      </td>
                    </tr>
                  ) : paginatedExceptions.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-4 text-center text-muted-foreground">
                        No exceptions found
                      </td>
                    </tr>
                  ) : (
                    paginatedExceptions.map(exc => (
                      <tr key={exc.id} className="border-b border-border hover:bg-muted/30 transition-colors">
                        <td className="p-4 font-medium">
                          <button
                            onClick={() => handleOpenModal(exc.id)}
                            className="text-blue-600 hover:text-blue-800 hover:underline cursor-pointer"
                          >
                            {exc.entity_id}
                          </button>
                        </td>
                        <td className="p-4 text-foreground">{exc.invoice_number || "—"}</td>
                        <td className="p-4 text-foreground">{exc.from_email || "—"}</td>
                        <td className="p-4 text-foreground">
                          <div
                            ref={(el) => {
                              if (el) openDescriptionRefs.current.set(exc.id, el);
                            }}
                            className={expandedDescriptions.has(exc.id) ? "" : "line-clamp-2"}
                          >
                            {exc.description}
                          </div>
                          {truncatedOpenItems.has(exc.id) && (
                            <button
                              onClick={() => {
                                const newExpanded = new Set(expandedDescriptions);
                                if (newExpanded.has(exc.id)) {
                                  newExpanded.delete(exc.id);
                                } else {
                                  newExpanded.add(exc.id);
                                }
                                setExpandedDescriptions(newExpanded);
                              }}
                              className="text-red-500 text-xs hover:underline"
                            >
                              {expandedDescriptions.has(exc.id) ? "Read Less" : "Read More..."}
                            </button>
                          )}
                        </td>

                        <td className="p-4">
                          <Box display="flex" alignItems="center">
                            {[1, 2, 3, 4].map((step) => (
                              <Box key={step} display="flex" alignItems="center">
                                <Tooltip title={stageTitles[step]}>
                                  <Box
                                    sx={{
                                      width: 21,
                                      height: 21,
                                      borderRadius: "50%",
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "center",
                                      backgroundColor:
                                        step < exc.stage
                                          ? "#3b82fac4"
                                          : step === exc.stage
                                            ? exc.is_hold === 1
                                              ? "#fbe26ab0"
                                              : "#ef444485"
                                            : "#e5e7eb"
                                    }}
                                  >
                                    {step === exc.stage ? (
                                      exc.is_hold === 1 ? (
                                        <span style={{ color: "#fff", fontSize: 16 }}>!</span>
                                      ) : (
                                        <CloseIcon sx={{ color: "#fff", fontSize: 16 }} />
                                      )
                                    ) : step < exc.stage ? (
                                      <CheckIcon sx={{ color: "#fff", fontSize: 16 }} />
                                    ) : (
                                      <RadioButtonUncheckedIcon sx={{ color: "#999", fontSize: 16 }} />
                                    )}
                                  </Box>
                                </Tooltip>

                                {step !== 4 && (
                                  <Box
                                    sx={{
                                      width: 18,
                                      height: 2,
                                      mx: 0.5,
                                      backgroundColor:
                                        step < exc.stage
                                          ? "#c9f3fd"
                                          : step === exc.stage
                                            ? exc.is_hold === 1
                                              ? "#fbe26ab0"
                                              : "#f9c8c8"
                                            : "#ccc",
                                    }}
                                  />
                                )}
                              </Box>
                            ))}
                          </Box>
                        </td>

                        <td className="p-4 text-foreground max-w-xs truncate">{new Date(exc.log_time).toLocaleString()}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

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
          </>
        ) : tableTab === "reviewed" ? (
          // Reviewed Tab Table
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left p-4 font-medium text-muted-foreground">Reference Id</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Inv No</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">From</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Error Description</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Action Taken</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Log Time</th>
                  </tr>
                </thead>
                <tbody>
                  {reviewedLoading ? (
                    <tr>
                      <td colSpan={6} className="p-4 text-center text-muted-foreground">
                        Loading reviewed exceptions...
                      </td>
                    </tr>
                  ) : reviewedData.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-4 text-center text-muted-foreground">
                        No reviewed exceptions found
                      </td>
                    </tr>
                  ) : (
                    paginatedReviewed.map((row) => (
                      <tr key={row.entity_id} className="border-b border-border hover:bg-muted/30 transition-colors">
                        <td className="p-4 font-medium">{row.entity_id}</td>
                        <td className="p-4 text-foreground">{row.invoice_number || "—"}</td>
                        <td className="p-4 text-foreground">{row.from_email || "—"}</td>
                        <td className="p-4 text-foreground">
                          <div
                            ref={(el) => {
                              if (el) reviewedDescriptionRefs.current.set(row.entity_id, el);
                            }}
                            className={expandedReviewedDescriptions.has(row.entity_id) ? "" : "line-clamp-2"}
                          >
                            {row.description}
                          </div>
                          {truncatedReviewedItems.has(row.entity_id) && (
                            <button
                              onClick={() => {
                                const newExpanded = new Set(expandedReviewedDescriptions);
                                if (newExpanded.has(row.entity_id)) {
                                  newExpanded.delete(row.entity_id);
                                } else {
                                  newExpanded.add(row.entity_id);
                                }
                                setExpandedReviewedDescriptions(newExpanded);
                              }}
                              className="text-red-500 text-xs hover:underline"
                            >
                              {expandedReviewedDescriptions.has(row.entity_id) ? "Read Less" : "Read More..."}
                            </button>
                          )}
                        </td>
                        <td className="p-4 text-foreground">{row.action_taken}</td>
                        <td className="p-4 text-foreground max-w-xs truncate">{row.log_time ? new Date(row.log_time).toLocaleString() : "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {/* Pagination for reviewed tab - always visible */}
            <div className="p-4 flex justify-end items-center gap-2">
              <button
                className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
                disabled={reviewedPage === 1 || reviewedLoading}
                onClick={() => setReviewedPage(prev => prev - 1)}
              >
                Prev
              </button>

              <span className="text-xs text-muted-foreground">
                Page {reviewedPage} of {reviewedTotalPages || 1}
              </span>

              <button
                className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
                disabled={reviewedPage === reviewedTotalPages || reviewedLoading || reviewedTotalPages === 0}
                onClick={() => setReviewedPage(prev => prev + 1)}
              >
                Next
              </button>
            </div>
          </>
        ) : (
          // My Approvals Tab — Admin only
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left p-4 font-medium text-muted-foreground">Reference Id</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Invoice No</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">From</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Description</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Stage</th>
                    <th className="text-left p-4 font-medium text-muted-foreground">Log Time</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedApprovals.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-8 text-center text-muted-foreground">
                        No approval records found
                      </td>
                    </tr>
                  ) : (
                    paginatedApprovals.map((exc) => (
                      <tr
                        key={exc.id}
                        className="border-b border-border hover:bg-muted/30 transition-colors"
                      >
                        <td className="p-4 font-medium">
                          <button
                            onClick={() => handleOpenModal(exc.id)}
                            className="text-blue-600 hover:text-blue-800 hover:underline cursor-pointer"
                          >
                            {exc.entity_id}
                          </button>
                        </td>

                        <td className="p-4 text-foreground">
                          {exc.invoice_number || "—"}
                        </td>

                        <td className="p-4 text-foreground">
                          {exc.from_email || "—"}
                        </td>

                        <td className="p-4 text-foreground">
                          {exc.description}
                        </td>

                        <td className="p-4">
                          <Box display="flex" alignItems="center">
                            {[1, 2, 3, 4].map((step) => (
                              <Box key={step} display="flex" alignItems="center">
                                <Tooltip title={stageTitles[step]}>
                                  <Box
                                    sx={{
                                      width: 21,
                                      height: 21,
                                      borderRadius: "50%",
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "center",
                                      backgroundColor:
                                        step < exc.stage
                                          ? "#3b82fac4"
                                          : step === exc.stage
                                            ? exc.is_hold === 1
                                              ? "#fbe26ab0"
                                              : "#ef444485"
                                            : "#e5e7eb"
                                    }}
                                  >
                                    {step === exc.stage ? (
                                      exc.is_hold === 1 ? (
                                        <span style={{ color: "#fff", fontSize: 16 }}>!</span>
                                      ) : (
                                        <CloseIcon sx={{ color: "#fff", fontSize: 16 }} />
                                      )
                                    ) : step < exc.stage ? (
                                      <CheckIcon sx={{ color: "#fff", fontSize: 16 }} />
                                    ) : (
                                      <RadioButtonUncheckedIcon sx={{ color: "#999", fontSize: 16 }} />
                                    )}
                                  </Box>
                                </Tooltip>

                                {step !== 4 && (
                                  <Box
                                    sx={{
                                      width: 18,
                                      height: 2,
                                      mx: 0.5,
                                      backgroundColor:
                                        step < exc.stage
                                          ? "#c9f3fd"
                                          : step === exc.stage
                                            ? exc.is_hold === 1
                                              ? "#fbe26ab0"
                                              : "#f9c8c8"
                                            : "#ccc",
                                    }}
                                  />
                                )}
                              </Box>
                            ))}
                          </Box>
                        </td>

                        <td className="p-4 text-foreground">
                          {new Date(exc.log_time).toLocaleString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <div className="p-4 flex justify-end items-center gap-2">
              <button
                className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
                disabled={approvalPage === 1}
                onClick={() => setApprovalPage(prev => prev - 1)}
              >
                Prev
              </button>

              <span className="text-xs text-muted-foreground">
                Page {approvalPage} of {approvalTotalPages || 1}
              </span>

              <button
                className="px-3 py-1 text-xs border rounded-md disabled:opacity-50"
                disabled={
                  approvalPage === approvalTotalPages ||
                  approvalTotalPages === 0
                }
                onClick={() => setApprovalPage(prev => prev + 1)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>

      <Dialog open={modalOpen} onOpenChange={handleCloseModal}>
        <DialogContent className="max-w-4xl w-11/12 max-h-[85vh] flex flex-col p-0">
          {(isSendingEmail || isApproving || isReprocessing || isSubmittingRequest) && (
            <div className="absolute inset-0 bg-black/30 backdrop-blur-sm rounded-lg flex items-center justify-center z-50">
              <div className="flex flex-col items-center gap-4">
                <div className="flex gap-2">
                  <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '0s' }}></div>
                  <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
                </div>
                <p className="text-white font-medium">
                  {isSendingEmail ? 'Sending email...' : isApproving ? 'Approving...' : isSubmittingRequest? 'Submitting Request...' : 'Reprocessing...'}
                </p>
              </div>
            </div>
          )}
          <DialogHeader className="border-b border-border px-6 py-4 flex-shrink-0">
            <DialogTitle>
              {modalView === "exception" ? `Exception Details - ${selectedException?.entity_id}` : "Send Email"}
            </DialogTitle>
          </DialogHeader>

          {modalView === "exception" ? (
            <>
              <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col">
                <div className="space-y-4 flex-1">
                  <div className="grid grid-cols-2 gap-4 h-96">
                    {/* Left side - PDF Viewer */}
                    <div className="border border-border rounded-lg bg-muted p-2 flex flex-col overflow-hidden">
                      {pdfLoading ? (
                        <div className="flex-1 flex items-center justify-center text-muted-foreground">Loading PDF...</div>
                      ) : pdfUrl ? (
                        <iframe src={pdfUrl} className="flex-1 w-full border-none rounded" title="Invoice PDF" />
                      ) : detailsLoading ? (
                        <div className="flex-1 flex items-center justify-center text-muted-foreground">Loading document...</div>
                      ) : detailsError ? (
                        <div className="flex-1 flex items-center justify-center text-red-500">{detailsError}</div>
                      ) : (
                        <div className="flex-1 flex items-center justify-center text-center text-muted-foreground">
                          <div>
                            <p className="font-medium mb-2">PDF Viewer</p>
                            <p className="text-sm">Invoice document will display here</p>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Right side — fixed height, no outer scroll, internal scroll only */}
                    <div className="border border-border rounded-lg flex flex-col overflow-hidden">
                      {detailsLoading ? (
                        <div className="p-4 text-muted-foreground">Loading details...</div>
                      ) : detailsError ? (
                        <div className="p-4 text-red-500">{detailsError}</div>
                      ) : exceptionDetails?.header_line_items?.length ? (
                        <>
                          {/* Note banner — inside right panel, above scroll, only for User + Request Approval */}
                          {isUser && exceptionDetails?.action_button === "Request Approval" && (
                            <div className="mx-3 mt-3 rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2.5 flex-shrink-0">
                              <p className="text-xs font-semibold text-yellow-800 mb-0.5">Note:</p>
                              <p className="text-xs text-yellow-700">
                                In case the AI-extracted values are incorrect, you can edit them and request approval for reprocessing. If the extracted values are accurate, you can either archive or send an email.
                              </p>
                            </div>
                          )}

                          {/* Note banner for already exists error */}
                          {exceptionDetails?.error_desc?.some(err => err.toLowerCase().includes("already exists")) && (
                            <div className="mx-3 mt-3 rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2.5 flex-shrink-0">
                              <p className="text-xs font-semibold text-yellow-800 mb-0.5">Note:</p>
                              <p className="text-xs text-yellow-700">
                                This invoice number already exists. You can either send an email to the customer or archive it.
                              </p>
                            </div>
                          )}

                          {/* Note banner for modified fields in approvals tab */}
                          {tableTab === "approvals" && exceptionDetails?.modified_list && exceptionDetails.modified_list.length > 0 && (
                            <div className="mx-3 mt-3 rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2.5 flex-shrink-0">
                              <p className="text-xs font-semibold text-yellow-800 mb-0.5">⚠️Warning:</p>
                              <p className="text-xs text-yellow-700">
                                {(() => {
                                  const fieldNameMap: Record<string, string> = {
                                    'supplier_name': 'Company',
                                    'invoice_number': 'Invoice Number',
                                    'invoice_date': 'Invoice Date',
                                    'customer_po_number': 'PO Number',
                                    'item_desc': 'Item Description',
                                    'item_name': 'Item Name'
                                  };
                                  const displayNames = exceptionDetails.modified_list
                                    .flatMap(item => {
                                      if (!item) return [];
                                      return item.split(',').map(field => fieldNameMap[field.trim()] || field.trim());
                                    })
                                    .filter(Boolean);
                                  return `${displayNames.join(', ')} have been modified.`;
                                })()}
                              </p>
                            </div>
                          )}

                          {/* Sticky header row with Edit icon */}
                          <div className="flex items-center justify-between px-4 py-2 border-b border-border flex-shrink-0">
                            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Invoice Details</span>
                            {isUser && exceptionDetails?.action_button === "Request Approval" && (
                              <button
                                onClick={() => {
                                  if (isEditing) {
                                    // Cancel — restore original
                                    setExceptionDetails(JSON.parse(JSON.stringify(originalDetailsRef.current)));
                                    setIsDirty(false);
                                    setChangedFields({});
                                  }
                                  setIsEditing(v => !v);
                                }}
                                title={isEditing ? "Cancel editing" : "Edit fields"}
                                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${isEditing
                                  ? "bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"
                                  : "bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80 border border-border"
                                  }`}
                              >
                                <Pencil className="w-3 h-3" />
                                {isEditing ? "Cancel" : "Edit"}
                              </button>
                            )}
                          </div>

                          {/* Scrollable form */}
                          <div className="flex-1 overflow-y-auto p-4 space-y-4">
                            {/* Header fields */}
                            <div className="grid grid-cols-2 gap-3 pb-4 border-b border-border">
                              <div>
                                <Label htmlFor="company">Company</Label>
                                <Input 
                                  id="supplier_name" 
                                  value={exceptionDetails.header_line_items[0].supplier_name} 
                                  disabled={!isEditing}
                                  className={`mt-1 ${!isEditing ? "bg-muted" : ""}`}
                                  onChange={e => {
                                    const val = e.target.value;
                                    const updated = { ...exceptionDetails };
                                    updated.header_line_items[0].supplier_name = val;
                                    setExceptionDetails({ ...updated });
                                    setChangedFields(prev => ({ ...prev, supplier_name: val }));
                                    setIsDirty(true);
                                  }}
                                />
                              </div>
                              <div>
                                <Label htmlFor="invoice_number">Invoice Number</Label>
                                <Input
                                  id="invoice_number"
                                  value={exceptionDetails.header_line_items[0].invoice_number}
                                  disabled={!isEditing}
                                  className={`mt-1 ${!isEditing ? "bg-muted" : ""}`}
                                  onChange={e => {
                                    const val = e.target.value;
                                    const updated = { ...exceptionDetails };
                                    updated.header_line_items[0].invoice_number = val;
                                    setExceptionDetails({ ...updated });
                                    setChangedFields(prev => ({ ...prev, invoice_number: val }));
                                    setIsDirty(true);
                                  }}
                                />
                              </div>
                              <div>
                                <Label htmlFor="invoice_date">Invoice Date</Label>
                                <Input
                                  id="invoice_date"
                                  value={exceptionDetails.header_line_items[0].invoice_date}
                                  disabled={!isEditing}
                                  className={`mt-1 ${!isEditing ? "bg-muted" : ""}`}
                                  placeholder="YYYY-MM-DD"
                                  onChange={e => {
                                    const val = e.target.value;
                                    const updated = { ...exceptionDetails };
                                    updated.header_line_items[0].invoice_date = val;
                                    setExceptionDetails({ ...updated });
                                    setChangedFields(prev => ({ ...prev, invoice_date: val }));
                                    setIsDirty(true);
                                  }}
                                />
                              </div>
                              <div>
                                <Label htmlFor="customer_po_number">PO Number</Label>
                                <Input
                                  id="customer_po_number"
                                  value={exceptionDetails.header_line_items[0].customer_po_number}
                                  disabled={!isEditing}
                                  className={`mt-1 ${!isEditing ? "bg-muted" : ""}`}
                                  onChange={e => {
                                    const val = e.target.value;
                                    const updated = { ...exceptionDetails };
                                    updated.header_line_items[0].customer_po_number = val;
                                    setExceptionDetails({ ...updated });
                                    setChangedFields(prev => ({ ...prev, customer_po_number: val }));
                                    setIsDirty(true);
                                  }}
                                />
                              </div>
                            </div>

                            {/* Line Items — table format */}
                            <div className="space-y-2">
                              <h3 className="text-sm font-semibold text-foreground">Line Items</h3>
                              <div className="overflow-x-auto rounded-lg border border-border">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="bg-muted/50 border-b border-border">
                                      <th className="text-left px-2 py-2 font-medium text-muted-foreground w-10">Line #</th>
                                      <th className="text-left px-2 py-2 font-medium text-muted-foreground">Item Name</th>
                                      <th className="text-left px-2 py-2 font-medium text-muted-foreground">Description</th>
                                      <th className="text-right px-2 py-2 font-medium text-muted-foreground w-20">Total</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {exceptionDetails.header_line_items[0].line_items.map((item, idx) => (
                                      <tr key={idx} className="border-b border-border last:border-0 hover:bg-muted/20">
                                        <td className="px-2 py-1.5 text-center text-muted-foreground">{item.line_number ?? idx + 1}</td>
                                        <td className="px-2 py-1.5">
                                          {isEditing ? (
                                            <Input
                                              value={item.item_name}
                                              className="h-6 text-xs px-1.5"
                                              onChange={e => {
                                                const val = e.target.value;
                                                const updated = { ...exceptionDetails };
                                                updated.header_line_items[0].line_items[idx].item_name = val;
                                                setExceptionDetails({ ...updated });
                                                setChangedFields(prev => ({ ...prev, item_name: val }));
                                                setIsDirty(true);
                                              }}
                                            />
                                          ) : (
                                            <span>{item.item_name}</span>
                                          )}
                                        </td>
                                        <td className="px-2 py-1.5">
                                          {isEditing ? (
                                            <Input
                                              value={item.item_desc || ""}
                                              className="h-6 text-xs px-1.5"
                                              onChange={e => {
                                                const val = e.target.value;
                                                const updated = { ...exceptionDetails };
                                                updated.header_line_items[0].line_items[idx].item_desc = val;
                                                setExceptionDetails({ ...updated });
                                                setChangedFields(prev => ({ ...prev, item_desc: val }));
                                                setIsDirty(true);
                                              }}
                                            />
                                          ) : (
                                            <span className="text-muted-foreground">{item.item_desc || "—"}</span>
                                          )}
                                        </td>
                                        <td className="px-2 py-1.5 text-right">
                                          {isEditing ? (
                                            <Input
                                              value={item.total}
                                              type="number"
                                              className="h-6 text-xs px-1.5 text-right"
                                              onChange={e => {
                                                const val = e.target.value;
                                                const updated = { ...exceptionDetails };
                                                updated.header_line_items[0].line_items[idx].total = parseFloat(val) || 0;
                                                setExceptionDetails({ ...updated });
                                                setChangedFields(prev => ({ ...prev, total: val }));
                                                setIsDirty(true);
                                              }}
                                            />
                                          ) : (
                                            <span className="font-medium">{Number(item.total).toLocaleString("en-US", { minimumFractionDigits: 2 })}</span>
                                          )}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                  <tfoot>
                                    <tr className="bg-muted/50 border-t border-border">
                                      <td colSpan={3} className="px-2 py-2 font-semibold text-foreground text-right">Total</td>
                                      <td className="px-2 py-2 text-right font-bold text-foreground">
                                        {exceptionDetails.header_line_items[0].line_items
                                          .reduce((sum, item) => sum + (Number(item.total) || 0), 0)
                                          .toLocaleString("en-US", { minimumFractionDigits: 2 })}
                                      </td>
                                    </tr>
                                  </tfoot>
                                </table>
                              </div>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="p-4 text-muted-foreground">No details found.</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex justify-between items-center gap-4 px-6 py-4 border-t border-border flex-shrink-0 bg-white">
                {exceptionDetails?.error_desc?.length ? (
                  <div className="flex-1">
                    <h4 className="text-sm font-semibold text-red-600 mb-2">Error Description</h4>
                    <div className="space-y-1">
                      {exceptionDetails.error_desc.map((err, idx) => (
                        <div key={idx} className="text-sm text-red-600">• {err}</div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {!detailsLoading && !pdfLoading ? (
                  <div>
                    {
                      (exceptionDetails?.action_button === "Request Approval" && isUser) ? (
                        // Request Approval action - highest priority
                        <div className="flex gap-2">
                          {/* Request Approval */}
                          <Button
                            onClick={handleRequestApproval}
                            disabled={isSubmittingRequest || !isDirty}
                            title={!isDirty ? "Edit at least one field to enable" : undefined}
                          >
                            {isSubmittingRequest ? "Submitting Request..." : "Request Approval"}
                          </Button>

                          {/* Archive */}
                          <Button
                            variant="destructive"
                            onClick={() => setShowArchiveConfirm(true)}
                          >
                            Archive
                          </Button>

                          {/* Send Email */}
                          <Button
                            variant="secondary"
                            onClick={() => setModalView("email")}
                          >
                            Send Email
                          </Button>
                        </div>
                      ) : exceptionDetails?.error_desc?.some(err => err.toLowerCase().includes("already exists")) ? (
                        // Already exists error
                        <div>
                          <Button className="mr-2" onClick={() => setModalView("email")}>Email</Button>
                          <Button
                            variant="destructive"
                            onClick={() => setShowArchiveConfirm(true)}
                          >
                            Archive
                          </Button>
                        </div>
                      ) : exceptionDetails?.error_desc?.some(err => err.toLowerCase().includes("duplicate")) ? (
                        // Duplicate error
                        <Button onClick={() => setModalView("email")}>Email</Button>
                      ) : tableTab === "approvals" ? (
                        // Approvals tab
                        <div className="flex gap-2">
                          <Button
                            onClick={handleApprove}
                            disabled={isApproving}
                          >
                            {isApproving ? "Approving..." : "Approve for reprocess"}
                          </Button>
                        </div>
                      ) : exceptionDetails?.error_desc?.some(err => err.toLowerCase().includes("invalid")) ? (
                        // Invalid error
                        <Button onClick={handleReprocess} disabled={isReprocessing}>
                          {isReprocessing ? "Reprocessing..." : "Reprocess"}
                        </Button>
                      ) : null
                    }
                  </div>
                ) : null}
              </div>
            </>
          ) : (
            <>
              <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col">
                <div className="space-y-4 flex-1 flex flex-col">
                  <div>
                    <Label htmlFor="email-to">To</Label>
                    <Input
                      id="email-to"
                      type="email"
                      placeholder="recipient@example.com"
                      value={emailData.to}
                      onChange={(e) => setEmailData({ ...emailData, to: e.target.value })}
                      className="mt-1"
                    />
                  </div>

                  <div>
                    <Label htmlFor="email-subject">Subject</Label>
                    <Input
                      id="email-subject"
                      placeholder="Email subject"
                      value={
                        emailData.subject ||
                        (
                          exceptionDetails?.error_desc?.[0]?.toLowerCase().includes("invoice number already exists")
                            ? `RE: Duplicate Invoice # ${selectedException?.invoice_number || ""}`
                            : exceptionDetails?.error_desc?.[0]
                              ? `Regarding - ${exceptionDetails.error_desc[0]}`
                              : ""
                        )
                      }
                      onChange={(e) => setEmailData({ ...emailData, subject: e.target.value })}
                      className="mt-1"
                    />
                  </div>

                  {/* Attachment Section */}
                  {/* {!attachmentRemoved && (
                    <div className="mt-3 border border-border rounded-lg p-3 bg-gray-50 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-red-100 rounded flex items-center justify-center text-xs font-bold text-red-600">PDF</div>
                        <div>
                          <div className="text-sm font-medium text-foreground">{selectedException?.invoice_number || "Invoice_Document.pdf"}</div>
                          <div className="text-xs text-muted-foreground">36 KB</div>
                        </div>
                      </div>
                      <button
                        onClick={() => setAttachmentRemoved(true)}
                        className="text-muted-foreground hover:text-foreground p-1"
                      >
                        ✕
                      </button>
                    </div>
                  )} */}

                  {!attachmentRemoved && attachmentFile && (
                    <div className="border border-border rounded-lg p-3 bg-gray-50 flex items-center justify-between">

                      <div
                        className="flex items-center gap-3 cursor-pointer flex-1"
                        onClick={() => {
                          if (pdfUrl) {
                            window.open(pdfUrl, "_blank");
                          }
                        }}
                      >
                        <div className="w-10 h-10 bg-red-100 rounded flex items-center justify-center text-xs font-bold text-red-600">
                          PDF
                        </div>

                        <div>
                          <div className="text-sm font-medium text-foreground hover:underline">
                            {attachmentFile.name}
                          </div>

                          <div className="text-xs text-muted-foreground">
                            {(attachmentFile.size / 1024).toFixed(2)} KB
                          </div>
                        </div>
                      </div>

                      <button
                        onClick={() => {
                          setAttachmentRemoved(true);
                          setAttachmentFile(null);
                        }}
                        className="text-muted-foreground hover:text-foreground p-1"
                      >
                        ✕
                      </button>
                    </div>
                  )}

                  <div className="flex-1 flex flex-col">
                    <Label htmlFor="email-body">Body</Label>
                    <Textarea
                      id="email-body"
                      placeholder="Email body"
                      value={
                        emailData.body ||
                        (
                          exceptionDetails?.error_desc?.[0]
                            ?.toLowerCase()
                            .includes("invoice number already exists")
                            ? `Hi,

We have identified a duplicate Invoice.

Please find the attached invoice for which duplicate entry has been detected.

Kindly review it.

Thanks & Regards
AI Agent`
                            : `Hi,

We have received an invalid item reference number in the attached invoice.

Kindly review the invoice.

Thanks & Regards
AI Agent`
                        )
                      }
                      onChange={(e) => setEmailData({ ...emailData, body: e.target.value })}
                      className="mt-1 flex-1"
                      rows={6}
                    />
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-2 px-6 py-4 border-t border-border flex-shrink-0 bg-white">
                <Button variant="outline" onClick={() => {
                  setModalView("exception");
                  setEmailData(prev => ({ ...prev, subject: "", body: "" }));
                  setAttachmentRemoved(false);
                }}>
                  Back
                </Button>
                <Button onClick={async () => {
                  setIsSendingEmail(true);
                  try {
                    const exc =
                      exceptions.find(e => e.id === selectedExceptionId) ||
                      myApprovals.find(e => e.id === selectedExceptionId);
                    const emailFormData = new FormData();
                    emailFormData.append('src_id', exc?.entity_id || '');
                    emailFormData.append('email_to', emailData.to);
                    // Use auto-generated subject if user didn't enter anything
                    // const finalSubject = emailData.subject || (exceptionDetails?.error_desc?.[0] ? `Regarding - ${exceptionDetails.error_desc[0]}` : "");
                    const finalSubject =  exceptionDetails?.error_desc?.[0]?.toLowerCase().includes("invoice number already exists")
                            ? `RE: Duplicate Invoice # ${selectedException?.invoice_number || ""}`
                            : exceptionDetails?.error_desc?.[0]
                              ? `Regarding - ${exceptionDetails.error_desc[0]}`
                              : ""
                    const finalbody = exceptionDetails?.error_desc?.[0]
                            ?.toLowerCase()
                            .includes("invoice number already exists")
                            ? `Hi,

We have identified a duplicate Invoice.
Please find the attached invoice for which duplicate entry has been detected.

Kindly review it.

Thanks & Regards
AI Agent`
                            : `Hi,

We have received an invalid item reference number in the attached invoice.

Kindly review the invoice.

Thanks & Regards
AI Agent`
                    emailFormData.append('subject', finalSubject);
                    emailFormData.append('body', finalbody);
                    // emailFormData.append('attachment', attachmentRemoved ? 'false' : 'true');
                    emailFormData.append("attachments",attachmentFile);

                    const response = await fetch("http://localhost:8011/ebs/email_exception_duplicate", {
                      method: "POST",
                      body: emailFormData,
                    });

                    if (response.ok) {
                      // toast({
                      //   title: "Email Sent Successfully",
                      //   description: `Email sent to ${emailData.to}`,
                      // });
                      hotToast.success(`Email sent to ${emailData.to}`);
                      handleCloseModal();
                      // Refresh data immediately after sending email
                      await fetchData();
                    } else {
                      // toast({
                      //   title: "Failed to Send Email",
                      //   description: "Please try again",
                      //   variant: "destructive",
                      // });
                      hotToast.error("Failed to send email. Please try again.");
                      setIsSendingEmail(false);
                    }
                  } catch (err) {
                    console.error("Error sending email:", err);
                    // toast({
                    //   title: "Error",
                    //   description: "An error occurred while sending the email",
                    //   variant: "destructive",
                    // });
                    hotToast.error("An error occurred while sending the email.");
                    setIsSendingEmail(false);
                  }
                }} disabled={isSendingEmail}>
                  {isSendingEmail ? 'Sending...' : 'Send'}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Approval Confirmation Modal */}
      <Dialog open={showApprovalConfirm} onOpenChange={setShowApprovalConfirm}>
        <DialogContent className="max-w-sm w-11/12 p-0 [&>button]:hidden">
          <DialogHeader className="border-b border-border px-6 py-4 text-center">
            <DialogTitle className="text-center">Confirm Approval</DialogTitle>
          </DialogHeader>
          <div className="px-6 py-4">
            <p className="text-foreground text-base">
              Are you sure you want to approve this invoice for reprocessing?
            </p>
          </div>
          <div className="flex justify-end gap-3 px-6 py-4 border-t border-border bg-white">
            <Button
              variant="outline"
              onClick={() => setShowApprovalConfirm(false)}
              disabled={isApproving}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirmApprove}
              disabled={isApproving}
              className="flex-1"
            >
              {isApproving ? 'Approving...' : 'Yes'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={showArchiveConfirm}
        onOpenChange={setShowArchiveConfirm}
      >
        <DialogContent className="sm:max-w-md">

          <DialogHeader>
            <DialogTitle>
              Confirm Archive
            </DialogTitle>

            <DialogDescription>
              Are you sure you want to archive this exception?
            </DialogDescription>
          </DialogHeader>

          <div className="flex justify-end gap-2 mt-4">

            <Button
              variant="outline"
              onClick={() => setShowArchiveConfirm(false)}
            >
              Cancel
            </Button>

            <Button
              variant="destructive"
              onClick={handleArchiveException}
              disabled={isArchiving}
            >
              {isArchiving ? "Archiving..." : "Confirm"}
            </Button>

          </div>

        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ExceptionsPage;