import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Papa from 'papaparse';
import * as XLSX from 'xlsx';
import {
  Box, Typography, Button, TextField, Switch, FormControlLabel,
  Slider, CircularProgress, Alert, Select, MenuItem, FormControl,
  Collapse, IconButton, Tooltip, Table, TableBody,
  TableCell, TableHead, TableRow, Chip,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import AddRoundedIcon from '@mui/icons-material/AddRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import CompareArrowsRoundedIcon from '@mui/icons-material/CompareArrowsRounded';
import TuneRoundedIcon from '@mui/icons-material/TuneRounded';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import TableRowsRoundedIcon from '@mui/icons-material/TableRowsRounded';
import SchemaRoundedIcon from '@mui/icons-material/SchemaRounded';
import RemoveCircleOutlineRoundedIcon from '@mui/icons-material/RemoveCircleOutlineRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import FunctionsRoundedIcon from '@mui/icons-material/FunctionsRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import ConnectionPicker from '../components/ConnectionPicker';
import { runChecks } from '../api';

const newPair = () => ({ id: Date.now() + Math.random(), srcQuery: '', tgtQuery: '', keyCols: '' });

const CHECK_META = [
  { type: 'row_count', label: 'Row Count', icon: TableRowsRoundedIcon, color: '#3171D6' },
  { type: 'metadata', label: 'Metadata', icon: SchemaRoundedIcon, color: '#0891B2' },
  { type: 'null_check', label: 'Nulls', icon: RemoveCircleOutlineRoundedIcon, color: '#D97706' },
  { type: 'duplicate', label: 'Duplicates', icon: ContentCopyRoundedIcon, color: '#DB2777' },
  { type: 'data', label: 'Data Diff', icon: CompareArrowsRoundedIcon, color: '#7C3AED' },
  { type: 'aggregate', label: 'Aggregates', icon: FunctionsRoundedIcon, color: '#059669' },
];

function parseFile(file, onDone, onError) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (ext === 'csv') {
    Papa.parse(file, { header: true, skipEmptyLines: true, complete: (r) => onDone(r.data, r.meta.fields), error: (e) => onError(e.message) });
  } else if (['xlsx', 'xls'].includes(ext)) {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const wb = XLSX.read(e.target.result, { type: 'array' });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const data = XLSX.utils.sheet_to_json(ws, { defval: '' });
        onDone(data, data.length ? Object.keys(data[0]) : []);
      } catch (err) { onError(err.message); }
    };
    reader.readAsArrayBuffer(file);
  } else { onError('Use .csv, .xlsx or .xls'); }
}

export default function SuiteRunner({ onResult }) {
  const navigate = useNavigate();
  const fileRef = useRef();

  const [suiteName, setSuiteName] = useState('');
  const [srcConnectionId, setSrcConnectionId] = useState(null);
  const [tgtConnectionId, setTgtConnectionId] = useState(null);
  const [srcConnection, setSrcConnection] = useState(null);
  const [tgtConnection, setTgtConnection] = useState(null);
  const [pairs, setPairs] = useState([]);
  const [uploadError, setUploadError] = useState('');
  const [uploadedFile, setUploadedFile] = useState(null);

  const [checks, setChecks] = useState(['row_count', 'metadata', 'null_check']);
  const [strategy, setStrategy] = useState('auto');
  const [samplePct, setSamplePct] = useState(10);
  const [drillDown, setDrillDown] = useState(true);
  const [showOptions, setShowOptions] = useState(false);
  const [parallel, setParallel] = useState(false);
  const [workers, setWorkers] = useState(4);
  const [failFast, setFailFast] = useState(false);
  const [incremental, setIncremental] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState('');

  const srcIsCsv = srcConnectionId === '__csv__' || srcConnection?.platform === 'csv';
  const tgtIsCsv = tgtConnectionId === '__csv__' || tgtConnection?.platform === 'csv';

  const srcLabel = srcIsCsv ? 'Source File Path' : 'Source Query';
  const tgtLabel = tgtIsCsv ? 'Target File Path' : 'Target Query';
  const srcPlaceholder = srcIsCsv
    ? (srcConnection?.file_path ? `filename.csv (relative to ${srcConnection.file_path})` : '/path/to/source.csv')
    : 'SELECT * FROM stg.orders';
  const tgtPlaceholder = tgtIsCsv
    ? (tgtConnection?.file_path ? `filename.csv (relative to ${tgtConnection.file_path})` : '/path/to/target.csv')
    : 'SELECT * FROM prod.orders';

  const toggleCheck = (type) => setChecks((p) => p.includes(type) ? p.filter((t) => t !== type) : [...p, type]);

  const handleFileDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files[0] || e.target.files[0];
    if (!file) return;
    setUploadError(''); setUploadedFile(file.name);
    parseFile(file, (rows, fields) => {
      const lf = fields.map((f) => f.toLowerCase());
      const reqCols = ['source_query', 'target_query'];
      const missing = reqCols.filter((c) => !lf.includes(c));
      if (missing.length) { setUploadError(`Missing columns: ${missing.join(', ')}`); setUploadedFile(null); return; }
      setPairs(rows.filter((r) => r.source_query || r.target_query).map((r) => ({
        id: Date.now() + Math.random(), srcQuery: (r.source_query || '').trim(), tgtQuery: (r.target_query || '').trim(), keyCols: (r.key_cols || '').trim(),
      })));
    }, (msg) => { setUploadError(msg); setUploadedFile(null); });
    e.target.value = '';
  };

  const handleDownloadTemplate = () => {
    const srcEx1 = srcIsCsv ? '/data/source_orders.csv' : "SELECT * FROM stg.orders WHERE load_date='2026-05-08'";
    const srcEx2 = srcIsCsv ? '/data/source_customers.csv' : 'SELECT * FROM stg.customers';
    const tgtEx1 = tgtIsCsv ? '/data/target_orders.csv' : "SELECT * FROM prod.orders WHERE load_date='2026-05-08'";
    const tgtEx2 = tgtIsCsv ? '/data/target_customers.csv' : 'SELECT * FROM prod.customers';
    const rows = [
      { source_query: srcEx1, target_query: tgtEx1, key_cols: 'id, order_date' },
      { source_query: srcEx2, target_query: tgtEx2, key_cols: 'customer_id' },
    ];
    const ws = XLSX.utils.json_to_sheet(rows);
    ws['!cols'] = [{ wch: 60 }, { wch: 60 }, { wch: 25 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Pairs');
    XLSX.writeFile(wb, 'suite_template.xlsx');
  };

  const addPair = () => setPairs((p) => [...p, newPair()]);
  const removePair = (id) => setPairs((p) => p.filter((r) => r.id !== id));
  const updatePair = (id, field, value) => setPairs((p) => p.map((r) => r.id === id ? { ...r, [field]: value } : r));
  const validPairs = pairs.filter((p) => p.srcQuery.trim() && p.tgtQuery.trim());
  const canRun = srcConnectionId && tgtConnectionId && validPairs.length > 0 && checks.length > 0;

  const handleRun = async () => {
    if (!srcConnectionId || !tgtConnectionId) { setError('Select source and target connections'); return; }
    if (validPairs.length === 0) { setError('Add at least one test case'); return; }
    if (checks.length === 0) { setError('Select at least one check'); return; }
    setError(''); setRunning(true);
    const checkSpecs = checks.map((type) => {
      const spec = { type };
      if (type === 'data') { spec.strategy = strategy; spec.column_drill_down = drillDown; if (strategy === 'sample') spec.sample_pct = samplePct; }
      return spec;
    });
    const startTime = Date.now();
    const batchId = validPairs.length > 1 ? crypto.randomUUID() : '';
    const pairResults = [];
    for (let i = 0; i < validPairs.length; i++) {
      const pair = validPairs[i];
      const label = pair.srcQuery.slice(0, 55) + (pair.srcQuery.length > 55 ? '\u2026' : '');
      setProgress({ done: i, total: validPairs.length, current: label });
      try {
        const pairChecks = pair.keyCols?.trim()
          ? checkSpecs.map((s) => s.type === 'data' ? { ...s, join_keys: pair.keyCols.split(',').map((k) => k.trim()) } : s)
          : checkSpecs;
        const payload = { checks: pairChecks, suite_name: suiteName.trim(), parallel, max_workers: workers, fail_fast: failFast, batch_id: batchId, incremental };

        // Resolve file paths: saved CSV connections prepend their base path
        const resolvePath = (conn, rawPath) => {
          if (conn?.platform === 'csv' && conn.file_path && conn.id !== '__csv__') {
            const base = conn.file_path.replace(/\/+$/, '');
            return rawPath.startsWith('/') || rawPath.startsWith('\\') ? rawPath : `${base}/${rawPath}`;
          }
          return rawPath;
        };

        if (srcIsCsv) {
          payload.source_file_path = resolvePath(srcConnection, pair.srcQuery.trim());
          payload.source_table = 'SELECT * FROM data';
          if (srcConnection?.id && srcConnection.id !== '__csv__') payload.source_connection_id = srcConnection.id;
        } else { payload.source_connection_id = srcConnectionId; payload.source_table = pair.srcQuery.trim(); }
        if (tgtIsCsv) {
          payload.target_file_path = resolvePath(tgtConnection, pair.tgtQuery.trim());
          payload.target_table = 'SELECT * FROM data';
          if (tgtConnection?.id && tgtConnection.id !== '__csv__') payload.target_connection_id = tgtConnection.id;
        } else { payload.target_connection_id = tgtConnectionId; payload.target_table = pair.tgtQuery.trim(); }
        const res = await runChecks(payload);
        pairResults.push({
          index: i + 1,
          source_label: pair.srcQuery.trim(),
          target_label: pair.tgtQuery.trim(),
          status: res.data?.summary?.overall_status || 'Error',
          result: res.data,
        });
        if (failFast && res.data?.summary?.overall_status === 'Fail') break;
      } catch (err) {
        pairResults.push({
          index: i + 1,
          source_label: pair.srcQuery.trim(),
          target_label: pair.tgtQuery.trim(),
          status: 'Error',
          error: err.response?.data?.detail || err.message || 'Request failed',
          result: null,
        });
        if (failFast) break;
      }
    }
    setProgress(null); setRunning(false);
    if (pairResults.length === 0) return;
    // For a single test case, pass through directly to the existing ResultDetail view
    if (pairResults.length === 1 && pairResults[0].result) {
      onResult(pairResults[0].result);
      navigate('/results');
      return;
    }
    // Build consolidated suite result
    const totalDuration = Number(((Date.now() - startTime) / 1000).toFixed(2));
    const passedPairs = pairResults.filter((p) => p.status === 'Pass').length;
    const failedPairs = pairResults.filter((p) => p.status === 'Fail').length;
    const errorPairs = pairResults.filter((p) => p.status === 'Error').length;
    const totalChecks = pairResults.reduce((s, p) => s + (p.result?.summary?.total || 0), 0);
    const passedChecks = pairResults.reduce((s, p) => s + (p.result?.summary?.passed || 0), 0);
    const failedChecks = pairResults.reduce((s, p) => s + (p.result?.summary?.failed || 0), 0);
    const errorChecks = pairResults.reduce((s, p) => s + (p.result?.summary?.errors || 0), 0);
    const suiteResult = {
      type: 'suite',
      suite_name: suiteName.trim() || 'Test Suite',
      started_at: new Date(startTime).toISOString(),
      duration_s: totalDuration,
      summary: {
        total_test_cases: pairResults.length,
        passed_test_cases: passedPairs,
        failed_test_cases: failedPairs,
        error_test_cases: errorPairs,
        total_checks: totalChecks,
        passed_checks: passedChecks,
        failed_checks: failedChecks,
        error_checks: errorChecks,
        quality_score: totalChecks > 0 ? Math.round((passedChecks / totalChecks) * 100) : 0,
        overall_status: failedPairs > 0 || errorPairs > 0 ? 'Fail' : 'Pass',
      },
      test_cases: pairResults,
    };
    onResult(suiteResult);
    navigate('/results');
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <Box sx={{
        display: 'flex', alignItems: 'center', gap: 2,
        px: 3, pt: 2.5, pb: 2, flexShrink: 0,
        borderBottom: '1px solid rgba(15,23,42,0.06)', bgcolor: '#fff',
      }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, color: '#0F172A', letterSpacing: '-0.02em', lineHeight: 1.2 }}>
            Test Suite
          </Typography>
          <Typography sx={{ fontSize: '0.8rem', color: '#64748B', mt: 0.25 }}>
            Validate multiple test cases in a single run
          </Typography>
        </Box>
        <TextField
          size="small" placeholder="Suite name (optional)"
          value={suiteName} onChange={(e) => setSuiteName(e.target.value)}
          sx={{ width: 220, '& .MuiInputBase-root': { fontSize: '0.8rem', height: 36, bgcolor: '#F8FAFC' } }}
        />
        {validPairs.length > 0 && (
          <Chip
            label={`${validPairs.length} test case${validPairs.length !== 1 ? 's' : ''}`}
            size="small"
            sx={{ bgcolor: 'rgba(13,148,136,0.1)', color: '#0D9488', fontWeight: 700, border: '1px solid rgba(13,148,136,0.2)', fontSize: '0.72rem' }}
          />
        )}
        {progress && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CircularProgress size={14} sx={{ color: '#3171D6' }} />
            <Typography sx={{ fontSize: '0.75rem', color: '#64748B' }}>{progress.done + 1}/{progress.total}</Typography>
          </Box>
        )}
        <Button
          variant="contained" onClick={handleRun}
          disabled={running || !canRun}
          startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}
          sx={{
            px: 3, py: 1, fontWeight: 700, fontSize: '0.875rem',
            borderRadius: 2, flexShrink: 0,
            background: canRun && !running ? 'linear-gradient(135deg, #1D55B0 0%, #3171D6 50%, #3171D6 100%)' : undefined,
            boxShadow: canRun && !running ? '0 2px 12px rgba(49,113,214,0.35)' : 'none',
            '&:hover': { transform: 'translateY(-1px)', boxShadow: '0 4px 16px rgba(49,113,214,0.45)' },
            '&:active': { transform: 'translateY(0)' },
          }}
        >
          {running ? 'Running\u2026' : 'Run'}
        </Button>
      </Box>

      {error && <Alert severity="error" onClose={() => setError('')} sx={{ mx: 3, mt: 1.5, borderRadius: 2, flexShrink: 0 }}>{error}</Alert>}

      {/* Body: sidebar + right panel */}
      <Box sx={{ flex: 1, display: 'flex', gap: 0, overflow: 'hidden', minHeight: 0 }}>

        {/* LEFT sidebar */}
        <Box sx={{
          width: 280, flexShrink: 0, borderRight: '1px solid rgba(15,23,42,0.07)',
          overflowY: 'auto', bgcolor: '#FAFBFC', display: 'flex', flexDirection: 'column', gap: 0,
        }}>
          {/* Connections */}
          <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(15,23,42,0.06)' }}>
            <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em', mb: 1.5 }}>
              Connections
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.75 }}>
                  <StorageRoundedIcon sx={{ color: '#3171D6', fontSize: 12 }} />
                  <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#3171D6', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Source</Typography>
                </Box>
                <ConnectionPicker label="Source" value={srcConnectionId} onChange={setSrcConnectionId} onConnectionChange={setSrcConnection} />
              </Box>
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.75 }}>
                  <CompareArrowsRoundedIcon sx={{ color: '#0D9488', fontSize: 12 }} />
                  <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#0D9488', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Target</Typography>
                </Box>
                <ConnectionPicker label="Target" value={tgtConnectionId} onChange={setTgtConnectionId} onConnectionChange={setTgtConnection} />
              </Box>
            </Box>
          </Box>

          {/* Checks */}
          <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(15,23,42,0.06)' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                Checks {'\u00b7'} {checks.length}/{CHECK_META.length}
              </Typography>
              <Box onClick={() => setChecks(checks.length === CHECK_META.length ? [] : CHECK_META.map((c) => c.type))}
                sx={{ fontSize: '0.68rem', color: '#3171D6', cursor: 'pointer', fontWeight: 600, '&:hover': { opacity: 0.7 } }}>
                {checks.length === CHECK_META.length ? 'Clear' : 'All'}
              </Box>
            </Box>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
              {CHECK_META.map((meta) => {
                const active = checks.includes(meta.type);
                const Icon = meta.icon;
                return (
                  <Box key={meta.type} onClick={() => toggleCheck(meta.type)}
                    sx={{
                      display: 'flex', alignItems: 'center', gap: 1.25, px: 1.25, py: 0.875,
                      borderRadius: 1.5, cursor: 'pointer', transition: 'all 0.12s',
                      bgcolor: active ? `${meta.color}0E` : 'transparent',
                      '&:hover': { bgcolor: active ? `${meta.color}16` : 'rgba(15,23,42,0.04)' },
                    }}>
                    <Icon sx={{ fontSize: 15, color: active ? meta.color : '#94A3B8', transition: 'color 0.12s', flexShrink: 0 }} />
                    <Typography sx={{ fontSize: '0.8rem', fontWeight: active ? 600 : 400, color: active ? '#1E293B' : '#64748B', flex: 1, transition: 'all 0.12s' }}>
                      {meta.label}
                    </Typography>
                    <Box sx={{
                      width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                      bgcolor: active ? meta.color : 'transparent',
                      border: `1.5px solid ${active ? meta.color : 'rgba(15,23,42,0.15)'}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.12s',
                    }}>
                      {active && <CheckRoundedIcon sx={{ fontSize: 10, color: '#fff' }} />}
                    </Box>
                  </Box>
                );
              })}
            </Box>
          </Box>

          {/* Data Diff options */}
          {checks.includes('data') && (
            <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(15,23,42,0.06)' }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em', mb: 1.5 }}>
                Data Diff
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                <FormControl fullWidth size="small">
                  <Select value={strategy} onChange={(e) => setStrategy(e.target.value)} sx={{ fontSize: '0.8rem' }}>
                    <MenuItem value="auto">Auto (intelligent)</MenuItem>
                    <MenuItem value="minus">MINUS (server-side)</MenuItem>
                    <MenuItem value="hash">Hash (fastest)</MenuItem>
                    <MenuItem value="full">Full diff</MenuItem>
                    <MenuItem value="sample">Sample %</MenuItem>
                  </Select>
                </FormControl>
                {strategy === 'sample' && (
                  <Box>
                    <Typography sx={{ fontSize: '0.72rem', color: '#64748B' }}>Sample: {samplePct}%</Typography>
                    <Slider value={samplePct} onChange={(_, v) => setSamplePct(v)} min={1} max={100} size="small" />
                  </Box>
                )}
                <FormControlLabel
                  control={<Switch checked={drillDown} onChange={(e) => setDrillDown(e.target.checked)} size="small" color="primary" />}
                  label={<Typography sx={{ fontSize: '0.78rem', color: '#475569' }}>Column drill-down</Typography>}
                  sx={{ m: 0 }}
                />
              </Box>
            </Box>
          )}

          {/* Advanced */}
          <Box sx={{ p: 2.5 }}>
            <Box onClick={() => setShowOptions((v) => !v)}
              sx={{ display: 'flex', alignItems: 'center', gap: 0.75, cursor: 'pointer', color: '#64748B', '&:hover': { color: '#374151' } }}>
              <TuneRoundedIcon sx={{ fontSize: 14 }} />
              <Typography sx={{ fontSize: '0.78rem', fontWeight: 600 }}>Advanced options</Typography>
              <ExpandMoreRoundedIcon sx={{ fontSize: 14, ml: 'auto', transition: 'transform 0.2s', transform: showOptions ? 'rotate(180deg)' : 'none' }} />
            </Box>
            <Collapse in={showOptions}>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, mt: 1.5 }}>
                <FormControlLabel
                  control={<Switch checked={parallel} onChange={(e) => setParallel(e.target.checked)} size="small" color="primary" />}
                  label={<Typography sx={{ fontSize: '0.78rem', color: '#475569' }}>Parallel execution</Typography>}
                  sx={{ m: 0 }}
                />
                {parallel && (
                  <Box sx={{ ml: 4.5 }}>
                    <Typography sx={{ fontSize: '0.72rem', color: '#64748B' }}>Workers: {workers}</Typography>
                    <Slider value={workers} onChange={(_, v) => setWorkers(v)} min={2} max={16} size="small" />
                  </Box>
                )}
                <FormControlLabel
                  control={<Switch checked={failFast} onChange={(e) => setFailFast(e.target.checked)} size="small" />}
                  label={<Typography sx={{ fontSize: '0.78rem', color: '#475569' }}>Stop on first failure</Typography>}
                  sx={{ m: 0 }}
                />
                <FormControlLabel
                  control={<Switch checked={incremental} onChange={(e) => setIncremental(e.target.checked)} size="small" color="secondary" />}
                  label={<Typography sx={{ fontSize: '0.78rem', color: '#475569' }}>Incremental (only changed rows)</Typography>}
                  sx={{ m: 0 }}
                />
              </Box>
            </Collapse>
          </Box>
        </Box>

        {/* RIGHT — Test Cases table (always the same layout) */}
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden', bgcolor: '#fff' }}>
          {/* Toolbar */}
          <Box sx={{
            display: 'flex', alignItems: 'center', gap: 1.5, px: 2.5, py: 1.5,
            borderBottom: '1px solid rgba(15,23,42,0.07)', bgcolor: '#FAFBFC', flexShrink: 0,
          }}>
            <Typography sx={{ fontSize: '0.875rem', fontWeight: 700, color: '#0F172A', flex: 1 }}>
              Test Cases
              {pairs.length > 0 && (
                <Typography component="span" sx={{ ml: 1, fontSize: '0.72rem', color: '#94A3B8', fontWeight: 500 }}>
                  {pairs.length} row{pairs.length !== 1 ? 's' : ''} {'\u00b7'} columns: source_query, target_query, key_cols
                </Typography>
              )}
            </Typography>
            <Tooltip title="Download Excel template">
              <Button size="small" startIcon={<DownloadRoundedIcon sx={{ fontSize: 14 }} />} onClick={handleDownloadTemplate}
                sx={{ fontSize: '0.75rem', color: '#64748B', px: 1.25, py: 0.5, border: '1px solid rgba(15,23,42,0.1)', borderRadius: 1.5, '&:hover': { bgcolor: 'rgba(15,23,42,0.04)' } }}>
                Template
              </Button>
            </Tooltip>
            <Box
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleFileDrop}
              sx={{
                display: 'flex', alignItems: 'center', gap: 0.75,
                px: 1.5, py: 0.6, borderRadius: 1.5, cursor: 'pointer',
                border: '1px dashed',
                borderColor: uploadedFile ? 'rgba(13,148,136,0.4)' : 'rgba(49,113,214,0.25)',
                bgcolor: uploadedFile ? 'rgba(13,148,136,0.05)' : 'rgba(49,113,214,0.04)',
                transition: 'all 0.15s',
                '&:hover': { borderColor: '#3171D6', bgcolor: 'rgba(49,113,214,0.08)' },
              }}
            >
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" style={{ display: 'none' }} onChange={handleFileDrop} />
              {uploadedFile
                ? <><CheckCircleRoundedIcon sx={{ fontSize: 14, color: '#0D9488' }} /><Typography sx={{ fontSize: '0.72rem', color: '#0D9488', fontWeight: 600 }}>{uploadedFile}</Typography></>
                : <><UploadFileRoundedIcon sx={{ fontSize: 14, color: '#3171D6' }} /><Typography sx={{ fontSize: '0.72rem', color: '#3171D6', fontWeight: 600 }}>Import file</Typography></>
              }
            </Box>
            <Button size="small" startIcon={<AddRoundedIcon sx={{ fontSize: 14 }} />} onClick={addPair}
              sx={{ fontSize: '0.75rem', color: '#64748B', px: 1.25, py: 0.5, border: '1px solid rgba(15,23,42,0.1)', borderRadius: 1.5, '&:hover': { bgcolor: 'rgba(15,23,42,0.04)', color: '#374151' } }}>
              Add row
            </Button>
            {validPairs.length > 0 && (
              <Chip
                icon={<CheckCircleRoundedIcon sx={{ fontSize: '13px !important', color: '#0D9488 !important' }} />}
                label={`${validPairs.length} valid`}
                size="small"
                sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600, bgcolor: 'rgba(13,148,136,0.08)', color: '#0D9488', border: '1px solid rgba(13,148,136,0.2)' }}
              />
            )}
          </Box>

          {uploadError && <Alert severity="error" sx={{ mx: 2, mt: 1.5, borderRadius: 2, flexShrink: 0 }}>{uploadError}</Alert>}

          {/* Table */}
          <Box sx={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
            {pairs.length > 0 ? (
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ width: 36, bgcolor: '#FAFBFC', color: '#94A3B8', fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', py: 1.25, borderBottom: '1px solid rgba(15,23,42,0.07)' }}>#</TableCell>
                    <TableCell sx={{ bgcolor: '#FAFBFC', borderBottom: '1px solid rgba(15,23,42,0.07)', py: 1.25 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                        <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#3171D6' }} />
                        <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#3171D6', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{srcLabel}</Typography>
                      </Box>
                    </TableCell>
                    <TableCell sx={{ bgcolor: '#FAFBFC', borderBottom: '1px solid rgba(15,23,42,0.07)', py: 1.25 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                        <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#0D9488' }} />
                        <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#0D9488', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{tgtLabel}</Typography>
                      </Box>
                    </TableCell>
                    <TableCell sx={{ bgcolor: '#FAFBFC', borderBottom: '1px solid rgba(15,23,42,0.07)', py: 1.25, width: '18%' }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                        <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#7C3AED' }} />
                        <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#7C3AED', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Key Cols</Typography>
                        <Typography sx={{ fontSize: '0.58rem', color: '#94A3B8', fontStyle: 'italic' }}>(optional)</Typography>
                      </Box>
                    </TableCell>
                    <TableCell sx={{ width: 40, bgcolor: '#FAFBFC', borderBottom: '1px solid rgba(15,23,42,0.07)', py: 1.25 }} />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {pairs.map((pair, idx) => (
                    <TableRow key={pair.id} hover sx={{ '&:hover td': { bgcolor: 'rgba(49,113,214,0.02)' } }}>
                      <TableCell sx={{ color: '#94A3B8', fontSize: '0.72rem', verticalAlign: 'top', pt: 1.25, fontFamily: 'monospace' }}>{idx + 1}</TableCell>
                      <TableCell sx={{ verticalAlign: 'top' }}>
                        <TextField variant="standard" size="small" fullWidth multiline
                          value={pair.srcQuery} onChange={(e) => updatePair(pair.id, 'srcQuery', e.target.value)}
                          placeholder={srcPlaceholder}
                          sx={{ '& .MuiInputBase-root': { fontSize: '0.78rem', fontFamily: '"JetBrains Mono", monospace' } }}
                          InputProps={{ disableUnderline: true }}
                        />
                      </TableCell>
                      <TableCell sx={{ verticalAlign: 'top' }}>
                        <TextField variant="standard" size="small" fullWidth multiline
                          value={pair.tgtQuery} onChange={(e) => updatePair(pair.id, 'tgtQuery', e.target.value)}
                          placeholder={tgtPlaceholder}
                          sx={{ '& .MuiInputBase-root': { fontSize: '0.78rem', fontFamily: '"JetBrains Mono", monospace' } }}
                          InputProps={{ disableUnderline: true }}
                        />
                      </TableCell>
                      <TableCell sx={{ verticalAlign: 'top' }}>
                        <TextField variant="standard" size="small" fullWidth
                          value={pair.keyCols} onChange={(e) => updatePair(pair.id, 'keyCols', e.target.value)}
                          placeholder="id, order_date"
                          sx={{ '& .MuiInputBase-root': { fontSize: '0.78rem', fontFamily: '"JetBrains Mono", monospace' } }}
                          InputProps={{ disableUnderline: true }}
                        />
                      </TableCell>
                      <TableCell sx={{ verticalAlign: 'top', pt: 0.75 }}>
                        <IconButton size="small" onClick={() => removePair(pair.id)} sx={{ color: '#CBD5E1', '&:hover': { color: '#E11D48', bgcolor: 'rgba(225,29,72,0.06)' } }}>
                          <DeleteOutlineRoundedIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 2, py: 8 }}>
                <Box sx={{ width: 60, height: 60, borderRadius: 3, bgcolor: 'rgba(49,113,214,0.06)', border: '1px solid rgba(49,113,214,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <UploadFileRoundedIcon sx={{ fontSize: 28, color: '#3171D6', opacity: 0.6 }} />
                </Box>
                <Box sx={{ textAlign: 'center' }}>
                  <Typography sx={{ fontSize: '0.9rem', fontWeight: 700, color: '#1E293B', mb: 0.5 }}>No test cases yet</Typography>
                  <Typography sx={{ fontSize: '0.8rem', color: '#64748B' }}>Import a CSV/Excel file or add test cases manually</Typography>
                </Box>
                <Button size="small" variant="outlined" startIcon={<AddRoundedIcon />} onClick={addPair}
                  sx={{ borderRadius: 2, fontSize: '0.8rem', px: 2 }}>
                  Add first test case
                </Button>
              </Box>
            )}
          </Box>

          {/* Incomplete test cases warning */}
          {pairs.length > validPairs.length && pairs.length > 0 && (
            <Box sx={{ px: 2.5, py: 1, borderTop: '1px solid rgba(15,23,42,0.05)', bgcolor: '#FAFBFC', flexShrink: 0 }}>
              <Chip label={`${pairs.length - validPairs.length} row${pairs.length - validPairs.length !== 1 ? 's' : ''} incomplete \u2014 both fields required`}
                size="small"
                sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600, bgcolor: 'rgba(217,119,6,0.08)', color: '#D97706', border: '1px solid rgba(217,119,6,0.2)' }}
              />
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}
