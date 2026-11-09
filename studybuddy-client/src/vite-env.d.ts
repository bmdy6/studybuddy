/// <reference types="vite/client" />

declare const __APP_BRAND__: {
  readonly name: string;
  readonly nameEn: string;
};

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
