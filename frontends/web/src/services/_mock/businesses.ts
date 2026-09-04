export interface Business {
  id: string;
  name: string;
  description?: string;
}

export const mockBusinesses: Business[] = [
  {
    id: 'equipment_decay',
    name: 'Equipment Decay Analysis',
    description: 'Equipment decay data analysis and prediction',
  },
  {
    id: 'fn_266',
    name: 'FN-266 Project',
    description: 'FN-266 project data management',
  },
];
