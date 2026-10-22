import { useState } from "react";
import {
  Bot,
  ChevronDown,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";

const VEESIGHTS_URL = "http://10.4.1.204:8080/";

const ChatbotWidget = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  // Starts true: the iframe below is always mounted (just hidden until
  // opened) so VeeChat preloads in the background from page load.
  const [isLoading, setIsLoading] = useState(true);
  // Bumped on close to remount the iframe with a fresh src, clearing the
  // VeeChat session while it reloads off-screen instead of on the next click.
  const [iframeKey, setIframeKey] = useState(0);

  const username = localStorage.getItem("username");

  const veeChatUrl = username
    ? `${VEESIGHTS_URL}?username=${encodeURIComponent(username)}`
    : VEESIGHTS_URL;

  const handleOpen = () => {
    setIsOpen(true);
  };

  const handleExpand = () => {
    setIsExpanded(true);
  };

  const handleMinimize = () => {
    setIsExpanded(false);
  };

  const handleClose = () => {
    // Hide the panel and start a fresh preload in the background so the
    // next open is instant, while still clearing the current VeeChat
    // session/state.
    setIsExpanded(false);
    setIsOpen(false);
    setIsLoading(true);
    setIframeKey((key) => key + 1);
  };

  return (
    <>
      {/* =====================================================
          CHAT CONTAINER

          Always mounted (never conditionally rendered on isOpen) so the
          iframe below can preload VeeChat in the background before the
          user ever clicks. Visibility is toggled purely with CSS.
          ===================================================== */}
      <div
        className={
          !isOpen
            ? "hidden"
            : isExpanded
              ? "fixed inset-0 z-[9999] flex h-screen w-screen flex-col bg-white"
              : "fixed bottom-20 right-2 z-50 flex h-[min(75vh,840px)] w-[min(94vw,900px)] flex-col overflow-hidden rounded-xl border border-[#63B7A8] bg-muted shadow-2xl"
        }
      >
        {/* =================================================
            HEADER
            ================================================= */}
        <div className="flex h-12 shrink-0 items-center justify-between bg-[#0A1734] px-4 text-white">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Bot className="h-4 w-4" aria-hidden="true" />
            VeeChat
          </div>

          <div className="flex items-center gap-1">
            {/* EXPAND */}
            {!isExpanded && (
              <button
                type="button"
                onClick={handleExpand}
                aria-label="Expand VeeChat"
                title="Expand"
                className="rounded-md p-1.5 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            )}

            {/* MINIMIZE */}
            {isExpanded && (
              <button
                type="button"
                onClick={handleMinimize}
                aria-label="Minimize VeeChat"
                title="Minimize"
                className="rounded-md p-1.5 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
              >
                <Minimize2 className="h-4 w-4" />
              </button>
            )}

            {/* CLOSE */}
            <button
              type="button"
              onClick={handleClose}
              aria-label="Close VeeChat"
              title="Close"
              className="rounded-md p-1.5 text-white/80 transition-colors hover:bg-white/10 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* =================================================
            IFRAME

            Mounted continuously (see CHAT CONTAINER above) and keyed
            on iframeKey. handleClose bumps the key to remount it with
            a fresh src, which clears the VeeChat session while it
            reloads off-screen, so the next open is instant.
            ================================================= */}
        <div className="relative min-h-0 w-full flex-1">
          {isLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-muted">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#63B7A8] border-t-transparent" />
            </div>
          )}
          <iframe
            key={iframeKey}
            src={veeChatUrl}
            title="VeeChat"
            onLoad={() => setIsLoading(false)}
            className="h-full w-full border-0"
          />
        </div>
      </div>

      {/* =====================================================
          CHAT BUTTON
          ===================================================== */}
      {!isExpanded && (
        <div className="fixed bottom-2 right-2 z-50">
          <button
            type="button"
            onClick={isOpen ? handleClose : handleOpen}
            aria-label={isOpen ? "Close VeeChat" : "Open VeeChat"}
            title={isOpen ? "Close VeeChat" : "Open VeeChat"}
            className="flex h-14 items-center gap-2.5 rounded-full border border-[#63B7A8] bg-[#D9F0EC] px-1.5 text-[#0A1734] shadow-lg transition-transform hover:scale-105 hover:shadow-xl"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#0A1734] text-white">
              {isOpen ? (
                <ChevronDown className="h-5 w-5" />
              ) : (
                <Bot className="h-5 w-5" />
              )}
            </span>

            <span className="pr-1 text-xs font-semibold">
              VeeChat
            </span>
          </button>
        </div>
      )}
    </>
  );
};

export default ChatbotWidget;
