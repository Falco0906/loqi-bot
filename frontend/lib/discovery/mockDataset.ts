import { Company } from "../types/discoveryModels";

export const MOCK_COMPANY_DATASET: Company[] = [
  { id: "1", name: "Acme Corp", industry: "SaaS", employeeCount: 150, location: "SF", fundingStage: "Series B", technologies: ["React", "Node.js"], hiring: true, description: "AI SaaS scaling fast." },
  { id: "2", name: "Globex", industry: "Fintech", employeeCount: 300, location: "NYC", fundingStage: "Series C", technologies: ["Python", "AWS"], hiring: false, description: "Enterprise fintech." },
  { id: "3", name: "Stark Ind", industry: "Manufacturing", employeeCount: 2000, location: "Bangalore", fundingStage: "Public", technologies: ["Python"], hiring: true, description: "Advanced robotics." },
];
