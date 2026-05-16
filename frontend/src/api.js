import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 300000,
  headers: { 'Content-Type': 'application/json' },
});

// Connections
export const listConnections = () => api.get('/api/connections');
export const createConnection = (data) => api.post('/api/connections', data);
export const updateConnection = (id, data) => api.put(`/api/connections/${id}`, data);
export const deleteConnection = (id) => api.delete(`/api/connections/${id}`);
export const testConnection = (data) => api.post('/api/connections/test', data);
// Execution
export const uploadCsv = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/api/upload-csv', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const runChecks = (data) => api.post('/api/run', data);
export const getHistory = (suite = '', days = 30) =>
  api.get('/api/history', { params: { suite, days } });
export const getRunResult = (runId) => api.get(`/api/history/${runId}`);
export const getBatchResult = (batchId) => api.get(`/api/history/batch/${batchId}`);

// Metadata Management
export const listMetadata = (group = '', activeOnly = true) =>
  api.get('/api/metadata', { params: { group, active_only: activeOnly } });
export const getMetadata = (id) => api.get(`/api/metadata/${id}`);
export const createMetadata = (data) => api.post('/api/metadata', data);
export const updateMetadata = (id, data) => api.put(`/api/metadata/${id}`, data);
export const deleteMetadata = (id) => api.delete(`/api/metadata/${id}`);
export const bulkImportMetadata = (entries) => api.post('/api/metadata/bulk-import', { entries });
export const runFromMetadata = (data) => api.post('/api/metadata/run', data);

export default api;
