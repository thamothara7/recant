/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FORENSICS_URL?: string;
  readonly VITE_QUARANTINE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
