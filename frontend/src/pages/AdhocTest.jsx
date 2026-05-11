import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Typography, Button, TextField,
  CircularProgress, Alert, Select, MenuItem, FormControl,
  IconButton, Tooltip, Chip,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import CompareArrowsRoundedIcon from '@mui/icons-material/CompareArrowsRounded';

import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import TableRowsRoundedIcon from '@mui/icons-material/TableRowsRounded';
import SchemaRoundedIcon from '@mui/icons-material/SchemaRounded';
import RemoveCircleOutlineRoundedIcon from '@mui/icons-material/RemoveCircleOutlineRounded';
import FunctionsRoundedIcon from '@mui/icons-material/FunctionsRounded';
import CheckRoundedIcon from '@mui/icons-material/CheckRounded';
import CheckCircleOutlineRoundedIcon from '@mui/icons-material/CheckCircleOutlineRounded';
import CodeRoundedIcon from '@mui/icons-material/CodeRounded';
import ConnectionPicker from '../components/ConnectionPicker';
import { runAdhoc, uploadCsv } from '../api';

const CHECK_META = [
  { type: 'row_count', label: 'Row Count', icon: TableRowsRoundedIcon, color: '#3171D6' },
  { type: 'metadata', label: 'Schema', icon: SchemaRoundedIcon, color: '#0891B2' },
  { type: 'null_check', label: 'Nulls', icon: RemoveCircleOutlineRoundedIcon, color: '#D97706' },
  { type: 'duplicate', label: 'Duplicates', icon: ContentCopyRoundedIcon, color: '#DB2777' },
  { type: 'data', label: 'Data Diff', icon: CompareArrowsRoundedIcon, color: '#7C3AED' },
  { type: 'aggregate', label: 'Aggregates', icon: FunctionsRoundedIcon, color: '#059669' },
];

const MONO = '"JetBrains Mono", "Fira Code", monospace';

export default function AdhocTest({ onResult }) {
  const navigate = useNavigate();
  const srcFileRef = useRef();
  const tgtFileRef = useRef();

  const [runName, setRunName] = useState('');
  const [srcConnectionId, setSrcConnectionId] = useState(null);
  const [tgtConnectionId, setTgtConnectionId] = useState(null);
  const [srcConn, setSrcConn] = useState(null);
  const [tgtConn, setTgtConn] = useState(null);
  const [srcQuery, setSrcQuery] = useState('');
  const [tgtQuery, setTgtQuery] = useState('');

  // CSV upload state
  const [srcFile, setSrcFile] = useState(null);
  const [srcFilePath, setSrcFilePath] = useState('');
  const [srcUploading, setSrcUploading] = useState(false);
  const [tgtFile, setTgtFile] = useState(null);
  const [tgtFilePath, setTgtFilePath] = useState('');
  const [tgtUploading, setTgtUploading] = useState(false);

  const [checks, setChecks] = useState(['row_count', 'metadata', 'null_check']);
  const [joinKeys, setJoinKeys] = useState('');
  const [strategy, setStrategy] = useState('full');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  const srcIsCsv = srcConnectionId === '__csv__';
  const tgtIsCsv = tgtConnectionId === '__csv__';
  const canRun = (srcIsCsv ? srcFilePath : srcConnectionId && srcQuery.trim())
    && (tgtIsCsv ? tgtFilePath : tgtConnectionId && tgtQuery.trim())
    && checks.length > 0;
  const toggleCheck = (type) => setChecks((p) => p.includes(type) ? p.filter((t) => t !== type) : [...p, type]);

  const handleFileUpload = async (file, side) => {
    if (!file || !file.name.toLowerCase().endsWith('.csv')) {
      setError('Only .csv files are accepted');
      return;
    }
    const setUploading = side === 'src' ? setSrcUploading : setTgtUploading;
    const setFileInfo = side === 'src' ? setSrcFile : setTgtFile;
    const setPath = side === 'src' ? setSrcFilePath : setTgtFilePath;
    setUploading(true);
    setError('');
    try {
      const res = await uploadCsv(file);
      setFileInfo({ name: res.data.filename, size: res.data.size });
      setPath(res.data.file_path);
    } catch (err) {
      setError(err.response?.data?.detail || 'Upload failed');
      setFileInfo(null);
      setPath('');
    } finally {
      setUploading(false);
    }
  };

  const clearFile = (side) => {
    if (side === 'src') { setSrcFile(null); setSrcFilePath(''); }
    else { setTgtFile(null); setTgtFilePath(''); }
  };

  const handleRun = async () => {
    if (!canRun) { setError('Connect source & target, provide data, and select at least one check.'); return; }
    setError(''); setRunning(true);
    const checkSpecs = checks.map((type) => {
      const spec = { type };
      if (type === 'data') {
        spec.strategy = strategy; spec.column_drill_down = true;
        if (joinKeys.trim()) spec.join_keys = joinKeys.split(',').map((k) => k.trim());
      }
      return spec;
    });
    try {
      const payload = { checks: checkSpecs, suite_name: runName.trim() };
      if (srcIsCsv) {
        payload.source_file_path = srcFilePath;
        payload.source_table = 'SELECT * FROM data';
      } else {
        payload.source_connection_id = srcConnectionId;
        payload.source_table = srcQuery.trim();
      }
      if (tgtIsCsv) {
        payload.target_file_path = tgtFilePath;
        payload.target_table = 'SELECT * FROM data';
      } else {
        payload.target_connection_id = tgtConnectionId;
        payload.target_table = tgtQuery.trim();
      }
      const res = await runAdhoc(payload);
      onResult(res.data); navigate('/results');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Validation failed');
    } finally { setRunning(false); }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const renderUploadZone = (side) => {
    const file = side === 'src' ? srcFile : tgtFile;
    const uploading = side === 'src' ? srcUploading : tgtUploading;
    const fileRef = side === 'src' ? srcFileRef : tgtFileRef;
    const color = side === 'src' ? '#3171D6' : '#0D9488';

    return (
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 1.5, px: 3 }}>
        <input
          ref={fileRef}
          type="file"
          accept=".csv"
          style={{ display: 'none' }}
          onChange={(e) => { handleFileUpload(e.target.files[0], side); e.target.value = ''; }}
        />
        {uploading ? (
          <>
            <CircularProgress size={32} sx={{ color }} />
            <Typography sx={{ fontSize: '0.8rem', color: '#64748B' }}>Uploading…</Typography>
          </>
        ) : file ? (
          <>
            <CheckCircleOutlineRoundedIcon sx={{ fontSize: 36, color, opacity: 0.6 }} />
            <Typography sx={{ fontSize: '0.85rem', fontWeight: 600, color: '#0F172A' }}>{file.name}</Typography>
            <Box sx={{
              display: 'flex', alignItems: 'center', gap: 1, px: 2, py: 0.75, borderRadius: 2,
              bgcolor: `${color}0A`, border: `1px solid ${color}1A`,
            }}>
              <Typography sx={{ fontSize: '0.75rem', color: '#64748B' }}>{formatSize(file.size)}</Typography>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
              <Button size="small" onClick={() => fileRef.current?.click()}
                sx={{ fontSize: '0.72rem', color, textTransform: 'none' }}>
                Replace
              </Button>
              <Button size="small" onClick={() => clearFile(side)}
                sx={{ fontSize: '0.72rem', color: '#94A3B8', textTransform: 'none' }}>
                Remove
              </Button>
            </Box>
          </>
        ) : (
          <Box
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); handleFileUpload(e.dataTransfer.files[0], side); }}
            sx={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5,
              p: 4, borderRadius: 3, cursor: 'pointer', width: '100%', maxWidth: 280,
              border: '2px dashed', borderColor: `${color}30`,
              bgcolor: `${color}04`,
              transition: 'all 0.2s',
              '&:hover': { borderColor: `${color}60`, bgcolor: `${color}08` },
            }}
          >
            <UploadFileRoundedIcon sx={{ fontSize: 36, color, opacity: 0.5 }} />
            <Typography sx={{ fontSize: '0.82rem', fontWeight: 600, color: '#334155', textAlign: 'center' }}>
              Drop CSV file here
            </Typography>
            <Typography sx={{ fontSize: '0.72rem', color: '#94A3B8' }}>
              or click to browse
            </Typography>
          </Box>
        )}
      </Box>
    );
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Top action bar */}
      <Box sx={{
        display: 'flex', alignItems: 'center', gap: 2,
        px: 3, pt: 2.5, pb: 2, flexShrink: 0,
        borderBottom: '1px solid rgba(15,23,42,0.06)', bgcolor: '#fff',
      }}>
        <Box sx={{ flex: 1 }}>
          <Typography sx={{ fontSize: '1.25rem', fontWeight: 800, color: '#0F172A', letterSpacing: '-0.02em', lineHeight: 1.2 }}>
            Ad-hoc Validation
          </Typography>
          <Typography sx={{ fontSize: '0.8rem', color: '#64748B', mt: 0.25 }}>
            Run a one-off check against a single test case
          </Typography>
        </Box>
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
          {running ? 'Running…' : 'Run'}
        </Button>
      </Box>

      {error && <Alert severity="error" onClose={() => setError('')} sx={{ mx: 3, mt: 1.5, borderRadius: 2, flexShrink: 0 }}>{error}</Alert>}

      {/* Two-column body */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* LEFT config strip */}
        <Box sx={{
          width: 280, flexShrink: 0, borderRight: '1px solid rgba(15,23,42,0.07)',
          overflowY: 'auto', bgcolor: '#FAFBFC', display: 'flex', flexDirection: 'column',
        }}>
          {/* Run Name */}
          <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(15,23,42,0.06)' }}>
            <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em', mb: 1 }}>
              Run Name
            </Typography>
            <TextField
              fullWidth size="small" placeholder="e.g. orders_daily_check"
              value={runName} onChange={(e) => setRunName(e.target.value)}
              inputProps={{ style: { fontSize: '0.8rem' } }}
              sx={{ '& .MuiOutlinedInput-root': { borderRadius: 1.5 } }}
            />
          </Box>

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
                <ConnectionPicker
                  label="Source" value={srcConnectionId}
                  onChange={(id) => { setSrcConnectionId(id); if (id !== '__csv__') { clearFile('src'); } }}
                  onConnectionChange={setSrcConn}
                />
              </Box>
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.75 }}>
                  <CompareArrowsRoundedIcon sx={{ color: '#0D9488', fontSize: 12 }} />
                  <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#0D9488', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Target</Typography>
                </Box>
                <ConnectionPicker
                  label="Target" value={tgtConnectionId}
                  onChange={(id) => { setTgtConnectionId(id); if (id !== '__csv__') { clearFile('tgt'); } }}
                  onConnectionChange={setTgtConn}
                />
              </Box>
            </Box>
          </Box>

          {/* Checks */}
          <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(15,23,42,0.06)' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
                Checks · {checks.length}/{CHECK_META.length}
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

          {/* Data diff options */}
          {checks.includes('data') && (
            <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(15,23,42,0.06)' }}>
              <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.07em', mb: 1.5 }}>Data Diff</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                <FormControl fullWidth size="small">
                  <Select value={strategy} onChange={(e) => setStrategy(e.target.value)} sx={{ fontSize: '0.8rem' }}>
                    <MenuItem value="hash">Hash (fastest)</MenuItem>
                    <MenuItem value="full">Full diff</MenuItem>
                    <MenuItem value="sample">Sample %</MenuItem>
                  </Select>
                </FormControl>
                <TextField size="small" fullWidth label="Key Cols" value={joinKeys} onChange={(e) => setJoinKeys(e.target.value)} placeholder="id, order_date" />
              </Box>
            </Box>
          )}
        </Box>

        {/* RIGHT — query editors or CSV upload */}
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden', bgcolor: '#fff' }}>
          {/* Header */}
          <Box sx={{
            display: 'flex', alignItems: 'center', gap: 1.5, px: 2.5, py: 1.5,
            borderBottom: '1px solid rgba(15,23,42,0.07)', bgcolor: '#FAFBFC', flexShrink: 0,
          }}>
            {srcIsCsv && tgtIsCsv ? (
              <>
                <UploadFileRoundedIcon sx={{ fontSize: 16, color: '#0D9488' }} />
                <Typography sx={{ fontSize: '0.875rem', fontWeight: 700, color: '#0F172A' }}>CSV Files</Typography>
                <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8', ml: 0.5 }}>
                  Upload source and target CSV files to compare
                </Typography>
              </>
            ) : srcIsCsv || tgtIsCsv ? (
              <>
                <CompareArrowsRoundedIcon sx={{ fontSize: 16, color: '#7C3AED' }} />
                <Typography sx={{ fontSize: '0.875rem', fontWeight: 700, color: '#0F172A' }}>Mixed Mode</Typography>
                <Typography sx={{ fontSize: '0.75rem', color: '#94A3B8', ml: 0.5 }}>
                  CSV upload + SQL query
                </Typography>
              </>
            ) : (
              <>
                <CodeRoundedIcon sx={{ fontSize: 16, color: '#3171D6' }} />
                <Typography sx={{ fontSize: '0.875rem', fontWeight: 700, color: '#0F172A' }}>SQL Queries</Typography>
              </>
            )}
          </Box>

          {/* Two panels side by side */}
          <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'row', minHeight: 0 }}>
            {/* Source */}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid rgba(15,23,42,0.07)', minWidth: 0 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2.5, py: 1.25, bgcolor: '#F8FAFF', borderBottom: '1px solid rgba(49,113,214,0.08)', flexShrink: 0 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#3171D6' }} />
                <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#3171D6', textTransform: 'uppercase', letterSpacing: '0.07em', flex: 1 }}>
                  {srcIsCsv ? 'Source File' : 'Source Query'}
                </Typography>
                {!srcIsCsv && (
                  <>
                    <Tooltip title="Clear">
                      <IconButton size="small" onClick={() => setSrcQuery('')} sx={{ color: '#CBD5E1', '&:hover': { color: '#475569' } }}>
                        <DeleteOutlineRoundedIcon sx={{ fontSize: 15 }} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Copy">
                      <IconButton size="small" onClick={() => navigator.clipboard?.writeText(srcQuery)} sx={{ color: '#CBD5E1', '&:hover': { color: '#475569' } }}>
                        <ContentCopyRoundedIcon sx={{ fontSize: 15 }} />
                      </IconButton>
                    </Tooltip>
                  </>
                )}
              </Box>
              {srcIsCsv ? renderUploadZone('src') : (
                <TextField
                  fullWidth multiline
                  value={srcQuery}
                  onChange={(e) => setSrcQuery(e.target.value)}
                  placeholder={"SELECT\n  order_id,\n  customer_id,\n  total_amount\nFROM staging.orders\nWHERE load_date = current_date"}
                  variant="outlined"
                  sx={{
                    flex: 1,
                    '& .MuiOutlinedInput-root': {
                      bgcolor: '#FAFEFF', borderRadius: 0, height: '100%', alignItems: 'flex-start',
                      '& fieldset': { border: 'none' },
                      '&.Mui-focused': { bgcolor: '#fff', boxShadow: 'inset 3px 0 0 #3171D6' },
                    },
                    '& .MuiOutlinedInput-input': {
                      fontFamily: MONO, fontSize: '0.875rem', lineHeight: 1.7, pt: 1.5, px: 2.5,
                    },
                  }}
                />
              )}
            </Box>

            {/* Target */}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2.5, py: 1.25, bgcolor: '#F5FFFB', borderBottom: '1px solid rgba(13,148,136,0.08)', flexShrink: 0 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#0D9488' }} />
                <Typography sx={{ fontSize: '0.68rem', fontWeight: 700, color: '#0D9488', textTransform: 'uppercase', letterSpacing: '0.07em', flex: 1 }}>
                  {tgtIsCsv ? 'Target File' : 'Target Query'}
                </Typography>
                {!tgtIsCsv && (
                  <>
                    <Tooltip title="Clear">
                      <IconButton size="small" onClick={() => setTgtQuery('')} sx={{ color: '#CBD5E1', '&:hover': { color: '#475569' } }}>
                        <DeleteOutlineRoundedIcon sx={{ fontSize: 15 }} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Copy">
                      <IconButton size="small" onClick={() => navigator.clipboard?.writeText(tgtQuery)} sx={{ color: '#CBD5E1', '&:hover': { color: '#475569' } }}>
                        <ContentCopyRoundedIcon sx={{ fontSize: 15 }} />
                      </IconButton>
                    </Tooltip>
                  </>
                )}
              </Box>
              {tgtIsCsv ? renderUploadZone('tgt') : (
                <TextField
                  fullWidth multiline
                  value={tgtQuery}
                  onChange={(e) => setTgtQuery(e.target.value)}
                  placeholder={"SELECT\n  order_id,\n  customer_id,\n  total_amount\nFROM production.orders\nWHERE load_date = current_date"}
                  variant="outlined"
                  sx={{
                    flex: 1,
                    '& .MuiOutlinedInput-root': {
                      bgcolor: '#FAFFFC', borderRadius: 0, height: '100%', alignItems: 'flex-start',
                      '& fieldset': { border: 'none' },
                      '&.Mui-focused': { bgcolor: '#fff', boxShadow: 'inset 3px 0 0 #0D9488' },
                    },
                    '& .MuiOutlinedInput-input': {
                      fontFamily: MONO, fontSize: '0.875rem', lineHeight: 1.7, pt: 1.5, px: 2.5,
                    },
                  }}
                />
              )}
            </Box>
          </Box>

          {/* Status footer */}
          <Box sx={{ display: 'flex', alignItems: 'center', px: 2.5, py: 1.25, borderTop: '1px solid rgba(15,23,42,0.06)', bgcolor: '#FAFBFC', gap: 1.5, flexShrink: 0 }}>
            {srcIsCsv ? srcFile && (
              <Chip size="small" label={`Source: ${srcFile.name}`}
                sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600, bgcolor: 'rgba(49,113,214,0.08)', color: '#3171D6', border: '1px solid rgba(49,113,214,0.2)' }} />
            ) : srcQuery.trim() && (
              <Chip size="small" label="Source ✓"
                sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600, bgcolor: 'rgba(49,113,214,0.08)', color: '#3171D6', border: '1px solid rgba(49,113,214,0.2)' }} />
            )}
            {tgtIsCsv ? tgtFile && (
              <Chip size="small" label={`Target: ${tgtFile.name}`}
                sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600, bgcolor: 'rgba(13,148,136,0.08)', color: '#0D9488', border: '1px solid rgba(13,148,136,0.2)' }} />
            ) : tgtQuery.trim() && (
              <Chip size="small" label="Target ✓"
                sx={{ height: 22, fontSize: '0.7rem', fontWeight: 600, bgcolor: 'rgba(13,148,136,0.08)', color: '#0D9488', border: '1px solid rgba(13,148,136,0.2)' }} />
            )}
            {checks.length > 0 && (
              <Typography sx={{ fontSize: '0.7rem', color: '#94A3B8', ml: 'auto' }}>
                {checks.length} check{checks.length !== 1 ? 's' : ''} selected
              </Typography>
            )}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
