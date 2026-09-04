import { mockBusinesses, type Business } from './_mock/businesses';

/**
 * Fetch available businesses.
 * Currently returns mock data; will switch to API call when backend endpoint is ready.
 */
export async function fetchBusinesses(): Promise<Business[]> {
  // TODO: replace with actual API call when backend provides the endpoint
  // return request('/api/v1/businesses');
  return Promise.resolve(mockBusinesses);
}
