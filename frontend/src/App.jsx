import { useState, useEffect } from 'react';
import { ThemeProvider, CssBaseline, Box, CircularProgress, Typography } from '@mui/material';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import theme from './theme';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import SuiteRunner from './pages/SuiteRunner';
import Connections from './pages/Connections';
import ResultDetail from './pages/ResultDetail';
import SuiteResultsView from './pages/SuiteResultsView';
import MetadataManager from './pages/MetadataManager';
import { getBatchResult } from './api';

function BatchResultPage() {
  const { batchId } = useParams();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    getBatchResult(batchId)
      .then((res) => setResult(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load batch'))
      .finally(() => setLoading(false));
  }, [batchId]);

  if (loading) return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 2 }}>
      <CircularProgress size={24} />
      <Typography sx={{ color: '#64748B' }}>Loading batch results…</Typography>
    </Box>
  );
  if (error) return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
      <Typography sx={{ color: '#DC2626' }}>{error}</Typography>
    </Box>
  );
  return <SuiteResultsView result={result} />;
}

export default function App() {
  const [lastResult, setLastResult] = useState(null);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: '#EEF2FA' }}>
          <Sidebar />
          <Box
            component="main"
            sx={{
              flexGrow: 1,
              height: '100vh',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              bgcolor: '#F8FAFC',
            }}
          >
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/connections" element={<Connections />} />
              <Route path="/metadata" element={<MetadataManager />} />
              <Route path="/suite" element={<SuiteRunner onResult={setLastResult} />} />
              <Route path="/results/batch/:batchId" element={<BatchResultPage />} />
              <Route path="/results/:runId" element={<ResultDetail />} />
              <Route
                path="/results"
                element={
                  lastResult?.type === 'suite' ? (
                    <SuiteResultsView result={lastResult} />
                  ) : lastResult ? (
                    <ResultDetail result={lastResult} />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
            </Routes>
          </Box>
        </Box>
      </BrowserRouter>
    </ThemeProvider>
  );
}
