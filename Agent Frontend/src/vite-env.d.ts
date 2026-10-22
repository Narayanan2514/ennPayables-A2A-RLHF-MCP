/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PIPELINE_API_BASE: string;
  readonly VITE_EXCEPTIONS_API_BASE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
