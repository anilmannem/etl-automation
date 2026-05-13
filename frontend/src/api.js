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

export default api;
