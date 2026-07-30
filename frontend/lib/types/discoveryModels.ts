export interface ParsedQuery {
  industry?: string;
  employeeRange?: [number, number];
  location?: string;
  title?: string;
  fundingStage?: string;
  keywords: string[];
  exclusions: string[];
}

export interface Company {
  id: string;
  name: string;
  industry: string;
  employeeCount: number;
  location: string;
  fundingStage: string;
  technologies: string[];
  hiring: boolean;
  description: string;
}
