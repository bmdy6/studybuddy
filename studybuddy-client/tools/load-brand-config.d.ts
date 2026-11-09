export interface BrandConfig {
  readonly name: string;
  readonly nameEn: string;
}

export function loadBrandConfig(filePath?: string): BrandConfig;
