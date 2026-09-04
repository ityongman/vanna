import { extend } from 'umi-request';

const request = extend({
  prefix: '/api',
  timeout: 30000,
  errorHandler: (error) => {
    console.error('Request error:', error);
    throw error;
  },
});

// Response interceptor
request.interceptors.response.use(async (response) => {
  return response;
});

export default request;
